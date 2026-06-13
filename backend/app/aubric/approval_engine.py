"""Aubric Approval Engine — validates decisions against risk assessments."""

from __future__ import annotations

import logging
from typing import Any

from app.database import add_audit_entry

logger = logging.getLogger(__name__)


class ApprovalEngine:
    """Validates that approval decisions comply with risk engine requirements."""

    async def process_approval(
        self,
        claim_id: str,
        decision: str,
        approver: str,
        risk_assessment: dict[str, Any],
    ) -> dict[str, Any]:
        """Process an approval/denial decision, validating against risk constraints.

        Args:
            claim_id: The claim being decided on.
            decision: One of 'approve', 'deny', 'escalate'.
            approver: Name/ID of the person making the decision.
            risk_assessment: Output from RiskEngine.evaluate().

        Returns:
            Dict with approved (bool), reason, and details.
        """
        recommended_action = risk_assessment.get("recommended_action", "require_human")
        fraud_score = risk_assessment.get("fraud_score", 0)

        # ── Rule 1: If risk says "block", nobody can approve ─────────────
        if recommended_action == "block" and decision == "approve":
            reason = (
                f"BLOCKED: Fraud score ({fraud_score:.0f}/100) exceeds critical threshold. "
                "Claim cannot be approved without SIU investigation clearance. "
                "Decision overridden to 'deny'."
            )
            await add_audit_entry(
                claim_id, "approval_blocked", approver,
                {"attempted_decision": decision, "reason": reason},
            )
            logger.warning("Approval blocked for %s by risk engine", claim_id)
            return {
                "approved": False,
                "decision": "deny",
                "reason": reason,
                "override_applied": True,
            }

        # ── Rule 2: If risk says "escalate_fraud", only SIU can approve ──
        if recommended_action == "escalate_fraud" and decision == "approve":
            if approver.lower() not in ("siu_investigator", "siu", "fraud_unit"):
                reason = (
                    f"ESCALATED: Fraud score ({fraud_score:.0f}/100) requires SIU review. "
                    f"Approver '{approver}' does not have SIU authority. "
                    "Only 'siu_investigator' role can approve escalated claims."
                )
                await add_audit_entry(
                    claim_id, "approval_escalation_required", approver,
                    {"attempted_decision": decision, "reason": reason},
                )
                logger.warning(
                    "Approval denied for %s: SIU required, got %s",
                    claim_id, approver,
                )
                return {
                    "approved": False,
                    "decision": "escalate",
                    "reason": reason,
                    "override_applied": True,
                }

        # ── Rule 3: Denial is always allowed ─────────────────────────────
        if decision == "deny":
            await add_audit_entry(
                claim_id, "claim_denied", approver,
                {"decision": "deny", "risk_action": recommended_action},
            )
            logger.info("Claim %s denied by %s", claim_id, approver)
            return {
                "approved": True,  # The denial was successfully processed
                "decision": "deny",
                "reason": f"Claim denied by {approver}.",
                "override_applied": False,
            }

        # ── Rule 4: Escalation request ───────────────────────────────────
        if decision == "escalate":
            await add_audit_entry(
                claim_id, "claim_escalated", approver,
                {"decision": "escalate", "risk_action": recommended_action},
            )
            logger.info("Claim %s escalated by %s", claim_id, approver)
            return {
                "approved": True,
                "decision": "escalate",
                "reason": f"Claim escalated for further review by {approver}.",
                "override_applied": False,
            }

        # ── Rule 5: Standard approval ────────────────────────────────────
        await add_audit_entry(
            claim_id, "claim_approved", approver,
            {
                "decision": "approve",
                "risk_action": recommended_action,
                "fraud_score": fraud_score,
            },
        )
        logger.info("Claim %s approved by %s", claim_id, approver)
        return {
            "approved": True,
            "decision": "approve",
            "reason": f"Claim approved by {approver}. Risk level: {risk_assessment.get('action_risk_level', 'unknown')}.",
            "override_applied": False,
        }


# Module-level singleton
approval_engine = ApprovalEngine()
