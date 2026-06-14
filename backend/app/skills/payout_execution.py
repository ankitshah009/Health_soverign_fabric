"""Recovery Execution Skill — records the patient-authorized filing of an appeal/dispute (mock for demo).

The "amount" is the patient's estimated RECOVERABLE total (overcharges to be removed +
wrongly-denied amount to be restored), not an insurer payout. "Execution" here means
recording the patient's consent and filing the appeal/dispute on their behalf — no real
money moves in this demo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.database import add_audit_entry, update_claim
from app.models.decision import DecisionReceipt
from app.utils.crypto import compute_signature, generate_receipt_id

logger = logging.getLogger(__name__)

SKILL_METADATA = {
    "skill_name": "payout_execution_skill",
    "action_category": "claims_payout",
    "read_or_write": "write",
    "money_movement": True,
    "identity_impact": False,
    "external_communication": True,
    "reversible": False,
    # Patient-side: the patient authorizes filing on their own behalf (consent).
    # There is no insurer-side claims role in this product.
    "required_approval_role": "patient",
}


class PayoutExecutionSkill:
    """Files the appeal/dispute after the patient's consent. Mock — no real money moves."""

    async def execute(
        self,
        claim_id: str,
        approved_by: str,
        amount: float,
    ) -> DecisionReceipt:
        now = datetime.now(timezone.utc).isoformat()
        receipt_id = generate_receipt_id()

        # Build signature fields
        sig_fields = {
            "receipt_id": receipt_id,
            "claim_id": claim_id,
            "action": "payout_approved",
            "approved_by": approved_by,
            "amount": amount,
            "timestamp": now,
        }
        sig_result = compute_signature(sig_fields)

        receipt = DecisionReceipt(
            receipt_id=receipt_id,
            claim_id=claim_id,
            action="payout_approved",
            requested_by="system",
            approved_by=approved_by,
            identity_confidence=0.95,
            fraud_score=0.0,  # Will be overwritten by caller if available
            policy_check="passed",
            simulation_summary=(
                f"Appeal/dispute filed for an estimated ${amount:,.2f} in recoverable "
                f"charges, authorized by {approved_by}."
            ),
            timestamp=now,
            signature_hash=sig_result["signature"],
            signature=sig_result["signature"],
            public_key=sig_result["public_key"],
            signature_algorithm=sig_result["signature_algorithm"],
            signing_key_id=sig_result["signing_key_id"],
        )

        # Update claim in DB
        await update_claim(
            claim_id,
            status="approved",
            decision="approve",
            decision_by=approved_by,
            decision_at=now,
            receipt=receipt.model_dump(),
        )

        # Audit trail
        await add_audit_entry(
            claim_id=claim_id,
            action="payout_executed",
            actor=approved_by,
            details={
                "receipt_id": receipt_id,
                "amount": amount,
                "signature_hash": sig_result["signature"],
                "note": "Mock filing — appeal/dispute recorded; no real money transferred.",
            },
        )

        logger.info(
            "Recovery filing executed: %s | %s | $%.2f recoverable | receipt=%s",
            claim_id, approved_by, amount, receipt_id,
        )

        return receipt


# Module-level singleton
payout_execution_skill = PayoutExecutionSkill()
