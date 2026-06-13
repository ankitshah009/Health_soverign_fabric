"""Async SQLite database layer using aiosqlite.

Uses a module-level connection singleton to avoid opening/closing
a new connection on every DB operation (~20 per claim pipeline).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite

from app.config import DATABASE_PATH

logger = logging.getLogger(__name__)

# ── Connection singleton (write) + read-only connection ──────────────────────

_db: aiosqlite.Connection | None = None
_db_lock: asyncio.Lock | None = None
_read_db: aiosqlite.Connection | None = None
_read_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Lazily create the DB write lock in the current event loop."""
    global _db_lock
    if _db_lock is None:
        _db_lock = asyncio.Lock()
    return _db_lock


def _get_read_lock() -> asyncio.Lock:
    """Lazily create the DB read lock in the current event loop."""
    global _read_lock
    if _read_lock is None:
        _read_lock = asyncio.Lock()
    return _read_lock


async def _get_db() -> aiosqlite.Connection:
    """Return the shared WRITE database connection, creating it if needed."""
    global _db
    if _db is None:
        async with _get_lock():
            if _db is None:
                _db = await aiosqlite.connect(str(DATABASE_PATH))
                _db.row_factory = aiosqlite.Row
                await _db.execute("PRAGMA journal_mode=WAL")
                await _db.execute("PRAGMA busy_timeout=5000")
    return _db


async def _get_read_db() -> aiosqlite.Connection:
    """Return the shared READ-ONLY database connection.

    Uses file: URI with ?mode=ro for true OS-level read-only access,
    preventing interference with WAL recovery on crash.
    """
    global _read_db
    if _read_db is None:
        async with _get_read_lock():
            if _read_db is None:
                _read_db = await aiosqlite.connect(
                    f"file:{DATABASE_PATH}?mode=ro", uri=True,
                )
                _read_db.row_factory = aiosqlite.Row
                await _read_db.execute("PRAGMA query_only = ON")
                await _read_db.execute("PRAGMA busy_timeout=5000")
    return _read_db

# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'submitted',
    claimant_name TEXT NOT NULL,
    incident_description TEXT NOT NULL,
    policy_number TEXT,
    file_path TEXT,
    file_type TEXT,
    created_at TEXT NOT NULL,
    extracted_data TEXT,
    fraud_score REAL,
    fraud_signals TEXT,
    risk_level TEXT,
    coverage_result TEXT,
    payout_recommendation TEXT,
    simulation_result TEXT,
    risk_assessment TEXT,
    decision TEXT,
    decision_by TEXT,
    decision_at TEXT,
    receipt TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'system',
    details TEXT,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS investigation_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'info',
    data TEXT,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_created_at
    ON claims(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_claim_timestamp
    ON audit_log(claim_id, timestamp);

CREATE INDEX IF NOT EXISTS idx_investigation_events_claim_id_id
    ON investigation_events(claim_id, id);
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dumps(obj: Any) -> str | None:
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, default=str)


def _json_loads(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _row_to_dict(row: aiosqlite.Row, cursor: aiosqlite.Cursor) -> dict[str, Any]:
    cols = [desc[0] for desc in cursor.description]
    d = dict(zip(cols, row))
    # Auto-deserialize JSON columns
    json_columns = {
        "extracted_data", "coverage_result", "payout_recommendation",
        "simulation_result", "risk_assessment", "receipt", "fraud_signals",
        "details", "data",
    }
    for col in json_columns:
        if col in d:
            d[col] = _json_loads(d[col])
    return d


# ── Initialization & Shutdown ─────────────────────────────────────────────────

async def init_db() -> None:
    """Create tables if they don't exist."""
    db = await _get_db()
    async with _get_lock():
        await db.executescript(_CREATE_TABLES)
        await db.commit()
    # Pre-create read connection so first read doesn't pay setup cost
    await _get_read_db()
    logger.info("Database initialized at %s", DATABASE_PATH)


async def close_db() -> None:
    """Close both write and read database connections."""
    global _db, _read_db
    if _read_db is not None:
        try:
            await _read_db.close()
        except Exception:
            pass
        _read_db = None
    if _db is not None:
        try:
            await _db.close()
        except Exception:
            pass
        _db = None
    logger.info("Database connections closed")


# ── Claims CRUD ───────────────────────────────────────────────────────────────

async def create_claim(
    claim_id: str,
    claimant_name: str,
    incident_description: str,
    policy_number: str | None,
    file_path: str | None,
    file_type: str | None,
) -> dict[str, Any]:
    now = _now()
    db = await _get_db()
    async with _get_lock():
        await db.execute(
            """INSERT INTO claims
               (id, status, claimant_name, incident_description, policy_number,
                file_path, file_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (claim_id, "submitted", claimant_name, incident_description,
             policy_number, file_path, file_type, now),
        )
        await db.commit()
    return await get_claim(claim_id)  # type: ignore[return-value]


async def _safe_read_db() -> aiosqlite.Connection:
    """Get the read-only connection with fallback to the write connection.

    If the read connection is closed or corrupted (e.g., after shutdown),
    attempts to reconnect. Falls back to the write connection as a last resort.
    """
    global _read_db
    try:
        db = await _get_read_db()
        return db
    except Exception as exc:
        logger.warning("Read-only DB connection failed (%s), falling back to write connection", exc)
        _read_db = None  # Force reconnect on next attempt
        return await _get_db()


async def get_claim(claim_id: str) -> dict[str, Any] | None:
    db = await _safe_read_db()
    async with _get_read_lock():
        cursor = await db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, cursor)


async def list_claims() -> list[dict[str, Any]]:
    db = await _safe_read_db()
    async with _get_read_lock():
        cursor = await db.execute("SELECT * FROM claims ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cursor) for r in rows]


async def update_claim(claim_id: str, **fields: Any) -> None:
    """Update claim fields. Does NOT read back the updated record (performance).

    Callers that need the updated record should call get_claim() separately.
    """
    if not fields:
        return

    # Serialize JSON columns
    json_columns = {
        "extracted_data", "coverage_result", "payout_recommendation",
        "simulation_result", "risk_assessment", "receipt", "fraud_signals",
    }
    processed: dict[str, Any] = {}
    for k, v in fields.items():
        if k in json_columns:
            processed[k] = _json_dumps(v)
        else:
            processed[k] = v

    set_clause = ", ".join(f"{k} = ?" for k in processed)
    values = list(processed.values()) + [claim_id]

    db = await _get_db()
    async with _get_lock():
        await db.execute(
            f"UPDATE claims SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await db.commit()


# ── Audit Log ─────────────────────────────────────────────────────────────────

async def add_audit_entry(
    claim_id: str,
    action: str,
    actor: str = "system",
    details: Any = None,
) -> None:
    db = await _get_db()
    async with _get_lock():
        await db.execute(
            """INSERT INTO audit_log (claim_id, action, actor, details, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (claim_id, action, actor, _json_dumps(details), _now()),
        )
        await db.commit()


async def get_audit_log(claim_id: str) -> list[dict[str, Any]]:
    db = await _safe_read_db()
    async with _get_read_lock():
        cursor = await db.execute(
            "SELECT * FROM audit_log WHERE claim_id = ? ORDER BY timestamp ASC",
            (claim_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cursor) for r in rows]


# ── Investigation Events ──────────────────────────────────────────────────────

async def add_investigation_event(
    claim_id: str,
    event_type: str,
    message: str,
    status: str = "info",
    data: Any = None,
) -> int:
    db = await _get_db()
    async with _get_lock():
        cursor = await db.execute(
            """INSERT INTO investigation_events
               (claim_id, event_type, message, status, data, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (claim_id, event_type, message, status, _json_dumps(data), _now()),
        )
        await db.commit()
        return cursor.lastrowid  # type: ignore[return-value]


async def get_investigation_events(
    claim_id: str,
    after_id: int = 0,
) -> list[dict[str, Any]]:
    db = await _safe_read_db()
    async with _get_read_lock():
        cursor = await db.execute(
            """SELECT * FROM investigation_events
               WHERE claim_id = ? AND id > ?
               ORDER BY id ASC""",
            (claim_id, after_id),
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r, cursor) for r in rows]
