"""Unit tests for SimulationEngine and IntentNormalizer.

SimulationEngine (app.aubric.simulation):
    - simulate() delegates to grok_service.simulate_outcome
    - simulate() returns a SimulationResult
    - simulate() propagates the graceful fallback on grok failure

IntentNormalizer (app.aubric.intent_normalizer):
    - normalize() maps skill_metadata to expected output fields
    - normalize() handles missing / partial skill_metadata gracefully
    - normalize() extracts monetary_value correctly
    - normalize() computes severity, identity/document checks, and action type
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.aubric.intent_normalizer import IntentNormalizer
from app.aubric.simulation import SimulationEngine
from app.models.claim import (
    FraudScore,
    PayoutRecommendation,
    RiskLevel,
    SimulationResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fraud_score(
    score: float = 20.0,
    risk_level: str = "low",
) -> FraudScore:
    return FraudScore(
        overall_score=score,
        risk_level=RiskLevel(risk_level),
        signals=[],
        explanation="Test fraud score.",
    )


def _make_payout_rec(amount: float = 3000.0, confidence: float = 0.9) -> PayoutRecommendation:
    return PayoutRecommendation(
        recommended_amount=amount,
        confidence=confidence,
        rationale="Standard repair cost minus deductible.",
        comparable_claims=[],
    )


def _make_simulation_result(**kwargs) -> SimulationResult:
    defaults = dict(
        approval_probability=0.85,
        dispute_risk=0.1,
        fraud_escalation_likelihood=0.05,
        financial_exposure=3000.0,
        historical_comparison="Similar to 90% of auto claims.",
        recommended_action="approve",
    )
    defaults.update(kwargs)
    return SimulationResult(**defaults)


def _make_raw_action(
    claim_id: str = "CLM-001",
    monetary_value: float = 3000.0,
    action_category: str = "claims_processing",
    read_or_write: str = "read",
    money_movement: bool = False,
    reversible: bool = True,
    skill_name: str = "test_skill",
    required_approval_role: str | None = None,
) -> dict:
    return {
        "claim_id": claim_id,
        "monetary_value": monetary_value,
        "skill_metadata": {
            "action_category": action_category,
            "read_or_write": read_or_write,
            "money_movement": money_movement,
            "reversible": reversible,
            "skill_name": skill_name,
            "required_approval_role": required_approval_role,
        },
    }


# ---------------------------------------------------------------------------
# SimulationEngine.simulate() — delegates to grok_service.simulate_outcome
# ---------------------------------------------------------------------------


class TestSimulationEngineDelegate:
    @pytest.mark.asyncio
    async def test_simulate_calls_grok_service_simulate_outcome(self):
        engine = SimulationEngine()
        claim_data = {"id": "CLM-001", "claimant_name": "Alice"}
        fraud = _make_fraud_score()
        payout = _make_payout_rec()
        expected = _make_simulation_result()

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=expected)

        with patch("app.aubric.simulation.grok_service", mock_grok):
            await engine.simulate(claim_data, fraud, payout)

        mock_grok.simulate_outcome.assert_awaited_once_with(claim_data, fraud, payout)

    @pytest.mark.asyncio
    async def test_simulate_passes_all_args_to_simulate_outcome(self):
        engine = SimulationEngine()
        claim_data = {"id": "CLM-XYZ", "claimant_name": "Bob", "status": "pending"}
        fraud = _make_fraud_score(score=55.0, risk_level="high")
        payout = _make_payout_rec(amount=12000.0, confidence=0.6)

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=_make_simulation_result())

        with patch("app.aubric.simulation.grok_service", mock_grok):
            await engine.simulate(claim_data, fraud, payout)

        call_args = mock_grok.simulate_outcome.call_args
        assert call_args.args[0] is claim_data
        assert call_args.args[1] is fraud
        assert call_args.args[2] is payout


# ---------------------------------------------------------------------------
# SimulationEngine.simulate() — returns SimulationResult
# ---------------------------------------------------------------------------


class TestSimulationEngineReturnType:
    @pytest.mark.asyncio
    async def test_simulate_returns_simulation_result_instance(self):
        engine = SimulationEngine()
        expected = _make_simulation_result()

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=expected)

        with patch("app.aubric.simulation.grok_service", mock_grok):
            result = await engine.simulate({}, _make_fraud_score(), _make_payout_rec())

        assert isinstance(result, SimulationResult)

    @pytest.mark.asyncio
    async def test_simulate_returns_value_from_grok_service(self):
        engine = SimulationEngine()
        expected = _make_simulation_result(
            approval_probability=0.72,
            recommended_action="partial_approval",
        )

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=expected)

        with patch("app.aubric.simulation.grok_service", mock_grok):
            result = await engine.simulate({}, _make_fraud_score(), _make_payout_rec())

        assert result.approval_probability == pytest.approx(0.72)
        assert result.recommended_action == "partial_approval"

    @pytest.mark.asyncio
    async def test_simulate_result_contains_all_expected_fields(self):
        engine = SimulationEngine()
        expected = _make_simulation_result()

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=expected)

        with patch("app.aubric.simulation.grok_service", mock_grok):
            result = await engine.simulate({}, _make_fraud_score(), _make_payout_rec())

        assert hasattr(result, "approval_probability")
        assert hasattr(result, "dispute_risk")
        assert hasattr(result, "fraud_escalation_likelihood")
        assert hasattr(result, "financial_exposure")
        assert hasattr(result, "historical_comparison")
        assert hasattr(result, "recommended_action")


# ---------------------------------------------------------------------------
# SimulationEngine.simulate() — graceful handling of grok failure
# ---------------------------------------------------------------------------


class TestSimulationEngineGrokFailure:
    @pytest.mark.asyncio
    async def test_simulate_returns_fallback_result_when_grok_raises(self):
        """GrokService.simulate_outcome already swallows errors and returns a
        fallback SimulationResult — verify simulate() propagates that result."""
        engine = SimulationEngine()
        fallback = SimulationResult(
            approval_probability=0.5,
            dispute_risk=0.5,
            fraud_escalation_likelihood=0.5,
            financial_exposure=3000.0,
            historical_comparison="Simulation unavailable due to error.",
            recommended_action="investigate_further",
        )

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=fallback)

        with patch("app.aubric.simulation.grok_service", mock_grok):
            result = await engine.simulate(
                {"id": "CLM-ERR"},
                _make_fraud_score(),
                _make_payout_rec(),
            )

        assert result.recommended_action == "investigate_further"
        assert result.historical_comparison == "Simulation unavailable due to error."

    @pytest.mark.asyncio
    async def test_simulate_does_not_raise_when_grok_returns_fallback(self):
        engine = SimulationEngine()
        fallback = _make_simulation_result(recommended_action="investigate_further")

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=fallback)

        with patch("app.aubric.simulation.grok_service", mock_grok):
            # Should complete without raising
            result = await engine.simulate({}, _make_fraud_score(), _make_payout_rec())

        assert isinstance(result, SimulationResult)

    @pytest.mark.asyncio
    async def test_simulate_uses_payout_amount_in_fallback_financial_exposure(self):
        """The real simulate_outcome fallback sets financial_exposure to
        payout_rec.recommended_amount — simulate() must return that as-is."""
        engine = SimulationEngine()
        payout = _make_payout_rec(amount=7500.0)
        fallback = SimulationResult(
            approval_probability=0.5,
            dispute_risk=0.5,
            fraud_escalation_likelihood=0.5,
            financial_exposure=payout.recommended_amount,
            historical_comparison="Simulation unavailable due to error.",
            recommended_action="investigate_further",
        )

        mock_grok = MagicMock()
        mock_grok.simulate_outcome = AsyncMock(return_value=fallback)

        with patch("app.aubric.simulation.grok_service", mock_grok):
            result = await engine.simulate({}, _make_fraud_score(), payout)

        assert result.financial_exposure == pytest.approx(7500.0)


# ---------------------------------------------------------------------------
# IntentNormalizer.normalize() — correct field mapping
# ---------------------------------------------------------------------------


class TestIntentNormalizerFields:
    @pytest.fixture
    def normalizer(self) -> IntentNormalizer:
        return IntentNormalizer()

    def test_normalize_returns_dict(self, normalizer):
        result = normalizer.normalize(_make_raw_action())
        assert isinstance(result, dict)

    def test_normalize_sets_claim_id(self, normalizer):
        result = normalizer.normalize(_make_raw_action(claim_id="CLM-999"))
        assert result["claim_id"] == "CLM-999"

    def test_normalize_maps_claims_processing_to_process_claim(self, normalizer):
        result = normalizer.normalize(_make_raw_action(action_category="claims_processing"))
        assert result["action_type"] == "process_claim"

    def test_normalize_maps_fraud_detection_to_assess_fraud(self, normalizer):
        result = normalizer.normalize(_make_raw_action(action_category="fraud_detection"))
        assert result["action_type"] == "assess_fraud"

    def test_normalize_maps_claims_payout_with_money_to_execute_payout(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(action_category="claims_payout", money_movement=True)
        )
        assert result["action_type"] == "execute_payout"

    def test_normalize_maps_claims_payout_without_money_to_recommend_payout(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(action_category="claims_payout", money_movement=False)
        )
        assert result["action_type"] == "recommend_payout"

    def test_normalize_maps_unknown_category_to_unknown_action(self, normalizer):
        result = normalizer.normalize(_make_raw_action(action_category="something_new"))
        assert result["action_type"] == "unknown_action"

    def test_normalize_sets_source_skill_from_metadata(self, normalizer):
        result = normalizer.normalize(_make_raw_action(skill_name="fraud_signal_skill"))
        assert result["source_skill"] == "fraud_signal_skill"

    def test_normalize_sets_read_or_write(self, normalizer):
        result = normalizer.normalize(_make_raw_action(read_or_write="write"))
        assert result["read_or_write"] == "write"

    def test_normalize_sets_money_movement_true(self, normalizer):
        result = normalizer.normalize(_make_raw_action(money_movement=True))
        assert result["money_movement"] is True

    def test_normalize_sets_money_movement_false(self, normalizer):
        result = normalizer.normalize(_make_raw_action(money_movement=False))
        assert result["money_movement"] is False

    def test_normalize_sets_is_reversible(self, normalizer):
        result = normalizer.normalize(_make_raw_action(reversible=False))
        assert result["is_reversible"] is False

    def test_normalize_sets_required_approval_role(self, normalizer):
        result = normalizer.normalize(_make_raw_action(required_approval_role="senior_adjuster"))
        assert result["required_approval_role"] == "senior_adjuster"

    def test_normalize_required_approval_role_none_when_not_provided(self, normalizer):
        result = normalizer.normalize(_make_raw_action(required_approval_role=None))
        assert result["required_approval_role"] is None

    def test_normalize_output_has_all_expected_keys(self, normalizer):
        result = normalizer.normalize(_make_raw_action())
        expected_keys = {
            "action_type",
            "claim_id",
            "severity",
            "monetary_value",
            "requires_identity_check",
            "requires_document_check",
            "is_reversible",
            "money_movement",
            "read_or_write",
            "source_skill",
            "required_approval_role",
        }
        assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# IntentNormalizer.normalize() — missing / partial skill_metadata
# ---------------------------------------------------------------------------


class TestIntentNormalizerMissingMetadata:
    @pytest.fixture
    def normalizer(self) -> IntentNormalizer:
        return IntentNormalizer()

    def test_normalize_empty_dict_does_not_raise(self, normalizer):
        result = normalizer.normalize({})
        assert isinstance(result, dict)

    def test_normalize_missing_skill_metadata_uses_defaults(self, normalizer):
        result = normalizer.normalize({"claim_id": "CLM-X"})
        assert result["action_type"] == "unknown_action"
        assert result["severity"] == "low"
        assert result["source_skill"] == "unknown"

    def test_normalize_missing_skill_metadata_claim_id_preserved(self, normalizer):
        result = normalizer.normalize({"claim_id": "CLM-555"})
        assert result["claim_id"] == "CLM-555"

    def test_normalize_missing_claim_id_defaults_to_unknown(self, normalizer):
        result = normalizer.normalize({"monetary_value": 100.0})
        assert result["claim_id"] == "unknown"

    def test_normalize_partial_metadata_only_action_category(self, normalizer):
        result = normalizer.normalize({
            "claim_id": "CLM-P",
            "skill_metadata": {"action_category": "fraud_detection"},
        })
        assert result["action_type"] == "assess_fraud"
        # money_movement absent → defaults to False
        assert result["money_movement"] is False

    def test_normalize_empty_skill_metadata_dict(self, normalizer):
        result = normalizer.normalize({
            "claim_id": "CLM-EMPTY",
            "skill_metadata": {},
        })
        assert result["action_type"] == "unknown_action"
        assert result["source_skill"] == "unknown"
        assert result["is_reversible"] is True  # default
        assert result["read_or_write"] == "read"  # default


# ---------------------------------------------------------------------------
# IntentNormalizer.normalize() — monetary_value extraction
# ---------------------------------------------------------------------------


class TestIntentNormalizerMonetaryValue:
    @pytest.fixture
    def normalizer(self) -> IntentNormalizer:
        return IntentNormalizer()

    def test_monetary_value_cast_to_float(self, normalizer):
        result = normalizer.normalize(_make_raw_action(monetary_value=5000))
        assert isinstance(result["monetary_value"], float)
        assert result["monetary_value"] == 5000.0

    def test_monetary_value_zero_when_missing(self, normalizer):
        result = normalizer.normalize({"claim_id": "CLM-0"})
        assert result["monetary_value"] == 0.0

    def test_monetary_value_preserved_as_float(self, normalizer):
        result = normalizer.normalize(_make_raw_action(monetary_value=12345.67))
        assert result["monetary_value"] == pytest.approx(12345.67)

    def test_large_monetary_value_preserved(self, normalizer):
        result = normalizer.normalize(_make_raw_action(monetary_value=1_000_000.0))
        assert result["monetary_value"] == pytest.approx(1_000_000.0)


# ---------------------------------------------------------------------------
# IntentNormalizer.normalize() — severity logic
# ---------------------------------------------------------------------------


class TestIntentNormalizerSeverity:
    @pytest.fixture
    def normalizer(self) -> IntentNormalizer:
        return IntentNormalizer()

    def test_severity_high_when_money_movement_and_above_10000(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(money_movement=True, monetary_value=10001.0)
        )
        assert result["severity"] == "high"

    def test_severity_medium_when_money_movement_and_between_1000_and_10000(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(money_movement=True, monetary_value=5000.0)
        )
        assert result["severity"] == "medium"

    def test_severity_low_when_money_movement_and_below_1000(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(money_movement=True, monetary_value=500.0)
        )
        assert result["severity"] == "low"

    def test_severity_medium_when_fraud_detection_no_money(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(action_category="fraud_detection", money_movement=False)
        )
        assert result["severity"] == "medium"

    def test_severity_low_when_no_money_movement_and_not_fraud(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(action_category="claims_processing", money_movement=False)
        )
        assert result["severity"] == "low"

    def test_severity_high_boundary_exactly_10000_is_medium(self, normalizer):
        # 10000 is NOT > 10000, so it falls into the medium branch
        result = normalizer.normalize(
            _make_raw_action(money_movement=True, monetary_value=10000.0)
        )
        assert result["severity"] == "medium"

    def test_severity_medium_boundary_exactly_1000_is_low(self, normalizer):
        # 1000 is NOT > 1000, so it falls into the low branch
        result = normalizer.normalize(
            _make_raw_action(money_movement=True, monetary_value=1000.0)
        )
        assert result["severity"] == "low"


# ---------------------------------------------------------------------------
# IntentNormalizer.normalize() — identity and document check flags
# ---------------------------------------------------------------------------


class TestIntentNormalizerCheckFlags:
    @pytest.fixture
    def normalizer(self) -> IntentNormalizer:
        return IntentNormalizer()

    def test_requires_identity_check_true_when_money_movement(self, normalizer):
        result = normalizer.normalize(_make_raw_action(money_movement=True))
        assert result["requires_identity_check"] is True

    def test_requires_identity_check_true_when_write_and_irreversible(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(read_or_write="write", reversible=False, money_movement=False)
        )
        assert result["requires_identity_check"] is True

    def test_requires_identity_check_false_for_read_reversible_no_money(self, normalizer):
        result = normalizer.normalize(
            _make_raw_action(read_or_write="read", reversible=True, money_movement=False)
        )
        assert result["requires_identity_check"] is False

    def test_requires_document_check_true_for_claims_processing(self, normalizer):
        result = normalizer.normalize(_make_raw_action(action_category="claims_processing"))
        assert result["requires_document_check"] is True

    def test_requires_document_check_true_for_fraud_detection(self, normalizer):
        result = normalizer.normalize(_make_raw_action(action_category="fraud_detection"))
        assert result["requires_document_check"] is True

    def test_requires_document_check_false_for_claims_payout(self, normalizer):
        result = normalizer.normalize(_make_raw_action(action_category="claims_payout"))
        assert result["requires_document_check"] is False

    def test_requires_document_check_false_for_unknown_category(self, normalizer):
        result = normalizer.normalize(_make_raw_action(action_category="irrelevant_category"))
        assert result["requires_document_check"] is False
