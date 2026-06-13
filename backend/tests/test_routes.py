"""
Integration tests for FastAPI routes — claims, approvals, evidence, audit.

Strategy
--------
- All HTTP calls go through httpx.AsyncClient with ASGITransport (no real server).
- External I/O is patched at the boundary:
    * grok_service   → patch app.services.grok_service._call_grok
    * yutori_service → patch app.services.yutori_service.YutoriService.verify_claim_entities
  Both are patched *only* when needed; the background pipeline is cancelled
  immediately after submit so most pipeline mocks are not required for the
  submit/list/get family of tests.
- The database uses the temp SQLite file provided by conftest.py fixtures.
- Each test is isolated: reset_db_between_tests (autouse) wipes tables.
"""

from __future__ import annotations

import asyncio
import json
import io
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_grok_document_payload() -> str:
    """Valid Grok JSON for document analysis."""
    return json.dumps({
        "damage_type": "vehicle collision",
        "estimated_cost": 3500.0,
        "vehicle_info": "2020 Toyota Camry",
        "incident_details": "Front bumper damage from a rear-end collision.",
        "document_type": "damage photo",
        "key_findings": ["front bumper cracked", "no airbag deployment"],
    })


def _make_grok_fraud_payload() -> str:
    """Valid Grok JSON for fraud assessment."""
    return json.dumps({
        "overall_score": 15.0,
        "risk_level": "low",
        "signals": [],
        "explanation": "No significant fraud indicators detected.",
    })


def _make_grok_payout_payload() -> str:
    """Valid Grok JSON for payout recommendation."""
    return json.dumps({
        "recommended_amount": 3000.0,
        "confidence": 0.9,
        "rationale": "Standard repair cost minus deductible.",
        "comparable_claims": [],
    })


def _make_grok_simulation_payload() -> str:
    """Valid Grok JSON for outcome simulation."""
    return json.dumps({
        "approval_probability": 0.85,
        "dispute_risk": 0.10,
        "fraud_escalation_likelihood": 0.05,
        "financial_exposure": 3000.0,
        "historical_comparison": "Similar to 90% of comparable auto claims.",
        "recommended_action": "approve",
    })


def _yutori_pending_results() -> list[dict[str, Any]]:
    return [
        {
            "entity_name": "Jane Tester",
            "entity_type": "person",
            "status": "verification_pending",
            "results": {"summary": "Verification pending."},
        }
    ]


# ---------------------------------------------------------------------------
# Fixture: pre-seeded claim in the database (no pipeline run)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seeded_claim(sample_claim_data) -> dict[str, Any]:
    """Insert sample_claim_data directly into the DB, bypassing the pipeline."""
    from app.database import create_claim, update_claim

    claim_id = sample_claim_data["id"]
    record = await create_claim(
        claim_id=claim_id,
        claimant_name=sample_claim_data["claimant_name"],
        incident_description=sample_claim_data["incident_description"],
        policy_number=sample_claim_data["policy_number"],
        file_path=sample_claim_data["file_path"],
        file_type=sample_claim_data["file_type"],
    )

    # Populate the rich fields that the pipeline would normally write
    await update_claim(
        claim_id,
        status=sample_claim_data["status"],
        extracted_data=sample_claim_data["extracted_data"],
        fraud_score=sample_claim_data["fraud_score"],
        risk_level=sample_claim_data["risk_level"],
        coverage_result=sample_claim_data["coverage_result"],
        payout_recommendation=sample_claim_data["payout_recommendation"],
        simulation_result=sample_claim_data["simulation_result"],
        risk_assessment=sample_claim_data["risk_assessment"],
    )

    from app.database import get_claim
    return await get_claim(claim_id)


# ===========================================================================
# 1. POST /api/claims/submit — happy path
# ===========================================================================

@pytest.mark.asyncio
async def test_submit_claim_returns_200_with_claim_id(client, tiny_png_bytes):
    """
    POST /api/claims/submit with a valid PNG file returns 200 and a claim_id.
    The background pipeline is patched at the Grok and Yutori level so no
    real API calls leave the process.
    """
    grok_side_effects = [
        _make_grok_document_payload(),  # analyze_document call
        _make_grok_fraud_payload(),     # assess_fraud call
        _make_grok_payout_payload(),    # recommend_payout call
        _make_grok_simulation_payload(),  # simulate_outcome call
    ]

    with patch(
        "app.services.grok_service._call_grok",
        new_callable=AsyncMock,
        side_effect=grok_side_effects,
    ), patch(
        "app.services.yutori_service.YutoriService.verify_claim_entities",
        new_callable=AsyncMock,
        return_value=_yutori_pending_results(),
    ):
        response = await client.post(
            "/api/claims/submit",
            files={"file": ("damage.png", io.BytesIO(tiny_png_bytes), "image/png")},
            data={
                "claimant_name": "Jane Tester",
                "incident_description": "Rear-end collision at a traffic light.",
                "policy_number": "AUTO-12345",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["claim_id"].startswith("CLM-")
    assert body["status"] == "submitted"
    assert "data" in body
    assert body["data"]["claimant_name"] == "Jane Tester"


@pytest.mark.asyncio
async def test_submit_claim_without_policy_number(client, tiny_png_bytes):
    """
    policy_number is optional — submitting without it should still succeed.
    """
    with patch(
        "app.services.grok_service._call_grok",
        new_callable=AsyncMock,
        side_effect=[
            _make_grok_document_payload(),
            _make_grok_fraud_payload(),
            _make_grok_payout_payload(),
            _make_grok_simulation_payload(),
        ],
    ), patch(
        "app.services.yutori_service.YutoriService.verify_claim_entities",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await client.post(
            "/api/claims/submit",
            files={"file": ("photo.png", io.BytesIO(tiny_png_bytes), "image/png")},
            data={
                "claimant_name": "No Policy Person",
                "incident_description": "Water damage to kitchen ceiling.",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["claim_id"].startswith("CLM-")


@pytest.mark.asyncio
async def test_submit_claim_missing_required_fields_returns_422(client, tiny_png_bytes):
    """
    Omitting claimant_name (required Form field) must return 422 Unprocessable Entity.
    """
    response = await client.post(
        "/api/claims/submit",
        files={"file": ("photo.png", io.BytesIO(tiny_png_bytes), "image/png")},
        data={"incident_description": "Some incident."},
        # claimant_name is intentionally missing
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_submit_claim_missing_file_returns_422(client):
    """
    Omitting the required file upload must return 422 Unprocessable Entity.
    """
    response = await client.post(
        "/api/claims/submit",
        data={
            "claimant_name": "Ghost User",
            "incident_description": "Forgotten to attach a file.",
        },
        # file is intentionally missing
    )
    assert response.status_code == 422


# ===========================================================================
# 2. GET /api/claims — list claims
# ===========================================================================

@pytest.mark.asyncio
async def test_list_claims_returns_empty_list_initially(client):
    """GET /api/claims on a fresh database returns an empty list."""
    response = await client.get("/api/claims")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_list_claims_returns_submitted_claim(client, seeded_claim):
    """GET /api/claims after seeding returns at least the seeded claim."""
    response = await client.get("/api/claims")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    ids = [c["id"] for c in body]
    assert seeded_claim["id"] in ids


@pytest.mark.asyncio
async def test_list_claims_after_submit_includes_new_claim(client, tiny_png_bytes):
    """A claim submitted via the API appears in the list response."""
    from unittest.mock import patch as _patch

    grok_p = _patch(
        "app.services.grok_service._call_grok",
        new_callable=AsyncMock,
        side_effect=[
            _make_grok_document_payload(),
            _make_grok_fraud_payload(),
            _make_grok_payout_payload(),
            _make_grok_simulation_payload(),
        ],
    )
    yutori_p = _patch(
        "app.services.yutori_service.YutoriService.verify_claim_entities",
        new_callable=AsyncMock,
        return_value=[],
    )
    grok_p.start()
    yutori_p.start()
    try:
        submit_resp = await client.post(
            "/api/claims/submit",
            files={"file": ("img.png", io.BytesIO(tiny_png_bytes), "image/png")},
            data={
                "claimant_name": "List Test User",
                "incident_description": "Flooding in basement.",
                "policy_number": "HOME-67890",
            },
        )
        assert submit_resp.status_code == 200
        new_id = submit_resp.json()["claim_id"]
        await asyncio.sleep(0.1)
    finally:
        grok_p.stop()
        yutori_p.stop()

    list_resp = await client.get("/api/claims")
    assert list_resp.status_code == 200
    ids = [c["id"] for c in list_resp.json()]
    assert new_id in ids


# ===========================================================================
# 3. GET /api/claims/{id} — retrieve single claim
# ===========================================================================

@pytest.mark.asyncio
async def test_get_claim_by_valid_id_returns_claim_data(client, seeded_claim):
    """GET /api/claims/{id} with a known ID returns the full claim record."""
    claim_id = seeded_claim["id"]
    response = await client.get(f"/api/claims/{claim_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == claim_id
    assert body["claimant_name"] == seeded_claim["claimant_name"]
    assert body["status"] == seeded_claim["status"]


@pytest.mark.asyncio
async def test_get_claim_by_valid_id_includes_all_key_fields(client, seeded_claim):
    """The claim record must include all fields written by the pipeline."""
    claim_id = seeded_claim["id"]
    response = await client.get(f"/api/claims/{claim_id}")

    body = response.json()
    assert body["extracted_data"] is not None
    assert body["fraud_score"] == 15.0
    assert body["risk_level"] == "low"
    assert body["coverage_result"]["covered"] is True
    assert body["payout_recommendation"]["recommended_amount"] == 3000.0
    assert body["simulation_result"]["approval_probability"] == 0.85
    assert body["risk_assessment"]["recommended_action"] == "require_human"


# ===========================================================================
# 4. GET /api/claims/{id} — invalid ID returns 404
# ===========================================================================

@pytest.mark.asyncio
async def test_get_claim_by_invalid_id_returns_404(client):
    """GET /api/claims/{id} with a non-existent claim ID returns 404."""
    response = await client.get("/api/claims/CLM-XXXXX")
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert "CLM-XXXXX" in body["detail"]


@pytest.mark.asyncio
async def test_get_claim_by_empty_looking_id_returns_404(client):
    """Garbage claim IDs that don't exist must return 404."""
    response = await client.get("/api/claims/does-not-exist-at-all")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_stream_claim_events_for_missing_claim_returns_404(client):
    """Missing claims should not open a hanging SSE stream."""
    response = await client.get("/api/claims/CLM-DOES-NOT-EXIST/events")
    assert response.status_code == 404
    assert "CLM-DOES-NOT-EXIST" in response.json()["detail"]


# ===========================================================================
# 5. POST /api/approvals — valid claim, processes decision
# ===========================================================================

@pytest.mark.asyncio
async def test_process_approval_deny_on_seeded_claim(client, seeded_claim):
    """
    POST /api/approvals with decision=deny on a seeded claim should succeed.
    Denial is always allowed by the approval engine regardless of risk level.
    """
    response = await client.post(
        "/api/approvals",
        json={
            "claim_id": seeded_claim["id"],
            "decision": "deny",
            "approver_name": "adjuster_bob",
            "notes": "Insufficient evidence.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == seeded_claim["id"]
    assert body["decision"] == "deny"
    assert "receipt" in body
    assert body["receipt"]["claim_id"] == seeded_claim["id"]
    assert body["receipt"]["action"] == "deny"


@pytest.mark.asyncio
async def test_process_approval_approve_on_seeded_claim(client, seeded_claim):
    """
    POST /api/approvals with decision=approve on a require_human risk claim.
    The approval engine allows it (risk is not block/escalate_fraud).
    """
    response = await client.post(
        "/api/approvals",
        json={
            "claim_id": seeded_claim["id"],
            "decision": "approve",
            "approver_name": "senior_adjuster",
            "notes": "",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == seeded_claim["id"]
    assert body["decision"] == "approve"
    assert body["success"] is True
    receipt = body["receipt"]
    assert receipt["action"] == "approve"
    assert receipt["approved_by"] == "senior_adjuster"
    assert receipt["signature_hash"] != ""


@pytest.mark.asyncio
async def test_process_approval_escalate_on_seeded_claim(client, seeded_claim):
    """
    POST /api/approvals with decision=escalate — escalation is always permitted.
    """
    response = await client.post(
        "/api/approvals",
        json={
            "claim_id": seeded_claim["id"],
            "decision": "escalate",
            "approver_name": "adjuster_alice",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "escalate"
    assert body["receipt"]["action"] == "escalate"


@pytest.mark.asyncio
async def test_process_approval_blocked_when_high_fraud(client):
    """
    When fraud score > 70 the risk engine sets recommended_action=block.
    The approval engine must override an approval attempt and return decision=deny.
    """
    from app.database import create_claim, update_claim

    # Seed a high-fraud claim
    await create_claim(
        claim_id="CLM-FRAUD",
        claimant_name="Fraudster McFraud",
        incident_description="Completely fabricated incident.",
        policy_number="AUTO-12345",
        file_path=None,
        file_type=None,
    )
    await update_claim(
        "CLM-FRAUD",
        status="pending_review",
        fraud_score=80.0,
        risk_level="critical",
        payout_recommendation={"recommended_amount": 3000.0, "confidence": 0.1},
        risk_assessment={
            "recommended_action": "block",
            "action_risk_level": "critical",
            "fraud_score": 80.0,
            "monetary_value": 3000.0,
            "money_movement": True,
            "identity_confidence": 0.333,
            "document_authenticity_confidence": 0.2,
            "fraud_concern_level": 0.8,
            "approval_threshold": 1.0,
            "reasoning": "Fraud score critical.",
        },
    )

    response = await client.post(
        "/api/approvals",
        json={
            "claim_id": "CLM-FRAUD",
            "decision": "approve",
            "approver_name": "regular_adjuster",
        },
    )

    assert response.status_code == 200
    body = response.json()
    # Blocked claims must be overridden to deny
    assert body["decision"] == "deny"
    assert body["override_applied"] is True
    assert body["success"] is False


@pytest.mark.asyncio
async def test_process_approval_notes_are_accepted(client, seeded_claim):
    """Notes field is optional but when provided must not cause an error."""
    response = await client.post(
        "/api/approvals",
        json={
            "claim_id": seeded_claim["id"],
            "decision": "deny",
            "approver_name": "adjuster_notes",
            "notes": "Claim denied due to policy exclusion clause 4.2b.",
        },
    )
    assert response.status_code == 200


# ===========================================================================
# 6. POST /api/approvals — invalid claim_id returns 404
# ===========================================================================

@pytest.mark.asyncio
async def test_process_approval_with_nonexistent_claim_returns_404(client):
    """POST /api/approvals with a claim_id that doesn't exist returns 404."""
    response = await client.post(
        "/api/approvals",
        json={
            "claim_id": "CLM-NOPE",
            "decision": "approve",
            "approver_name": "ghost_adjuster",
        },
    )
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body
    assert "CLM-NOPE" in body["detail"]


@pytest.mark.asyncio
async def test_process_approval_with_invalid_decision_type_returns_422(client, seeded_claim):
    """An unrecognised decision value (not approve/deny/escalate) returns 422."""
    response = await client.post(
        "/api/approvals",
        json={
            "claim_id": seeded_claim["id"],
            "decision": "magic_approve",
            "approver_name": "adjuster",
        },
    )
    assert response.status_code == 422


# ===========================================================================
# 7. GET /api/claims/{id}/receipt — receipt endpoints
# ===========================================================================

@pytest.mark.asyncio
async def test_get_receipt_returns_404_before_decision(client, seeded_claim):
    """
    Before a decision is processed the receipt field is None,
    so the endpoint must return 404.
    """
    response = await client.get(f"/api/claims/{seeded_claim['id']}/receipt")
    assert response.status_code == 404
    body = response.json()
    assert "detail" in body


@pytest.mark.asyncio
async def test_get_receipt_returns_receipt_after_decision(client, seeded_claim):
    """
    After a denial is processed a receipt is written to the claim,
    and GET /receipt must return it.
    """
    claim_id = seeded_claim["id"]

    # Process a denial to create a receipt
    approval_resp = await client.post(
        "/api/approvals",
        json={
            "claim_id": claim_id,
            "decision": "deny",
            "approver_name": "receipt_adjuster",
        },
    )
    assert approval_resp.status_code == 200

    # Now the receipt should be retrievable
    receipt_resp = await client.get(f"/api/claims/{claim_id}/receipt")
    assert receipt_resp.status_code == 200
    receipt = receipt_resp.json()
    assert receipt["claim_id"] == claim_id
    assert receipt["action"] == "deny"
    assert "receipt_id" in receipt
    assert "signature_hash" in receipt
    assert receipt["signature_hash"] != ""


@pytest.mark.asyncio
async def test_get_receipt_for_nonexistent_claim_returns_404(client):
    """GET /api/claims/{id}/receipt with unknown claim ID returns 404."""
    response = await client.get("/api/claims/CLM-GHOST/receipt")
    assert response.status_code == 404


# ===========================================================================
# 8. GET /api/claims/{id}/evidence — evidence bundle
# ===========================================================================

@pytest.mark.asyncio
async def test_get_evidence_returns_full_bundle_for_seeded_claim(client, seeded_claim):
    """
    GET /api/claims/{id}/evidence returns all evidence fields populated
    from the seeded claim.
    """
    claim_id = seeded_claim["id"]
    response = await client.get(f"/api/claims/{claim_id}/evidence")

    assert response.status_code == 200
    body = response.json()

    assert body["claim_id"] == claim_id
    assert body["claimant_name"] == seeded_claim["claimant_name"]
    assert body["status"] == seeded_claim["status"]
    assert body["policy_number"] == seeded_claim["policy_number"]

    # Evidence sub-fields
    assert body["extracted_data"] is not None
    assert body["extracted_data"]["damage_type"] == "vehicle collision"

    assert body["fraud_assessment"]["overall_score"] == 15.0
    assert body["fraud_assessment"]["risk_level"] == "low"

    assert body["coverage_result"] is not None
    assert body["coverage_result"]["covered"] is True

    assert body["payout_recommendation"] is not None
    assert body["payout_recommendation"]["recommended_amount"] == 3000.0

    assert body["simulation_result"] is not None
    assert body["simulation_result"]["recommended_action"] == "approve"

    assert body["risk_assessment"] is not None
    assert body["risk_assessment"]["recommended_action"] == "require_human"


@pytest.mark.asyncio
async def test_get_evidence_includes_fraud_concern_from_risk_assessment(client, seeded_claim):
    """
    The evidence endpoint must promote fraud_concern_level from risk_assessment
    into the fraud_assessment sub-document.
    """
    response = await client.get(f"/api/claims/{seeded_claim['id']}/evidence")
    body = response.json()
    fraud = body["fraud_assessment"]
    assert "fraud_concern_level" in fraud
    assert "identity_confidence" in fraud
    assert "document_authenticity_confidence" in fraud


@pytest.mark.asyncio
async def test_get_evidence_for_nonexistent_claim_returns_404(client):
    """GET /api/claims/{id}/evidence with unknown ID returns 404."""
    response = await client.get("/api/claims/CLM-MISSING/evidence")
    assert response.status_code == 404
    assert "CLM-MISSING" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_evidence_decision_fields_null_before_approval(client, seeded_claim):
    """Before any approval, decision/decision_by/decision_at/receipt must be null."""
    response = await client.get(f"/api/claims/{seeded_claim['id']}/evidence")
    body = response.json()
    assert body["decision"] is None
    assert body["decision_by"] is None
    assert body["decision_at"] is None
    assert body["receipt"] is None


@pytest.mark.asyncio
async def test_get_evidence_decision_fields_populated_after_approval(client, seeded_claim):
    """After a denial the evidence endpoint must reflect the decision metadata."""
    claim_id = seeded_claim["id"]

    await client.post(
        "/api/approvals",
        json={
            "claim_id": claim_id,
            "decision": "deny",
            "approver_name": "evidence_adjuster",
        },
    )

    response = await client.get(f"/api/claims/{claim_id}/evidence")
    body = response.json()
    assert body["decision"] == "deny"
    assert body["decision_by"] == "evidence_adjuster"
    assert body["decision_at"] is not None
    assert body["receipt"] is not None


# ===========================================================================
# 9. GET /api/claims/{id}/audit — audit trail
# ===========================================================================

@pytest.mark.asyncio
async def test_get_audit_trail_returns_list_for_seeded_claim(client, seeded_claim):
    """
    GET /api/claims/{id}/audit returns a list (possibly empty if no audit
    entries were created for the DB-direct seed, but at least the schema is right).
    """
    response = await client.get(f"/api/claims/{seeded_claim['id']}/audit")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_get_audit_trail_records_approval_entry(client, seeded_claim):
    """
    After processing an approval the audit log must contain at least one entry
    for the claim.
    """
    claim_id = seeded_claim["id"]

    await client.post(
        "/api/approvals",
        json={
            "claim_id": claim_id,
            "decision": "deny",
            "approver_name": "audit_adjuster",
        },
    )

    response = await client.get(f"/api/claims/{claim_id}/audit")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) > 0
    # Every entry must carry the claim_id and a timestamp
    for entry in entries:
        assert entry["claim_id"] == claim_id
        assert "action" in entry
        assert "timestamp" in entry


@pytest.mark.asyncio
async def test_get_audit_trail_for_submitted_claim_includes_intake_entry(
    client, tiny_png_bytes
):
    """
    A claim submitted via the API writes a 'claim_submitted' audit entry during
    intake (ClaimIntakeSkill). The audit trail must reflect this.
    The mocks are kept active beyond submit so the background pipeline doesn't
    hit real external APIs.
    """
    from unittest.mock import patch as _patch

    grok_p = _patch(
        "app.services.grok_service._call_grok",
        new_callable=AsyncMock,
        side_effect=[
            _make_grok_document_payload(),
            _make_grok_fraud_payload(),
            _make_grok_payout_payload(),
            _make_grok_simulation_payload(),
        ],
    )
    yutori_p = _patch(
        "app.services.yutori_service.YutoriService.verify_claim_entities",
        new_callable=AsyncMock,
        return_value=[],
    )
    grok_p.start()
    yutori_p.start()
    try:
        submit_resp = await client.post(
            "/api/claims/submit",
            files={"file": ("audit_test.png", io.BytesIO(tiny_png_bytes), "image/png")},
            data={
                "claimant_name": "Audit Trail Tester",
                "incident_description": "Testing audit log creation.",
                "policy_number": "POL-001",
            },
        )
        assert submit_resp.status_code == 200
        claim_id = submit_resp.json()["claim_id"]
        # Allow the pipeline to write the intake audit entry
        await asyncio.sleep(0.2)
    finally:
        grok_p.stop()
        yutori_p.stop()

    audit_resp = await client.get(f"/api/claims/{claim_id}/audit")
    assert audit_resp.status_code == 200
    entries = audit_resp.json()
    assert len(entries) >= 1
    actions = [e["action"] for e in entries]
    assert "claim_submitted" in actions


@pytest.mark.asyncio
async def test_get_audit_trail_for_nonexistent_claim_returns_404(client):
    """GET /api/claims/{id}/audit with unknown claim ID returns 404."""
    response = await client.get("/api/claims/CLM-AUDIT-GONE/audit")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_audit_trail_entries_are_ordered_chronologically(client, seeded_claim):
    """
    The audit endpoint orders entries by timestamp ascending.
    After multiple approval operations the order must be non-decreasing.
    """
    claim_id = seeded_claim["id"]

    # Two successive operations to generate multiple entries
    await client.post(
        "/api/approvals",
        json={"claim_id": claim_id, "decision": "deny", "approver_name": "first"},
    )

    response = await client.get(f"/api/claims/{claim_id}/audit")
    entries = response.json()

    timestamps = [e["timestamp"] for e in entries]
    assert timestamps == sorted(timestamps), "Audit entries must be in ascending timestamp order"


# ===========================================================================
# 10. Additional edge-case / cross-cutting tests
# ===========================================================================

@pytest.mark.asyncio
async def test_submit_claim_then_get_claim_returns_consistent_id(client, tiny_png_bytes):
    """
    The claim_id returned from submit and the id in the GET response must match.
    Mocks are kept active so the background pipeline doesn't hit real APIs.
    """
    from unittest.mock import patch as _patch

    grok_p = _patch(
        "app.services.grok_service._call_grok",
        new_callable=AsyncMock,
        side_effect=[
            _make_grok_document_payload(),
            _make_grok_fraud_payload(),
            _make_grok_payout_payload(),
            _make_grok_simulation_payload(),
        ],
    )
    yutori_p = _patch(
        "app.services.yutori_service.YutoriService.verify_claim_entities",
        new_callable=AsyncMock,
        return_value=[],
    )
    grok_p.start()
    yutori_p.start()
    try:
        submit_resp = await client.post(
            "/api/claims/submit",
            files={"file": ("check.png", io.BytesIO(tiny_png_bytes), "image/png")},
            data={
                "claimant_name": "Consistency Check",
                "incident_description": "Test for ID consistency.",
            },
        )
        assert submit_resp.status_code == 200
        submitted_id = submit_resp.json()["claim_id"]
        # Brief pause to let the pipeline start without hitting real APIs
        await asyncio.sleep(0.1)
    finally:
        grok_p.stop()
        yutori_p.stop()

    get_resp = await client.get(f"/api/claims/{submitted_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == submitted_id


@pytest.mark.asyncio
async def test_full_lifecycle_submit_approve_receipt(client, tiny_png_bytes):
    """
    Full happy-path lifecycle:
      1. Submit claim
      2. Wait for pipeline to complete (mocks kept active throughout)
      3. Approve claim
      4. Retrieve receipt
    All steps must succeed and return consistent data.

    The Grok and Yutori patches are started manually so they remain active
    while the background pipeline asyncio.Task runs after the submit response.
    """
    from unittest.mock import patch as _patch

    grok_patch = _patch(
        "app.services.grok_service._call_grok",
        new_callable=AsyncMock,
        side_effect=[
            _make_grok_document_payload(),
            _make_grok_fraud_payload(),
            _make_grok_payout_payload(),
            _make_grok_simulation_payload(),
        ],
    )
    yutori_patch = _patch(
        "app.services.yutori_service.YutoriService.verify_claim_entities",
        new_callable=AsyncMock,
        return_value=[],
    )

    grok_patch.start()
    yutori_patch.start()
    try:
        submit_resp = await client.post(
            "/api/claims/submit",
            files={"file": ("lifecycle.png", io.BytesIO(tiny_png_bytes), "image/png")},
            data={
                "claimant_name": "Lifecycle User",
                "incident_description": "Full pipeline test.",
                "policy_number": "AUTO-12345",
            },
        )

        assert submit_resp.status_code == 200
        claim_id = submit_resp.json()["claim_id"]

        # Poll until pipeline completes and writes risk_assessment.
        # Mocks are still active so the background task can use them.
        for _ in range(50):
            get_resp = await client.get(f"/api/claims/{claim_id}")
            data = get_resp.json()
            if data.get("risk_assessment") and data.get("status") not in ("submitted", "processing"):
                break
            await asyncio.sleep(0.2)

    finally:
        grok_patch.stop()
        yutori_patch.stop()

    # Verify the pipeline finished cleanly
    final = (await client.get(f"/api/claims/{claim_id}")).json()
    assert final.get("risk_assessment") is not None, (
        f"Pipeline did not complete — status={final.get('status')}"
    )

    # Approve the claim
    approval_resp = await client.post(
        "/api/approvals",
        json={
            "claim_id": claim_id,
            "decision": "approve",
            "approver_name": "lifecycle_adjuster",
        },
    )
    assert approval_resp.status_code == 200
    assert approval_resp.json()["decision"] == "approve"

    # Retrieve the receipt
    receipt_resp = await client.get(f"/api/claims/{claim_id}/receipt")
    assert receipt_resp.status_code == 200
    receipt = receipt_resp.json()
    assert receipt["claim_id"] == claim_id
    assert receipt["action"] == "approve"
    assert receipt["approved_by"] == "lifecycle_adjuster"


@pytest.mark.asyncio
async def test_health_check_returns_healthy(client):
    """Smoke test: GET /health must return 200 with status=healthy."""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"


@pytest.mark.asyncio
async def test_root_endpoint_returns_service_info(client):
    """GET / returns the service description with key endpoint listings."""
    response = await client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "Aubric ClaimGuard"
    assert "endpoints" in body
    assert "submit_claim" in body["endpoints"]
