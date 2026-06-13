"""Payout Recommendation Skill — recommends claim payout via Grok."""

from __future__ import annotations

import logging

from app.models.claim import (
    CoverageResult,
    ExtractedData,
    FraudScore,
    PayoutRecommendation,
)
from app.services.grok_service import grok_service

logger = logging.getLogger(__name__)

SKILL_METADATA = {
    "skill_name": "payout_recommendation_skill",
    "action_category": "claims_payout",
    "read_or_write": "read",
    "money_movement": False,
    "reversible": True,
}


class PayoutRecommendationSkill:
    """Calls Grok to recommend a payout amount for the claim."""

    async def execute(
        self,
        extracted_data: ExtractedData,
        coverage: CoverageResult,
        fraud_score: FraudScore,
    ) -> PayoutRecommendation:
        recommendation = await grok_service.recommend_payout(
            extracted_data, coverage, fraud_score,
        )
        logger.info(
            "Payout recommendation: $%.2f (confidence: %.2f)",
            recommendation.recommended_amount,
            recommendation.confidence,
        )
        return recommendation


# Module-level singleton
payout_recommendation_skill = PayoutRecommendationSkill()
