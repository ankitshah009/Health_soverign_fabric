"""Tests for app.aubric.risk_engine.RiskEngine.evaluate()."""

from __future__ import annotations

import pytest

from app.aubric.risk_engine import RiskEngine, _build_reasoning
from app.models.claim import FraudScore, RiskLevel


@pytest.fixture
def engine() -> RiskEngine:
    return RiskEngine()


def _fraud(score: float, level: str = "low") -> FraudScore:
    return FraudScore(overall_score=score, risk_level=RiskLevel(level))


def _money_action(amount: float, money: bool = True) -> dict:
    return {"money_movement": money, "monetary_value": amount, "claim_id": "CLM-TEST"}


def _no_money_action() -> dict:
    return {"money_movement": False, "monetary_value": 0.0, "claim_id": "CLM-TEST"}


# ---------------------------------------------------------------------------
# Branch 1: fraud_score > 70 → block
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_block_when_fraud_score_above_70(engine):
    result = await engine.evaluate(_money_action(3000), _fraud(71.0), {})
    assert result["recommended_action"] == "block"
    assert result["action_risk_level"] == "critical"
    assert result["approval_threshold"] == 1.0


@pytest.mark.asyncio
async def test_block_at_exactly_71(engine):
    result = await engine.evaluate(_money_action(500), _fraud(71.0), {})
    assert result["recommended_action"] == "block"


@pytest.mark.asyncio
async def test_block_at_100(engine):
    result = await engine.evaluate(_money_action(1000), _fraud(100.0), {})
    assert result["recommended_action"] == "block"


# ---------------------------------------------------------------------------
# Branch 2: fraud_score > 50 (and ≤ 70) → escalate_fraud
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalate_fraud_when_score_between_50_and_70(engine):
    result = await engine.evaluate(_money_action(3000), _fraud(55.0), {})
    assert result["recommended_action"] == "escalate_fraud"
    assert result["action_risk_level"] == "high"
    assert result["approval_threshold"] == 0.95


@pytest.mark.asyncio
async def test_escalate_fraud_at_exactly_51(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(51.0), {})
    assert result["recommended_action"] == "escalate_fraud"


@pytest.mark.asyncio
async def test_escalate_fraud_at_exactly_70(engine):
    # 70 is NOT > 70, falls into escalate_fraud branch (score > 50 is true)
    result = await engine.evaluate(_no_money_action(), _fraud(70.0), {})
    assert result["recommended_action"] == "escalate_fraud"


# ---------------------------------------------------------------------------
# Branch 3: money_movement AND amount > 5000 → require_human
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_require_human_when_money_movement_and_high_amount(engine):
    result = await engine.evaluate(_money_action(5001.0), _fraud(10.0), {})
    assert result["recommended_action"] == "require_human"
    assert result["action_risk_level"] == "medium"
    assert result["approval_threshold"] == 0.8


@pytest.mark.asyncio
async def test_require_human_not_triggered_without_money_movement_high_amount(engine):
    # No money_movement, low fraud → should default to require_human via else
    result = await engine.evaluate(_no_money_action(), _fraud(10.0), {})
    # Falls to else → require_human
    assert result["recommended_action"] == "require_human"


@pytest.mark.asyncio
async def test_high_amount_no_money_movement_not_branch3(engine):
    # money_movement=False means branch 3 is not taken
    action = {"money_movement": False, "monetary_value": 10000.0, "claim_id": "CLM-TEST"}
    result = await engine.evaluate(action, _fraud(10.0), {})
    # Falls through to else → require_human (not due to amount)
    assert result["recommended_action"] == "require_human"


# ---------------------------------------------------------------------------
# Branch 4: money_movement AND fraud_score > 30 → require_human
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_require_human_when_money_movement_and_fraud_above_30(engine):
    # score=40 (>30, <=50), amount=500 (<=5000) → branch 4
    result = await engine.evaluate(_money_action(500.0), _fraud(40.0), {})
    assert result["recommended_action"] == "require_human"


@pytest.mark.asyncio
async def test_fraud_31_with_money_movement_and_small_amount(engine):
    result = await engine.evaluate(_money_action(800.0), _fraud(31.0), {})
    assert result["recommended_action"] == "require_human"


# ---------------------------------------------------------------------------
# Branch 5: money_movement AND amount <= 1000 AND fraud_score < 20 → auto_approve
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_approve_low_amount_low_fraud(engine):
    result = await engine.evaluate(_money_action(999.0), _fraud(15.0), {})
    assert result["recommended_action"] == "auto_approve"
    assert result["action_risk_level"] == "low"
    assert result["approval_threshold"] == 0.5


@pytest.mark.asyncio
async def test_auto_approve_exactly_1000_and_score_19(engine):
    result = await engine.evaluate(_money_action(1000.0), _fraud(19.0), {})
    assert result["recommended_action"] == "auto_approve"


@pytest.mark.asyncio
async def test_auto_approve_not_triggered_when_amount_over_1000(engine):
    result = await engine.evaluate(_money_action(1001.0), _fraud(15.0), {})
    # Doesn't match branch 5 (amount > 1000), and fraud <= 30 so not branch 4
    # and not branch 3 (<=5000) → else → require_human
    assert result["recommended_action"] == "require_human"


@pytest.mark.asyncio
async def test_auto_approve_not_triggered_when_fraud_score_20_or_above(engine):
    result = await engine.evaluate(_money_action(500.0), _fraud(20.0), {})
    # fraud=20 is not < 20 → else → require_human
    assert result["recommended_action"] == "require_human"


# ---------------------------------------------------------------------------
# Default branch: else → require_human
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_require_human_no_money_movement_low_fraud(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(10.0), {})
    assert result["recommended_action"] == "require_human"


@pytest.mark.asyncio
async def test_default_require_human_money_movement_medium_amount_medium_fraud(engine):
    # amount=2000, fraud=25 → not branch 3 (<=5000), not branch 4 (<=30), not branch 5 (>1000)
    result = await engine.evaluate(_money_action(2000.0), _fraud(25.0), {})
    assert result["recommended_action"] == "require_human"


# ---------------------------------------------------------------------------
# Confidence scores
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_identity_confidence_decreases_with_higher_fraud_score(engine):
    low = await engine.evaluate(_no_money_action(), _fraud(10.0), {})
    high = await engine.evaluate(_no_money_action(), _fraud(60.0), {})
    assert low["identity_confidence"] > high["identity_confidence"]


@pytest.mark.asyncio
async def test_identity_confidence_bounded_between_0_1_and_1(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(100.0), {})
    assert 0.0 <= result["identity_confidence"] <= 1.0
    assert result["identity_confidence"] >= 0.1


@pytest.mark.asyncio
async def test_document_authenticity_decreases_with_higher_fraud(engine):
    low = await engine.evaluate(_no_money_action(), _fraud(0.0), {})
    high = await engine.evaluate(_no_money_action(), _fraud(80.0), {})
    assert low["document_authenticity_confidence"] > high["document_authenticity_confidence"]


@pytest.mark.asyncio
async def test_document_authenticity_at_zero_fraud_is_1(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(0.0), {})
    assert result["document_authenticity_confidence"] == 1.0


@pytest.mark.asyncio
async def test_fraud_concern_level_normalized(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(50.0), {})
    assert result["fraud_concern_level"] == pytest.approx(0.5, abs=0.01)


@pytest.mark.asyncio
async def test_fraud_concern_capped_at_1(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(100.0), {})
    assert result["fraud_concern_level"] == 1.0


# ---------------------------------------------------------------------------
# Reasoning string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_is_non_empty_string(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(10.0), {})
    assert isinstance(result["reasoning"], str)
    assert len(result["reasoning"]) > 0


@pytest.mark.asyncio
async def test_reasoning_mentions_block_when_score_high(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(80.0), {})
    assert "blocked" in result["reasoning"].lower() or "critical" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_reasoning_mentions_siu_when_escalated(engine):
    result = await engine.evaluate(_no_money_action(), _fraud(55.0), {})
    assert "siu" in result["reasoning"].lower() or "escalation" in result["reasoning"].lower()


@pytest.mark.asyncio
async def test_reasoning_mentions_amount_when_money_movement(engine):
    result = await engine.evaluate(_money_action(3000.0), _fraud(10.0), {})
    assert "3,000" in result["reasoning"] or "monetary" in result["reasoning"].lower()


def test_build_reasoning_standard_processing():
    text = _build_reasoning(10.0, 0.0, False, "require_human")
    assert "Standard processing" in text
    assert "10" in text


def test_build_reasoning_block():
    text = _build_reasoning(75.0, 0.0, False, "block")
    assert "blocked" in text.lower() or "investigation" in text.lower()


def test_build_reasoning_escalate():
    text = _build_reasoning(55.0, 0.0, False, "escalate_fraud")
    assert "siu" in text.lower() or "escalation" in text.lower()


def test_build_reasoning_auto_approve():
    text = _build_reasoning(10.0, 500.0, True, "auto_approve")
    assert "auto-approval" in text.lower() or "low" in text.lower()


def test_build_reasoning_high_amount():
    text = _build_reasoning(10.0, 6000.0, True, "require_human")
    assert "5,000" in text or "human review" in text.lower()


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_result_contains_all_expected_keys(engine):
    result = await engine.evaluate(_money_action(1000.0), _fraud(30.0), {})
    expected_keys = {
        "action_risk_level",
        "identity_confidence",
        "document_authenticity_confidence",
        "fraud_concern_level",
        "approval_threshold",
        "recommended_action",
        "fraud_score",
        "monetary_value",
        "money_movement",
        "reasoning",
    }
    assert expected_keys.issubset(result.keys())


@pytest.mark.asyncio
async def test_result_monetary_value_and_money_movement_echoed(engine):
    result = await engine.evaluate(_money_action(2500.0), _fraud(20.0), {})
    assert result["monetary_value"] == 2500.0
    assert result["money_movement"] is True
