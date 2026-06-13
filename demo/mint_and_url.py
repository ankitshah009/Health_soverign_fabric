"""Mint a fresh signed receipt and print the browser verify URL."""
import asyncio
import base64
import json
import urllib.parse
import httpx

BASE = "http://localhost:8000"
BILL = "/Users/ankitparagshah/GitHub/Health_soverign_fabric/demo/sample_er_bill.png"


async def main() -> None:
    async with httpx.AsyncClient(timeout=90) as c:
        with open(BILL, "rb") as f:
            r = await c.post(
                f"{BASE}/api/claims/submit",
                files={"file": ("bill.png", f, "image/png")},
                data={
                    "claimant_name": "Demo Patient",
                    "incident_description": "I got a $4,200 ER bill for a sprained ankle and my insurance denied it.",
                    "policy_number": "POL-2026-0048817",
                },
            )
        cid = r.json().get("id") or r.json().get("claim_id")
        for _ in range(60):
            j = (await c.get(f"{BASE}/api/claims/{cid}")).json()
            if j.get("risk_assessment") and j.get("status") not in ("processing", "submitted", None):
                break
            await asyncio.sleep(2)
        await asyncio.sleep(6)  # let async simulation populate so the receipt carries the appeal odds

        ap = await c.post(f"{BASE}/api/approvals", json={
            "claim_id": cid, "decision": "approve",
            "approver_name": "Demo Patient", "notes": "I consent to file the appeal.",
        })
        receipt = ap.json().get("receipt")
        v = (await c.post(f"{BASE}/api/verify", json={"receipt": receipt})).json()
        print("CASE:", cid, "| BACKEND_VERIFY_VALID:", v.get("valid"))
        b64 = base64.b64encode(json.dumps(receipt).encode()).decode()
        print("VERIFY_URL=http://localhost:3000/verify?receipt=" + urllib.parse.quote(b64))


asyncio.run(main())
