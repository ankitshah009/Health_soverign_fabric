"""Tests for app.aubric.approval_engine.ApprovalEngine.process_approval()."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

from app.aubric.approval_engine import ApprovalEngine
from app.database import get_audit_log


@pytest.fixture
def engine() -> ApprovalEngine:
    return ApprovalEngine()


def _risk(action: str, fraud_score: float = 30.0) -> dict:
    return {
        "recommended_action": action,
        "fraud_score": fraud_score,
        "action_risk_level": "medium",
    }


@pytest_asyncio.fixture
async def claim_in_db():
    """Create a minimal claim record in the test database for audit log checks."""
    from app.database import create_claim
    await create_claim(
        claim_id="CLM-AUDIT",
        claimant_name="Audit Tester",
        incident_description="Test incident",
        policy_number=None,
        file_path=None,
        file_type=None,
    )
    return "CLM-AUDIT"


# ---------------------------------------------------------------------------
# Rule 1: block + approve → deny override
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rule1_block_approve_overridden_to_deny(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="adjuster1",
        risk_assessment=_risk("block", fraud_score=80.0),
    )
    assert result["approved"] is False
    assert result["decision"] == "deny"
    assert result["override_applied"] is True
    assert "BLOCKED" in result["reason"]


@pytest.mark.asyncio
async def test_rule1_block_deny_is_allowed(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="deny",
        approver="adjuster1",
        risk_assessment=_risk("block", fraud_score=80.0),
    )
    # Denial is always allowed (Rule 3 takes precedence after Rule 1 check passes)
    assert result["decision"] == "deny"
    assert result["override_applied"] is False


@pytest.mark.asyncio
async def test_rule1_creates_audit_entry(engine, claim_in_db):
    cid = claim_in_db
    await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="adjuster1",
        risk_assessment=_risk("block", fraud_score=80.0),
    )
    log = await get_audit_log(cid)
    actions = [entry["action"] for entry in log]
    assert "approval_blocked" in actions


# ---------------------------------------------------------------------------
# Rule 2: escalate_fraud + approve (non-SIU) → deny
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rule2_escalate_fraud_non_siu_approver_denied(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="regular_adjuster",
        risk_assessment=_risk("escalate_fraud", fraud_score=60.0),
    )
    assert result["approved"] is False
    assert result["decision"] == "escalate"
    assert result["override_applied"] is True
    assert "SIU" in result["reason"]


@pytest.mark.asyncio
async def test_rule2_escalate_fraud_siu_investigator_can_approve(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="siu_investigator",
        risk_assessment=_risk("escalate_fraud", fraud_score=60.0),
    )
    assert result["approved"] is True
    assert result["decision"] == "approve"
    assert result["override_applied"] is False


@pytest.mark.asyncio
async def test_rule2_siu_alias_fraud_unit_can_approve(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="fraud_unit",
        risk_assessment=_risk("escalate_fraud", fraud_score=60.0),
    )
    assert result["approved"] is True
    assert result["decision"] == "approve"


@pytest.mark.asyncio
async def test_rule2_siu_alias_siu_can_approve(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="siu",
        risk_assessment=_risk("escalate_fraud", fraud_score=60.0),
    )
    assert result["approved"] is True
    assert result["decision"] == "approve"


@pytest.mark.asyncio
async def test_rule2_siu_check_is_case_insensitive(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="SIU_Investigator",
        risk_assessment=_risk("escalate_fraud", fraud_score=60.0),
    )
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_rule2_creates_audit_entry_for_non_siu_escalation(engine, claim_in_db):
    cid = claim_in_db
    await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="regular_adjuster",
        risk_assessment=_risk("escalate_fraud", fraud_score=60.0),
    )
    log = await get_audit_log(cid)
    actions = [entry["action"] for entry in log]
    assert "approval_escalation_required" in actions


# ---------------------------------------------------------------------------
# Rule 3: deny → always allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rule3_deny_always_allowed_for_any_risk_level(engine, claim_in_db):
    cid = claim_in_db
    for recommended in ("block", "escalate_fraud", "require_human", "auto_approve"):
        result = await engine.process_approval(
            claim_id=cid,
            decision="deny",
            approver="adjuster1",
            risk_assessment=_risk(recommended),
        )
        assert result["decision"] == "deny"
        assert result["override_applied"] is False


@pytest.mark.asyncio
async def test_rule3_deny_result_has_approved_true(engine, claim_in_db):
    # "approved" here means the *denial* was successfully processed
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="deny",
        approver="adjuster1",
        risk_assessment=_risk("require_human"),
    )
    assert result["approved"] is True


@pytest.mark.asyncio
async def test_rule3_deny_creates_audit_entry(engine, claim_in_db):
    cid = claim_in_db
    await engine.process_approval(
        claim_id=cid,
        decision="deny",
        approver="adjuster1",
        risk_assessment=_risk("require_human"),
    )
    log = await get_audit_log(cid)
    actions = [entry["action"] for entry in log]
    assert "claim_denied" in actions


# ---------------------------------------------------------------------------
# Rule 4: escalate → always allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rule4_escalate_always_allowed(engine, claim_in_db):
    cid = claim_in_db
    for recommended in ("block", "escalate_fraud", "require_human", "auto_approve"):
        result = await engine.process_approval(
            claim_id=cid,
            decision="escalate",
            approver="adjuster1",
            risk_assessment=_risk(recommended),
        )
        assert result["decision"] == "escalate"
        assert result["approved"] is True
        assert result["override_applied"] is False


@pytest.mark.asyncio
async def test_rule4_escalate_creates_audit_entry(engine, claim_in_db):
    cid = claim_in_db
    await engine.process_approval(
        claim_id=cid,
        decision="escalate",
        approver="adjuster1",
        risk_assessment=_risk("require_human"),
    )
    log = await get_audit_log(cid)
    actions = [entry["action"] for entry in log]
    assert "claim_escalated" in actions


# ---------------------------------------------------------------------------
# Rule 5: standard approve → allowed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rule5_standard_approve_allowed(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="adjuster1",
        risk_assessment=_risk("require_human"),
    )
    assert result["approved"] is True
    assert result["decision"] == "approve"
    assert result["override_applied"] is False


@pytest.mark.asyncio
async def test_rule5_approve_reason_includes_approver_name(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="mary_jones",
        risk_assessment=_risk("require_human"),
    )
    assert "mary_jones" in result["reason"]


@pytest.mark.asyncio
async def test_rule5_approve_creates_audit_entry(engine, claim_in_db):
    cid = claim_in_db
    await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="adjuster1",
        risk_assessment=_risk("require_human"),
    )
    log = await get_audit_log(cid)
    actions = [entry["action"] for entry in log]
    assert "claim_approved" in actions


@pytest.mark.asyncio
async def test_rule5_auto_approve_recommendation_also_passes(engine, claim_in_db):
    cid = claim_in_db
    result = await engine.process_approval(
        claim_id=cid,
        decision="approve",
        approver="system",
        risk_assessment=_risk("auto_approve"),
    )
    assert result["approved"] is True
    assert result["decision"] == "approve"
