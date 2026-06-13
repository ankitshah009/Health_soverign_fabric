"""Aubric Receipt Engine -- generates tamper-evident decision receipts."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.database import add_audit_entry, update_claim
from app.models.decision import DecisionReceipt
from app.utils.crypto import compute_signature, generate_receipt_id
from app.services.webhook_dispatcher import fire_event, EVENT_RECEIPT_GENERATED

logger = logging.getLogger(__name__)


class ReceiptEngine:
    """Generates signed decision receipts for claim actions."""

    async def generate_receipt(
        self,
        claim_id: str,
        action: str,
        approver: str,
        risk_assessment: dict[str, Any],
        claim_data: dict[str, Any],
        payout_amount: float = 0.0,
    ) -> DecisionReceipt:
        """Create and persist a decision receipt.

        Args:
            claim_id: The claim this receipt is for.
            action: The decision taken (approve, deny, escalate).
            approver: Who made the decision.
            risk_assessment: Output from RiskEngine.evaluate().
            claim_data: Current claim record from DB.

        Returns:
            A signed DecisionReceipt.
        """
        now = datetime.now(timezone.utc).isoformat()
        receipt_id = generate_receipt_id()

        # Extract values from risk assessment
        identity_confidence = risk_assessment.get("identity_confidence", 0.0)
        fraud_score_val = risk_assessment.get("fraud_score", 0.0)

        # Build policy check summary
        coverage = claim_data.get("coverage_result")
        if isinstance(coverage, dict):
            policy_check = (
                f"Policy {coverage.get('policy_number', 'N/A')}: "
                f"{'covered' if coverage.get('covered') else 'not covered'}. "
                f"Type: {coverage.get('coverage_type', 'N/A')}. "
                f"Limit: ${coverage.get('coverage_limit', 0):,.2f}."
            )
        else:
            policy_check = "No policy information available."

        # Build simulation summary
        sim = claim_data.get("simulation_result")
        if isinstance(sim, dict):
            simulation_summary = (
                f"Approval probability: {sim.get('approval_probability', 'N/A')}. "
                f"Dispute risk: {sim.get('dispute_risk', 'N/A')}. "
                f"Recommended: {sim.get('recommended_action', 'N/A')}."
            )
        else:
            simulation_summary = "No simulation data available."

        # Sign EXACTLY the fields the DecisionReceipt will carry (minus the
        # signature fields and the derived signature_hash). This payload must
        # match what TrustSigner.verify() reconstructs from the full receipt, or
        # verification fails. Values are rounded here to match what is stored.
        requested_by = claim_data.get("claimant_name", "unknown")
        id_conf_rounded = round(identity_confidence, 3)
        fraud_rounded = round(fraud_score_val, 1)
        sig_data = {
            "receipt_id": receipt_id,
            "claim_id": claim_id,
            "action": action,
            "requested_by": requested_by,
            "approved_by": approver,
            "identity_confidence": id_conf_rounded,
            "fraud_score": fraud_rounded,
            "policy_check": policy_check,
            "simulation_summary": simulation_summary,
            "payout_amount": payout_amount,
            "timestamp": now,
        }

        # Sign with Ed25519 -- returns dict with signature, public_key,
        # signature_algorithm, signing_key_id
        sig_result = compute_signature(sig_data)

        # Legacy field kept for backwards compat — use the full Ed25519 signature
        signature_hash = sig_result["signature"]

        receipt = DecisionReceipt(
            receipt_id=receipt_id,
            claim_id=claim_id,
            action=action,
            requested_by=requested_by,
            approved_by=approver,
            identity_confidence=id_conf_rounded,
            fraud_score=fraud_rounded,
            policy_check=policy_check,
            simulation_summary=simulation_summary,
            payout_amount=payout_amount,
            timestamp=now,
            signature_hash=signature_hash,
            signature=sig_result["signature"],
            public_key=sig_result["public_key"],
            signature_algorithm=sig_result["signature_algorithm"],
            signing_key_id=sig_result["signing_key_id"],
        )

        # Persist receipt to claim record
        await update_claim(claim_id, receipt=receipt.model_dump())

        # Audit trail
        await add_audit_entry(
            claim_id=claim_id,
            action=f"receipt_generated_{action}",
            actor=approver,
            details={
                "receipt_id": receipt_id,
                "signature_algorithm": sig_result["signature_algorithm"],
                "signing_key_id": sig_result["signing_key_id"],
                "risk_level": risk_assessment.get("action_risk_level"),
            },
        )

        # Fire webhook event
        fire_event(
            EVENT_RECEIPT_GENERATED,
            {
                "claim_id": claim_id,
                "receipt_id": receipt_id,
                "action": action,
                "approver": approver,
                "signing_key_id": sig_result["signing_key_id"],
            },
        )

        logger.info(
            "Receipt generated: %s for claim %s (action=%s, approver=%s, key_id=%s)",
            receipt_id, claim_id, action, approver, sig_result["signing_key_id"],
        )

        return receipt


# Module-level singleton
receipt_engine = ReceiptEngine()
