"""Evidence and audit API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.database import get_audit_log, get_claim

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claims", tags=["evidence"])


@router.get("/{claim_id}/evidence")
async def get_claim_evidence(claim_id: str) -> dict[str, Any]:
    """Return all evidence for a claim: extracted data, fraud signals,
    Yutori results, coverage, payout recommendation, simulation, and risk assessment."""
    claim = await get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    # Build a comprehensive evidence bundle
    extracted_data = claim.get("extracted_data")
    coverage_result = claim.get("coverage_result")
    payout_recommendation = claim.get("payout_recommendation")
    simulation_result = claim.get("simulation_result")
    risk_assessment = claim.get("risk_assessment")

    # Fraud score details
    fraud_details: dict[str, Any] = {
        "overall_score": claim.get("fraud_score"),
        "risk_level": claim.get("risk_level"),
    }

    # If risk_assessment contains fraud signals, include them
    if isinstance(risk_assessment, dict):
        fraud_details["fraud_concern_level"] = risk_assessment.get("fraud_concern_level")
        fraud_details["identity_confidence"] = risk_assessment.get("identity_confidence")
        fraud_details["document_authenticity_confidence"] = risk_assessment.get(
            "document_authenticity_confidence"
        )

    # Short-circuited claims (fraud > 70) won't have payout or simulation data.
    # Mark them explicitly so the frontend can show an appropriate message.
    short_circuited = (
        claim.get("status") == "blocked"
        and payout_recommendation is None
        and simulation_result is None
        and claim.get("fraud_score") is not None
        and claim.get("fraud_score", 0) > 70
    )

    return {
        "claim_id": claim_id,
        "status": claim.get("status"),
        "claimant_name": claim.get("claimant_name"),
        "incident_description": claim.get("incident_description"),
        "policy_number": claim.get("policy_number"),
        "file_type": claim.get("file_type"),
        "created_at": claim.get("created_at"),
        "extracted_data": extracted_data,
        "fraud_assessment": fraud_details,
        "coverage_result": coverage_result,
        "payout_recommendation": payout_recommendation,
        "simulation_result": simulation_result,
        "risk_assessment": risk_assessment,
        "decision": claim.get("decision"),
        "decision_by": claim.get("decision_by"),
        "decision_at": claim.get("decision_at"),
        "receipt": claim.get("receipt"),
        "short_circuited": short_circuited,
    }


@router.get("/{claim_id}/audit")
async def get_claim_audit(claim_id: str) -> list[dict[str, Any]]:
    """Return the full audit trail for a claim."""
    claim = await get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    audit_entries = await get_audit_log(claim_id)
    return audit_entries
