"""Prove the full patient demo climax: submit bill -> analyze -> CONSENT -> signed receipt -> verify."""
import asyncio
import httpx

BASE = "http://localhost:8000"
BILL = "/Users/ankitparagshah/GitHub/Health_soverign_fabric/demo/sample_er_bill.png"


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as c:
        with open(BILL, "rb") as f:
            files = {"file": ("bill.png", f, "image/png")}
            data = {
                "claimant_name": "Demo Patient",
                "incident_description": "I got a $4,200 ER bill for a sprained ankle and my insurance denied it.",
                "policy_number": "POL-2026-0048817",
            }
            r = await c.post(f"{BASE}/api/claims/submit", files=files, data=data)
        r.raise_for_status()
        sub = r.json()
        cid = sub.get("id") or sub.get("claim_id")
        print("SUBMITTED:", cid)

        j = {}
        for _ in range(60):
            j = (await c.get(f"{BASE}/api/claims/{cid}")).json()
            if j.get("risk_assessment") and j.get("status") not in ("processing", "submitted", None):
                break
            await asyncio.sleep(2)

        ra = j.get("risk_assessment") or {}
        pr = j.get("payout_recommendation") or {}
        sim = j.get("simulation_result") or {}
        print("STATUS:", j.get("status"), "(want: needs_consent / ready / analyzed — NOT blocked)")
        print("OVERCHARGE_SCORE:", j.get("fraud_score"), "| RISK_ACTION:", ra.get("recommended_action"))
        print("RECOVERY_EST:", pr.get("recommended_amount"), "| APPEAL_SUCCESS:", sim.get("approval_probability"), "| SIM_ACTION:", sim.get("recommended_action"))

        # PATIENT CONSENT -> file the appeal on their behalf
        ap = await c.post(f"{BASE}/api/approvals", json={
            "claim_id": cid, "decision": "approve",
            "approver_name": "Demo Patient", "notes": "I consent to file the appeal.",
        })
        apj = ap.json()
        print("CONSENT -> APPROVED:", apj.get("success"), "| DECISION:", apj.get("decision"), "| OVERRIDE_APPLIED:", apj.get("override_applied"), "(want: True / approve / False)")
        receipt = apj.get("receipt")
        print("RECEIPT_ID:", (receipt or {}).get("receipt_id"), "| SIGNED:", bool((receipt or {}).get("signature")))

        if receipt:
            v = (await c.post(f"{BASE}/api/verify", json={"receipt": receipt})).json()
            print("VERIFY:", v)


asyncio.run(main())
