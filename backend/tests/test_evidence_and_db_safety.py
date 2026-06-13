"""Unit + integration tests for the /evidence endpoint and database safety helpers.

Coverage:
  Evidence endpoint (app/routes/evidence.py)
  ──────────────────────────────────────────
  - GET /{claim_id}/evidence returns short_circuited=True for high-fraud blocked claims
  - GET /{claim_id}/evidence returns short_circuited=False for normal (low-fraud) claims
  - GET /{claim_id}/evidence response contains all expected top-level fields
  - GET /{claim_id}/evidence returns 404 for unknown claim IDs

  Database safety (app/database.py)
  ──────────────────────────────────
  - _safe_read_db() returns the read-only connection under normal conditions
  - _safe_read_db() falls back to the write connection when _get_read_db() raises
  - close_db() closes both connections without raising
  - close_db() is idempotent (safe to call when connections are already None)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database import (
    close_db,
    create_claim,
    update_claim,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid(suffix: str) -> str:
    return f"CLM-ev{suffix}"


async def _make_claim(claim_id: str, **overrides: Any) -> dict[str, Any]:
    """Create a minimal claim in the test DB then optionally update it."""
    await create_claim(
        claim_id=claim_id,
        claimant_name=overrides.pop("claimant_name", "Test Claimant"),
        incident_description=overrides.pop("incident_description", "A test incident"),
        policy_number=overrides.pop("policy_number", "POL-0001"),
        file_path=None,
        file_type=overrides.pop("file_type", "image/jpeg"),
    )
    if overrides:
        await update_claim(claim_id, **overrides)
    return {"id": claim_id}


# ---------------------------------------------------------------------------
# Evidence endpoint — short_circuited flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEvidenceShortCircuited:
    """Tests that the short_circuited field is set correctly by the evidence endpoint."""

    async def test_short_circuited_true_when_fraud_above_70_and_status_blocked(
        self,
        client: Any,
    ) -> None:
        """A blocked claim with fraud_score > 70 and no payout/simulation data
        must have short_circuited=True in the evidence response."""
        claim_id = _uid("sc01")
        await _make_claim(
            claim_id,
            status="blocked",
            fraud_score=75.0,
            risk_level="high",
            # payout_recommendation and simulation_result are intentionally absent
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        assert body["short_circuited"] is True
        assert body["claim_id"] == claim_id
        assert body["status"] == "blocked"

    async def test_short_circuited_false_for_normal_low_fraud_claim(
        self,
        client: Any,
    ) -> None:
        """A claim with low fraud score must have short_circuited=False."""
        claim_id = _uid("sc02")
        await _make_claim(
            claim_id,
            status="pending_review",
            fraud_score=15.0,
            risk_level="low",
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        assert body["short_circuited"] is False

    async def test_short_circuited_false_when_fraud_exactly_70(
        self,
        client: Any,
    ) -> None:
        """Fraud score of exactly 70 is not strictly greater than 70 — must be False."""
        claim_id = _uid("sc03")
        await _make_claim(
            claim_id,
            status="blocked",
            fraud_score=70.0,
            risk_level="high",
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        assert body["short_circuited"] is False

    async def test_short_circuited_false_when_payout_recommendation_present(
        self,
        client: Any,
    ) -> None:
        """Even with fraud_score > 70, if payout_recommendation exists the flag must be False."""
        claim_id = _uid("sc04")
        await _make_claim(
            claim_id,
            status="blocked",
            fraud_score=80.0,
            risk_level="high",
            payout_recommendation={
                "recommended_amount": 500.0,
                "confidence": 0.5,
                "rationale": "Manual override",
                "comparable_claims": [],
            },
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        assert body["short_circuited"] is False

    async def test_short_circuited_false_when_simulation_result_present(
        self,
        client: Any,
    ) -> None:
        """Even with fraud_score > 70, if simulation_result exists the flag must be False."""
        claim_id = _uid("sc05")
        await _make_claim(
            claim_id,
            status="blocked",
            fraud_score=85.0,
            risk_level="critical",
            simulation_result={
                "approval_probability": 0.0,
                "dispute_risk": 0.9,
                "fraud_escalation_likelihood": 0.9,
                "financial_exposure": 0.0,
                "historical_comparison": "Unusual pattern.",
                "recommended_action": "deny",
            },
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        assert body["short_circuited"] is False


# ---------------------------------------------------------------------------
# Evidence endpoint — response shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestEvidenceResponseFields:
    """Tests that the evidence endpoint always returns the full set of expected fields."""

    _EXPECTED_KEYS = {
        "claim_id",
        "status",
        "claimant_name",
        "incident_description",
        "policy_number",
        "file_type",
        "created_at",
        "extracted_data",
        "fraud_assessment",
        "coverage_result",
        "payout_recommendation",
        "simulation_result",
        "risk_assessment",
        "decision",
        "decision_by",
        "decision_at",
        "receipt",
        "short_circuited",
    }

    async def test_all_expected_fields_present_for_fresh_claim(
        self,
        client: Any,
    ) -> None:
        """A freshly created claim with no pipeline data must still have all top-level keys."""
        claim_id = _uid("fields01")
        await _make_claim(claim_id)

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        missing = self._EXPECTED_KEYS - set(body.keys())
        assert not missing, f"Missing keys in evidence response: {missing}"

    async def test_fraud_assessment_contains_overall_score_and_risk_level(
        self,
        client: Any,
    ) -> None:
        """fraud_assessment must include overall_score and risk_level sub-fields."""
        claim_id = _uid("fields02")
        await _make_claim(
            claim_id,
            fraud_score=32.0,
            risk_level="medium",
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        fraud = body["fraud_assessment"]
        assert "overall_score" in fraud
        assert "risk_level" in fraud
        assert fraud["overall_score"] == pytest.approx(32.0)
        assert fraud["risk_level"] == "medium"

    async def test_fraud_assessment_includes_risk_assessment_sub_fields_when_present(
        self,
        client: Any,
    ) -> None:
        """When risk_assessment is populated, fraud_assessment must contain
        fraud_concern_level, identity_confidence, and document_authenticity_confidence."""
        claim_id = _uid("fields03")
        risk_data = {
            "recommended_action": "require_human",
            "action_risk_level": "medium",
            "fraud_score": 25.0,
            "monetary_value": 2000.0,
            "money_movement": True,
            "identity_confidence": 0.88,
            "document_authenticity_confidence": 0.92,
            "fraud_concern_level": 0.25,
            "approval_threshold": 0.8,
            "reasoning": "Within normal parameters.",
        }
        await _make_claim(
            claim_id,
            fraud_score=25.0,
            risk_level="low",
            risk_assessment=risk_data,
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        fraud = body["fraud_assessment"]
        assert fraud["fraud_concern_level"] == pytest.approx(0.25)
        assert fraud["identity_confidence"] == pytest.approx(0.88)
        assert fraud["document_authenticity_confidence"] == pytest.approx(0.92)

    async def test_payout_recommendation_and_coverage_roundtrip(
        self,
        client: Any,
    ) -> None:
        """Payout recommendation and coverage result stored in DB must survive the
        JSON serialisation round-trip through the evidence endpoint unchanged."""
        claim_id = _uid("fields04")
        coverage = {
            "policy_number": "AUTO-99",
            "coverage_type": "comprehensive_auto",
            "coverage_limit": 50000.0,
            "deductible": 500.0,
            "covered": True,
            "explanation": "Covered.",
        }
        payout = {
            "recommended_amount": 3000.0,
            "confidence": 0.9,
            "rationale": "Standard repair minus deductible.",
            "comparable_claims": [],
        }
        await _make_claim(
            claim_id,
            coverage_result=coverage,
            payout_recommendation=payout,
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        assert body["coverage_result"]["policy_number"] == "AUTO-99"
        assert body["coverage_result"]["covered"] is True
        assert body["payout_recommendation"]["recommended_amount"] == pytest.approx(3000.0)
        assert body["payout_recommendation"]["confidence"] == pytest.approx(0.9)

    async def test_claimant_name_and_incident_description_returned(
        self,
        client: Any,
    ) -> None:
        """claimant_name and incident_description must be echoed back verbatim."""
        claim_id = _uid("fields05")
        await _make_claim(
            claim_id,
            claimant_name="Grace Hopper",
            incident_description="A rear-end collision on Highway 101.",
        )

        response = await client.get(f"/api/claims/{claim_id}/evidence")
        assert response.status_code == 200
        body = response.json()

        assert body["claimant_name"] == "Grace Hopper"
        assert body["incident_description"] == "A rear-end collision on Highway 101."

    async def test_evidence_returns_404_for_unknown_claim(
        self,
        client: Any,
    ) -> None:
        """Requesting evidence for a non-existent claim must return HTTP 404."""
        response = await client.get("/api/claims/CLM-doesnotexist/evidence")
        assert response.status_code == 404
        body = response.json()
        assert "CLM-doesnotexist" in body.get("detail", "")


# ---------------------------------------------------------------------------
# _safe_read_db() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestSafeReadDb:
    """Tests for app.database._safe_read_db()."""

    async def test_safe_read_db_returns_read_connection_normally(self) -> None:
        """Under normal conditions _safe_read_db() must return the read-only connection."""
        import app.database as db_module
        from app.database import _safe_read_db

        fake_read_conn = MagicMock()

        with patch.object(db_module, "_get_read_db", new_callable=AsyncMock) as mock_get_read:
            mock_get_read.return_value = fake_read_conn
            result = await _safe_read_db()

        mock_get_read.assert_awaited_once()
        assert result is fake_read_conn

    async def test_safe_read_db_falls_back_to_write_connection_on_failure(
        self,
    ) -> None:
        """When _get_read_db() raises, _safe_read_db() must fall back to the write connection
        and reset _read_db to None so the next call will attempt a fresh reconnect."""
        import app.database as db_module
        from app.database import _safe_read_db

        fake_write_conn = MagicMock()

        with patch.object(
            db_module, "_get_read_db",
            new_callable=AsyncMock,
            side_effect=Exception("read-only connection lost"),
        ), patch.object(
            db_module, "_get_db",
            new_callable=AsyncMock,
            return_value=fake_write_conn,
        ) as mock_get_write:
            result = await _safe_read_db()

        mock_get_write.assert_awaited_once()
        assert result is fake_write_conn
        # _read_db must have been cleared to force reconnect on next attempt
        assert db_module._read_db is None

    async def test_safe_read_db_clears_read_db_singleton_on_failure(self) -> None:
        """After a read connection failure _read_db singleton must be None."""
        import app.database as db_module
        from app.database import _safe_read_db

        # Pretend there was a stale connection object
        db_module._read_db = MagicMock()
        fake_write_conn = MagicMock()

        with patch.object(
            db_module, "_get_read_db",
            new_callable=AsyncMock,
            side_effect=OSError("file not found"),
        ), patch.object(
            db_module, "_get_db",
            new_callable=AsyncMock,
            return_value=fake_write_conn,
        ):
            await _safe_read_db()

        assert db_module._read_db is None


# ---------------------------------------------------------------------------
# close_db() tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestCloseDb:
    """Tests for app.database.close_db()."""

    @patch("app.database._read_db", new=None)
    @patch("app.database._db", new=None)
    async def test_close_db_closes_both_connections(self) -> None:
        """close_db() must await close() on both the write and read connections."""
        import app.database as db_module

        mock_write = AsyncMock()
        mock_read = AsyncMock()

        db_module._db = mock_write
        db_module._read_db = mock_read

        await close_db()

        mock_write.close.assert_awaited_once()
        mock_read.close.assert_awaited_once()
        assert db_module._db is None
        assert db_module._read_db is None

    @patch("app.database._read_db", new=None)
    @patch("app.database._db", new=None)
    async def test_close_db_handles_already_none_connections(self) -> None:
        """close_db() must not raise when both connections are already None."""
        import app.database as db_module

        db_module._db = None
        db_module._read_db = None

        # Must complete without error
        await close_db()

        assert db_module._db is None
        assert db_module._read_db is None

    @patch("app.database._read_db", new=None)
    @patch("app.database._db", new=None)
    async def test_close_db_handles_read_connection_close_exception(self) -> None:
        """close_db() must swallow exceptions from the read connection's close()
        and still proceed to close the write connection."""
        import app.database as db_module

        mock_write = AsyncMock()
        mock_read = AsyncMock()
        mock_read.close.side_effect = Exception("read close error")

        db_module._db = mock_write
        db_module._read_db = mock_read

        # Must not propagate the exception
        await close_db()

        mock_write.close.assert_awaited_once()
        assert db_module._db is None
        assert db_module._read_db is None

    @patch("app.database._read_db", new=None)
    @patch("app.database._db", new=None)
    async def test_close_db_handles_write_connection_close_exception(self) -> None:
        """close_db() must swallow exceptions from the write connection's close()."""
        import app.database as db_module

        mock_write = AsyncMock()
        mock_write.close.side_effect = OSError("write close error")
        mock_read = AsyncMock()

        db_module._db = mock_write
        db_module._read_db = mock_read

        await close_db()

        mock_read.close.assert_awaited_once()
        assert db_module._db is None
        assert db_module._read_db is None

    @patch("app.database._read_db", new=None)
    @patch("app.database._db", new=None)
    async def test_close_db_sets_both_globals_to_none_even_on_partial_failure(
        self,
    ) -> None:
        """After close_db(), both _db and _read_db must be None regardless of errors."""
        import app.database as db_module

        failing_read = AsyncMock()
        failing_read.close.side_effect = RuntimeError("oops")
        failing_write = AsyncMock()
        failing_write.close.side_effect = RuntimeError("also oops")

        db_module._db = failing_write
        db_module._read_db = failing_read

        await close_db()

        assert db_module._db is None
        assert db_module._read_db is None

    @patch("app.database._read_db", new=None)
    @patch("app.database._db", new=None)
    async def test_close_db_is_idempotent(self) -> None:
        """Calling close_db() twice in a row must not raise on the second call."""
        import app.database as db_module

        mock_write = AsyncMock()
        mock_read = AsyncMock()
        db_module._db = mock_write
        db_module._read_db = mock_read

        await close_db()
        # Second call — both singletons are now None
        await close_db()

        # Still None, no error
        assert db_module._db is None
        assert db_module._read_db is None
