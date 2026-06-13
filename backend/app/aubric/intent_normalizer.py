"""Aubric Intent Normalizer — converts raw skill actions into typed action objects."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class IntentNormalizer:
    """Rules-based normalizer that converts raw action proposals into typed action objects."""

    def normalize(self, raw_action: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw action proposal from any skill into a standardized format.

        Args:
            raw_action: Dict with keys like skill_metadata, claim_id, monetary_value, etc.

        Returns:
            Normalized action dict with standardized fields.
        """
        skill_meta = raw_action.get("skill_metadata", {})
        claim_id = raw_action.get("claim_id", "unknown")
        monetary_value = raw_action.get("monetary_value", 0.0)

        # Determine action type from skill metadata
        action_category = skill_meta.get("action_category", "unknown")
        read_or_write = skill_meta.get("read_or_write", "read")
        money_movement = skill_meta.get("money_movement", False)
        reversible = skill_meta.get("reversible", True)

        # Map action category to type
        action_type_map = {
            "claims_processing": "process_claim",
            "fraud_detection": "assess_fraud",
            "claims_payout": "execute_payout" if money_movement else "recommend_payout",
        }
        action_type = action_type_map.get(action_category, "unknown_action")

        # Determine severity based on monetary value and action nature
        if money_movement and monetary_value > 10000:
            severity = "high"
        elif money_movement and monetary_value > 1000:
            severity = "medium"
        elif money_movement:
            severity = "low"
        elif action_category == "fraud_detection":
            severity = "medium"
        else:
            severity = "low"

        # Determine what checks are needed
        requires_identity_check = money_movement or (
            read_or_write == "write" and not reversible
        )
        requires_document_check = action_category in (
            "claims_processing", "fraud_detection",
        )

        normalized = {
            "action_type": action_type,
            "claim_id": claim_id,
            "severity": severity,
            "monetary_value": float(monetary_value),
            "requires_identity_check": requires_identity_check,
            "requires_document_check": requires_document_check,
            "is_reversible": reversible,
            "money_movement": money_movement,
            "read_or_write": read_or_write,
            "source_skill": skill_meta.get("skill_name", "unknown"),
            "required_approval_role": skill_meta.get("required_approval_role"),
        }

        logger.info(
            "Normalized action: %s | %s | severity=%s | money=%s",
            claim_id, action_type, severity, money_movement,
        )

        return normalized


# Module-level singleton
intent_normalizer = IntentNormalizer()
