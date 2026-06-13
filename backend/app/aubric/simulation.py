"""Aubric Simulation Engine — predicts claim outcomes via Grok."""

from __future__ import annotations

import logging
from typing import Any

from app.models.claim import FraudScore, PayoutRecommendation, SimulationResult
from app.services.grok_service import grok_service

logger = logging.getLogger(__name__)


class SimulationEngine:
    """Uses Grok to simulate probable claim outcomes."""

    async def simulate(
        self,
        claim_data: dict[str, Any],
        fraud_score: FraudScore,
        payout_rec: PayoutRecommendation,
    ) -> SimulationResult:
        """Run outcome simulation for a claim.

        Args:
            claim_data: Current claim record dict.
            fraud_score: Computed fraud score.
            payout_rec: Payout recommendation.

        Returns:
            SimulationResult with probabilities and risk estimates.
        """
        result = await grok_service.simulate_outcome(
            claim_data, fraud_score, payout_rec,
        )
        logger.info(
            "Simulation complete for %s: approval_prob=%.2f, dispute_risk=%.2f, "
            "recommended=%s",
            claim_data.get("id", "?"),
            result.approval_probability,
            result.dispute_risk,
            result.recommended_action,
        )
        return result


# Module-level singleton
simulation_engine = SimulationEngine()
