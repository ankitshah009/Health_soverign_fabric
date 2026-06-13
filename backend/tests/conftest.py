"""Shared pytest fixtures for the Aubric ClaimGuard test suite."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ---------------------------------------------------------------------------
# Make the backend package importable from the tests directory
# ---------------------------------------------------------------------------
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


# ---------------------------------------------------------------------------
# pytest-asyncio event-loop configuration (one loop per session)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop shared across the whole test session."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Temp-file SQLite database — override DATABASE_PATH before any import
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def override_database_path(tmp_path_factory):
    """Point the app at a temporary SQLite file for the entire test session."""
    tmp_dir = tmp_path_factory.mktemp("db")
    db_file = tmp_dir / "test_claimguard.db"

    # Patch the config value AND the database module attribute before anything
    # accesses them.
    with patch("app.config.DATABASE_PATH", db_file), \
         patch("app.database.DATABASE_PATH", db_file):
        yield db_file


@pytest_asyncio.fixture(scope="session", autouse=True)
async def init_test_database(override_database_path):
    """Initialise the schema once per session on the temp database."""
    import app.database as db_module
    db_module.DATABASE_PATH = override_database_path
    db_module._db = None  # reset the singleton so it connects to the temp DB
    from app.database import init_db
    await init_db()
    yield
    # Tear down the connection after the session
    if db_module._db is not None:
        await db_module._db.close()
        db_module._db = None


@pytest_asyncio.fixture(autouse=True)
async def reset_db_between_tests(override_database_path):
    """
    Drop and recreate all tables between tests so each test starts clean.
    Also resets the connection singleton so it picks up the patched path.
    """
    import app.database as db_module
    db_module.DATABASE_PATH = override_database_path
    # Close existing connection and reopen against the temp file
    if db_module._db is not None:
        await db_module._db.close()
        db_module._db = None

    from app.database import init_db
    import aiosqlite

    db = await aiosqlite.connect(str(override_database_path))
    await db.executescript(
        "DROP TABLE IF EXISTS claims;"
        "DROP TABLE IF EXISTS audit_log;"
        "DROP TABLE IF EXISTS investigation_events;"
    )
    await db.commit()
    await db.close()

    db_module._db = None
    await init_db()
    yield


# ---------------------------------------------------------------------------
# AsyncClient fixture — wraps the FastAPI app for HTTP-level tests
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def client() -> AsyncGenerator:
    """Async HTTP client wired directly to the FastAPI app (no real server)."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Minimal valid PNG image bytes (1x1 pixel, pure white)
# ---------------------------------------------------------------------------
@pytest.fixture
def tiny_png_bytes() -> bytes:
    """Return a valid minimal 1x1 white PNG as raw bytes (no Pillow needed)."""
    import struct
    import zlib

    def _chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png_sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 1x1 RGB
    ihdr = _chunk(b"IHDR", ihdr_data)
    raw_row = b"\x00\xFF\xFF\xFF"  # filter byte + R G B = white
    idat = _chunk(b"IDAT", zlib.compress(raw_row))
    iend = _chunk(b"IEND", b"")
    return png_sig + ihdr + idat + iend


# ---------------------------------------------------------------------------
# Sample data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_extracted_data() -> dict[str, Any]:
    return {
        "damage_type": "vehicle collision",
        "estimated_cost": 3500.00,
        "vehicle_info": "2020 Toyota Camry",
        "incident_details": "Front bumper damage from rear-end collision at intersection.",
        "document_type": "damage photo",
        "key_findings": ["front bumper cracked", "airbag deployed", "no frame damage"],
    }


@pytest.fixture
def sample_fraud_score_low():
    from app.models.claim import FraudScore, FraudSignal, RiskLevel, Severity
    return FraudScore(
        overall_score=15.0,
        risk_level=RiskLevel.LOW,
        signals=[
            FraudSignal(
                signal_name="low_cost_claim",
                description="Claimed amount is within normal range.",
                severity=Severity.LOW,
                confidence=0.8,
            )
        ],
        explanation="No significant fraud indicators detected.",
    )


@pytest.fixture
def sample_fraud_score_medium():
    from app.models.claim import FraudScore, FraudSignal, RiskLevel, Severity
    return FraudScore(
        overall_score=45.0,
        risk_level=RiskLevel.MEDIUM,
        signals=[
            FraudSignal(
                signal_name="inconsistent_description",
                description="Minor inconsistency between document and description.",
                severity=Severity.MEDIUM,
                confidence=0.6,
            )
        ],
        explanation="Moderate fraud risk — inconsistencies present.",
    )


@pytest.fixture
def sample_fraud_score_high():
    from app.models.claim import FraudScore, FraudSignal, RiskLevel, Severity
    return FraudScore(
        overall_score=75.0,
        risk_level=RiskLevel.HIGH,
        signals=[
            FraudSignal(
                signal_name="staged_damage",
                description="Damage pattern is consistent with staged accident.",
                severity=Severity.HIGH,
                confidence=0.85,
            )
        ],
        explanation="High fraud risk — staged accident indicators present.",
    )


@pytest.fixture
def sample_coverage_result():
    from app.models.claim import CoverageResult
    return CoverageResult(
        policy_number="AUTO-12345",
        coverage_type="comprehensive_auto",
        coverage_limit=50000.00,
        deductible=500.00,
        covered=True,
        explanation="Vehicle collision is covered. Estimated cost $3,500.00. After deductible: $3,000.00.",
    )


@pytest.fixture
def sample_claim_data() -> dict[str, Any]:
    return {
        "id": "CLM-00001",
        "status": "pending_review",
        "claimant_name": "John Smith",
        "incident_description": "Rear-end collision at an intersection.",
        "policy_number": "AUTO-12345",
        "file_path": None,
        "file_type": None,
        "created_at": "2024-01-01T12:00:00+00:00",
        "extracted_data": {
            "damage_type": "vehicle collision",
            "estimated_cost": 3500.00,
            "vehicle_info": "2020 Toyota Camry",
            "incident_details": "Front bumper damage.",
            "document_type": "damage photo",
            "key_findings": ["front bumper cracked"],
        },
        "fraud_score": 15.0,
        "risk_level": "low",
        "coverage_result": {
            "policy_number": "AUTO-12345",
            "coverage_type": "comprehensive_auto",
            "coverage_limit": 50000.00,
            "deductible": 500.00,
            "covered": True,
            "explanation": "Covered.",
        },
        "payout_recommendation": {
            "recommended_amount": 3000.00,
            "confidence": 0.9,
            "rationale": "Standard repair cost minus deductible.",
            "comparable_claims": [],
        },
        "simulation_result": {
            "approval_probability": 0.85,
            "dispute_risk": 0.1,
            "fraud_escalation_likelihood": 0.05,
            "financial_exposure": 3000.00,
            "historical_comparison": "Similar to 90% of auto claims.",
            "recommended_action": "approve",
        },
        "risk_assessment": {
            "recommended_action": "require_human",
            "action_risk_level": "medium",
            "fraud_score": 15.0,
            "monetary_value": 3000.00,
            "money_movement": True,
            "identity_confidence": 0.875,
            "document_authenticity_confidence": 0.85,
            "fraud_concern_level": 0.15,
            "approval_threshold": 0.8,
            "reasoning": "Standard processing.",
        },
        "decision": None,
        "decision_by": None,
        "decision_at": None,
        "receipt": None,
    }


@pytest.fixture
def sample_risk_assessment_low() -> dict[str, Any]:
    return {
        "recommended_action": "require_human",
        "action_risk_level": "medium",
        "fraud_score": 15.0,
        "monetary_value": 3000.00,
        "money_movement": True,
        "identity_confidence": 0.875,
        "document_authenticity_confidence": 0.85,
        "fraud_concern_level": 0.15,
        "approval_threshold": 0.8,
        "reasoning": "Standard processing.",
    }


@pytest.fixture
def sample_risk_assessment_blocked() -> dict[str, Any]:
    return {
        "recommended_action": "block",
        "action_risk_level": "critical",
        "fraud_score": 80.0,
        "monetary_value": 3000.00,
        "money_movement": True,
        "identity_confidence": 0.333,
        "document_authenticity_confidence": 0.2,
        "fraud_concern_level": 0.8,
        "approval_threshold": 1.0,
        "reasoning": "Fraud score exceeds critical threshold.",
    }


@pytest.fixture
def sample_risk_assessment_escalated() -> dict[str, Any]:
    return {
        "recommended_action": "escalate_fraud",
        "action_risk_level": "high",
        "fraud_score": 60.0,
        "monetary_value": 3000.00,
        "money_movement": True,
        "identity_confidence": 0.5,
        "document_authenticity_confidence": 0.4,
        "fraud_concern_level": 0.6,
        "approval_threshold": 0.95,
        "reasoning": "High fraud score. SIU review required.",
    }


# ---------------------------------------------------------------------------
# Grok API mock
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_grok_response():
    """Return a factory for mocked Grok API responses."""
    def _factory(payload: dict[str, Any]) -> str:
        import json
        return json.dumps(payload)
    return _factory


@pytest.fixture
def mock_grok_service():
    """Patch _call_grok so no real HTTP calls are made."""
    with patch("app.services.grok_service._call_grok") as mock_fn:
        yield mock_fn


# ---------------------------------------------------------------------------
# Yutori API mock
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_yutori_response_pending() -> list[dict[str, Any]]:
    return [
        {
            "entity_name": "John Smith",
            "entity_type": "person",
            "status": "verification_pending",
            "results": {"summary": "Verification in progress."},
        }
    ]


@pytest.fixture
def mock_yutori_response_completed_clean() -> list[dict[str, Any]]:
    return [
        {
            "entity_name": "John Smith",
            "entity_type": "person",
            "status": "completed",
            "results": {
                "credibility_score": 0.85,
                "risk_indicators": [],
                "summary": "Entity verified — no issues found.",
            },
        }
    ]


@pytest.fixture
def mock_yutori_response_completed_risky() -> list[dict[str, Any]]:
    return [
        {
            "entity_name": "Jane Suspect",
            "entity_type": "person",
            "status": "completed",
            "results": {
                "risk_indicators": ["prior fraud conviction", "address mismatch"],
                "summary": "Risk indicators found.",
            },
        }
    ]


@pytest.fixture
def mock_yutori_response_low_credibility() -> list[dict[str, Any]]:
    return [
        {
            "entity_name": "Bob Unknown",
            "entity_type": "person",
            "status": "completed",
            "results": {
                "credibility_score": 0.2,
                "risk_indicators": [],
                "summary": "Low credibility entity.",
            },
        }
    ]
