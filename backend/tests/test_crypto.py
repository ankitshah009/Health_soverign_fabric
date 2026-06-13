"""Unit tests for app.utils.crypto and app.utils.trust_signer.

Covers:
  - generate_receipt_id format and uniqueness
  - compute_signature returns Ed25519 signature dict
  - Ed25519 signing determinism and tamper detection
  - TrustSigner sign/verify round-trip
"""
from __future__ import annotations

import pytest

from app.utils.crypto import compute_signature, generate_receipt_id
from app.utils.trust_signer import TrustSigner, get_signer


# ---------------------------------------------------------------------------
# generate_receipt_id
# ---------------------------------------------------------------------------

class TestGenerateReceiptId:

    def test_starts_with_rec_prefix(self):
        rid = generate_receipt_id()
        assert rid.startswith("REC-")

    def test_total_length_is_twelve_characters(self):
        rid = generate_receipt_id()
        assert len(rid) == 12

    def test_suffix_is_all_hex(self):
        rid = generate_receipt_id()
        suffix = rid[len("REC-"):]
        assert all(c in "0123456789abcdef" for c in suffix), f"Expected hex, got: {suffix!r}"

    def test_suffix_has_exactly_eight_hex_chars(self):
        rid = generate_receipt_id()
        suffix = rid[len("REC-"):]
        assert len(suffix) == 8

    def test_uniqueness_across_multiple_calls(self):
        ids = {generate_receipt_id() for _ in range(50)}
        assert len(ids) == 50

    def test_format_matches_rec_hex_pattern(self):
        import re
        rid = generate_receipt_id()
        assert re.fullmatch(r"REC-[0-9a-f]{8}", rid), f"Does not match REC-xxxxxxxx: {rid!r}"


# ---------------------------------------------------------------------------
# compute_signature — Ed25519 output format
# ---------------------------------------------------------------------------

class TestComputeSignatureFormat:

    def test_returns_dict_with_signature_fields(self):
        sig = compute_signature({"key": "value"})
        assert isinstance(sig, dict)
        assert "signature" in sig
        assert "public_key" in sig
        assert "signature_algorithm" in sig
        assert "signing_key_id" in sig

    def test_signature_algorithm_is_ed25519(self):
        sig = compute_signature({"key": "value"})
        assert sig["signature_algorithm"] == "Ed25519"

    def test_signing_key_id_is_8_hex_chars(self):
        sig = compute_signature({"key": "value"})
        assert len(sig["signing_key_id"]) == 8
        int(sig["signing_key_id"], 16)  # must be valid hex


# ---------------------------------------------------------------------------
# Ed25519 sign/verify round-trip
# ---------------------------------------------------------------------------

class TestTrustSignerRoundTrip:

    def test_signer_is_available(self):
        signer = get_signer()
        assert signer.available

    def test_sign_and_verify_succeeds(self):
        signer = get_signer()
        data = {"receipt_id": "REC-test01", "claim_id": "CLM-001", "action": "approve"}
        signed = signer.sign(data)
        assert TrustSigner.verify(signed) is True

    def test_tampered_data_fails_verification(self):
        signer = get_signer()
        data = {"receipt_id": "REC-test02", "claim_id": "CLM-002", "action": "approve"}
        signed = signer.sign(data)
        signed["action"] = "deny"  # tamper
        assert TrustSigner.verify(signed) is False

    def test_missing_signature_fails_verification(self):
        assert TrustSigner.verify({"key": "value"}) is False

    def test_same_data_produces_same_signature(self):
        signer = get_signer()
        data = {"a": 1, "b": 2}
        sig1 = signer.sign(data)["signature"]
        sig2 = signer.sign(data)["signature"]
        assert sig1 == sig2

    def test_different_data_produces_different_signature(self):
        signer = get_signer()
        sig1 = signer.sign({"action": "approve"})["signature"]
        sig2 = signer.sign({"action": "deny"})["signature"]
        assert sig1 != sig2

    def test_key_order_does_not_affect_signature(self):
        signer = get_signer()
        sig1 = signer.sign({"a": 1, "b": 2})["signature"]
        sig2 = signer.sign({"b": 2, "a": 1})["signature"]
        assert sig1 == sig2


# ---------------------------------------------------------------------------
# compute_signature — sensitivity to field changes
# ---------------------------------------------------------------------------

class TestComputeSignatureSensitivity:

    BASE = {
        "receipt_id": "REC-55555",
        "claim_id": "CLM-STABLE",
        "action": "approve",
        "approver": "verifier",
        "identity_confidence": 0.9,
        "fraud_score": 5.0,
        "timestamp": "2024-06-01T12:00:00+00:00",
    }

    def test_changing_action_changes_signature(self):
        sig1 = compute_signature(self.BASE)["signature"]
        sig2 = compute_signature({**self.BASE, "action": "deny"})["signature"]
        assert sig1 != sig2

    def test_changing_claim_id_changes_signature(self):
        sig1 = compute_signature(self.BASE)["signature"]
        sig2 = compute_signature({**self.BASE, "claim_id": "CLM-TAMPERED"})["signature"]
        assert sig1 != sig2

    def test_changing_approver_changes_signature(self):
        sig1 = compute_signature(self.BASE)["signature"]
        sig2 = compute_signature({**self.BASE, "approver": "fraud_actor"})["signature"]
        assert sig1 != sig2

    def test_changing_fraud_score_changes_signature(self):
        sig1 = compute_signature(self.BASE)["signature"]
        sig2 = compute_signature({**self.BASE, "fraud_score": 99.9})["signature"]
        assert sig1 != sig2

    def test_adding_extra_field_changes_signature(self):
        sig1 = compute_signature(self.BASE)["signature"]
        sig2 = compute_signature({**self.BASE, "extra_key": "extra_value"})["signature"]
        assert sig1 != sig2
