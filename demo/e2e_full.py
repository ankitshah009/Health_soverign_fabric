"""End-to-end check: submit a real bill, dump the full analysis, and grep for any
leftover auto/home-insurance content. Then consent -> signed receipt -> verify."""
import asyncio
import json
import re
import httpx

BASE = "http://localhost:8000"
BILL = "/Users/ankitparagshah/GitHub/Health_soverign_fabric/demo/sample_er_bill.png"

# Auto/home-insurance content words (NOT the kept field-name keys like damage_type).
AUTO = re.compile(
    r"vehicle collision|fire damage|water damage|fender|bumper|vandal|\bcollision\b|"
    r"adjuster|repair shop|hit and run|weather damage|salvage|\bVIN\b",
    re.I,
)


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as c:
        with open(BILL, "rb") as f:
            r = await c.post(
                f"{BASE}/api/claims/submit",
                files={"file": ("bill.png", f, "image/png")},
                data={
                    "claimant_name": "Sofia Ramirez",
                    "incident_description": "I got a $4,200 ER bill for a sprained ankle, denied as 'not medically necessary'.",
                    "policy_number": "BCBS-PPO-2026",
                },
            )
        cid = r.json().get("id") or r.json().get("claim_id")
        print("CASE:", cid)
        j = {}
        for _ in range(60):
            j = (await c.get(f"{BASE}/api/claims/{cid}")).json()
            if j.get("risk_assessment") and j.get("status") not in ("processing", "submitted", None):
                break
            await asyncio.sleep(2)
        await asyncio.sleep(7)  # let async simulation populate
        j = (await c.get(f"{BASE}/api/claims/{cid}")).json()

        cov = j.get("coverage_result") or {}
        print("\n=== COVERAGE (the part that was showing car-insurance) ===")
        print("type:", cov.get("coverage_type"), "| covered:", cov.get("covered"))
        print("EXPLANATION:", cov.get("explanation"))

        print("\n=== OVERCHARGE SIGNALS ===", [s.get("signal_name") for s in (j.get("fraud_signals") or [])])
        pr = j.get("payout_recommendation") or {}
        print("RECOVERABLE $:", pr.get("recommended_amount"))
        sim = j.get("simulation_result") or {}
        print("APPEAL SUCCESS:", sim.get("approval_probability"), "| ACTION:", sim.get("recommended_action"))

        blob = json.dumps(j)
        hits = sorted(set(m.lower() for m in AUTO.findall(blob)))
        print("\n=== AUTO-INSURANCE LEFTOVERS IN THE ANALYSIS:", hits if hits else "NONE ✓")

        ap = await c.post(f"{BASE}/api/approvals", json={
            "claim_id": cid, "decision": "approve", "approver_name": "Sofia Ramirez", "notes": "I consent.",
        })
        rec = ap.json().get("receipt") or {}
        print("\n=== RECEIPT policy_check ===", rec.get("policy_check"))
        if rec:
            v = (await c.post(f"{BASE}/api/verify", json={"receipt": rec})).json()
            print("RECEIPT VERIFY:", v.get("valid"))


asyncio.run(main())
