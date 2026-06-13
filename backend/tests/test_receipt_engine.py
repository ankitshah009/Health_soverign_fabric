"""Unit tests for app.aubric.receipt_engine.ReceiptEngine.generate_receipt().

Database side-effects (update_claim, add_audit_entry) are replaced with
AsyncMock so tests are fully self-contained and deterministic.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.aubric.receipt_engine import ReceiptEngine
from app.models.decision import DecisionReceipt


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> ReceiptEngine:
    return ReceiptEngine()


def _risk(
    identity_confidence: float = 0.875,
    fraud_score: float = 15.0,
    action_risk_level: str = "medium",
) -> dict:
    return {
        "recommended_action": "require_human",
        "action_risk_level": action_risk_level,
        "fraud_score": fraud_score,
        "monetary_value": 3000.0,
        "money_movement": True,
        "identity_confidence": identity_confidence,
        "document_authenticity_confidence": 0.85,
        "fraud_concern_level": 0.15,
        "approval_threshold": 0.8,
        "reasoning": "Standard processing.",
    }


def _claim(
    *,
    claimant_name: str = "Jane Claimant",
    covered: bool = True,
    policy_number: str = "AUTO-12345",
    coverage_type: str = "comprehensive_auto",
    coverage_limit: float = 50000.0,
    with_simulation: bool = True,
) -> dict:
    claim = {
        "id": "CLM-00001",
        "claimant_name": claimant_name,
        "coverage_result": {
            "policy_number": policy_number,
            "coverage_type": coverage_type,
            "coverage_limit": coverage_limit,
            "covered": covered,
        },
    }
    if with_simulation:
        claim["simulation_result"] = {
            "approval_probability": 0.85,
            "dispute_risk": 0.1,
            "recommended_action": "approve",
        }
    return claim


# Patch targets used in all tests
_PATCH_UPDATE = "app.aubric.receipt_engine.update_claim"
_PATCH_AUDIT = "app.aubric.receipt_engine.add_audit_entry"


# ---------------------------------------------------------------------------
# generate_receipt — return type and required fields
# ---------------------------------------------------------------------------

class TestReceiptStructure:

    @pytest.mark.asyncio
    async def test_returns_decision_receipt_instance(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        assert isinstance(receipt, DecisionReceipt)

    @pytest.mark.asyncio
    async def test_receipt_claim_id_matches_input(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-XYZ", "approve", "adjuster_a", _risk(), _claim()
            )
        assert receipt.claim_id == "CLM-XYZ"

    @pytest.mark.asyncio
    async def test_receipt_action_matches_input(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "deny", "adjuster_a", _risk(), _claim()
            )
        assert receipt.action == "deny"

    @pytest.mark.asyncio
    async def test_receipt_approved_by_matches_approver(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "mary_jones", _risk(), _claim()
            )
        assert receipt.approved_by == "mary_jones"

    @pytest.mark.asyncio
    async def test_receipt_requested_by_matches_claimant_name(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a",
                _risk(), _claim(claimant_name="Alice Applicant")
            )
        assert receipt.requested_by == "Alice Applicant"

    @pytest.mark.asyncio
    async def test_receipt_requested_by_defaults_to_unknown_when_name_missing(self, engine):
        claim_no_name = {"id": "CLM-001"}  # no claimant_name key
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), claim_no_name
            )
        assert receipt.requested_by == "unknown"

    @pytest.mark.asyncio
    async def test_receipt_timestamp_is_non_empty_string(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        assert isinstance(receipt.timestamp, str)
        assert len(receipt.timestamp) > 0


# ---------------------------------------------------------------------------
# receipt_id format
# ---------------------------------------------------------------------------

class TestReceiptId:

    @pytest.mark.asyncio
    async def test_receipt_id_starts_with_REC_prefix(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        assert receipt.receipt_id.startswith("REC-")

    @pytest.mark.asyncio
    async def test_receipt_id_has_exactly_five_trailing_digits(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        suffix = receipt.receipt_id[len("REC-"):]
        assert len(suffix) == 8
        assert all(c in "0123456789abcdef" for c in suffix)

    @pytest.mark.asyncio
    async def test_two_receipts_have_different_ids(self, engine):
        """Consecutive calls should produce unique IDs (with overwhelming probability)."""
        ids = set()
        for _ in range(20):
            with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
                 patch(_PATCH_AUDIT, new_callable=AsyncMock):
                receipt = await engine.generate_receipt(
                    "CLM-001", "approve", "adjuster_a", _risk(), _claim()
                )
            ids.add(receipt.receipt_id)
        assert len(ids) > 1


# ---------------------------------------------------------------------------
# signature_hash — determinism and tamper detection
# ---------------------------------------------------------------------------

class TestSignatureHash:

    @pytest.mark.asyncio
    async def test_signature_hash_is_non_empty_hex_string(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        # Ed25519 signature is a base64 string, not a hex digest
        assert len(receipt.signature_hash) > 0
        assert isinstance(receipt.signature_hash, str)

    @pytest.mark.asyncio
    async def test_signature_hash_changes_when_action_changes(self, engine):
        """Changing a single field in the signed payload must change the hash."""
        from app.utils.crypto import compute_signature
        base = {
            "receipt_id": "REC-00001",
            "claim_id": "CLM-001",
            "action": "approve",
            "approver": "adjuster_a",
            "identity_confidence": 0.875,
            "fraud_score": 15.0,
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        sig1 = compute_signature(base)["signature"]
        sig2 = compute_signature({**base, "action": "deny"})["signature"]
        assert sig1 != sig2

    @pytest.mark.asyncio
    async def test_signature_hash_changes_when_claim_id_changes(self, engine):
        from app.utils.crypto import compute_signature
        base = {
            "receipt_id": "REC-00001",
            "claim_id": "CLM-001",
            "action": "approve",
            "approver": "adjuster_a",
            "identity_confidence": 0.875,
            "fraud_score": 15.0,
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        sig1 = compute_signature(base)["signature"]
        sig2 = compute_signature({**base, "claim_id": "CLM-999"})["signature"]
        assert sig1 != sig2

    @pytest.mark.asyncio
    async def test_signature_hash_changes_when_approver_changes(self, engine):
        from app.utils.crypto import compute_signature
        base = {
            "receipt_id": "REC-00001",
            "claim_id": "CLM-001",
            "action": "approve",
            "approver": "adjuster_a",
            "identity_confidence": 0.875,
            "fraud_score": 15.0,
            "timestamp": "2024-01-01T00:00:00+00:00",
        }
        sig1 = compute_signature(base)
        sig2 = compute_signature({**base, "approver": "fraud_actor"})
        assert sig1 != sig2

    @pytest.mark.asyncio
    async def test_signature_deterministic_for_same_inputs(self, engine):
        """Same signed fields must always produce the same hash."""
        from app.utils.crypto import compute_signature
        fields = {
            "receipt_id": "REC-55555",
            "claim_id": "CLM-STABLE",
            "action": "approve",
            "approver": "verifier",
            "identity_confidence": 0.9,
            "fraud_score": 5.0,
            "timestamp": "2024-06-01T12:00:00+00:00",
        }
        assert compute_signature(fields) == compute_signature(fields)


# ---------------------------------------------------------------------------
# payout_amount is included in receipt
# ---------------------------------------------------------------------------

class TestPayoutAmount:

    @pytest.mark.asyncio
    async def test_payout_amount_default_zero(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        assert receipt.payout_amount == 0.0

    @pytest.mark.asyncio
    async def test_payout_amount_explicit_value(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim(),
                payout_amount=3500.0,
            )
        assert receipt.payout_amount == 3500.0

    @pytest.mark.asyncio
    async def test_payout_amount_zero_when_denied(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "deny", "adjuster_a", _risk(), _claim(),
                payout_amount=0.0,
            )
        assert receipt.payout_amount == 0.0


# ---------------------------------------------------------------------------
# policy_check and simulation_summary
# ---------------------------------------------------------------------------

class TestPolicyCheckAndSimulationSummary:

    @pytest.mark.asyncio
    async def test_policy_check_includes_policy_number(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a",
                _risk(), _claim(policy_number="AUTO-12345")
            )
        assert "AUTO-12345" in receipt.policy_check

    @pytest.mark.asyncio
    async def test_policy_check_indicates_covered(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a",
                _risk(), _claim(covered=True)
            )
        assert "covered" in receipt.policy_check

    @pytest.mark.asyncio
    async def test_policy_check_indicates_not_covered(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "deny", "adjuster_a",
                _risk(), _claim(covered=False)
            )
        assert "not covered" in receipt.policy_check

    @pytest.mark.asyncio
    async def test_policy_check_includes_coverage_limit(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a",
                _risk(), _claim(coverage_limit=75000.0)
            )
        assert "75,000.00" in receipt.policy_check

    @pytest.mark.asyncio
    async def test_policy_check_fallback_when_no_coverage_result(self, engine):
        claim_no_coverage = {"id": "CLM-001", "claimant_name": "Test"}
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), claim_no_coverage
            )
        assert "No policy information available" in receipt.policy_check

    @pytest.mark.asyncio
    async def test_simulation_summary_includes_approval_probability(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim(with_simulation=True)
            )
        assert "0.85" in receipt.simulation_summary

    @pytest.mark.asyncio
    async def test_simulation_summary_fallback_when_no_simulation(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim(with_simulation=False)
            )
        assert "No simulation data available" in receipt.simulation_summary


# ---------------------------------------------------------------------------
# confidence scores from risk assessment
# ---------------------------------------------------------------------------

class TestConfidenceFields:

    @pytest.mark.asyncio
    async def test_identity_confidence_from_risk_assessment(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a",
                _risk(identity_confidence=0.72), _claim()
            )
        assert receipt.identity_confidence == 0.72

    @pytest.mark.asyncio
    async def test_fraud_score_from_risk_assessment(self, engine):
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a",
                _risk(fraud_score=42.0), _claim()
            )
        assert receipt.fraud_score == 42.0


# ---------------------------------------------------------------------------
# DB side-effects: update_claim and add_audit_entry are called
# ---------------------------------------------------------------------------

class TestDbSideEffects:

    @pytest.mark.asyncio
    async def test_update_claim_called_once(self, engine):
        mock_update = AsyncMock()
        with patch(_PATCH_UPDATE, mock_update), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        mock_update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_claim_called_with_correct_claim_id(self, engine):
        mock_update = AsyncMock()
        with patch(_PATCH_UPDATE, mock_update), \
             patch(_PATCH_AUDIT, new_callable=AsyncMock):
            await engine.generate_receipt(
                "CLM-TARGET", "approve", "adjuster_a", _risk(), _claim()
            )
        assert mock_update.call_args[0][0] == "CLM-TARGET"

    @pytest.mark.asyncio
    async def test_add_audit_entry_called_once(self, engine):
        mock_audit = AsyncMock()
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, mock_audit):
            await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        mock_audit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_audit_entry_action_contains_action_name(self, engine):
        mock_audit = AsyncMock()
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, mock_audit):
            await engine.generate_receipt(
                "CLM-001", "deny", "adjuster_a", _risk(), _claim()
            )
        audit_action = mock_audit.call_args[1]["action"] if mock_audit.call_args[1] \
            else mock_audit.call_args[0][1]
        assert "deny" in audit_action

    @pytest.mark.asyncio
    async def test_audit_entry_includes_receipt_id(self, engine):
        mock_audit = AsyncMock()
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, mock_audit):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        # details is either kwarg or 4th positional arg
        call = mock_audit.call_args
        details = call[1].get("details") if call[1] else call[0][3]
        assert details["receipt_id"] == receipt.receipt_id

    @pytest.mark.asyncio
    async def test_audit_entry_includes_signature_hash(self, engine):
        mock_audit = AsyncMock()
        with patch(_PATCH_UPDATE, new_callable=AsyncMock), \
             patch(_PATCH_AUDIT, mock_audit):
            receipt = await engine.generate_receipt(
                "CLM-001", "approve", "adjuster_a", _risk(), _claim()
            )
        call = mock_audit.call_args
        details = call[1].get("details") if call[1] else call[0][3]
        assert "signing_key_id" in details
        assert "signature_algorithm" in details
