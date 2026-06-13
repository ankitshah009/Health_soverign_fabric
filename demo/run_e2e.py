#!/usr/bin/env python3
"""Live end-to-end test for Sovereign — proves Grok VISION works on a real bill image.

Flow:
  1. POST demo/sample_er_bill.png as multipart to /api/claims/submit
     (fields: file, claimant_name, incident_description, policy_number).
  2. Poll GET /api/claims/{id} until the pipeline reaches a terminal/analyzed state.
  3. Fetch GET /api/claims/{id}/evidence  and  GET /api/claims/{id}/receipt.
  4. Save the full bundle to demo/e2e_result.json.
  5. Print a human summary: what VISION extracted (total billed + line items)
     and what OVERCHARGE SIGNALS the pipeline detected.

Usage:
    backend/.venv/bin/python demo/run_e2e.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

BASE = "http://localhost:8000"
REPO = Path(__file__).resolve().parents[1]
BILL = REPO / "demo" / "sample_er_bill.png"
OUT = REPO / "demo" / "e2e_result.json"

CLAIMANT = "Demo Patient"
INCIDENT = (
    "I got a $4,200 ER bill for a sprained ankle and my insurance denied it. "
    "The hospital itemized statement looks like it charged me for the same ER visit "
    "twice. Please review it and find anything I was overcharged for."
)
POLICY = "BCBS-PPO-4471-2026"

# A claim is "done enough" once it reaches any of these statuses, OR once
# extracted_data is populated (vision step finished) and the pipeline has settled.
TERMINAL = {
    "auto_approved", "approved", "pending_review", "denied",
    "blocked", "escalated", "error",
}
POLL_TIMEOUT_S = 120.0
POLL_INTERVAL_S = 2.0


def _money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def submit() -> str:
    if not BILL.exists():
        sys.exit(f"FATAL: bill image missing at {BILL} — run demo/make_bill.py first.")
    print(f"→ Submitting {BILL.name} ({BILL.stat().st_size:,} bytes) to {BASE}/api/claims/submit")
    with httpx.Client(timeout=60.0) as client:
        with BILL.open("rb") as fh:
            files = {"file": (BILL.name, fh, "image/png")}
            data = {
                "claimant_name": CLAIMANT,
                "incident_description": INCIDENT,
                "policy_number": POLICY,
            }
            resp = client.post(f"{BASE}/api/claims/submit", files=files, data=data)
    resp.raise_for_status()
    body = resp.json()
    claim_id = body.get("claim_id") or (body.get("data") or {}).get("id")
    if not claim_id:
        sys.exit(f"FATAL: no claim_id in submit response: {json.dumps(body)[:400]}")
    print(f"  submitted. claim_id={claim_id}  status={body.get('status')}")
    return claim_id


def poll(claim_id: str) -> dict[str, Any]:
    print(f"→ Polling {BASE}/api/claims/{claim_id} (timeout {POLL_TIMEOUT_S:.0f}s)...")
    deadline = time.monotonic() + POLL_TIMEOUT_S
    last_status = None
    vision_seen = False
    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            r = client.get(f"{BASE}/api/claims/{claim_id}")
            r.raise_for_status()
            claim = r.json()
            status = claim.get("status")
            if status != last_status:
                print(f"  status: {status}")
                last_status = status
            extracted = claim.get("extracted_data")
            if extracted and not vision_seen:
                vision_seen = True
                total = (extracted or {}).get("estimated_cost")
                print(f"  vision done — extracted total billed = {_money(total)}")
            if status in TERMINAL:
                # Give the async tail (simulation/receipt) a brief moment if approved.
                print(f"  reached terminal status: {status}")
                return claim
            time.sleep(POLL_INTERVAL_S)
    print("  WARN: poll timed out — returning last known claim state.")
    with httpx.Client(timeout=30.0) as client:
        return client.get(f"{BASE}/api/claims/{claim_id}").json()


def fetch(claim_id: str, path: str) -> Any:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(f"{BASE}/api/claims/{claim_id}/{path}")
        if r.status_code == 404:
            return {"_http_status": 404, "_note": f"{path} not available"}
        r.raise_for_status()
        return r.json()


def summarize(evidence: dict[str, Any], claim: dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print("  VISION + OVERCHARGE PROOF  —  Sovereign live E2E")
    print("=" * 72)

    extracted = evidence.get("extracted_data") or claim.get("extracted_data") or {}
    doc_type = extracted.get("document_type") or extracted.get("damage_type")
    total = extracted.get("estimated_cost")
    findings = extracted.get("key_findings") or []
    summary_txt = extracted.get("incident_details") or ""

    print(f"\n[VISION] document classified as : {doc_type}")
    print(f"[VISION] TOTAL BILLED extracted  : {_money(total)}")
    if summary_txt:
        print(f"[VISION] summary                 : {summary_txt[:200]}")
    print(f"[VISION] LINE ITEMS extracted ({len(findings)}):")
    for item in findings:
        print(f"           • {item}")

    fraud = evidence.get("fraud_assessment") or {}
    score = fraud.get("overall_score")
    level = fraud.get("risk_level")
    print(f"\n[OVERCHARGE] severity score      : {score}/100  ({level})")

    # Fraud signals live on the claim record (fraud_signals) — surface them.
    signals = claim.get("fraud_signals") or []
    print(f"[OVERCHARGE] signals detected ({len(signals)}):")
    for s in signals:
        if isinstance(s, dict):
            name = s.get("signal_name") or s.get("name") or "signal"
            desc = s.get("description") or ""
            sev = s.get("severity") or ""
            print(f"           • [{sev}] {name}: {desc}")
        else:
            print(f"           • {s}")

    dup = any(
        isinstance(s, dict) and "duplicate" in str(s.get("signal_name", "")).lower()
        for s in signals
    )
    print(f"\n[CHECK] duplicate CPT 99285 charge flagged? : {'YES ✓' if dup else 'no'}")

    payout = evidence.get("payout_recommendation") or {}
    if payout:
        print(f"[RECOVERY] recommended recoverable amount   : {_money(payout.get('recommended_amount'))}")
        if payout.get("rationale"):
            print(f"[RECOVERY] rationale: {str(payout.get('rationale'))[:200]}")

    receipt = evidence.get("receipt") or {}
    if receipt:
        print(f"\n[RECEIPT] receipt_id   : {receipt.get('receipt_id')}")
        print(f"[RECEIPT] action       : {receipt.get('action')}")
        print(f"[RECEIPT] sig algorithm: {receipt.get('signature_algorithm')}  key: {receipt.get('signing_key_id')}")
    else:
        print("\n[RECEIPT] none yet — receipt is minted after verbal consent / approval in the demo.")
    print("=" * 72)


def main() -> int:
    claim_id = submit()
    claim = poll(claim_id)
    evidence = fetch(claim_id, "evidence")
    receipt = fetch(claim_id, "receipt")
    audit = fetch(claim_id, "audit")

    # Refresh the claim once more so fraud_signals/payout are fully captured.
    with httpx.Client(timeout=30.0) as client:
        claim = client.get(f"{BASE}/api/claims/{claim_id}").json()

    bundle = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "base_url": BASE,
        "image": str(BILL),
        "submit_fields": {
            "claimant_name": CLAIMANT,
            "incident_description": INCIDENT,
            "policy_number": POLICY,
        },
        "claim_id": claim_id,
        "final_status": claim.get("status"),
        "claim": claim,
        "evidence": evidence,
        "receipt": receipt,
        "audit": audit,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(bundle, indent=2, default=str))
    print(f"\n→ Saved full results to {OUT}  ({OUT.stat().st_size:,} bytes)")

    summarize(evidence if isinstance(evidence, dict) else {}, claim)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
