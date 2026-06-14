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
        """Process the patient's consent/decline decision, validating against the consent gate.

        Args:
            claim_id: The case being decided on.
            decision: One of 'approve' (the patient consents to file), 'deny'
                (the patient declines), 'escalate' (route for manual review).
            approver: Name/ID of the patient giving or declining consent.
            risk_assessment: Output from RiskEngine.evaluate().

        Returns:
            Dict with approved (bool), reason, and details.
        """
        recommended_action = risk_assessment.get("recommended_action", "require_consent")
        # NOTE: fraud_score here is OVERCHARGE-SEVERITY (how strong the patient's case
        # is), not a score against the patient.
        fraud_score = risk_assessment.get("fraud_score", 0)

        # ── Rule 1: If a step is hard-gated for manual review, it can't auto-file ──
        # (Defensive: the patient-side risk engine normally only returns
        # 'require_consent' / 'auto_approve', so this branch is a safety net.)
        if recommended_action == "block" and decision == "approve":
            reason = (
                "HOLD: This case is flagged for manual review before Sovereign can file "
                "on the patient's behalf. Filing is paused pending that review."
            )
            await add_audit_entry(
                claim_id, "approval_blocked", approver,
                {"attempted_decision": decision, "reason": reason},
            )
            logger.warning("Filing paused for %s pending manual review", claim_id)
            return {
                "approved": False,
                "decision": "deny",
                "reason": reason,
                "override_applied": True,
            }

        # ── Rule 2: If the case needs a specialist's sign-off, gate on that role ──
        # (Defensive safety net; not emitted by the patient-side risk engine.)
        if recommended_action == "escalate_fraud" and decision == "approve":
            if approver.lower() not in ("billing_advocate", "case_reviewer", "supervisor"):
                reason = (
                    "ESCALATED: This case needs a billing advocate / case reviewer to "
                    f"sign off before filing. '{approver}' is not authorized to approve "
                    "an escalated case. Route it to a 'billing_advocate' reviewer."
                )
                await add_audit_entry(
                    claim_id, "approval_escalation_required", approver,
                    {"attempted_decision": decision, "reason": reason},
                )
                logger.warning(
                    "Filing held for %s: reviewer sign-off required, got %s",
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
