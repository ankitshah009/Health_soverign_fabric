"""Unit tests for the FraudSignalSkill and _adjust_score_with_yutori helper.

The Grok service is always mocked with AsyncMock so no real HTTP calls are made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.models.claim import ExtractedData, FraudScore, FraudSignal, RiskLevel, Severity
from app.skills.fraud_signal import FraudSignalSkill, _adjust_score_with_yutori


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fraud_score(score: float, signals: list | None = None) -> FraudScore:
    """Build a minimal FraudScore for testing."""
    return FraudScore(
        overall_score=score,
        risk_level=RiskLevel.LOW if score < 30 else (
            RiskLevel.MEDIUM if score < 50 else (
                RiskLevel.HIGH if score < 70 else RiskLevel.CRITICAL
            )
        ),
        signals=signals or [],
        explanation="Test explanation",
    )


def _make_extracted_data(**kwargs) -> ExtractedData:
    defaults = {
        "damage_type": "vehicle collision",
        "estimated_cost": 3000.0,
        "vehicle_info": "2020 Toyota Camry",
        "incident_details": "Rear-end collision.",
        "document_type": "damage photo",
        "key_findings": ["front bumper cracked"],
    }
    defaults.update(kwargs)
    return ExtractedData(**defaults)


@pytest.fixture
def skill() -> FraudSignalSkill:
    return FraudSignalSkill()


@pytest.fixture
def base_score_20() -> FraudScore:
    return _make_fraud_score(20.0)


@pytest.fixture
def base_score_50() -> FraudScore:
    return _make_fraud_score(50.0)


@pytest.fixture
def base_score_95() -> FraudScore:
    return _make_fraud_score(95.0)


@pytest.fixture
def base_score_2() -> FraudScore:
    return _make_fraud_score(2.0)


@pytest.fixture
def extracted_data() -> ExtractedData:
    return _make_extracted_data()


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — no results
# ---------------------------------------------------------------------------

class TestAdjustScoreNoResults:
    def test_empty_list_score_unchanged(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [])
        assert result.overall_score == 20.0

    def test_empty_list_risk_level_unchanged(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [])
        assert result.risk_level == RiskLevel.LOW

    def test_empty_list_signals_empty(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [])
        assert result.signals == []

    def test_empty_list_explanation_preserved(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [])
        assert result.explanation == base_score_20.explanation


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — verification_pending raises score +3 per entity
# ---------------------------------------------------------------------------

class TestAdjustScoreVerificationPending:
    def _pending(self, name="John Smith", entity_type="person") -> dict:
        return {
            "entity_name": name,
            "entity_type": entity_type,
            "status": "verification_pending",
            "results": {},
        }

    def test_single_pending_adds_two(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._pending()])
        assert result.overall_score == pytest.approx(22.0)

    def test_two_pending_entities_adds_four(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [
            self._pending("Alice"),
            self._pending("Bob"),
        ])
        assert result.overall_score == pytest.approx(24.0)

    def test_pending_adds_unverified_signal(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._pending(entity_type="person")])
        signal_names = [s["signal_name"] if isinstance(s, dict) else s.signal_name
                        for s in result.signals]
        assert any("yutori_unverified_person" in n for n in signal_names)

    def test_pending_signal_severity_is_low(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._pending()])
        sig = result.signals[-1]
        severity = sig["severity"] if isinstance(sig, dict) else sig.severity
        assert severity == "low"


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — completed with risk_indicators → +10
# ---------------------------------------------------------------------------

class TestAdjustScoreCompletedWithRiskIndicators:
    def _risky(self, indicators=None) -> dict:
        return {
            "entity_name": "Jane Suspect",
            "entity_type": "person",
            "status": "completed",
            "results": {
                "risk_indicators": indicators or ["prior fraud conviction", "address mismatch"],
            },
        }

    def test_risk_indicators_adds_ten(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky()])
        assert result.overall_score == pytest.approx(30.0)

    def test_risk_indicators_signal_name_contains_yutori_risk(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky()])
        signal_names = [s["signal_name"] if isinstance(s, dict) else s.signal_name
                        for s in result.signals]
        assert any("yutori_risk" in n for n in signal_names)

    def test_risk_indicators_severity_is_medium(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky()])
        sig = result.signals[-1]
        severity = sig["severity"] if isinstance(sig, dict) else sig.severity
        assert severity == "medium"

    def test_risk_indicators_description_contains_entity_name(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky()])
        sig = result.signals[-1]
        desc = sig["description"] if isinstance(sig, dict) else sig.description
        assert "Jane Suspect" in desc

    def test_risk_indicators_risk_level_updates_correctly(self, base_score_20):
        # base 20 + 10 = 30 → medium
        result = _adjust_score_with_yutori(base_score_20, [self._risky()])
        assert result.risk_level == RiskLevel.MEDIUM


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — completed with high credibility (>0.7) → -5
# ---------------------------------------------------------------------------

class TestAdjustScoreCompletedHighCredibility:
    def _high_cred(self, score=0.85) -> dict:
        return {
            "entity_name": "Alice Good",
            "entity_type": "person",
            "status": "completed",
            "results": {
                "credibility_score": score,
                "risk_indicators": [],
            },
        }

    def test_high_credibility_subtracts_three(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._high_cred()])
        assert result.overall_score == pytest.approx(17.0)

    def test_high_credibility_adds_verified_signal(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._high_cred()])
        signal_names = [s["signal_name"] if isinstance(s, dict) else s.signal_name
                        for s in result.signals]
        assert any("yutori_verified" in n for n in signal_names)

    def test_high_credibility_signal_severity_is_low(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._high_cred()])
        sig = result.signals[-1]
        severity = sig["severity"] if isinstance(sig, dict) else sig.severity
        assert severity == "low"

    def test_boundary_exactly_0_7_does_not_qualify_for_high_cred_reduction(self, base_score_20):
        # credibility == 0.7 is NOT > 0.7, so no -5 reduction.
        # It also is NOT < 0.3, and the outer elif (credibility is not None) is True,
        # so the neutral else branch does NOT fire — adjustment stays 0.
        result_07 = _adjust_score_with_yutori(base_score_20, [self._high_cred(0.7)])
        assert result_07.overall_score == pytest.approx(20.0)

    def test_score_0_71_qualifies_for_reduction(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._high_cred(0.71)])
        assert result.overall_score == pytest.approx(17.0)


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — completed with low credibility (<0.3) → +8
# ---------------------------------------------------------------------------

class TestAdjustScoreCompletedLowCredibility:
    def _low_cred(self, score=0.2) -> dict:
        return {
            "entity_name": "Bob Unknown",
            "entity_type": "person",
            "status": "completed",
            "results": {
                "credibility_score": score,
                "risk_indicators": [],
            },
        }

    def test_low_credibility_adds_eight(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._low_cred()])
        assert result.overall_score == pytest.approx(28.0)

    def test_low_credibility_adds_low_credibility_signal(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._low_cred()])
        signal_names = [s["signal_name"] if isinstance(s, dict) else s.signal_name
                        for s in result.signals]
        assert any("yutori_low_credibility" in n for n in signal_names)

    def test_low_credibility_signal_severity_is_high(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._low_cred()])
        sig = result.signals[-1]
        severity = sig["severity"] if isinstance(sig, dict) else sig.severity
        assert severity == "high"

    def test_boundary_exactly_0_3_does_not_qualify_as_low_credibility(self, base_score_20):
        # credibility == 0.3 is NOT < 0.3, so the low-cred branch does not fire.
        # The outer elif (credibility is not None) IS True, so the neutral else
        # branch also does not fire — adjustment stays 0.
        result = _adjust_score_with_yutori(base_score_20, [self._low_cred(0.3)])
        assert result.overall_score == pytest.approx(20.0)

    def test_score_0_29_qualifies_as_low_credibility(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._low_cred(0.29)])
        assert result.overall_score == pytest.approx(28.0)


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — completed, no strong signals → -2
# ---------------------------------------------------------------------------

class TestAdjustScoreCompletedNoStrongSignals:
    def _neutral(self) -> dict:
        return {
            "entity_name": "Charlie Neutral",
            "entity_type": "contractor",
            "status": "completed",
            "results": {
                # no risk_indicators and no credibility_score
            },
        }

    def test_no_strong_signals_subtracts_two(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._neutral()])
        assert result.overall_score == pytest.approx(18.0)

    def test_no_strong_signals_adds_neutral_signal(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._neutral()])
        signal_names = [s["signal_name"] if isinstance(s, dict) else s.signal_name
                        for s in result.signals]
        assert any("yutori_neutral" in n for n in signal_names)

    def test_neutral_signal_entity_type_in_name(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._neutral()])
        signal_names = [s["signal_name"] if isinstance(s, dict) else s.signal_name
                        for s in result.signals]
        assert any("contractor" in n for n in signal_names)

    def test_neutral_signal_severity_is_low(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._neutral()])
        sig = result.signals[-1]
        severity = sig["severity"] if isinstance(sig, dict) else sig.severity
        assert severity == "low"


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — score clamped to [0, 100]
# ---------------------------------------------------------------------------

class TestAdjustScoreClamping:
    def test_score_clamped_at_100(self, base_score_95):
        # base=95, risk_indicators → +10; would be 105, clamped to 100
        yutori_results = [{
            "entity_name": "Eve Suspect",
            "entity_type": "person",
            "status": "completed",
            "results": {"risk_indicators": ["fraud"]},
        }]
        result = _adjust_score_with_yutori(base_score_95, yutori_results)
        assert result.overall_score == pytest.approx(100.0)

    def test_score_clamped_at_zero(self, base_score_2):
        # base=2, high credibility → -5; would be -3, clamped to 0
        yutori_results = [{
            "entity_name": "Frank Good",
            "entity_type": "person",
            "status": "completed",
            "results": {"credibility_score": 0.9, "risk_indicators": []},
        }]
        result = _adjust_score_with_yutori(base_score_2, yutori_results)
        assert result.overall_score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _adjust_score_with_yutori — signals list merges base + Yutori signals
# ---------------------------------------------------------------------------

class TestAdjustScoreSignalsMerge:
    def test_base_signals_preserved_in_output(self):
        base_signal = FraudSignal(
            signal_name="base_signal",
            description="Pre-existing base signal.",
            severity=Severity.MEDIUM,
            confidence=0.7,
        )
        base = FraudScore(
            overall_score=30.0,
            risk_level=RiskLevel.MEDIUM,
            signals=[base_signal],
            explanation="Base explanation",
        )
        yutori_results = [{
            "entity_name": "Alice",
            "entity_type": "person",
            "status": "verification_pending",
            "results": {},
        }]
        result = _adjust_score_with_yutori(base, yutori_results)
        result_signal_names = [
            s["signal_name"] if isinstance(s, dict) else s.signal_name
            for s in result.signals
        ]
        assert "base_signal" in result_signal_names

    def test_yutori_signals_appended_after_base(self):
        base_signal = FraudSignal(
            signal_name="base_signal",
            description="Pre-existing base signal.",
            severity=Severity.LOW,
            confidence=0.5,
        )
        base = FraudScore(
            overall_score=20.0,
            risk_level=RiskLevel.LOW,
            signals=[base_signal],
            explanation="Base explanation",
        )
        yutori_results = [{
            "entity_name": "Bob",
            "entity_type": "person",
            "status": "verification_pending",
            "results": {},
        }]
        result = _adjust_score_with_yutori(base, yutori_results)
        assert len(result.signals) == 2

    def test_multiple_yutori_results_all_signals_present(self):
        base = _make_fraud_score(40.0)
        yutori_results = [
            {
                "entity_name": "Alice",
                "entity_type": "person",
                "status": "verification_pending",
                "results": {},
            },
            {
                "entity_name": "Bob Corp",
                "entity_type": "organization",
                "status": "completed",
                "results": {"risk_indicators": ["shell company"]},
            },
        ]
        result = _adjust_score_with_yutori(base, yutori_results)
        assert len(result.signals) == 2
        signal_names = [s["signal_name"] if isinstance(s, dict) else s.signal_name
                        for s in result.signals]
        assert any("yutori_unverified_person" in n for n in signal_names)
        assert any("yutori_risk_organization" in n for n in signal_names)


# ---------------------------------------------------------------------------
# Risk level thresholds
# ---------------------------------------------------------------------------

class TestAdjustScoreRiskLevelThresholds:
    def _result_for_score(self, score: float) -> FraudScore:
        base = _make_fraud_score(score)
        return _adjust_score_with_yutori(base, [])

    def test_score_below_30_is_low(self):
        result = self._result_for_score(25.0)
        assert result.risk_level == RiskLevel.LOW

    def test_score_30_is_medium(self):
        result = self._result_for_score(30.0)
        assert result.risk_level == RiskLevel.MEDIUM

    def test_score_50_is_high(self):
        result = self._result_for_score(50.0)
        assert result.risk_level == RiskLevel.HIGH

    def test_score_70_is_critical(self):
        result = self._result_for_score(70.0)
        assert result.risk_level == RiskLevel.CRITICAL

    def test_score_69_is_high_not_critical(self):
        result = self._result_for_score(69.0)
        assert result.risk_level == RiskLevel.HIGH


# ---------------------------------------------------------------------------
# FraudSignalSkill.execute — mocked grok_service
# ---------------------------------------------------------------------------

class TestFraudSignalSkillExecute:
    """Tests for the full execute() path; grok_service.assess_fraud is mocked."""

    def _make_mock_grok(self, base_score: FraudScore) -> AsyncMock:
        mock = AsyncMock()
        mock.assess_fraud = AsyncMock(return_value=base_score)
        return mock

    @pytest.mark.asyncio
    async def test_execute_returns_fraud_score(self, skill, extracted_data):
        base = _make_fraud_score(20.0)
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "Rear-end collision", [])
        assert isinstance(result, FraudScore)

    @pytest.mark.asyncio
    async def test_execute_calls_assess_fraud_with_correct_args(self, skill, extracted_data):
        base = _make_fraud_score(20.0)
        mock_grok = self._make_mock_grok(base)
        description = "Car was hit from behind at a traffic light."
        with patch("app.skills.fraud_signal.grok_service", mock_grok):
            await skill.execute(extracted_data, description, [])
        mock_grok.assess_fraud.assert_awaited_once_with(extracted_data, description)

    @pytest.mark.asyncio
    async def test_execute_no_yutori_results_passes_through_base_score(self, skill, extracted_data):
        base = _make_fraud_score(35.0)
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "description", [])
        assert result.overall_score == pytest.approx(35.0)

    @pytest.mark.asyncio
    async def test_execute_applies_yutori_risk_adjustment(self, skill, extracted_data):
        base = _make_fraud_score(30.0)
        yutori_results = [{
            "entity_name": "Suspicious Corp",
            "entity_type": "organization",
            "status": "completed",
            "results": {"risk_indicators": ["known fraud ring"]},
        }]
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "description", yutori_results)
        # +10 for risk indicators
        assert result.overall_score == pytest.approx(40.0)

    @pytest.mark.asyncio
    async def test_execute_applies_yutori_pending_adjustment(self, skill, extracted_data):
        base = _make_fraud_score(50.0)
        yutori_results = [{
            "entity_name": "Unknown Person",
            "entity_type": "person",
            "status": "verification_pending",
            "results": {},
        }]
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "description", yutori_results)
        # +2 for pending (adjusted from +3 with SIU vectors)
        assert result.overall_score == pytest.approx(52.0)

    @pytest.mark.asyncio
    async def test_execute_applies_high_credibility_reduction(self, skill, extracted_data):
        base = _make_fraud_score(40.0)
        yutori_results = [{
            "entity_name": "Verified Business",
            "entity_type": "organization",
            "status": "completed",
            "results": {"credibility_score": 0.95, "risk_indicators": []},
        }]
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "description", yutori_results)
        # -3 for high credibility (adjusted from -5 with SIU vectors)
        assert result.overall_score == pytest.approx(37.0)

    @pytest.mark.asyncio
    async def test_execute_score_clamped_to_100(self, skill, extracted_data):
        base = _make_fraud_score(98.0)
        yutori_results = [{
            "entity_name": "Bad Actor",
            "entity_type": "person",
            "status": "completed",
            "results": {"risk_indicators": ["multiple fraud flags"]},
        }]
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "description", yutori_results)
        assert result.overall_score == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_execute_score_clamped_to_zero(self, skill, extracted_data):
        base = _make_fraud_score(3.0)
        yutori_results = [
            {
                "entity_name": "Alice",
                "entity_type": "person",
                "status": "completed",
                "results": {"credibility_score": 0.9, "risk_indicators": []},
            },
            {
                "entity_name": "Bob",
                "entity_type": "person",
                "status": "completed",
                "results": {"credibility_score": 0.9, "risk_indicators": []},
            },
        ]
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "description", yutori_results)
        assert result.overall_score == pytest.approx(0.0)

    @pytest.mark.asyncio
    async def test_execute_merges_base_signals_with_yutori_signals(self, skill, extracted_data):
        base_signal = FraudSignal(
            signal_name="base_fraud_signal",
            description="Suspicious claim pattern.",
            severity=Severity.MEDIUM,
            confidence=0.7,
        )
        base = FraudScore(
            overall_score=40.0,
            risk_level=RiskLevel.MEDIUM,
            signals=[base_signal],
            explanation="Base explanation",
        )
        yutori_results = [{
            "entity_name": "Suspect",
            "entity_type": "person",
            "status": "verification_pending",
            "results": {},
        }]
        with patch("app.skills.fraud_signal.grok_service", self._make_mock_grok(base)):
            result = await skill.execute(extracted_data, "description", yutori_results)

        signal_names = [
            s["signal_name"] if isinstance(s, dict) else s.signal_name
            for s in result.signals
        ]
        assert "base_fraud_signal" in signal_names
        assert any("yutori_unverified" in n for n in signal_names)


# ---------------------------------------------------------------------------
# SIU entity-type-specific risk adjustments (new in SIU vectors expansion)
# ---------------------------------------------------------------------------

class TestSIUEntityTypeSpecificScoring:
    """Test that different SIU entity types get different risk adjustments."""

    def _risky_entity(self, entity_type: str) -> dict:
        return {
            "entity_name": "Test Entity",
            "entity_type": entity_type,
            "status": "completed",
            "results": {"risk_indicators": ["suspicious finding"]},
        }

    def test_claimant_history_risk_adds_fifteen(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("claimant_history")])
        assert result.overall_score == pytest.approx(35.0)

    def test_vehicle_property_risk_adds_twelve(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("vehicle_property")])
        assert result.overall_score == pytest.approx(32.0)

    def test_repair_provider_risk_adds_ten(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("repair_provider")])
        assert result.overall_score == pytest.approx(30.0)

    def test_incident_corroboration_risk_adds_eight(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("incident_corroboration")])
        assert result.overall_score == pytest.approx(28.0)

    def test_financial_stress_risk_adds_eight(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("financial_stress")])
        assert result.overall_score == pytest.approx(28.0)

    def test_browse_bbb_risk_adds_twelve(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("browse_bbb")])
        assert result.overall_score == pytest.approx(32.0)

    def test_browse_court_records_risk_adds_fifteen(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("browse_court_records")])
        assert result.overall_score == pytest.approx(35.0)

    def test_unknown_entity_type_uses_default_ten(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("some_new_type")])
        assert result.overall_score == pytest.approx(30.0)

    def test_claimant_history_risk_severity_is_high(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("claimant_history")])
        sig = result.signals[-1]
        severity = sig["severity"] if isinstance(sig, dict) else sig.severity
        assert severity == "high"

    def test_incident_corroboration_risk_severity_is_medium(self, base_score_20):
        result = _adjust_score_with_yutori(base_score_20, [self._risky_entity("incident_corroboration")])
        sig = result.signals[-1]
        severity = sig["severity"] if isinstance(sig, dict) else sig.severity
        assert severity == "medium"

    def test_multiple_siu_vectors_combine(self, base_score_20):
        """All 5 SIU vectors with risk indicators should combine additively."""
        results = [
            self._risky_entity("claimant_history"),      # +15
            self._risky_entity("vehicle_property"),       # +12
            self._risky_entity("incident_corroboration"), # +8
            self._risky_entity("repair_provider"),        # +10
            self._risky_entity("financial_stress"),       # +8
        ]
        result = _adjust_score_with_yutori(base_score_20, results)
        # 20 + 15 + 12 + 8 + 10 + 8 = 73, but clamped to 100
        assert result.overall_score == pytest.approx(73.0)

    def test_all_vectors_clean_reduces_score(self, base_score_20):
        """All 5 SIU vectors verified with high credibility should reduce score."""
        clean = lambda et: {
            "entity_name": "Clean Entity",
            "entity_type": et,
            "status": "completed",
            "results": {"credibility_score": 0.9, "risk_indicators": []},
        }
        results = [
            clean("claimant_history"),
            clean("vehicle_property"),
            clean("incident_corroboration"),
            clean("repair_provider"),
            clean("financial_stress"),
        ]
        result = _adjust_score_with_yutori(base_score_20, results)
        # 20 + 5*(-3) = 5
        assert result.overall_score == pytest.approx(5.0)
