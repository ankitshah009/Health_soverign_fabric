"""Aubric Risk Engine — evaluates actions and determines authorization requirements."""

from __future__ import annotations

import logging
from typing import Any

from app.models.claim import FraudScore

logger = logging.getLogger(__name__)


class RiskEngine:
    """Evaluates risk for a proposed action and decides authorization path."""

    async def evaluate(
        self,
        normalized_action: dict[str, Any],
        fraud_score: FraudScore,
        claim_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute risk assessment and determine required authorization.

        Returns:
            Dict with action_risk_level, identity_confidence,
            document_authenticity_confidence, fraud_concern_level,
            approval_threshold, and recommended_action.
        """
        score = fraud_score.overall_score
        money_movement = normalized_action.get("money_movement", False)
        monetary_value = normalized_action.get("monetary_value", 0.0)

        # ── Determine recommended_action based on rules ───────────────────
        recommended_action: str

        # Patient-side: a HIGH overcharge score is the patient's STRONGEST case,
        # never a reason to block. Gate only on whether the action acts on the
        # patient's behalf or discloses their data (file appeal / share record):
        # those need the patient's explicit consent. Read-only steps auto-approve.
        read_or_write = normalized_action.get("read_or_write", "read")
        acts_on_behalf = money_movement or read_or_write == "write"
        recommended_action = "require_consent" if acts_on_behalf else "auto_approve"

        # ── Risk level ────────────────────────────────────────────────────
        action_risk_level = "medium" if recommended_action == "require_consent" else "low"

        # ── Confidence scores ─────────────────────────────────────────────
        # We represent the patient: identity is trusted, the bill is their own
        # real document, and "concern" now reads as overcharge severity.
        identity_confidence = 0.95
        document_authenticity = 0.92
        fraud_concern = min(1.0, score / 100.0)

        # Approval threshold — minimum confidence needed to proceed
        approval_threshold = 0.8 if recommended_action == "require_consent" else 0.5

        assessment = {
            "action_risk_level": action_risk_level,
            "identity_confidence": round(identity_confidence, 3),
            "document_authenticity_confidence": round(document_authenticity, 3),
            "fraud_concern_level": round(fraud_concern, 3),
            "approval_threshold": approval_threshold,
            "recommended_action": recommended_action,
            "fraud_score": score,
            "monetary_value": monetary_value,
            "money_movement": money_movement,
            "reasoning": _build_reasoning(
                score, monetary_value, money_movement, recommended_action
            ),
        }

        logger.info(
            "Risk assessment for %s: %s (fraud=%.1f, amount=$%.2f)",
            normalized_action.get("claim_id", "?"),
            recommended_action,
            score,
            monetary_value,
        )

        return assessment


def _build_reasoning(
    fraud_score: float,
    amount: float,
    money_movement: bool,
    action: str,
) -> str:
    """Build a human-readable reasoning string."""
    parts: list[str] = []
    if fraud_score >= 70:
        parts.append(
            f"Strong case: overcharge / billing-error severity {fraud_score:.0f}/100. "
            "Clear grounds to dispute and appeal on the patient's behalf."
        )
    elif fraud_score >= 40:
        parts.append(
            f"Moderate case: overcharge severity {fraud_score:.0f}/100. "
            "Worth disputing the flagged charges."
        )
    else:
        parts.append(
            f"Low overcharge severity ({fraud_score:.0f}/100). "
            "Review the bill, but recovery may be limited."
        )

    if action == "require_consent":
        parts.append(
            "This step acts on the patient's behalf or discloses their data, so it "
            "requires the patient's explicit consent before Sovereign proceeds."
        )
    else:
        parts.append("Read-only step — no patient consent required.")

    return " ".join(parts)


# Module-level singleton
risk_engine = RiskEngine()
