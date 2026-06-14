"""
Lightweight webhook dispatcher for Aubric Sovereign.

Fires asynchronous HTTP POST events to registered endpoints when billing cases
are submitted, completed, or overcharge-severity thresholds are crossed.

(The ``X-ClaimGuard-*`` HTTP header names are kept as a stable wire contract so
existing webhook consumers' signature verification keeps working.)

Design principles:
- All deliveries are non-blocking: fired via asyncio.create_task()
- SSRF prevention: private/loopback IPs are rejected before every call
- HMAC-SHA256 payload signing with per-endpoint secrets
- Exponential backoff retry (1s -> 10s -> 60s, max 3 attempts)
- In-memory registry -- acceptable for single-process deployments
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BACKOFF_SCHEDULE = [1, 10, 60]  # Seconds between retry attempts
_MAX_ATTEMPTS = 3
_TIMEOUT_SECONDS = 10.0

# Supported event names
EVENT_CLAIM_SUBMITTED = "claim.submitted"
EVENT_CLAIM_COMPLETED = "claim.completed"
EVENT_RISK_THRESHOLD_CROSSED = "risk.threshold_crossed"
EVENT_RECEIPT_GENERATED = "receipt.generated"
EVENT_WEBHOOK_TEST = "webhook.test"

ALL_EVENTS: set[str] = {
    EVENT_CLAIM_SUBMITTED,
    EVENT_CLAIM_COMPLETED,
    EVENT_RISK_THRESHOLD_CROSSED,
    EVENT_RECEIPT_GENERATED,
    EVENT_WEBHOOK_TEST,
}

# Risk thresholds that trigger risk.threshold_crossed
RISK_THRESHOLDS = [50, 70]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class WebhookEndpoint:
    """Registered webhook endpoint (in-memory)."""

    def __init__(self, url: str, secret: str, events: List[str]) -> None:
        self.webhook_id: str = str(uuid.uuid4())
        self.url: str = url
        self.secret: str = secret
        # Normalise: store as a set; "*" means subscribe to all events
        self.events: Set[str] = set(events) if events else {"*"}
        self.created_at: str = datetime.now(timezone.utc).isoformat()

    def subscribes_to(self, event: str) -> bool:
        """Check if this endpoint is subscribed to the given event."""
        return "*" in self.events or event in self.events

    def to_dict(self) -> dict:
        """Serialize for API responses (never exposes the secret)."""
        return {
            "webhook_id": self.webhook_id,
            "url": self.url,
            "events": sorted(self.events),
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------------

_registry: Dict[str, WebhookEndpoint] = {}

# Per-claim set of thresholds already fired: claim_id -> {50, 70, ...}
_threshold_crossed: Dict[str, Set[int]] = {}

# Reusable async HTTP client — avoids per-request pool setup overhead
_http_client = httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# SSRF prevention
# ---------------------------------------------------------------------------


def _is_private_ip(addr: ipaddress._BaseAddress) -> bool:
    """Check if an IP address is private/loopback/reserved."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved


# Well-known internal hostnames that should never be webhook targets
_BLOCKED_HOSTNAMES = frozenset({
    "metadata.google.internal",
    "instance-data.ec2.internal",
    "metadata.azure.internal",
})


def _is_safe_url(url: str) -> bool:
    """
    Return True if the URL target is not a private/loopback/reserved address.

    Checks both raw IPs and DNS-resolved hostnames to prevent SSRF attacks
    targeting cloud metadata endpoints (169.254.169.254, etc.).
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return False

    # Check raw IP
    try:
        addr = ipaddress.ip_address(hostname)
        return not _is_private_ip(addr)
    except ValueError:
        pass

    # DNS-resolve hostname and check all resolved IPs
    try:
        results = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for _family, _, _, _, sockaddr in results:
            ip_str = sockaddr[0]
            try:
                addr = ipaddress.ip_address(ip_str)
                if _is_private_ip(addr):
                    return False
            except ValueError:
                continue
        return True
    except socket.gaierror:
        # DNS resolution failed -- block by default
        return False


async def _is_safe_url_async(url: str) -> bool:
    """Non-blocking version of _is_safe_url for async delivery paths."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _is_safe_url, url)


# ---------------------------------------------------------------------------
# HMAC-SHA256 signing
# ---------------------------------------------------------------------------


def _sign_payload(payload: bytes, secret: str) -> str:
    """Return the HMAC-SHA256 hex digest of *payload* using *secret*."""
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Core delivery logic
# ---------------------------------------------------------------------------


async def _deliver_to_endpoint(endpoint: WebhookEndpoint, event: str, data: dict) -> None:
    """
    Attempt to deliver *event* to a single endpoint with exponential backoff.

    SSRF check is performed before every HTTP call to prevent bypass via
    endpoint URL updates between registration and delivery.
    """
    if not await _is_safe_url_async(endpoint.url):
        logger.warning(
            "Blocked webhook delivery to unsafe URL %s (SSRF prevention)", endpoint.url
        )
        return

    body_obj = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    body_bytes = json.dumps(body_obj, default=str).encode()
    signature = _sign_payload(body_bytes, endpoint.secret)

    headers = {
        "Content-Type": "application/json",
        "X-ClaimGuard-Signature": signature,
        "X-ClaimGuard-Event": event,
    }

    for attempt in range(_MAX_ATTEMPTS):
        try:
            resp = await _http_client.post(
                endpoint.url,
                content=body_bytes,
                headers=headers,
            )
            if 200 <= resp.status_code < 300:
                logger.debug(
                    "Webhook %s delivered event '%s' -> HTTP %d",
                    endpoint.url,
                    event,
                    resp.status_code,
                )
                return
            logger.warning(
                "Webhook %s returned HTTP %d for event '%s' (attempt %d/%d)",
                endpoint.url,
                resp.status_code,
                event,
                attempt + 1,
                _MAX_ATTEMPTS,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "Webhook %s HTTP error for event '%s' (attempt %d/%d): %s",
                endpoint.url,
                event,
                attempt + 1,
                _MAX_ATTEMPTS,
                exc,
            )

        # Wait before next attempt (skip after the last attempt)
        if attempt < _MAX_ATTEMPTS - 1:
            backoff = (
                _BACKOFF_SCHEDULE[attempt]
                if attempt < len(_BACKOFF_SCHEDULE)
                else _BACKOFF_SCHEDULE[-1]
            )
            await asyncio.sleep(backoff)

    logger.error(
        "Webhook %s failed to deliver event '%s' after %d attempts",
        endpoint.url,
        event,
        _MAX_ATTEMPTS,
    )


async def _fan_out(event: str, data: dict) -> None:
    """Deliver *event* to all subscribed endpoints concurrently."""
    tasks = [
        _deliver_to_endpoint(ep, event, data)
        for ep in _registry.values()
        if ep.subscribes_to(event)
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Public fire-and-forget API
# ---------------------------------------------------------------------------


def fire_event(event: str, data: dict) -> None:
    """
    Schedule asynchronous delivery of *event* to all subscribed endpoints.

    This is a synchronous call that returns immediately -- the actual HTTP
    delivery happens in the background via asyncio.create_task(). Must be
    called from within an async context (e.g. a FastAPI request handler).
    """
    if not _registry:
        return  # Nothing registered, fast path

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("fire_event called outside an asyncio event loop -- skipped")
        return

    loop.create_task(_fan_out(event, data))


# ---------------------------------------------------------------------------
# Threshold tracking helpers
# ---------------------------------------------------------------------------


def check_and_fire_threshold(claim_id: str, fraud_score: float) -> None:
    """
    Fire risk.threshold_crossed events for any new threshold crossings.

    Each threshold (50, 70) fires at most once per claim.
    """
    already_fired = _threshold_crossed.setdefault(claim_id, set())

    for threshold in RISK_THRESHOLDS:
        if fraud_score >= threshold and threshold not in already_fired:
            already_fired.add(threshold)
            policy_action = "block" if threshold >= 70 else "escalate"
            fire_event(
                EVENT_RISK_THRESHOLD_CROSSED,
                {
                    "claim_id": claim_id,
                    "fraud_score": fraud_score,
                    "threshold": threshold,
                    "policy_action": policy_action,
                },
            )
            logger.info(
                "Fired %s for claim %s (fraud_score=%.1f, threshold=%d)",
                EVENT_RISK_THRESHOLD_CROSSED,
                claim_id,
                fraud_score,
                threshold,
            )


def clear_threshold_state(claim_id: str) -> None:
    """Remove threshold tracking state for a completed claim."""
    _threshold_crossed.pop(claim_id, None)


# ---------------------------------------------------------------------------
# Registry CRUD (called from main.py endpoints)
# ---------------------------------------------------------------------------


def register_webhook(url: str, secret: str, events: List[str]) -> WebhookEndpoint:
    """Add a new webhook endpoint and return it."""
    ep = WebhookEndpoint(url=url, secret=secret, events=events)
    _registry[ep.webhook_id] = ep
    logger.info("Registered webhook %s -> %s events=%s", ep.webhook_id, url, ep.events)
    return ep


def list_webhooks() -> List[dict]:
    """Return all registered webhooks (without secrets)."""
    return [ep.to_dict() for ep in _registry.values()]


def get_webhook(webhook_id: str) -> Optional[WebhookEndpoint]:
    """Retrieve a single webhook endpoint by ID, or None."""
    return _registry.get(webhook_id)


def remove_webhook(webhook_id: str) -> bool:
    """Remove a webhook by ID. Returns True if it existed."""
    if webhook_id in _registry:
        del _registry[webhook_id]
        logger.info("Removed webhook %s", webhook_id)
        return True
    return False


async def send_test_event(endpoint: WebhookEndpoint) -> dict:
    """
    Deliver a webhook.test event synchronously and return the result.

    Unlike fire_event(), this awaits the result so the caller can report
    success/failure back to the API consumer.
    """
    if not await _is_safe_url_async(endpoint.url):
        return {"success": False, "status_code": None, "error": "Blocked: unsafe URL target"}

    body_obj = {
        "event": EVENT_WEBHOOK_TEST,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": {
            "test": True,
            "message": "This is a test event from Aubric Sovereign.",
            "webhook_id": endpoint.webhook_id,
        },
    }
    body_bytes = json.dumps(body_obj, default=str).encode()
    signature = _sign_payload(body_bytes, endpoint.secret)

    headers = {
        "Content-Type": "application/json",
        "X-ClaimGuard-Signature": signature,
        "X-ClaimGuard-Event": EVENT_WEBHOOK_TEST,
    }

    try:
        resp = await _http_client.post(endpoint.url, content=body_bytes, headers=headers)
        success = 200 <= resp.status_code < 300
        return {"success": success, "status_code": resp.status_code}
    except httpx.HTTPError as exc:
        return {"success": False, "status_code": None, "error": str(exc)}
