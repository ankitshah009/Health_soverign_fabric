"""
Ed25519 decision receipt signing service for Aubric ClaimGuard.

Signs decision receipts with Ed25519 to produce cryptographically verifiable
attestations. Any third party can verify a receipt was genuinely issued by
ClaimGuard and hasn't been tampered with.

Architecture:
  Receipt (dict) -> canonical_serialize -> Ed25519 sign -> add signature fields
  Verification:  -> strip signature fields -> canonical_serialize -> Ed25519 verify
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.config import ED25519_PRIVATE_KEY_B64, ED25519_PRIVATE_KEY_FILE

logger = logging.getLogger(__name__)

# Fields added by signing -- excluded from the canonical payload.
# signature_hash is a derived duplicate of `signature`, so it is also excluded:
# both sign() and verify() must agree on the exact same field set or every
# receipt fails verification.
_SIGNATURE_FIELDS = {"signature", "public_key", "signature_algorithm", "signing_key_id", "signature_hash"}


class TrustSignerError(Exception):
    """Raised when signing or verification fails."""


class TrustSigner:
    """
    Ed25519 receipt signing and verification.

    Key sources (checked in order):
      1. ED25519_PRIVATE_KEY_B64 env var (base64-encoded 32-byte seed)
      2. ED25519_PRIVATE_KEY_FILE env var (path to PEM file)
      3. Auto-generate ephemeral key (development only, logged as warning)
    """

    def __init__(self) -> None:
        self._private_key: Optional[Ed25519PrivateKey] = None
        self._public_key: Optional[Ed25519PublicKey] = None
        self._key_id: str = ""
        self._public_key_b64_cached: str = ""
        self._load_key()

    @property
    def available(self) -> bool:
        """Whether a signing key is loaded and ready."""
        return self._private_key is not None

    @property
    def public_key_b64(self) -> str:
        """Base64-encoded public key bytes (32 bytes, raw format). Cached at key load time."""
        return self._public_key_b64_cached

    @property
    def key_id(self) -> str:
        """Short identifier for the signing key (first 8 chars of SHA-256 of public key)."""
        return self._key_id

    # -- Signing ---------------------------------------------------------------

    def sign(self, data: dict) -> dict:
        """
        Sign a dict and return a new dict with signature fields added.

        Adds fields: signature, public_key, signature_algorithm, signing_key_id.

        Raises TrustSignerError if no signing key is available. Never returns
        an unsigned payload -- the caller should handle the error.
        """
        if not self._private_key:
            raise TrustSignerError("No signing key available -- cannot sign receipt")

        # Strip any existing signature fields before computing canonical form
        payload = {k: v for k, v in data.items() if k not in _SIGNATURE_FIELDS}

        canonical = _canonical_serialize(payload)
        try:
            signature_bytes = self._private_key.sign(canonical)
        except Exception as e:
            raise TrustSignerError(f"Ed25519 signing failed: {e}") from e

        # Build result with signature fields appended
        result = dict(data)
        result["signature"] = base64.b64encode(signature_bytes).decode("ascii")
        result["public_key"] = self.public_key_b64
        result["signature_algorithm"] = "Ed25519"
        result["signing_key_id"] = self._key_id

        logger.info(
            "Receipt signed (key_id=%s, receipt_id=%s)",
            self._key_id,
            data.get("receipt_id", "unknown"),
        )
        return result

    # -- Verification ----------------------------------------------------------

    @staticmethod
    def verify(data: dict) -> bool:
        """
        Verify a signed dict's Ed25519 signature.

        Returns True if the signature is valid. Returns False if:
          - No signature field present
          - Public key is missing or invalid
          - Signature doesn't match the payload

        This is a static method -- anyone with the signed data can verify it
        without needing the private key.
        """
        signature_b64 = data.get("signature")
        public_key_b64 = data.get("public_key")

        if not signature_b64 or not public_key_b64:
            return False

        try:
            signature_bytes = base64.b64decode(signature_b64)
            public_key_bytes = base64.b64decode(public_key_b64)

            public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)

            # Reconstruct canonical payload (excluding signature fields)
            payload = {k: v for k, v in data.items() if k not in _SIGNATURE_FIELDS}
            canonical = _canonical_serialize(payload)

            public_key.verify(signature_bytes, canonical)
            return True

        except Exception:
            return False

    # -- Key Management --------------------------------------------------------

    def _cache_public_key(self) -> None:
        """Cache the base64-encoded public key so sign() doesn't re-encode every call."""
        if self._public_key:
            raw = self._public_key.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
            self._public_key_b64_cached = base64.b64encode(raw).decode("ascii")

    def _load_key(self) -> None:
        """Load or generate the signing key."""
        # Try base64-encoded seed from config
        key_b64 = ED25519_PRIVATE_KEY_B64
        if key_b64:
            try:
                seed = base64.b64decode(key_b64)
                self._private_key = Ed25519PrivateKey.from_private_bytes(seed)
                self._public_key = self._private_key.public_key()
                self._key_id = _compute_key_id(self._public_key)
                self._cache_public_key()
                logger.info(
                    "Loaded Ed25519 signing key from ED25519_PRIVATE_KEY_B64 (key_id=%s)",
                    self._key_id,
                )
                return
            except Exception as e:
                logger.error("Failed to load ED25519_PRIVATE_KEY_B64: %s", e)

        # Try PEM file
        key_file = ED25519_PRIVATE_KEY_FILE
        if key_file and os.path.isfile(key_file):
            try:
                with open(key_file, "rb") as f:
                    self._private_key = serialization.load_pem_private_key(  # type: ignore[assignment]
                        f.read(), password=None
                    )
                self._public_key = self._private_key.public_key()
                self._key_id = _compute_key_id(self._public_key)
                self._cache_public_key()
                logger.info(
                    "Loaded Ed25519 signing key from %s (key_id=%s)",
                    key_file,
                    self._key_id,
                )
                return
            except Exception as e:
                logger.error("Failed to load key file %s: %s", key_file, e)

        # Auto-generate ephemeral key for development
        logger.warning(
            "No Ed25519 signing key configured -- generating ephemeral key. "
            "Set ED25519_PRIVATE_KEY_B64 or ED25519_PRIVATE_KEY_FILE for production."
        )
        self._private_key = Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()
        self._key_id = _compute_key_id(self._public_key)
        self._cache_public_key()
        logger.info("Generated ephemeral Ed25519 key (key_id=%s)", self._key_id)


# -- Helpers -------------------------------------------------------------------


def _normalize_numbers(obj: Any) -> Any:
    """Make int and integer-valued float canonicalize identically.

    A receipt is signed in Python (json renders 100.0 -> "100.0") but verified
    after a browser round-trip, where JavaScript's JSON collapses 100.0 -> 100
    and 0.0 -> 0. That would change the canonical bytes and break verification.
    Normalizing integer-valued floats to int on BOTH sign and verify keeps the
    signature stable across languages.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        try:
            if obj == int(obj):
                return int(obj)
        except (ValueError, OverflowError):
            pass
        return obj
    if isinstance(obj, dict):
        return {k: _normalize_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_numbers(v) for v in obj]
    return obj


def _canonical_serialize(payload: dict) -> bytes:
    """
    Deterministic, cross-language JSON serialization for signing.

    Sorted keys, no whitespace, ensure_ascii=True, and integer-valued floats
    normalized to int so Python-signed receipts verify after a JS round-trip.
    """
    return json.dumps(
        _normalize_numbers(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,  # Handle datetime, enums, etc.
    ).encode("utf-8")


def _compute_key_id(public_key: Ed25519PublicKey) -> str:
    """First 8 hex chars of SHA-256 of the raw public key bytes."""
    raw = public_key.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:8]


# -- Module-level singleton (eager initialization) ----------------------------

_signer: TrustSigner = TrustSigner()


def get_signer() -> TrustSigner:
    """Return the module-level TrustSigner singleton (created at import time)."""
    return _signer
