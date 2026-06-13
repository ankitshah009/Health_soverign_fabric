"""No Surprises Act complaint API route.

Exposes POST /api/cases/{case_id}/complaint — drafts a formal federal
No Surprises Act (NSA) complaint to CMS for a stored case, citing the
specific illegal balance-billing / surprise out-of-network violations
detected during the pipeline, and requesting the federal complaint + IDR
(Independent Dispute Resolution) process.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.database import get_claim
from app.models.claim import ExtractedData, FraudScore
from app.services.grok_service import grok_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cases", tags=["complaint"])


@router.post("/{case_id}/complaint")
async def file_nsa_complaint(case_id: str) -> dict[str, Any]:
    """Draft a formal federal No Surprises Act complaint for a case.

    Loads the stored case, reconstructs the ExtractedData + FraudScore from the
    persisted fields (mirroring how the pipeline stores them), and asks Grok to
    draft a regulator complaint to CMS citing the specific NSA / balance-billing
    violations found. Returns the complaint dict (agency, contact, subject, body,
    key_facts). Returns 404 if the case is missing.
    """
    claim = await get_claim(case_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")

    # Reconstruct ExtractedData from the stored dict (pipeline persists it via
    # extracted_data=extracted_data.model_dump()).
    extracted_raw = claim.get("extracted_data")
    if isinstance(extracted_raw, dict):
        try:
            extracted_data = ExtractedData(**extracted_raw)
        except Exception:
            extracted_data = ExtractedData()
    else:
        extracted_data = ExtractedData()

    # Reconstruct FraudScore from the persisted top-level fields:
    #   fraud_score   (float)        -> overall_score
    #   risk_level    (str)          -> risk_level
    #   fraud_signals (list[dict])   -> signals
    fraud_score_val = claim.get("fraud_score")
    fraud_signals_raw = claim.get("fraud_signals") or []
    if not isinstance(fraud_signals_raw, list):
        fraud_signals_raw = []

    try:
        fraud_score = FraudScore(
            overall_score=float(fraud_score_val) if fraud_score_val is not None else 0.0,
            risk_level=claim.get("risk_level") or "low",
            signals=fraud_signals_raw,
            explanation=claim.get("incident_description") or "",
        )
    except Exception:
        # Fall back to a minimal FraudScore so drafting can still proceed.
        fraud_score = FraudScore(
            overall_score=float(fraud_score_val) if fraud_score_val is not None else 0.0,
            risk_level="low",
        )

    complaint = await grok_service.draft_complaint(extracted_data, fraud_score)
    return {"case_id": case_id, **complaint}
