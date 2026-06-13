"""Unit tests for the async SQLite database layer (app/database.py).

The shared conftest.py already handles:
  - Patching app.config.DATABASE_PATH and app.database.DATABASE_PATH to a temp file
  - Calling init_db() once per session (init_test_database fixture)
  - Dropping and recreating all tables between tests (reset_db_between_tests fixture)

All fixtures here are therefore at function scope and build on those guarantees.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from app.database import (
    add_audit_entry,
    add_investigation_event,
    create_claim,
    get_audit_log,
    get_claim,
    get_investigation_events,
    init_db,
    list_claims,
    update_claim,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return f"CLM-{uuid.uuid4().hex[:8].upper()}"


async def _create(
    claim_id: str | None = None,
    claimant_name: str = "Test User",
    incident_description: str = "A test incident.",
    policy_number: str | None = "AUTO-12345",
    file_path: str | None = None,
    file_type: str | None = None,
) -> dict[str, Any]:
    return await create_claim(
        claim_id or _uid(),
        claimant_name,
        incident_description,
        policy_number,
        file_path,
        file_type,
    )


# ---------------------------------------------------------------------------
# init_db — idempotent table creation
# ---------------------------------------------------------------------------

class TestInitDb:
    @pytest.mark.asyncio
    async def test_init_db_creates_claims_table(self):
        """init_db is already called by the session fixture; calling again is safe."""
        await init_db()  # idempotent — must not raise

    @pytest.mark.asyncio
    async def test_init_db_called_twice_does_not_raise(self):
        await init_db()
        await init_db()

    @pytest.mark.asyncio
    async def test_tables_exist_after_init_db(self):
        """Verify claims table is queryable after init_db."""
        claims = await list_claims()
        assert isinstance(claims, list)


# ---------------------------------------------------------------------------
# create_claim + get_claim — round trip
# ---------------------------------------------------------------------------

class TestCreateAndGetClaim:
    @pytest.mark.asyncio
    async def test_create_claim_returns_dict(self):
        result = await _create()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_claim_id_preserved(self):
        cid = _uid()
        result = await _create(claim_id=cid)
        assert result["id"] == cid

    @pytest.mark.asyncio
    async def test_create_claim_default_status_is_submitted(self):
        result = await _create()
        assert result["status"] == "submitted"

    @pytest.mark.asyncio
    async def test_create_claim_claimant_name_preserved(self):
        result = await _create(claimant_name="Jane Doe")
        assert result["claimant_name"] == "Jane Doe"

    @pytest.mark.asyncio
    async def test_create_claim_incident_description_preserved(self):
        result = await _create(incident_description="Water pipe burst in kitchen.")
        assert result["incident_description"] == "Water pipe burst in kitchen."

    @pytest.mark.asyncio
    async def test_create_claim_policy_number_preserved(self):
        result = await _create(policy_number="HOME-67890")
        assert result["policy_number"] == "HOME-67890"

    @pytest.mark.asyncio
    async def test_create_claim_null_policy_number_allowed(self):
        result = await _create(policy_number=None)
        assert result["policy_number"] is None

    @pytest.mark.asyncio
    async def test_create_claim_created_at_is_string(self):
        result = await _create()
        assert isinstance(result["created_at"], str)
        assert len(result["created_at"]) > 0

    @pytest.mark.asyncio
    async def test_get_claim_returns_same_record(self):
        cid = _uid()
        await _create(claim_id=cid, claimant_name="Alice Smith")
        fetched = await get_claim(cid)
        assert fetched is not None
        assert fetched["id"] == cid
        assert fetched["claimant_name"] == "Alice Smith"

    @pytest.mark.asyncio
    async def test_get_claim_unknown_id_returns_none(self):
        result = await get_claim("NONEXISTENT-000")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_claim_json_columns_start_as_none(self):
        cid = _uid()
        await _create(claim_id=cid)
        fetched = await get_claim(cid)
        assert fetched["extracted_data"] is None
        assert fetched["coverage_result"] is None


# ---------------------------------------------------------------------------
# update_claim — including JSON fields
# ---------------------------------------------------------------------------

class TestUpdateClaim:
    @pytest.mark.asyncio
    async def test_update_status(self):
        cid = _uid()
        await _create(claim_id=cid)
        await update_claim(cid, status="under_review")
        updated = await get_claim(cid)
        assert updated["status"] == "under_review"

    @pytest.mark.asyncio
    async def test_update_fraud_score(self):
        cid = _uid()
        await _create(claim_id=cid)
        await update_claim(cid, fraud_score=42.5, risk_level="medium")
        updated = await get_claim(cid)
        assert updated["fraud_score"] == pytest.approx(42.5)
        assert updated["risk_level"] == "medium"

    @pytest.mark.asyncio
    async def test_update_extracted_data_json_roundtrip(self):
        cid = _uid()
        await _create(claim_id=cid)
        payload = {
            "damage_type": "vehicle collision",
            "estimated_cost": 3500.0,
            "vehicle_info": "2020 Toyota Camry",
            "incident_details": "Front bumper damaged.",
            "document_type": "damage photo",
            "key_findings": ["bumper cracked", "airbag deployed"],
        }
        await update_claim(cid, extracted_data=payload)
        updated = await get_claim(cid)
        assert isinstance(updated["extracted_data"], dict)
        assert updated["extracted_data"]["damage_type"] == "vehicle collision"
        assert updated["extracted_data"]["estimated_cost"] == pytest.approx(3500.0)
        assert updated["extracted_data"]["key_findings"] == ["bumper cracked", "airbag deployed"]

    @pytest.mark.asyncio
    async def test_update_coverage_result_json_roundtrip(self):
        cid = _uid()
        await _create(claim_id=cid)
        payload = {
            "policy_number": "AUTO-12345",
            "coverage_type": "comprehensive_auto",
            "coverage_limit": 50000.0,
            "deductible": 500.0,
            "covered": True,
            "explanation": "Vehicle collision covered.",
        }
        await update_claim(cid, coverage_result=payload)
        updated = await get_claim(cid)
        cr = updated["coverage_result"]
        assert isinstance(cr, dict)
        assert cr["covered"] is True
        assert cr["policy_number"] == "AUTO-12345"
        assert cr["coverage_limit"] == pytest.approx(50000.0)

    @pytest.mark.asyncio
    async def test_update_with_no_fields_is_noop(self):
        cid = _uid()
        await _create(claim_id=cid, claimant_name="Bob Jones")
        await update_claim(cid)
        result = await get_claim(cid)
        assert result["claimant_name"] == "Bob Jones"

    @pytest.mark.asyncio
    async def test_update_decision_fields(self):
        cid = _uid()
        await _create(claim_id=cid)
        await update_claim(
            cid,
            decision="approved",
            decision_by="adjuster@example.com",
            decision_at="2024-01-15T09:00:00+00:00",
        )
        updated = await get_claim(cid)
        assert updated["decision"] == "approved"
        assert updated["decision_by"] == "adjuster@example.com"
        assert updated["decision_at"] == "2024-01-15T09:00:00+00:00"

    @pytest.mark.asyncio
    async def test_update_payout_recommendation_json_roundtrip(self):
        cid = _uid()
        await _create(claim_id=cid)
        payload = {
            "recommended_amount": 3000.0,
            "confidence": 0.9,
            "rationale": "Standard repair minus deductible.",
            "comparable_claims": ["CLM-A", "CLM-B"],
        }
        await update_claim(cid, payout_recommendation=payload)
        updated = await get_claim(cid)
        pr = updated["payout_recommendation"]
        assert pr["recommended_amount"] == pytest.approx(3000.0)
        assert pr["comparable_claims"] == ["CLM-A", "CLM-B"]


# ---------------------------------------------------------------------------
# list_claims — ordering and content
# ---------------------------------------------------------------------------

class TestListClaims:
    @pytest.mark.asyncio
    async def test_list_claims_empty_db_returns_empty_list(self):
        result = await list_claims()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_claims_returns_all_claims(self):
        await _create(claimant_name="Alpha")
        await _create(claimant_name="Beta")
        await _create(claimant_name="Gamma")
        result = await list_claims()
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_claims_ordered_by_created_at_desc(self):
        """Most recently created claim appears first."""
        id1 = _uid()
        id2 = _uid()
        id3 = _uid()
        await _create(claim_id=id1)
        await _create(claim_id=id2)
        await _create(claim_id=id3)
        result = await list_claims()
        returned_ids = [c["id"] for c in result]
        # The last created claim should appear first
        assert returned_ids[0] == id3
        assert returned_ids[-1] == id1

    @pytest.mark.asyncio
    async def test_list_claims_single_claim(self):
        cid = _uid()
        await _create(claim_id=cid, claimant_name="Solo Claimant")
        result = await list_claims()
        assert len(result) == 1
        assert result[0]["id"] == cid

    @pytest.mark.asyncio
    async def test_list_claims_contains_all_fields(self):
        await _create(claimant_name="Test Person", policy_number="POL-001")
        result = await list_claims()
        claim = result[0]
        assert "id" in claim
        assert "status" in claim
        assert "claimant_name" in claim
        assert "created_at" in claim


# ---------------------------------------------------------------------------
# add_investigation_event + get_investigation_events
# ---------------------------------------------------------------------------

class TestInvestigationEvents:
    @pytest.mark.asyncio
    async def test_add_event_returns_integer_id(self):
        cid = _uid()
        await _create(claim_id=cid)
        event_id = await add_investigation_event(cid, "analysis", "Starting analysis.")
        assert isinstance(event_id, int)
        assert event_id > 0

    @pytest.mark.asyncio
    async def test_get_events_returns_list(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_investigation_event(cid, "analysis", "Event one.")
        events = await get_investigation_events(cid)
        assert isinstance(events, list)
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_event_fields_preserved(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_investigation_event(
            cid, "fraud_check", "Fraud check complete.", status="warning"
        )
        events = await get_investigation_events(cid)
        evt = events[0]
        assert evt["claim_id"] == cid
        assert evt["event_type"] == "fraud_check"
        assert evt["message"] == "Fraud check complete."
        assert evt["status"] == "warning"

    @pytest.mark.asyncio
    async def test_event_data_json_roundtrip(self):
        cid = _uid()
        await _create(claim_id=cid)
        payload = {"fraud_score": 25.0, "risk_level": "low"}
        await add_investigation_event(cid, "score_update", "Score updated.", data=payload)
        events = await get_investigation_events(cid)
        assert events[0]["data"] == payload

    @pytest.mark.asyncio
    async def test_get_events_after_id_filters_correctly(self):
        cid = _uid()
        await _create(claim_id=cid)
        id1 = await add_investigation_event(cid, "step", "Event 1.")
        id2 = await add_investigation_event(cid, "step", "Event 2.")
        id3 = await add_investigation_event(cid, "step", "Event 3.")

        # Retrieve only events after id1
        events = await get_investigation_events(cid, after_id=id1)
        returned_ids = [e["id"] for e in events]
        assert id1 not in returned_ids
        assert id2 in returned_ids
        assert id3 in returned_ids

    @pytest.mark.asyncio
    async def test_get_events_after_id_zero_returns_all(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_investigation_event(cid, "step", "Event A.")
        await add_investigation_event(cid, "step", "Event B.")
        events = await get_investigation_events(cid, after_id=0)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_get_events_after_last_id_returns_empty(self):
        cid = _uid()
        await _create(claim_id=cid)
        last_id = await add_investigation_event(cid, "final", "Last event.")
        events = await get_investigation_events(cid, after_id=last_id)
        assert events == []

    @pytest.mark.asyncio
    async def test_events_only_returned_for_correct_claim_id(self):
        cid1 = _uid()
        cid2 = _uid()
        await _create(claim_id=cid1)
        await _create(claim_id=cid2)
        await add_investigation_event(cid1, "step", "Claim 1 event.")
        await add_investigation_event(cid2, "step", "Claim 2 event.")

        events_1 = await get_investigation_events(cid1)
        events_2 = await get_investigation_events(cid2)
        assert len(events_1) == 1
        assert events_1[0]["claim_id"] == cid1
        assert len(events_2) == 1
        assert events_2[0]["claim_id"] == cid2

    @pytest.mark.asyncio
    async def test_events_default_status_is_info(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_investigation_event(cid, "step", "No status supplied.")
        events = await get_investigation_events(cid)
        assert events[0]["status"] == "info"

    @pytest.mark.asyncio
    async def test_events_ordered_by_id_ascending(self):
        cid = _uid()
        await _create(claim_id=cid)
        id1 = await add_investigation_event(cid, "step", "First.")
        id2 = await add_investigation_event(cid, "step", "Second.")
        id3 = await add_investigation_event(cid, "step", "Third.")
        events = await get_investigation_events(cid)
        assert [e["id"] for e in events] == [id1, id2, id3]


# ---------------------------------------------------------------------------
# add_audit_entry + get_audit_log
# ---------------------------------------------------------------------------

class TestAuditLog:
    @pytest.mark.asyncio
    async def test_add_audit_entry_does_not_raise(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "claim_submitted")

    @pytest.mark.asyncio
    async def test_get_audit_log_returns_entries(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "claim_submitted")
        log = await get_audit_log(cid)
        assert isinstance(log, list)
        assert len(log) == 1

    @pytest.mark.asyncio
    async def test_audit_entry_action_preserved(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "document_analyzed")
        log = await get_audit_log(cid)
        assert log[0]["action"] == "document_analyzed"

    @pytest.mark.asyncio
    async def test_audit_entry_actor_defaults_to_system(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "fraud_scored")
        log = await get_audit_log(cid)
        assert log[0]["actor"] == "system"

    @pytest.mark.asyncio
    async def test_audit_entry_custom_actor_preserved(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "decision_made", actor="adjuster@example.com")
        log = await get_audit_log(cid)
        assert log[0]["actor"] == "adjuster@example.com"

    @pytest.mark.asyncio
    async def test_audit_entry_details_json_roundtrip(self):
        cid = _uid()
        await _create(claim_id=cid)
        details = {"old_status": "submitted", "new_status": "under_review", "score": 42}
        await add_audit_entry(cid, "status_changed", details=details)
        log = await get_audit_log(cid)
        assert log[0]["details"] == details

    @pytest.mark.asyncio
    async def test_audit_log_ordered_by_timestamp_asc(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "action_first")
        await add_audit_entry(cid, "action_second")
        await add_audit_entry(cid, "action_third")
        log = await get_audit_log(cid)
        actions = [e["action"] for e in log]
        assert actions == ["action_first", "action_second", "action_third"]

    @pytest.mark.asyncio
    async def test_get_audit_log_empty_for_unknown_claim(self):
        log = await get_audit_log("NONEXISTENT-999")
        assert log == []

    @pytest.mark.asyncio
    async def test_audit_log_only_returned_for_correct_claim_id(self):
        cid1 = _uid()
        cid2 = _uid()
        await _create(claim_id=cid1)
        await _create(claim_id=cid2)
        await add_audit_entry(cid1, "claim1_action")
        await add_audit_entry(cid2, "claim2_action")

        log1 = await get_audit_log(cid1)
        log2 = await get_audit_log(cid2)
        assert len(log1) == 1
        assert log1[0]["claim_id"] == cid1
        assert len(log2) == 1
        assert log2[0]["claim_id"] == cid2

    @pytest.mark.asyncio
    async def test_audit_entry_has_timestamp(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "test_action")
        log = await get_audit_log(cid)
        assert isinstance(log[0]["timestamp"], str)
        assert len(log[0]["timestamp"]) > 0

    @pytest.mark.asyncio
    async def test_audit_entry_null_details_stored_as_none(self):
        cid = _uid()
        await _create(claim_id=cid)
        await add_audit_entry(cid, "no_details_action", details=None)
        log = await get_audit_log(cid)
        assert log[0]["details"] is None

    @pytest.mark.asyncio
    async def test_multiple_audit_entries_for_same_claim(self):
        cid = _uid()
        await _create(claim_id=cid)
        for i in range(5):
            await add_audit_entry(cid, f"action_{i}")
        log = await get_audit_log(cid)
        assert len(log) == 5
