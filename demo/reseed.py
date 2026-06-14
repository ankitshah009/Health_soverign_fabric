"""Re-seed the demo dashboard with fresh, clean medical cases (named patients)."""
import asyncio
import httpx

BASE = "http://localhost:8000"
BILL = "/Users/ankitparagshah/GitHub/Health_soverign_fabric/demo/sample_er_bill.png"

CASES = [
    ("Sofia Ramirez", "BCBS-PPO-2026",
     "I got a $4,200 ER bill for a sprained ankle and my insurance denied it as 'not medically necessary'."),
    ("James Carter", "AETNA-HDHP-2026",
     "I got a surprise out-of-network radiologist bill on top of my in-network hospital visit."),
    ("Priya Nair", "UHC-EPO-2026",
     "My itemized hospital bill charged me twice for the same ER visit and the codes look upcoded."),
]


async def submit(c, name, pol, desc):
    with open(BILL, "rb") as f:
        r = await c.post(
            f"{BASE}/api/claims/submit",
            files={"file": ("bill.png", f, "image/png")},
            data={"claimant_name": name, "incident_description": desc, "policy_number": pol},
        )
    return r.json().get("id") or r.json().get("claim_id")


async def main() -> None:
    async with httpx.AsyncClient(timeout=120) as c:
        ids = []
        for name, pol, desc in CASES:
            cid = await submit(c, name, pol, desc)
            ids.append((cid, name))
            print("submitted:", name, cid)
            await asyncio.sleep(1)
        for _ in range(45):
            statuses = []
            for cid, _n in ids:
                j = (await c.get(f"{BASE}/api/claims/{cid}")).json()
                statuses.append(j.get("status"))
            if all(s not in ("processing", "submitted", None) for s in statuses):
                break
            await asyncio.sleep(2)
        print("\n--- final ---")
        for cid, name in ids:
            j = (await c.get(f"{BASE}/api/claims/{cid}")).json()
            cov = j.get("coverage_result") or {}
            pr = j.get("payout_recommendation") or {}
            print(f"{name}: {j.get('status')} | coverage={cov.get('coverage_type')} | recoverable=${pr.get('recommended_amount')}")


asyncio.run(main())
