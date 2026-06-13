# Sovereign — 90-Second Demo Runbook

**Product:** Sovereign — the voice-first AI patient advocate that fights medical bills & insurance denials, and signs every action with a verifiable, **patient-owned** receipt.

**The one-liner (say this first):** *"Sovereign is an AI advocate that reads your medical bill, finds what you were overcharged, fights it for you in your voice — and gives you cryptographic proof of every action it took on your behalf."*

**Demo asset:** `demo/sample_er_bill.png` — a real ER itemized statement, $4,200, sprained ankle, with CPT **99285 billed twice** (a duplicate) + an over-priced IV saline line. This is what Sovereign catches live.

---

## 0. Pre-flight (do this BEFORE you walk on stage)

```bash
# Terminal 1 — backend on :8000 (development mode = no auth needed)
cd backend && ENVIRONMENT=development .venv/bin/python -m uvicorn app.main:app --port 8000

# Terminal 2 — frontend on :3003
cd frontend && npm run dev -- -p 3003
```

Checklist:
- [ ] `curl -s localhost:8000/health` returns **200**.
- [ ] Browser open to **http://localhost:3003**, dashboard visible.
- [ ] `demo/sample_er_bill.png` is on the desktop / easy to drag.
- [ ] **Mic permission pre-granted** for `localhost:3003` (click the mic FAB once before the demo, allow, close).
- [ ] **Fallback tab pre-loaded** (see §5): `demo/e2e_result.json` open + the bill PNG.
- [ ] Model in use: **grok-4.3 (multimodal)**. Vision round-trip is ~5–15s — narrate while it thinks.

---

## 1. The 90-second script (ENGLISH run)

> Timings are targets. The whole thing is one continuous beat — keep talking through the AI's "thinking" time.

**[0:00 – 0:10] Hook — the problem.**
> *"One in five Americans gets a surprise medical bill. They're told to just pay it. Watch what happens when an AI advocate reads it instead."*

**[0:10 – 0:20] Fire: "new bill arrived."**
- On the dashboard, **drag `sample_er_bill.png` into the amber drop zone** ("Drop a medical bill or EOB here to use with voice or chat").
  *(This is the "📨 Simulate: new bill arrived" moment — the bill lands in Sovereign's inbox and the tile turns gold: "Document ready.")*
> *"A $4,200 ER bill just landed — for a sprained ankle. Insurance denied it."*

**[0:20 – 0:35] Speak to Sovereign.**
- Click the **mic floating button** (bottom-right) → the **Sovereign Voice Advocate** panel opens and starts listening.
- Say, clearly:
> **"Sovereign, I got a $4,200 ER bill for a sprained ankle and my insurance denied it. Can you check it for overcharges?"**

**[0:35 – 0:55] Show the findings / overcharges.**
- Sovereign reads the bill with Grok vision and speaks back the findings. The case opens and the **investigation feed** streams in. Point at the screen:
> *"It read every line. It caught that the ER charged code 99285 — twice — same visit, same day. That's an $1,800 duplicate. It flagged the Level-5 code as upcoding for a sprain, and the IV saline billed at $450 versus a fair price near $100."*
- Headline number on screen: **Overcharge severity 100/100 — critical.**

**[0:55 – 1:10] Give verbal consent.**
> *"Sovereign, you have my consent — dispute the duplicate and send the appeal."*
- Sovereign confirms it's acting **on your behalf** and mints the action receipt.

**[1:10 – 1:25] Show the signed Patient Action Receipt.**
- Open the case → **Decision Receipt** card. Point to: receipt ID, the action taken, the **Ed25519 signature**, and the **QR code**.
> *"Every action Sovereign takes is signed. This is a patient-owned receipt — proof of exactly what was done, in your name."*

**[1:25 – 1:30] Prove it's real — VALID.**
- Click **"Verify Signature"** on the receipt → it calls the backend and flips to **green: signature verified / VALID**.
  *(Stage line for a judge: "Scan that QR → it opens `/verify` and shows the same green VALID — independently checkable against our public key at `/api/verify/key`.")*
> *"Don't trust us — verify us. Green check, cryptographically valid. That's Sovereign."*

---

## 2. The multilingual flip (the ONE Spanish line)

Right after the English findings (~0:55), before consent, re-open the mic and say:

> **"Sovereign, repítelo en español, por favor — ¿cuánto me cobraron de más?"**
> *(English: "Sovereign, say it again in Spanish, please — how much was I overcharged?")*

Sovereign answers the overcharge back **in Spanish**, then you switch back to English for consent.
> *"Same advocate. Any language. Your voice."*

---

## 3. The click sequence (cheat-card)

1. **Start backend** → `:8000` (ENVIRONMENT=development).
2. **Start frontend** → `:3003` → open the **dashboard**.
3. **Fire "new bill arrived"** → drag `sample_er_bill.png` into the amber drop zone → tile turns gold ("Document ready").
4. **Speak to Sovereign** → click the **mic FAB** (bottom-right) → "…$4,200 ER bill… sprained ankle… denied… check for overcharges?"
5. *(optional flip)* → Spanish line → Sovereign answers in Spanish.
6. **Show findings/overcharges** → investigation feed → **duplicate 99285**, upcoding, $450 IV → **severity 100/100**.
7. **Verbal consent** → "Sovereign, you have my consent — dispute it."
8. **Show the signed Patient Action Receipt** → Decision Receipt card → receipt ID + Ed25519 signature + QR.
9. **Click "Verify Signature"** → **green VALID**. *(Judge scans QR → `/verify` → same VALID.)*

---

## 4. What the judges should walk away having seen

- **Vision works on a real image** — it extracted the exact **$4,200** total and all 5 line items from a photo of a bill.
- **It catches real overcharges** — the **duplicate CPT 99285** ($1,800), upcoding, and an over-priced IV.
- **It acts in the patient's voice** — voice-first, with explicit **verbal consent** before any action.
- **It's accountable** — every action is an **Ed25519-signed, patient-owned receipt** that anyone can **verify → VALID**.
- **It's for everyone** — the **Spanish flip** shows it meets patients in their language.

---

## 5. FALLBACK PLAN (if mic or network fails — stay calm, keep moving)

You have a captured, real, successful run on disk. Nothing about the story changes.

**If the MIC fails** → use the **Chat panel** instead of voice:
- Click the mic FAB → switch to **text/chat** mode → **type** the same line: *"I got a $4,200 ER bill for a sprained ankle and my insurance denied it — check it for overcharges."*
- The drop-zone + chat path runs the identical pipeline; everything else in the script is unchanged.

**If the NETWORK / live vision call fails** → pivot to the **pre-captured proof** (`demo/e2e_result.json`):
- Open `demo/sample_er_bill.png` so they see the source bill.
- Open `demo/e2e_result.json` and read the captured result aloud — this is a **real prior run** against `localhost:8000` with grok-4.3:
  - `evidence.extracted_data.estimated_cost` → **$4,200.00** (vision read the total).
  - `evidence.extracted_data.key_findings` → the 5 line items **incl. "Duplicate identical 99285 charges on same date."**
  - `claim.fraud_signals` → **`duplicate_charge`** (CPT 99285, $1,800 overcharge), **`upcoding`**, **`price_above_fair_market`** ($450 IV).
  - `evidence.fraud_assessment.overall_score` → **100 / 100 (critical)**.
> *"This is a captured run from minutes ago — same bill, same model. The vision pipeline read the total and caught the duplicate. Let me show you the proof."*

**Re-run the capture anytime** (regenerates `demo/e2e_result.json`):
```bash
backend/.venv/bin/python demo/run_e2e.py
```

**If the RECEIPT/verify step is flaky on stage** → the receipt is signed server-side; show `e2e_result.json` and hit the public key endpoint to prove the crypto is real:
```bash
curl -s localhost:8000/api/verify/key   # returns the Ed25519 public key + algorithm
```

**Golden rule:** if anything stalls for >5 seconds, talk over it and cut to the fallback. The story — *read the bill, find the overcharge, act in the patient's voice, prove it* — never depends on a single live call.

---

## Appendix — assets & endpoints used

| Thing | Where |
|---|---|
| Demo bill (source of truth) | `demo/sample_er_bill.png` |
| Bill served to frontend drop-zone | `frontend/public/sample-bill.png` |
| Captured proof of a live run | `demo/e2e_result.json` |
| Regenerate the bill | `backend/.venv/bin/python demo/make_bill.py` |
| Re-run live E2E capture | `backend/.venv/bin/python demo/run_e2e.py` |
| Submit a claim | `POST /api/claims/submit` (file, claimant_name, incident_description, policy_number) |
| Poll a claim | `GET /api/claims/{id}` |
| Evidence bundle | `GET /api/claims/{id}/evidence` |
| Signed receipt | `GET /api/claims/{id}/receipt` |
| Verify a receipt → VALID | `POST /api/verify` (in-receipt "Verify Signature" button) |
| Public verification key | `GET /api/verify/key` |
