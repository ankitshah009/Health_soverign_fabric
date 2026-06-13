"""Shared receipt ID generation and tamper-evident signature computation."""

from __future__ import annotations

import secrets
from typing import Any


def generate_receipt_id() -> str:
    """Generate a unique receipt ID in REC-XXXXXXXX format."""
    return f"REC-{secrets.token_hex(4)}"


def compute_signature(fields: dict[str, Any]) -> dict[str, str]:
    """Sign all fields using Ed25519 and return signature metadata.

    Returns a dict with keys: signature, public_key, signature_algorithm,
    signing_key_id. Uses the module-level TrustSigner singleton.

    This replaces the previous SHA-256 hash implementation but keeps the
    same function name for backwards compatibility.
    """
    from app.utils.trust_signer import get_signer

    signer = get_signer()
    signed = signer.sign(fields)
    return {
        "signature": signed["signature"],
        "public_key": signed["public_key"],
        "signature_algorithm": signed["signature_algorithm"],
        "signing_key_id": signed["signing_key_id"],
    }
