"""FastAPI application entry point for Sovereign — the AI patient advocate."""

from __future__ import annotations

import hmac
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.requests import Request

from app.config import ALLOWED_ORIGINS, ENVIRONMENT, INTERNAL_API_KEY, UPLOAD_DIR
from app.database import close_db, init_db
from app.routes import approvals, chat, claims, complaint, evidence, voice
from app.services.grok_service import init_grok_client, close_grok_client
from app.services.yutori_service import init_yutori_client, close_yutori_client
from app.services.telemetry import init_telemetry, shutdown_telemetry
from app.utils.trust_signer import get_signer
from app.services.webhook_dispatcher import (
    register_webhook,
    remove_webhook,
    list_webhooks,
    get_webhook,
    send_test_event,
    ALL_EVENTS,
)

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("Starting Sovereign backend...")
    await init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory: %s", UPLOAD_DIR)
    # Initialize shared HTTP clients with connection pooling + warm connections
    await init_grok_client()
    await init_yutori_client()
    init_telemetry(app)
    logger.info("Sovereign is ready.")
    yield
    # Shutdown — close HTTP clients, then DB, then telemetry
    await close_grok_client()
    await close_yutori_client()
    await close_db()
    shutdown_telemetry()
    logger.info("Shutting down Sovereign.")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Sovereign — AI Patient Advocate",
    description=(
        "Voice-first AI patient advocate. Reads your medical bills and insurance "
        "denials with Grok Vision, detects overcharges and illegal balance-billing, "
        "checks whether a denial is appealable, drafts the appeal — and signs every "
        "action taken on your behalf with a verifiable, patient-owned receipt "
        "(the Sovereign Trust Layer)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── Auth middleware ───────────────────────────────────────────────────────────

_AUTH_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json"}

# Resolve the key once at startup: empty string → None (not configured)
_API_KEY: str | None = INTERNAL_API_KEY or None


@app.middleware("http")
async def api_key_auth(request: Request, call_next):
    """Validate Authorization: Bearer <key> on all non-exempt endpoints.

    Rules
    -----
    - /health, /docs, /openapi.json are always public.
    - ENVIRONMENT == "development" with no key set → allow all (dev convenience).
    - Non-development with no key set → 500 server misconfiguration.
    - Key set → every non-exempt request must carry a matching Bearer token;
      uses hmac.compare_digest() to prevent timing attacks.
    """
    if request.url.path in _AUTH_EXEMPT_PATHS:
        return await call_next(request)

    if _API_KEY is None:
        if ENVIRONMENT == "development":
            return await call_next(request)
        return JSONResponse(
            status_code=500,
            content={"detail": "Server misconfiguration: INTERNAL_API_KEY not set."},
        )

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or malformed Authorization header."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided_key = auth_header[len("Bearer "):]
    if not hmac.compare_digest(provided_key, _API_KEY):
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid API key."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


# ── Security headers middleware ───────────────────────────────────────────────

@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Attach security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    if ENVIRONMENT != "development":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


# ── CORS ─────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Routes ────────────────────────────────────────────────────────────────────

app.include_router(claims.router)
app.include_router(approvals.router)
app.include_router(evidence.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(complaint.router)

# ── Static files (uploads) ───────────────────────────────────────────────────

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "service": "Sovereign — AI Patient Advocate",
        "version": "1.0.0",
        "description": "Voice-first AI advocate that fights medical bills & insurance denials, with signed Patient Action Receipts",
        "endpoints": {
            "submit_claim": "POST /api/claims/submit",
            "list_claims": "GET /api/claims",
            "get_claim": "GET /api/claims/{claim_id}",
            "stream_events": "GET /api/claims/{claim_id}/events (SSE)",
            "get_evidence": "GET /api/claims/{claim_id}/evidence",
            "get_audit": "GET /api/claims/{claim_id}/audit",
            "process_approval": "POST /api/approvals",
            "get_receipt": "GET /api/claims/{claim_id}/receipt",
            "chat": "POST /api/chat (SSE streaming with function calling)",
            "voice": "WS /api/voice (WebSocket proxy to xAI real-time voice)",
            "verify_receipt": "POST /api/verify",
            "verification_key": "GET /api/verify/key",
            "webhooks": "POST/GET/DELETE /api/webhooks",
        },
        "stack": {
            "ai": "Grok (xAI) — grok-4.3 vision/chat + grok-voice-latest realtime",
            "research": "Yutori API",
            "trust_layer": "Sovereign Trust Layer (intent normalization, risk/consent engine, simulation, Ed25519 receipts)",
            "database": "SQLite (aiosqlite)",
        },
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "sovereign"}


# ── Pending file for voice/chat submissions ──────────────────────────────────
# NOTE: In-memory dict — lost on server restart. Acceptable for single-user
# hackathon demo. Production would use session-keyed persistent storage.

pending_files: dict[str, str] = {}  # "latest" -> file_path

MIME_BY_EXT = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf",
    ".txt": "text/plain",
}


def _guess_content_type(filename: str) -> str:
    """Guess MIME type from filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    return MIME_BY_EXT.get(ext, "application/octet-stream")


def consume_pending_file(fallback_content: bytes, fallback_filename: str) -> tuple[bytes, str, str]:
    """Consume the pending file if available, returning (content, filename, content_type).

    Clears the pending file after use. Falls back to provided defaults if no
    pending file exists or the file was deleted from disk.
    """
    pending_path = pending_files.pop("latest", None)
    if pending_path:
        p = Path(pending_path)
        if p.exists():
            logger.info("Using pending file: %s", p.name)
            return p.read_bytes(), p.name, _guess_content_type(p.name)
        logger.warning("Pending file path stale (deleted from disk): %s", pending_path)
    return fallback_content, fallback_filename, "text/plain"


@app.post("/api/pending-file")
async def upload_pending_file(file: UploadFile = File(...)):
    """Upload a file that will be attached to the next voice/chat claim submission."""
    file_id = str(uuid.uuid4())
    os.makedirs(str(UPLOAD_DIR), exist_ok=True)

    # Sanitize filename: strip directory components and unsafe chars
    import re
    raw_name = os.path.basename(file.filename or "upload")
    safe_name = re.sub(r"[^\w.\-]", "_", raw_name)
    file_path = os.path.join(str(UPLOAD_DIR), f"{file_id}_{safe_name}")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    with open(file_path, "wb") as f:
        f.write(content)

    pending_files["latest"] = file_path

    return {
        "file_id": file_id,
        "filename": file.filename,
        "content_type": file.content_type or _guess_content_type(file.filename or ""),
    }


@app.get("/api/pending-file")
async def get_pending_file():
    """Check if there's a pending file."""
    if "latest" in pending_files:
        p = Path(pending_files["latest"])
        return {"has_file": True, "filename": p.name}
    return {"has_file": False}


@app.delete("/api/pending-file")
async def clear_pending_file():
    """Clear the pending file after it's been used."""
    pending_files.pop("latest", None)
    return {"cleared": True}


# ── Receipt verification ────────────────────────────────────────────────────


class VerifyRequest(BaseModel):
    """Request body for receipt verification."""
    receipt: dict


@app.post("/api/verify")
async def verify_receipt(req: VerifyRequest):
    """Verify a decision receipt's Ed25519 signature.

    Accepts a full receipt dict (as returned by the receipt endpoint) and
    verifies the Ed25519 signature. Returns the verification result along
    with the key ID and algorithm found in the receipt.
    """
    signer = get_signer()
    receipt_data = req.receipt

    # Check that the receipt has signature fields
    if not receipt_data.get("signature") or not receipt_data.get("public_key"):
        raise HTTPException(
            status_code=400,
            detail="Receipt is missing signature fields (signature, public_key).",
        )

    valid = signer.verify(receipt_data)
    return {
        "valid": valid,
        "receipt_id": receipt_data.get("receipt_id"),
        "signing_key_id": receipt_data.get("signing_key_id"),
        "signature_algorithm": receipt_data.get("signature_algorithm"),
    }


@app.get("/api/verify/key")
async def get_verification_key():
    """Return the current public verification key.

    Third parties can use this key to independently verify any receipt
    signed by this ClaimGuard instance.
    """
    signer = get_signer()
    if not signer.available:
        raise HTTPException(
            status_code=503,
            detail="Signing key not available.",
        )
    return {
        "public_key": signer.public_key_b64,
        "key_id": signer.key_id,
        "algorithm": "Ed25519",
    }


# ── Webhooks ─────────────────────────────────────────────────────────────────


class WebhookRegisterRequest(BaseModel):
    """Request body for webhook registration."""
    url: str
    secret: str
    events: list[str] = []


@app.post("/api/webhooks", status_code=201)
async def create_webhook(req: WebhookRegisterRequest):
    """Register a new webhook endpoint.

    Events: claim.submitted, claim.completed, risk.threshold_crossed,
    receipt.generated, webhook.test. Pass an empty list or ["*"] for all.
    """
    # Validate events if provided
    if req.events:
        invalid = set(req.events) - ALL_EVENTS - {"*"}
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown events: {sorted(invalid)}. Valid events: {sorted(ALL_EVENTS)}",
            )

    ep = register_webhook(url=req.url, secret=req.secret, events=req.events)
    return ep.to_dict()


@app.get("/api/webhooks")
async def get_all_webhooks():
    """List all registered webhook endpoints (secrets are not exposed)."""
    return list_webhooks()


@app.delete("/api/webhooks/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str):
    """Remove a webhook endpoint by ID."""
    if not remove_webhook(webhook_id):
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found.")
    return Response(status_code=204)


@app.post("/api/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: str):
    """Send a test event to a specific webhook endpoint.

    Unlike normal event delivery, this awaits the HTTP response and returns
    the result so you can confirm the endpoint is reachable.
    """
    ep = get_webhook(webhook_id)
    if ep is None:
        raise HTTPException(status_code=404, detail=f"Webhook {webhook_id} not found.")
    result = await send_test_event(ep)
    return result
