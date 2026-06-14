"""Approvals API routes — process decisions and retrieve receipts."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.aubric.approval_engine import approval_engine
from app.aubric.intent_normalizer import intent_normalizer
from app.aubric.receipt_engine import receipt_engine
from app.aubric.risk_engine import risk_engine
from app.database import add_audit_entry, get_claim, list_claims, update_claim
from app.models.claim import FraudScore
from app.models.decision import ApprovalRequest, DecisionReceipt
from app.skills.payout_execution import payout_execution_skill

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["approvals"])


@router.post("/approvals", response_model=dict[str, Any])
async def process_approval(request: ApprovalRequest) -> dict[str, Any]:
    """Process an approval, denial, or escalation decision for a claim."""
    # 1. Validate claim exists
    claim = await get_claim(request.claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {request.claim_id} not found.")

    # 2. Get or recompute risk assessment
    risk_assessment = claim.get("risk_assessment")
    if risk_assessment is None:
        # Recompute if missing
        fraud_score_val = claim.get("fraud_score", 0.0)
        payout_rec = claim.get("payout_recommendation", {})
        monetary_value = 0.0
        if isinstance(payout_rec, dict):
            monetary_value = payout_rec.get("recommended_amount", 0.0)

        fraud_score = FraudScore(
            overall_score=fraud_score_val or 0.0,
            risk_level=claim.get("risk_level", "medium"),
        )

        normalized = intent_normalizer.normalize({
            "skill_metadata": {
                "skill_name": "payout_execution_skill",
                "action_category": "claims_payout",
                "read_or_write": "write",
                "money_movement": True,
                "reversible": False,
                "required_approval_role": "adjuster",
            },
            "claim_id": request.claim_id,
            "monetary_value": monetary_value,
        })

        risk_assessment = await risk_engine.evaluate(normalized, fraud_score, claim)

    # 3. Run Aubric approval engine
    approval_result = await approval_engine.process_approval(
        claim_id=request.claim_id,
        decision=request.decision.value,
        approver=request.approver_name,
        risk_assessment=risk_assessment,
    )

    final_decision = approval_result["decision"]

    # 4. If approved, execute payout
    payout_receipt = None
    if final_decision == "approve" and approval_result.get("approved"):
        payout_rec = claim.get("payout_recommendation", {})
        amount = 0.0
        if isinstance(payout_rec, dict):
            amount = payout_rec.get("recommended_amount", 0.0)

        if amount > 0:
            payout_receipt = await payout_execution_skill.execute(
                claim_id=request.claim_id,
                approved_by=request.approver_name,
                amount=amount,
            )

    # 5. Generate decision receipt
    # Refresh claim data after potential payout execution
    claim = await get_claim(request.claim_id) or claim

    # Determine payout amount for the receipt
    payout_amount = 0.0
    if payout_receipt:
        payout_amount = payout_receipt.payout_amount or 0.0
    elif final_decision == "approve":
        pr = claim.get("payout_recommendation", {})
        if isinstance(pr, dict):
            payout_amount = pr.get("recommended_amount", 0.0)

    receipt: DecisionReceipt = await receipt_engine.generate_receipt(
        claim_id=request.claim_id,
        action=final_decision,
        approver=request.approver_name,
        risk_assessment=risk_assessment,
        claim_data=claim,
        payout_amount=payout_amount,
    )

    # 6. Update claim status
    status_map = {
        "approve": "approved",
        "deny": "denied",
        "escalate": "escalated",
    }
    new_status = status_map.get(final_decision, "pending_review")

    await update_claim(
        request.claim_id,
        status=new_status,
        decision=final_decision,
        decision_by=request.approver_name,
        decision_at=receipt.timestamp,
    )

    # 7. Add notes to audit if provided
    if request.notes:
        await add_audit_entry(
            request.claim_id,
            "decision_notes",
            request.approver_name,
            {"notes": request.notes, "decision": final_decision},
        )

    return {
        "success": approval_result.get("approved", False),
        "claim_id": request.claim_id,
        "decision": final_decision,
        "reason": approval_result.get("reason", ""),
        "override_applied": approval_result.get("override_applied", False),
        "receipt": receipt.model_dump(),
        "payout_receipt": payout_receipt.model_dump() if payout_receipt else None,
    }


@router.get("/claims/{claim_id}/receipt")
async def get_claim_receipt(claim_id: str) -> dict[str, Any]:
    """Get the decision receipt for a claim."""
    claim = await get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")

    receipt = claim.get("receipt")
    if receipt is None:
        raise HTTPException(
            status_code=404,
            detail=f"No receipt found for claim {claim_id}. Decision may not have been made yet.",
        )

    return receipt


@router.get("/receipts/{receipt_id}")
async def get_receipt_by_id(receipt_id: str) -> dict[str, Any]:
    """Fetch a signed decision receipt by its receipt_id.

    Powers the short ``/verify?id=<receipt_id>`` QR-code flow: the QR encodes
    only the compact receipt_id, and the verify page calls this endpoint to
    retrieve the full receipt dict before running Ed25519 verification.
    """
    for claim in await list_claims():
        receipt = claim.get("receipt")
        if isinstance(receipt, dict) and receipt.get("receipt_id") == receipt_id:
            return receipt

    raise HTTPException(
        status_code=404,
        detail=f"No receipt found with receipt_id {receipt_id}.",
    )
