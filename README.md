# Sovereign — Your AI Patient Advocate

Sovereign puts patients in control of their medical bills. Talk to your advocate out loud, upload a bill or Explanation of Benefits (EOB), and Sovereign reads every line with Grok Vision — catching overcharges, illegal balance-billing, and incorrectly coded procedures that insurers quietly hope you miss. When a denial is appealable, Sovereign drafts the appeal letter on your behalf. Every action it takes — every dispute filed, every appeal submitted — is recorded in a consent-gated, Ed25519-signed Patient Action Receipt that you own and can verify independently. Sovereign does not work for your insurer. It works for you.

---

## Architecture

```
Patient
  │
  ├── Voice (Grok Voice Realtime API)
  │     Speak naturally; Sovereign transcribes, understands intent,
  │     routes to the right tool.
  │
  ├── Vision (Grok Vision)
  │     Reads medical bills, EOBs, denial letters.
  │     Extracts line items, CPT codes, billed vs. allowed amounts.
  │
  └── Sovereign Trust Layer
        Consent gate  — patient must approve every action.
        Simulation    — "what happens if I file this appeal?"
        Ed25519 sign  — every Patient Action Receipt is signed with
                        a verifiable key the patient can audit.
        Receipt store — immutable log the patient owns and can export.
```

**Stack:** xAI Grok Voice (realtime WebSocket) · xAI Grok Vision · FastAPI backend · Next.js 15 App Router frontend · Vercel deployment.

---

## Quick Start

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Runs on **http://localhost:8000** — Swagger UI at **/docs**.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on **http://localhost:3003**.

Set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `frontend/.env.local` (already the default fallback).

---

## Sponsor Stack

| Sponsor | How we use it |
|---|---|
| **xAI** | Grok Voice Realtime API — voice-first patient interaction; Grok Vision — medical bill parsing and overcharge detection |
| **Vercel + Next.js** | App Router, SSR, global edge deployment |

---

## What Makes This Different

Most "healthcare AI" tools are sold to insurers and hospital billing departments. Sovereign is the first AI advocate built exclusively for the patient:

- **Reads your bill like a forensic auditor** — Grok Vision extracts every CPT code, charge, and modifier and checks it against expected rates.
- **Knows the law** — flags No Surprises Act violations, balance-billing above allowed amounts, and denials that federal regulations require to be appealed.
- **Signs its work** — every action produces a tamper-evident Ed25519-signed receipt you can independently verify. Sovereign's conscience is provable.
- **Hands-free** — Grok Voice means a patient recovering from surgery can talk to their advocate without touching a keyboard.
