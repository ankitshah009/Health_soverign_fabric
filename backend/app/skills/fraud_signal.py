"""Fraud Signal Skill — combines Grok fraud assessment with Yutori verification."""

from __future__ import annotations

import logging
from typing import Any

from app.models.claim import ExtractedData, FraudScore
from app.services.grok_service import grok_service

logger = logging.getLogger(__name__)

SKILL_METADATA = {
    "skill_name": "fraud_signal_skill",
    "action_category": "fraud_detection",
    "read_or_write": "read",
    "money_movement": False,
    "reversible": True,
}


def _adjust_score_with_yutori(
    base_score: FraudScore,
    yutori_results: list[dict[str, Any]],
) -> FraudScore:
    """Adjust the fraud score based on Yutori web verification findings.

    Uses entity_type-specific adjustments calibrated for SIU research vectors:
      - claimant_history  +15  (prior fraud is the strongest signal)
      - vehicle_property  +12  (salvage / stolen is very suspicious)
      - repair_provider   +10  (fraud ring connection is serious)
      - incident_corroboration +8  (contradictions are meaningful)
      - financial_stress  +8   (motive indicator)
    High credibility (>0.7) → -3, low credibility (<0.3) → +8, unverified → +2.
    """
    adjustment = 0.0
    extra_signals = []

    # Per-vector risk adjustments when risk_indicators are found
    _risk_adjustment: dict[str, float] = {
        "claimant_history": 15.0,
        "vehicle_property": 12.0,
        "repair_provider": 10.0,
        "incident_corroboration": 8.0,
        "financial_stress": 8.0,
        # Browsing API deep-investigation vectors (second pass)
        "browse_bbb": 12.0,
        "browse_court_records": 15.0,
    }
    _default_risk_adjustment = 10.0

    for result in yutori_results:
        status = result.get("status", "verification_pending")
        entity_name = result.get("entity_name", "unknown")
        entity_type = result.get("entity_type", "unknown")
        results_data = result.get("results", {})

        if status == "completed":
            # Look for risk indicators in successful verification
            risk_indicators = results_data.get("risk_indicators", [])
            credibility = results_data.get("credibility_score")

            if risk_indicators:
                # Yutori found risk indicators — boost fraud score by vector weight
                bump = _risk_adjustment.get(entity_type, _default_risk_adjustment)
                adjustment += bump
                severity = "high" if bump >= 12 else "medium"
                extra_signals.append({
                    "signal_name": f"yutori_risk_{entity_type}",
                    "description": (
                        f"Web research ({entity_type}) on '{entity_name}' revealed "
                        f"risk indicators: {risk_indicators}"
                    ),
                    "severity": severity,
                    "confidence": 0.7,
                })
            elif credibility is not None and isinstance(credibility, (int, float)):
                if credibility > 0.7:
                    # High credibility — small reduction per vector
                    adjustment -= 3.0
                    extra_signals.append({
                        "signal_name": f"yutori_verified_{entity_type}",
                        "description": (
                            f"Web research verified {entity_type} '{entity_name}' "
                            f"with credibility score {credibility}."
                        ),
                        "severity": "low",
                        "confidence": 0.8,
                    })
                elif credibility < 0.3:
                    adjustment += 8.0
                    extra_signals.append({
                        "signal_name": f"yutori_low_credibility_{entity_type}",
                        "description": (
                            f"Web research found low credibility ({credibility}) "
                            f"for {entity_type} '{entity_name}'."
                        ),
                        "severity": "high",
                        "confidence": 0.6,
                    })
            else:
                # Completed but no strong signals either way — slight reduction
                adjustment -= 2.0
                extra_signals.append({
                    "signal_name": f"yutori_neutral_{entity_type}",
                    "description": (
                        f"Web research on {entity_type} '{entity_name}' "
                        "returned no significant risk indicators."
                    ),
                    "severity": "low",
                    "confidence": 0.5,
                })

        elif status == "verification_pending":
            # Could not verify — slight bump (less than before since we have more vectors)
            adjustment += 2.0
            extra_signals.append({
                "signal_name": f"yutori_unverified_{entity_type}",
                "description": (
                    f"Unable to verify {entity_type} '{entity_name}' "
                    "via web research. Verification pending."
                ),
                "severity": "low",
                "confidence": 0.4,
            })

    # Compute adjusted score
    new_score = max(0.0, min(100.0, base_score.overall_score + adjustment))

    # Determine risk level
    if new_score >= 70:
        risk_level = "critical"
    elif new_score >= 50:
        risk_level = "high"
    elif new_score >= 30:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Merge signals
    all_signals = list(base_score.signals) + extra_signals

    return FraudScore(
        overall_score=new_score,
        risk_level=risk_level,
        signals=all_signals,
        explanation=base_score.explanation,
    )


class FraudSignalSkill:
    """Combines Grok-based fraud assessment with Yutori web verification."""

    async def execute(
        self,
        extracted_data: ExtractedData,
        incident_description: str,
        yutori_results: list[dict[str, Any]],
    ) -> FraudScore:
        # Step 1: Get base fraud assessment from Grok
        base_score = await grok_service.assess_fraud(extracted_data, incident_description)
        logger.info(
            "Base fraud score: %.1f (%s)",
            base_score.overall_score,
            base_score.risk_level,
        )

        # Step 2: Adjust based on Yutori verification
        adjusted = _adjust_score_with_yutori(base_score, yutori_results)
        logger.info(
            "Adjusted fraud score: %.1f (%s) [%+.1f from Yutori]",
            adjusted.overall_score,
            adjusted.risk_level,
            adjusted.overall_score - base_score.overall_score,
        )

        return adjusted


# Module-level singleton
fraud_signal_skill = FraudSignalSkill()
