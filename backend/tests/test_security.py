"""
Security and feature tests for Aubric ClaimGuard.

Covers 6 untested feature gaps:
  1. Auth middleware (API key enforcement, exempt paths, dev mode)
  2. Security headers (X-Content-Type-Options, X-Frame-Options, etc.)
  3. POST /api/verify — Ed25519 receipt verification
  4. GET /api/verify/key — public key endpoint
  5. Webhook CRUD — register, list, delete, test
  6. Pipeline backpressure — 429 when at MAX_CONCURRENT_PIPELINES

All HTTP calls go through httpx.AsyncClient with ASGITransport (no real server).
External I/O is patched where needed. The in-memory webhook registry is cleared
before and after each webhook test.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app_client() -> AsyncClient:
    """Return an AsyncClient bound to the FastAPI app via ASGI transport."""
    from app.main import app
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def anon_client() -> AsyncGenerator[AsyncClient, None]:
    """Client that sends NO Authorization header — used for auth tests."""
    async with _make_app_client() as ac:
        yield ac


@pytest_asyncio.fixture
async def authed_client() -> AsyncGenerator[AsyncClient, None]:
    """Client that always sends the correct Bearer token."""
    async with _make_app_client() as ac:
        ac.headers.update({"Authorization": "Bearer test-key-123"})
        yield ac


@pytest.fixture(autouse=True)
def clear_webhook_registry():
    """Clear the in-memory webhook registry before and after every test."""
    from app.services.webhook_dispatcher import _registry
    _registry.clear()
    yield
    _registry.clear()


# ---------------------------------------------------------------------------
# Signed receipt helper
# ---------------------------------------------------------------------------

def _make_signed_receipt() -> dict:
    """Return a freshly signed receipt using the singleton TrustSigner."""
    from app.utils.trust_signer import get_signer
    payload = {
        "receipt_id": "test-receipt-001",
        "claim_id": "CLM-TEST",
        "action": "approve",
        "approved_by": "test_adjuster",
    }
    return get_signer().sign(payload)


# ===========================================================================
# 1. Auth Middleware Tests
# ===========================================================================

class TestAuthMiddleware:
    """Validate the api_key_auth middleware under various conditions."""

    @pytest.mark.asyncio
    async def test_missing_auth_header_returns_401(self, anon_client):
        """Non-exempt endpoint with no Authorization header must return 401."""
        with patch("app.main._API_KEY", "test-key-123"):
            response = await anon_client.get("/api/verify/key")
        assert response.status_code == 401
        body = response.json()
        assert "detail" in body
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    @pytest.mark.asyncio
    async def test_wrong_bearer_token_returns_401(self, anon_client):
        """A request with a Bearer token that does not match the configured key returns 401."""
        with patch("app.main._API_KEY", "test-key-123"):
            response = await anon_client.get(
                "/api/verify/key",
                headers={"Authorization": "Bearer wrong-key"},
            )
        assert response.status_code == 401
        body = response.json()
        assert "detail" in body
        assert response.headers.get("WWW-Authenticate") == "Bearer"

    @pytest.mark.asyncio
    async def test_correct_bearer_token_passes_through(self, anon_client):
        """A request with the exact configured Bearer token reaches the handler."""
        with patch("app.main._API_KEY", "test-key-123"):
            response = await anon_client.get(
                "/api/verify/key",
                headers={"Authorization": "Bearer test-key-123"},
            )
        # The endpoint itself may return 200 or 503 if no signing key;
        # what matters is that it is NOT 401.
        assert response.status_code != 401

    @pytest.mark.asyncio
    async def test_health_endpoint_is_exempt_from_auth(self, anon_client):
        """GET /health must always return 200 — no Authorization header needed."""
        with patch("app.main._API_KEY", "test-key-123"):
            response = await anon_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_docs_endpoint_is_exempt_from_auth(self, anon_client):
        """GET /docs must be accessible without a Bearer token."""
        with patch("app.main._API_KEY", "test-key-123"):
            response = await anon_client.get("/docs")
        # /docs returns 200 (HTML) or 301/302 redirect — never 401
        assert response.status_code not in (401, 403)

    @pytest.mark.asyncio
    async def test_development_mode_no_key_allows_all_requests(self, anon_client):
        """When ENVIRONMENT=development and no key is set, all requests pass through."""
        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await anon_client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_malformed_auth_scheme_returns_401(self, anon_client):
        """A header that does not start with 'Bearer ' is rejected with 401."""
        with patch("app.main._API_KEY", "test-key-123"):
            response = await anon_client.get(
                "/api/verify/key",
                headers={"Authorization": "Token test-key-123"},
            )
        assert response.status_code == 401


# ===========================================================================
# 2. Security Headers Tests
# ===========================================================================

class TestSecurityHeaders:
    """Every response must carry the required security headers."""

    @pytest.mark.asyncio
    async def test_x_content_type_options_nosniff(self, anon_client):
        """X-Content-Type-Options must be 'nosniff' on every response."""
        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await anon_client.get("/health")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    @pytest.mark.asyncio
    async def test_x_frame_options_deny(self, anon_client):
        """X-Frame-Options must be 'DENY' to prevent clickjacking."""
        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await anon_client.get("/health")
        assert response.headers.get("X-Frame-Options") == "DENY"

    @pytest.mark.asyncio
    async def test_x_xss_protection(self, anon_client):
        """X-XSS-Protection must be '1; mode=block'."""
        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await anon_client.get("/health")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    @pytest.mark.asyncio
    async def test_hsts_present_in_non_development(self, anon_client):
        """Strict-Transport-Security must appear when ENVIRONMENT != 'development'."""
        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "production"):
            response = await anon_client.get("/health")
        hsts = response.headers.get("Strict-Transport-Security", "")
        assert "max-age=" in hsts

    @pytest.mark.asyncio
    async def test_hsts_absent_in_development(self, anon_client):
        """Strict-Transport-Security must NOT appear in development mode."""
        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await anon_client.get("/health")
        assert "Strict-Transport-Security" not in response.headers

    @pytest.mark.asyncio
    async def test_security_headers_on_non_health_endpoint(self, anon_client):
        """Security headers must appear on all responses, not just /health."""
        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await anon_client.get("/")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"


# ===========================================================================
# 3. POST /api/verify Tests
# ===========================================================================

class TestVerifyReceipt:
    """POST /api/verify — Ed25519 signature verification."""

    @pytest.mark.asyncio
    async def test_valid_signed_receipt_returns_valid_true(self, authed_client):
        """A correctly signed receipt must return {valid: true}."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            signed = _make_signed_receipt()
            response = await authed_client.post("/api/verify", json={"receipt": signed})
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is True

    @pytest.mark.asyncio
    async def test_tampered_receipt_returns_valid_false(self, authed_client):
        """Modifying any field after signing must make verification fail."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            signed = _make_signed_receipt()
            # Tamper: change a payload field after signing
            signed["approved_by"] = "EVIL_ATTACKER"
            response = await authed_client.post("/api/verify", json={"receipt": signed})
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False

    @pytest.mark.asyncio
    async def test_receipt_with_no_signature_returns_400(self, authed_client):
        """A receipt missing the signature fields must return 400."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            unsigned = {
                "receipt_id": "test-001",
                "claim_id": "CLM-NOSIG",
                "action": "approve",
            }
            response = await authed_client.post("/api/verify", json={"receipt": unsigned})
        assert response.status_code == 400
        body = response.json()
        assert "detail" in body

    @pytest.mark.asyncio
    async def test_receipt_with_invalid_signature_returns_valid_false(self, authed_client):
        """A receipt whose signature is junk (not matching the key) must return valid=false."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            bad_receipt = {
                "receipt_id": "test-002",
                "claim_id": "CLM-BAD",
                "action": "deny",
                "signature": "aGVsbG8gd29ybGQ=",   # valid base64, wrong signature
                "public_key": "aGVsbG8gd29ybGQ=",   # wrong key
                "signature_algorithm": "Ed25519",
                "signing_key_id": "deadbeef",
            }
            response = await authed_client.post("/api/verify", json={"receipt": bad_receipt})
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False

    @pytest.mark.asyncio
    async def test_verify_returns_receipt_id_and_algorithm(self, authed_client):
        """The response must echo back receipt_id and signature_algorithm."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            signed = _make_signed_receipt()
            response = await authed_client.post("/api/verify", json={"receipt": signed})
        assert response.status_code == 200
        body = response.json()
        assert body["receipt_id"] == "test-receipt-001"
        assert body["signature_algorithm"] == "Ed25519"


# ===========================================================================
# 4. GET /api/verify/key Tests
# ===========================================================================

class TestVerifyKey:
    """GET /api/verify/key — public key info endpoint."""

    @pytest.mark.asyncio
    async def test_returns_public_key_algorithm_and_key_id(self, authed_client):
        """Response must contain public_key, algorithm, and key_id."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.get("/api/verify/key")
        assert response.status_code == 200
        body = response.json()
        assert "public_key" in body
        assert "algorithm" in body
        assert "key_id" in body

    @pytest.mark.asyncio
    async def test_algorithm_is_ed25519(self, authed_client):
        """The algorithm field must always be 'Ed25519'."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.get("/api/verify/key")
        assert response.status_code == 200
        assert response.json()["algorithm"] == "Ed25519"

    @pytest.mark.asyncio
    async def test_public_key_is_non_empty_string(self, authed_client):
        """public_key must be a non-empty base64 string."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.get("/api/verify/key")
        assert response.status_code == 200
        pk = response.json()["public_key"]
        assert isinstance(pk, str) and len(pk) > 0

    @pytest.mark.asyncio
    async def test_key_id_is_8_hex_chars(self, authed_client):
        """key_id must be exactly 8 hex characters (first 8 of SHA-256)."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.get("/api/verify/key")
        assert response.status_code == 200
        key_id = response.json()["key_id"]
        assert len(key_id) == 8
        assert all(c in "0123456789abcdef" for c in key_id)

    @pytest.mark.asyncio
    async def test_unavailable_signer_returns_503(self, authed_client):
        """When the signer reports available=False the endpoint must return 503."""
        from app.utils.trust_signer import TrustSigner
        mock_signer = MagicMock(spec=TrustSigner)
        mock_signer.available = False

        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"), \
             patch("app.main.get_signer", return_value=mock_signer):
            response = await authed_client.get("/api/verify/key")
        assert response.status_code == 503


# ===========================================================================
# 5. Webhook CRUD Tests
# ===========================================================================

class TestWebhookCRUD:
    """POST / GET / DELETE /api/webhooks and the test event endpoint."""

    # -- Registration ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_create_webhook_returns_201_and_webhook_id(self, authed_client):
        """POST /api/webhooks with a valid payload returns 201 and a webhook_id."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/webhook",
                    "secret": "super-secret",
                    "events": [],
                },
            )
        assert response.status_code == 201
        body = response.json()
        assert "webhook_id" in body
        assert isinstance(body["webhook_id"], str)
        assert len(body["webhook_id"]) > 0

    @pytest.mark.asyncio
    async def test_create_webhook_response_does_not_expose_secret(self, authed_client):
        """The registration response must never contain the endpoint secret."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/wh",
                    "secret": "my-very-secret-value",
                    "events": [],
                },
            )
        assert response.status_code == 201
        body = response.json()
        assert "secret" not in body
        # Also verify the secret is not buried in any value
        import json as _json
        assert "my-very-secret-value" not in _json.dumps(body)

    @pytest.mark.asyncio
    async def test_create_webhook_with_invalid_event_returns_400(self, authed_client):
        """Registering with an unknown event name must return 400."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/wh",
                    "secret": "s3cr3t",
                    "events": ["invalid.event.name"],
                },
            )
        assert response.status_code == 400

    # -- Listing ---------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_webhooks_returns_registered_webhook(self, authed_client):
        """GET /api/webhooks after registration must include the new endpoint."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            create_resp = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/list-test",
                    "secret": "list-secret",
                    "events": [],
                },
            )
            assert create_resp.status_code == 201
            webhook_id = create_resp.json()["webhook_id"]

            list_resp = await authed_client.get("/api/webhooks")
        assert list_resp.status_code == 200
        body = list_resp.json()
        assert isinstance(body, list)
        ids = [wh["webhook_id"] for wh in body]
        assert webhook_id in ids

    @pytest.mark.asyncio
    async def test_list_webhooks_does_not_expose_secrets(self, authed_client):
        """GET /api/webhooks must never return the endpoint secrets."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/secret-check",
                    "secret": "top-secret-value",
                    "events": [],
                },
            )
            list_resp = await authed_client.get("/api/webhooks")
        assert list_resp.status_code == 200
        import json as _json
        dumped = _json.dumps(list_resp.json())
        assert "top-secret-value" not in dumped

    @pytest.mark.asyncio
    async def test_list_webhooks_empty_when_none_registered(self, authed_client):
        """GET /api/webhooks on a clean registry returns an empty list."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.get("/api/webhooks")
        assert response.status_code == 200
        assert response.json() == []

    # -- Deletion --------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_webhook_returns_204(self, authed_client):
        """DELETE /api/webhooks/{id} on a registered webhook returns 204."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            create_resp = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/delete-me",
                    "secret": "del-secret",
                    "events": [],
                },
            )
            webhook_id = create_resp.json()["webhook_id"]
            delete_resp = await authed_client.delete(f"/api/webhooks/{webhook_id}")
        assert delete_resp.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_webhook_returns_404(self, authed_client):
        """DELETE /api/webhooks/{id} for an unknown ID must return 404."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.delete(
                "/api/webhooks/00000000-dead-beef-0000-000000000000"
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_removes_webhook_from_list(self, authed_client):
        """After deletion GET /api/webhooks must no longer include the endpoint."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            create_resp = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/gone",
                    "secret": "gone-secret",
                    "events": [],
                },
            )
            webhook_id = create_resp.json()["webhook_id"]
            await authed_client.delete(f"/api/webhooks/{webhook_id}")
            list_resp = await authed_client.get("/api/webhooks")
        ids = [wh["webhook_id"] for wh in list_resp.json()]
        assert webhook_id not in ids

    # -- Test event ------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_test_endpoint_returns_result_for_registered_webhook(self, authed_client):
        """POST /api/webhooks/{id}/test on a registered webhook returns a result dict."""
        from app.services import webhook_dispatcher

        # Mock the HTTP delivery so we don't make real network calls
        mock_result = {"success": True, "status_code": 200}

        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"), \
             patch.object(webhook_dispatcher, "send_test_event", new=AsyncMock(return_value=mock_result)):
            create_resp = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/test-target",
                    "secret": "test-secret",
                    "events": [],
                },
            )
            webhook_id = create_resp.json()["webhook_id"]
            test_resp = await authed_client.post(f"/api/webhooks/{webhook_id}/test")

        assert test_resp.status_code == 200
        body = test_resp.json()
        assert "success" in body

    @pytest.mark.asyncio
    async def test_test_endpoint_returns_404_for_missing_webhook(self, authed_client):
        """POST /api/webhooks/{id}/test with an unknown ID returns 404."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.post(
                "/api/webhooks/00000000-dead-beef-0000-000000000099/test"
            )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_create_webhook_with_wildcard_subscribes_to_all(self, authed_client):
        """Registering with events=['*'] subscribes to all events."""
        with patch("app.main._API_KEY", "test-key-123"), \
             patch("app.main.ENVIRONMENT", "development"):
            response = await authed_client.post(
                "/api/webhooks",
                json={
                    "url": "https://example.com/all-events",
                    "secret": "star-secret",
                    "events": ["*"],
                },
            )
        assert response.status_code == 201
        body = response.json()
        assert "*" in body["events"]


# ===========================================================================
# 6. Pipeline Backpressure Tests
# ===========================================================================

class TestPipelineBackpressure:
    """When _running_tasks is at MAX_CONCURRENT_PIPELINES, submit returns 429."""

    @pytest.mark.asyncio
    async def test_at_max_capacity_returns_429(self, anon_client):
        """POST /api/claims/submit when at capacity returns 429 with Retry-After."""
        import io
        import struct
        import zlib

        # Build a minimal valid PNG (1x1 white pixel) so form validation passes
        def _chunk(name: bytes, data: bytes) -> bytes:
            c = name + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(b"\x00\xFF\xFF\xFF"))
            + _chunk(b"IEND", b"")
        )

        # Fabricate a full registry of fake asyncio tasks so the guard triggers
        fake_task = MagicMock(spec=asyncio.Task)
        fake_running = {f"CLM-{i:05d}": fake_task for i in range(10)}

        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"), \
             patch("app.routes.claims._running_tasks", fake_running), \
             patch("app.routes.claims.MAX_CONCURRENT_PIPELINES", 10):
            response = await anon_client.post(
                "/api/claims/submit",
                files={"file": ("test.png", io.BytesIO(png), "image/png")},
                data={
                    "claimant_name": "Backpressure Tester",
                    "incident_description": "Testing capacity limit.",
                    "policy_number": "POL-999",
                },
            )

        assert response.status_code == 429

    @pytest.mark.asyncio
    async def test_at_max_capacity_response_has_retry_after_header(self, anon_client):
        """The 429 response must include a Retry-After header."""
        import io
        import struct
        import zlib

        def _chunk(name: bytes, data: bytes) -> bytes:
            c = name + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(b"\x00\xFF\xFF\xFF"))
            + _chunk(b"IEND", b"")
        )

        fake_task = MagicMock(spec=asyncio.Task)
        fake_running = {f"CLM-{i:05d}": fake_task for i in range(10)}

        with patch("app.main._API_KEY", None), \
             patch("app.main.ENVIRONMENT", "development"), \
             patch("app.routes.claims._running_tasks", fake_running), \
             patch("app.routes.claims.MAX_CONCURRENT_PIPELINES", 10):
            response = await anon_client.post(
                "/api/claims/submit",
                files={"file": ("test.png", io.BytesIO(png), "image/png")},
                data={
                    "claimant_name": "Header Tester",
                    "incident_description": "Checking Retry-After header.",
                },
            )

        assert response.status_code == 429
        assert "Retry-After" in response.headers

    @pytest.mark.asyncio
    async def test_below_max_capacity_submit_proceeds(self, anon_client):
        """When the registry is below capacity, requests are NOT rejected with 429."""
        from unittest.mock import AsyncMock as _AsyncMock, patch as _patch
        import io
        import json
        import struct
        import zlib

        def _chunk(name: bytes, data: bytes) -> bytes:
            c = name + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        png = (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(b"\x00\xFF\xFF\xFF"))
            + _chunk(b"IEND", b"")
        )

        grok_payloads = [
            json.dumps({"damage_type": "collision", "estimated_cost": 1000.0,
                        "vehicle_info": "Test Car", "incident_details": "Rear-end collision.",
                        "document_type": "photo", "key_findings": ["bumper cracked"]}),
            json.dumps({"overall_score": 10.0, "risk_level": "low", "signals": [],
                        "explanation": "Low risk."}),
            json.dumps({"recommended_amount": 500.0, "confidence": 0.9,
                        "rationale": "Minor damage.", "comparable_claims": []}),
            json.dumps({"approval_probability": 0.9, "dispute_risk": 0.05,
                        "fraud_escalation_likelihood": 0.02, "financial_exposure": 500.0,
                        "historical_comparison": "Normal.", "recommended_action": "approve"}),
        ]

        with _patch("app.main._API_KEY", None), \
             _patch("app.main.ENVIRONMENT", "development"), \
             _patch("app.routes.claims.MAX_CONCURRENT_PIPELINES", 10), \
             _patch("app.services.grok_service._call_grok",
                    new_callable=_AsyncMock, side_effect=grok_payloads), \
             _patch("app.services.yutori_service.YutoriService.verify_claim_entities",
                    new_callable=_AsyncMock, return_value=[]):
            response = await anon_client.post(
                "/api/claims/submit",
                files={"file": ("ok.png", io.BytesIO(png), "image/png")},
                data={
                    "claimant_name": "Under Capacity",
                    "incident_description": "Normal submission.",
                },
            )

        # Must NOT be rejected — expect 200 (success) not 429
        assert response.status_code != 429
        assert response.status_code == 200
