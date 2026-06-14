"""Prove the PDF upload flows end to end: PDF -> Grok Vision -> overcharge findings."""
import asyncio
import httpx

BASE = "http://localhost:8000"
PDF = "/Users/ankitparagshah/GitHub/Health_soverign_fabric/demo/sample_medical_bill.pdf"


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as c:
        with open(PDF, "rb") as f:
            r = await c.post(
                f"{BASE}/api/claims/submit",
                files={"file": ("bill.pdf", f, "application/pdf")},
                data={
                    "claimant_name": "Ankit Shah",
                    "incident_description": "My $4,200 ER bill for a sprained ankle was denied as not medically necessary.",
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
        await asyncio.sleep(6)
        j = (await c.get(f"{BASE}/api/claims/{cid}")).json()
        ed = j.get("extracted_data") or {}
        print("VISION read the PDF -> doc_type:", ed.get("document_type"), "| total billed:", ed.get("estimated_cost"))
        print("key findings:", (ed.get("key_findings") or [])[:5])
        print("OVERCHARGE signals:", [s.get("signal_name") for s in (j.get("fraud_signals") or [])][:5])
        pr = j.get("payout_recommendation") or {}
        sim = j.get("simulation_result") or {}
        print("recoverable $:", pr.get("recommended_amount"), "| appeal:", sim.get("approval_probability"))
        print("status:", j.get("status"))


asyncio.run(main())
