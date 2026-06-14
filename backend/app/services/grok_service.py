"""Grok (xAI) API service for patient medical-billing advocacy.

Wraps the xAI calls behind the pipeline: medical-document analysis (itemized bill /
EOB / denial), overcharge & billing-error detection, the patient's recoverable-amount
estimate, appeal/dispute outcome simulation, and appeal/No-Surprises-Act complaint drafting.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any

import asyncio
import hashlib
from functools import lru_cache

import httpx

from app.config import XAI_API_KEY, XAI_BASE_URL, XAI_MODEL
from app.models.claim import (
    CoverageResult,
    ExtractedData,
    FraudScore,
    PayoutRecommendation,
    SimulationResult,
)

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_POOL_TIMEOUT = httpx.Timeout(60.0, connect=10.0, pool=5.0)
_MAX_RETRIES = 1

# ── Shared HTTP client (created/closed via init/shutdown in main.py) ─────────
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    """Return the shared HTTP client. Raises if not initialized."""
    if _client is None:
        raise RuntimeError("Grok HTTP client not initialized. Call init_grok_client() first.")
    return _client


async def init_grok_client() -> None:
    """Create the shared HTTP client with connection pooling."""
    global _client
    _client = httpx.AsyncClient(timeout=_POOL_TIMEOUT, limits=_LIMITS)
    # Warm the connection pool with a lightweight request
    try:
        await _client.get(f"{XAI_BASE_URL}/models", headers=_headers())
        logger.info("Grok HTTP client initialized and connection warmed")
    except Exception:
        logger.info("Grok HTTP client initialized (warm-up request failed — non-blocking)")


async def close_grok_client() -> None:
    """Close the shared HTTP client."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        logger.info("Grok HTTP client closed")


# ── LRU response cache (keyed on content hash) ──────────────────────────────
_response_cache: dict[str, dict[str, Any]] = {}
_CACHE_MAX_SIZE = 100


def _content_hash(data: bytes) -> str:
    """SHA-256 hash of content for cache keying."""
    return hashlib.sha256(data).hexdigest()


def _cache_get(key: str) -> dict[str, Any] | None:
    """Get a cached response by content hash."""
    return _response_cache.get(key)


def _cache_put(key: str, value: dict[str, Any]) -> None:
    """Store a response in cache, evicting oldest if at capacity."""
    if len(_response_cache) >= _CACHE_MAX_SIZE:
        # Evict the first (oldest) entry
        oldest_key = next(iter(_response_cache))
        del _response_cache[oldest_key]
    _response_cache[key] = value

# Map file extensions to MIME subtypes for image_url
_IMAGE_EXTENSIONS: dict[str, str] = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".gif": "gif",
    ".webp": "webp",
    ".bmp": "bmp",
    ".tiff": "tiff",
    ".tif": "tiff",
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json",
    }


async def _call_grok(
    messages: list[dict[str, Any]],
    *,
    json_mode: bool = True,
    temperature: float = 0.2,
) -> str:
    """Low-level helper: call xAI chat completions with retry."""
    body: dict[str, Any] = {
        "model": XAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last_error: Exception | None = None
    client = get_client()
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.post(
                f"{XAI_BASE_URL}/chat/completions",
                headers=_headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content
        except httpx.PoolTimeout as exc:
            last_error = exc
            logger.error("Grok API pool exhausted (all connections busy): %s", exc)
            break
        except (httpx.HTTPStatusError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_error = exc
            logger.warning("Grok API attempt %d failed: %s", attempt + 1, exc)
        except Exception as exc:
            last_error = exc
            logger.error("Unexpected Grok API error: %s", exc)
            break

    raise RuntimeError(f"Grok API call failed after retries: {last_error}")


def _safe_json_parse(raw: str) -> dict[str, Any]:
    """Parse JSON from Grok response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        # Remove ```json ... ``` wrapper
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Grok JSON: %s", text[:500])
        return {}


def _pdf_first_page_png(pdf_bytes: bytes) -> bytes:
    """Render page 1 of a PDF to PNG bytes — vision models can't read PDFs directly."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc.load_page(0).get_pixmap(dpi=200)
        return pix.tobytes("png")
    finally:
        doc.close()


class GrokService:
    """Async service wrapping all Grok / xAI interactions."""

    # ── Document Analysis (Vision) ────────────────────────────────────────

    async def analyze_document(self, file_path: str, file_type: str) -> ExtractedData:
        """Use Grok vision to extract structured data from an uploaded document/image."""
        path = Path(file_path)
        if not path.exists():
            logger.error("File not found: %s", file_path)
            return ExtractedData()

        ext = path.suffix.lower()
        mime_sub = _IMAGE_EXTENSIONS.get(ext, "jpeg")

        # Read file off the event loop to avoid blocking at high concurrency
        raw_bytes = await asyncio.to_thread(path.read_bytes)

        # PDFs can't be sent to the vision model as image_url — render page 1 to PNG.
        if ext == ".pdf":
            raw_bytes = await asyncio.to_thread(_pdf_first_page_png, raw_bytes)
            mime_sub = "png"

        # Check LRU cache for identical content
        cache_key = _content_hash(raw_bytes)
        cached = _cache_get(cache_key)
        if cached is not None:
            logger.info("Cache hit for document analysis (hash=%s…)", cache_key[:12])
            return ExtractedData(**cached)

        b64_data = base64.b64encode(raw_bytes).decode("utf-8")

        system_prompt = (
            "You are an expert medical-billing document analyzer working FOR THE PATIENT. "
            "Examine the provided image/document — it is a MEDICAL BILL, itemized hospital "
            "statement, insurance Explanation of Benefits (EOB), or a claim DENIAL LETTER. "
            "Extract the provider/facility name, the date(s) of service, every line item "
            "(CPT/HCPCS code, plain-text description, billed/charged amount, and the allowed "
            "or plan-paid amount if shown), the total billed, and the patient responsibility "
            "(amount the patient is being asked to pay). Determine which kind of document this is.\n"
            "Return your analysis as a JSON object with exactly these fields:\n"
            "- doc_category (string): EXACTLY one of 'itemized_bill', 'EOB', 'denial_letter'\n"
            "- total_billed (number): the total billed/charged dollar amount on the document "
            "(if only patient responsibility is shown, use that)\n"
            "- patient_responsibility (number): dollar amount the patient is being asked to pay, else 0\n"
            "- summary (string): a clear plain-English summary of what this document is and what it says\n"
            "- line_items (array of strings): each notable line item as 'CODE — description — $billed "
            "(allowed $allowed)'; include the most expensive or most questionable charges\n"
            "- red_flags (array of strings): any sign the document looks synthetic, altered, "
            "inconsistent, or tampered with (e.g., mismatched fonts, impossible totals, fake codes); "
            "empty array if it looks genuine\n"
            "Return ONLY the JSON object, no other text."
        )

        user_content: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/{mime_sub};base64,{b64_data}"},
            },
            {
                "type": "text",
                "text": (
                    "Analyze this medical bill / EOB / denial letter on behalf of the patient. "
                    "Extract the provider, dates of service, every billed line item with its "
                    "CPT/HCPCS code and amounts, the total billed, and the patient responsibility. "
                    "Classify the document and flag anything that looks synthetic or altered."
                ),
            },
        ]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            raw = await _call_grok(messages, json_mode=True)
            parsed = _safe_json_parse(raw)
            # Map medical-billing fields onto the shared ExtractedData shape:
            #   damage_type      -> document category (itemized_bill / EOB / denial_letter)
            #   estimated_cost   -> total billed amount
            #   document_type    -> same document category
            #   incident_details -> plain-English summary of the document
            #   key_findings     -> notable line items / codes / charges + any synthetic-doc flags
            doc_category = parsed.get("doc_category", "unknown")
            line_items = parsed.get("line_items", []) or []
            red_flags = parsed.get("red_flags", []) or []
            patient_resp = float(parsed.get("patient_responsibility", 0) or 0)
            key_findings = list(line_items)
            if patient_resp:
                key_findings.append(f"Patient responsibility: ${patient_resp:,.2f}")
            for flag in red_flags:
                key_findings.append(f"POSSIBLE ALTERED/SYNTHETIC DOCUMENT: {flag}")
            result = ExtractedData(
                damage_type=doc_category,
                estimated_cost=float(parsed.get("total_billed", 0) or 0),
                vehicle_info="",
                incident_details=parsed.get("summary", ""),
                document_type=doc_category,
                key_findings=key_findings,
            )
            # Cache the result (keyed on content hash, not file path)
            _cache_put(cache_key, result.model_dump())
            return result
        except Exception as exc:
            logger.error("Document analysis failed: %s", exc)
            return ExtractedData(
                damage_type="analysis_failed",
                incident_details=f"Error during analysis: {exc}",
            )

    # ── Fraud Assessment ──────────────────────────────────────────────────

    async def assess_fraud(
        self, extracted_data: ExtractedData, incident_description: str
    ) -> FraudScore:
        """Detect billing errors and overcharges in the patient's bill/EOB."""
        system_prompt = (
            "You are an expert medical-billing advocate working FOR THE PATIENT. "
            "Analyze the patient's medical bill / EOB / denial letter for BILLING ERRORS and "
            "OVERCHARGES that hurt the patient. You are NOT investigating the patient — you are "
            "finding where the PATIENT was overcharged or wrongly billed.\n"
            "Return a JSON object with these fields:\n"
            "- overall_score (number 0-100): OVERCHARGE/ERROR SEVERITY where 0=bill looks clean and "
            "fair, 100=the patient is being severely overcharged or wrongly billed\n"
            "- risk_level (string): one of 'low', 'medium', 'high', 'critical' — the severity of the "
            "overcharge to the patient\n"
            "- signals (array of objects): each detected billing problem, with signal_name (string), "
            "description (string), severity ('low'/'medium'/'high'), confidence (number 0-1). "
            "signal_name MUST be EXACTLY one of: 'duplicate_charge', 'upcoding', 'unbundling', "
            "'balance_billing', 'no_surprises_act_violation', 'not_rendered', "
            "'out_of_network_surprise', 'coding_error', 'price_above_fair_market'. "
            "Each description MUST cite the specific line item / CPT-HCPCS code, the estimated "
            "OVERCHARGE in dollars to the patient, and a fair-price benchmark (e.g., typical "
            "Medicare/commercial allowed amount for that code).\n"
            "- explanation (string): a PATIENT-FACING narrative (address the patient as 'you'), "
            "e.g. 'You appear to have been overcharged by ~$X because ...'.\n\n"
            "Check for: duplicate charges (same code billed twice), upcoding (a higher-intensity "
            "code than the care delivered), unbundling (services that should be billed as one "
            "bundle billed separately), balance billing and surprise out-of-network charges, "
            "No Surprises Act violations, charges for services not rendered, coding errors, and "
            "prices far above the fair-market/allowed amount for the code."
        )

        user_msg = (
            f"Patient's note / situation: {incident_description}\n\n"
            f"Extracted document data (from the patient's bill/EOB/denial):\n"
            f"- Document category: {extracted_data.damage_type}\n"
            f"- Total billed: ${extracted_data.estimated_cost:,.2f}\n"
            f"- Document type: {extracted_data.document_type}\n"
            f"- Summary: {extracted_data.incident_details}\n"
            f"- Line items / notable charges: {', '.join(extracted_data.key_findings)}\n\n"
            "Find every billing error and overcharge that disadvantages the patient. "
            "Be thorough and cite specific codes, dollar overcharges, and fair-price benchmarks."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        try:
            raw = await _call_grok(messages, json_mode=True)
            parsed = _safe_json_parse(raw)
            signals = []
            for s in parsed.get("signals", []):
                signals.append({
                    "signal_name": s.get("signal_name", "unknown"),
                    "description": s.get("description", ""),
                    # Grok may return "critical" for a signal; the Severity enum is
                    # low/medium/high — coerce to keep validation from dropping signals.
                    "severity": {"critical": "high", "low": "low", "medium": "medium", "high": "high"}.get(
                        str(s.get("severity", "low")).lower(), "low"
                    ),
                    "confidence": float(s.get("confidence", 0.5)),
                })
            return FraudScore(
                overall_score=float(parsed.get("overall_score", 25)),
                risk_level=parsed.get("risk_level", "low"),
                signals=signals,
                explanation=parsed.get("explanation", ""),
            )
        except Exception as exc:
            logger.error("Fraud assessment failed: %s", exc)
            return FraudScore(
                overall_score=50.0,
                risk_level="medium",
                explanation=f"Fraud assessment encountered an error: {exc}. Defaulting to medium risk.",
            )

    # ── Payout Recommendation ─────────────────────────────────────────────

    async def recommend_payout(
        self,
        extracted_data: ExtractedData,
        coverage: CoverageResult,
        fraud_score: FraudScore,
    ) -> PayoutRecommendation:
        """Estimate how much money the patient can RECOVER (overcharges + wrongly-denied amounts)."""
        system_prompt = (
            "You are a patient-advocate AI that estimates how much money a patient can RECOVER "
            "or SAVE by disputing their medical bill and appealing wrongful denials. "
            "Based on the detected billing errors/overcharges, the patient's coverage, and the "
            "overcharge-severity assessment, estimate the recoverable amount. "
            "Return a JSON object with:\n"
            "- recommended_amount (number): the dollar amount the PATIENT can realistically recover "
            "or have removed from their bill (sum of identified overcharges plus any amount that was "
            "wrongly denied but should be covered)\n"
            "- confidence (number 0-1): confidence in this recovery estimate\n"
            "- rationale (string): patient-facing reasoning for the amount — which overcharges and "
            "denied amounts make it up and why they are recoverable\n"
            "- comparable_claims (array of strings): comparable PATIENT cases / typical outcomes for "
            "similar disputes (e.g., 'patients who disputed duplicate ER facility fees commonly had "
            "$X removed')\n"
            "Consider: the size of each overcharge vs. fair-market/allowed price, whether the service "
            "was covered, the deductible the patient still genuinely owes, and how strong the "
            "documentation is."
        )

        user_msg = (
            f"Patient bill evidence:\n"
            f"- Document category: {extracted_data.damage_type}\n"
            f"- Total billed: ${extracted_data.estimated_cost:,.2f}\n"
            f"- Summary: {extracted_data.incident_details}\n"
            f"- Line items / notable charges: {', '.join(extracted_data.key_findings)}\n\n"
            f"Patient coverage:\n"
            f"- Policy: {coverage.policy_number}\n"
            f"- Type: {coverage.coverage_type}\n"
            f"- Limit: ${coverage.coverage_limit:,.2f}\n"
            f"- Deductible: ${coverage.deductible:,.2f}\n"
            f"- Covered: {coverage.covered}\n\n"
            f"Overcharge / billing-error assessment:\n"
            f"- Overcharge severity score: {fraud_score.overall_score}/100\n"
            f"- Severity level: {fraud_score.risk_level}\n"
            f"- Explanation: {fraud_score.explanation}\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        try:
            raw = await _call_grok(messages, json_mode=True)
            parsed = _safe_json_parse(raw)
            return PayoutRecommendation(
                recommended_amount=float(parsed.get("recommended_amount", 0)),
                confidence=float(parsed.get("confidence", 0.5)),
                rationale=parsed.get("rationale", ""),
                comparable_claims=parsed.get("comparable_claims", []),
            )
        except Exception as exc:
            logger.error("Payout recommendation failed: %s", exc)
            return PayoutRecommendation(
                recommended_amount=0.0,
                confidence=0.0,
                rationale=f"Recommendation engine error: {exc}",
            )

    # ── Outcome Simulation ────────────────────────────────────────────────

    async def simulate_outcome(
        self,
        claim_data: dict[str, Any],
        fraud_score: FraudScore,
        payout_rec: PayoutRecommendation,
    ) -> SimulationResult:
        """Simulate the likely outcome of the patient's appeal / billing dispute."""
        system_prompt = (
            "You are an appeal-outcome simulation engine for a PATIENT advocate. "
            "Given the bill details, the detected overcharges/errors, and the estimated recoverable "
            "amount, simulate how the patient's appeal or billing dispute is likely to resolve. "
            "Return a JSON object with:\n"
            "- approval_probability (number 0-1): probability the PATIENT'S APPEAL/DISPUTE SUCCEEDS "
            "(overcharges removed or denial overturned)\n"
            "- dispute_risk (number 0-1): risk that the insurer or provider PUSHES BACK / resists the "
            "correction\n"
            "- fraud_escalation_likelihood (number 0-1): likelihood the patient will need EXTERNAL "
            "ESCALATION (state insurance regulator complaint or a federal No Surprises Act complaint) "
            "to win\n"
            "- financial_exposure (number): dollars at stake FOR THE PATIENT (what they stand to "
            "wrongly pay if they do nothing)\n"
            "- historical_comparison (string): how similar patient disputes have typically resolved\n"
            "- recommended_action (string): EXACTLY one of 'file_appeal', 'negotiate_bill', "
            "'request_itemization', 'file_nsa_complaint', 'pay_corrected_amount'\n"
        )

        user_msg = (
            f"Patient dispute summary:\n"
            f"- Patient: {claim_data.get('claimant_name', 'unknown')}\n"
            f"- Situation: {claim_data.get('incident_description', 'unknown')}\n"
            f"- Status: {claim_data.get('status', 'unknown')}\n\n"
            f"Overcharge severity: {fraud_score.overall_score}/100 ({fraud_score.risk_level})\n"
            f"Overcharge explanation: {fraud_score.explanation}\n\n"
            f"Estimated recoverable amount: ${payout_rec.recommended_amount:,.2f} "
            f"(confidence: {payout_rec.confidence})\n"
            f"Rationale: {payout_rec.rationale}\n"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        try:
            raw = await _call_grok(messages, json_mode=True)
            parsed = _safe_json_parse(raw)
            return SimulationResult(
                approval_probability=float(parsed.get("approval_probability", 0.5)),
                dispute_risk=float(parsed.get("dispute_risk", 0.3)),
                fraud_escalation_likelihood=float(parsed.get("fraud_escalation_likelihood", 0.1)),
                financial_exposure=float(parsed.get("financial_exposure", 0)),
                historical_comparison=parsed.get("historical_comparison", ""),
                recommended_action=parsed.get("recommended_action", "request_itemization"),
            )
        except Exception as exc:
            logger.error("Simulation failed: %s", exc)
            return SimulationResult(
                approval_probability=0.5,
                dispute_risk=0.5,
                fraud_escalation_likelihood=0.5,
                financial_exposure=payout_rec.recommended_amount,
                historical_comparison="Simulation unavailable due to error.",
                recommended_action="request_itemization",
            )

    # ── Appeal / Dispute Letter Drafting ──────────────────────────────────

    async def draft_appeal(
        self,
        extracted_data: ExtractedData,
        fraud_score: FraudScore,
        simulation: SimulationResult,
    ) -> dict[str, Any]:
        """Draft a patient-ready appeal/dispute letter, phone script, and supporting points.

        Returns a plain dict (no Pydantic model) with keys: recipient, subject, body,
        negotiation_script, supporting_points.
        """
        # Summarize the detected billing problems for the prompt
        signal_lines = []
        for s in fraud_score.signals:
            name = getattr(s, "signal_name", "") or ""
            desc = getattr(s, "description", "") or ""
            signal_lines.append(f"- {name}: {desc}")
        signals_text = "\n".join(signal_lines) if signal_lines else "- (no specific signals detected)"

        system_prompt = (
            "You are a patient-advocate AI that drafts professional, ready-to-send appeal and "
            "billing-dispute letters on behalf of a PATIENT. Write firmly but politely, in plain "
            "language the patient can send as-is. Ground every claim in the specific overcharges, "
            "codes, and denial details provided. Where relevant, assert the patient's rights: the "
            "federal No Surprises Act (protection from surprise out-of-network and balance billing), "
            "the right to a fully itemized bill, and the right to both an INTERNAL appeal and an "
            "EXTERNAL/independent review. Do NOT invent specific statutes, dollar amounts, dates, or "
            "account numbers that were not provided; use clearly marked placeholders like "
            "'[Account Number]' or '[Date of Service]' when a detail is unknown.\n"
            "Return a JSON object with EXACTLY these fields:\n"
            "- recipient (string): who the letter should be addressed to (e.g., the insurer's appeals "
            "department or the provider's billing/patient-accounts department)\n"
            "- subject (string): a concise subject/RE line for the letter\n"
            "- body (string): the COMPLETE professional appeal/dispute letter the patient can send, "
            "citing the specific overcharges or wrongful denial and the patient's rights (No Surprises "
            "Act, right to an itemized bill, internal and external appeal). Include a greeting, the "
            "itemized objections, the requested remedy, and a sign-off with '[Patient Name]' placeholder.\n"
            "- negotiation_script (string): a short, friendly phone script the patient can read when "
            "calling the billing or appeals line\n"
            "- supporting_points (array of strings): the key bullet points / evidence the patient "
            "should reference\n"
            "Return ONLY the JSON object, no other text."
        )

        user_msg = (
            f"Document category: {extracted_data.damage_type}\n"
            f"Total billed: ${extracted_data.estimated_cost:,.2f}\n"
            f"Document summary: {extracted_data.incident_details}\n"
            f"Notable line items / charges: {', '.join(extracted_data.key_findings)}\n\n"
            f"Overcharge severity: {fraud_score.overall_score}/100 ({fraud_score.risk_level})\n"
            f"Patient-facing overcharge explanation: {fraud_score.explanation}\n"
            f"Detected billing problems (signals):\n{signals_text}\n\n"
            f"Appeal-outcome simulation:\n"
            f"- Probability the appeal/dispute succeeds: {simulation.approval_probability:.0%}\n"
            f"- Risk of insurer/provider push-back: {simulation.dispute_risk:.0%}\n"
            f"- Likelihood external escalation (regulator / NSA complaint) needed: "
            f"{simulation.fraud_escalation_likelihood:.0%}\n"
            f"- Dollars at stake for the patient: ${simulation.financial_exposure:,.2f}\n"
            f"- Recommended action: {simulation.recommended_action}\n"
            f"- How similar disputes resolved: {simulation.historical_comparison}\n\n"
            "Draft the appeal/dispute letter, the phone script, and the supporting points so the "
            "patient can act today."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        try:
            raw = await _call_grok(messages, json_mode=True)
            parsed = _safe_json_parse(raw)
            supporting = parsed.get("supporting_points", []) or []
            if not isinstance(supporting, list):
                supporting = [str(supporting)]
            return {
                "recipient": parsed.get("recipient", "Billing / Appeals Department"),
                "subject": parsed.get("subject", "Appeal of Medical Bill / Insurance Denial"),
                "body": parsed.get("body", ""),
                "negotiation_script": parsed.get("negotiation_script", ""),
                "supporting_points": [str(p) for p in supporting],
            }
        except Exception as exc:
            logger.error("Appeal drafting failed: %s", exc)
            return {
                "recipient": "Billing / Appeals Department",
                "subject": "Appeal of Medical Bill / Insurance Denial",
                "body": (
                    "To Whom It May Concern,\n\n"
                    "I am writing to formally dispute charges on my recent medical bill / to appeal "
                    "the denial of my claim. I request a fully itemized statement and a review of the "
                    "charges, and I am exercising my right to both an internal appeal and an external "
                    "independent review. Where applicable, I assert my protections under the federal "
                    "No Surprises Act against surprise out-of-network and balance billing.\n\n"
                    "Please correct the billing errors and respond in writing.\n\n"
                    "Sincerely,\n[Patient Name]"
                ),
                "negotiation_script": (
                    "Hi, I'm calling about my bill. I believe I was overcharged and I'd like a fully "
                    "itemized statement. Can you review the charges with me and tell me how to file a "
                    "formal appeal?"
                ),
                "supporting_points": [
                    "Request a fully itemized bill (CPT/HCPCS level).",
                    "Identify and dispute duplicate or incorrect charges.",
                    "Assert No Surprises Act protections if out-of-network/balance billing applies.",
                    "Request both an internal appeal and an external independent review.",
                    f"Appeal drafting encountered an error: {exc}",
                ],
            }

    # ── No Surprises Act Regulator Complaint Drafting ─────────────────────

    async def draft_complaint(
        self,
        extracted_data: ExtractedData,
        fraud_score: FraudScore,
    ) -> dict[str, Any]:
        """Draft a formal federal No Surprises Act complaint to the regulator (CMS).

        Models the style of draft_appeal, but targets the federal NSA complaint /
        IDR (Independent Dispute Resolution) process rather than the insurer/provider.

        Returns a plain dict (no Pydantic model) with keys: agency, contact,
        subject, body, key_facts.
        """
        _DEFAULT_AGENCY = "CMS / No Surprises Act Help Desk"
        _DEFAULT_CONTACT = "1-800-985-3059 · cms.gov/nosurprises"

        # Summarize the detected NSA / balance-billing problems for the prompt.
        # Mirror draft_appeal: tolerate FraudSignal objects OR raw dicts.
        signal_lines: list[str] = []
        for s in fraud_score.signals:
            if isinstance(s, dict):
                name = s.get("signal_name", "") or ""
                desc = s.get("description", "") or ""
            else:
                name = getattr(s, "signal_name", "") or ""
                desc = getattr(s, "description", "") or ""
            signal_lines.append(f"- {name}: {desc}")
        signals_text = (
            "\n".join(signal_lines) if signal_lines else "- (no specific signals detected)"
        )

        system_prompt = (
            "You are a patient-advocate AI that drafts FORMAL COMPLAINTS to the FEDERAL "
            "REGULATOR (the Centers for Medicare & Medicaid Services, CMS) under the federal "
            "No Surprises Act (NSA). The patient has been illegally balance-billed or hit with "
            "a surprise out-of-network charge, and wants to file a federal complaint and invoke "
            "the Independent Dispute Resolution (IDR) process.\n"
            "Write a formal, regulator-grade complaint in plain language the patient can submit "
            "as-is. Ground EVERY allegation in the SPECIFIC violations provided (balance billing, "
            "surprise out-of-network charges, No Surprises Act violations). Name the "
            "provider/facility and the specific dollar amounts and codes from the bill. Explicitly "
            "REQUEST that CMS open a federal No Surprises Act complaint and initiate the IDR "
            "(Independent Dispute Resolution) process. Do NOT invent statutes, dates, or account "
            "numbers that were not provided; use clearly marked placeholders like '[Date of "
            "Service]', '[Account Number]', or '[Patient Name]' when a detail is unknown.\n"
            "Return a JSON object with EXACTLY these fields:\n"
            "- agency (string): the federal agency the complaint is directed to (default "
            f"'{_DEFAULT_AGENCY}')\n"
            "- contact (string): how to reach that agency (default "
            f"'{_DEFAULT_CONTACT}')\n"
            "- subject (string): a concise RE/subject line for the complaint (e.g., 'No Surprises "
            "Act Complaint — Illegal Balance Billing by [Provider]')\n"
            "- body (string): the COMPLETE formal complaint addressed to CMS, citing the specific "
            "illegal balance-billing / surprise out-of-network / NSA violations found, naming the "
            "provider and the specific amounts/codes, and explicitly requesting the federal "
            "complaint be opened and the IDR process initiated. Include a greeting to the agency, "
            "an itemized statement of the violations, the requested remedy, and a sign-off with a "
            "'[Patient Name]' placeholder.\n"
            "- key_facts (array of strings): the key facts / evidence the regulator should note "
            "(provider name, amounts, the specific NSA violations, the protections that apply)\n"
            "Return ONLY the JSON object, no other text."
        )

        user_msg = (
            f"Document category: {extracted_data.damage_type}\n"
            f"Provider / facility & document summary: {extracted_data.incident_details}\n"
            f"Total billed: ${extracted_data.estimated_cost:,.2f}\n"
            f"Notable line items / charges (codes & amounts): "
            f"{', '.join(extracted_data.key_findings)}\n\n"
            f"Overcharge / NSA severity: {fraud_score.overall_score}/100 "
            f"({fraud_score.risk_level})\n"
            f"Patient-facing explanation: {fraud_score.explanation}\n"
            f"Detected illegal balance-billing / surprise out-of-network / NSA violations "
            f"(signals):\n{signals_text}\n\n"
            "Draft the formal federal No Surprises Act complaint to CMS. Cite the specific "
            "violations above, name the provider and the specific amounts, and request that CMS "
            "open the federal complaint and initiate the Independent Dispute Resolution (IDR) "
            "process so the patient can act today."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ]

        try:
            raw = await _call_grok(messages, json_mode=True)
            parsed = _safe_json_parse(raw)
            key_facts = parsed.get("key_facts", []) or []
            if not isinstance(key_facts, list):
                key_facts = [str(key_facts)]
            return {
                "agency": parsed.get("agency", _DEFAULT_AGENCY) or _DEFAULT_AGENCY,
                "contact": parsed.get("contact", _DEFAULT_CONTACT) or _DEFAULT_CONTACT,
                "subject": parsed.get(
                    "subject",
                    "No Surprises Act Complaint — Illegal Balance Billing / Surprise Out-of-Network Charge",
                ),
                "body": parsed.get("body", ""),
                "key_facts": [str(f) for f in key_facts],
            }
        except Exception as exc:
            logger.error("Complaint drafting failed: %s", exc)
            return {
                "agency": _DEFAULT_AGENCY,
                "contact": _DEFAULT_CONTACT,
                "subject": (
                    "No Surprises Act Complaint — Illegal Balance Billing / "
                    "Surprise Out-of-Network Charge"
                ),
                "body": (
                    "To the No Surprises Act Help Desk (Centers for Medicare & Medicaid Services),\n\n"
                    "I am filing a formal complaint under the federal No Surprises Act. I believe I "
                    "have been illegally balance-billed and/or charged a surprise out-of-network "
                    "amount in violation of my federal protections. The provider/facility on the "
                    "bill is '[Provider Name]', for services on [Date of Service], with charges "
                    "totaling the disputed amount shown on my statement (account [Account Number]).\n\n"
                    "I am protected under the No Surprises Act from surprise out-of-network and "
                    "balance billing for this care, and I did not knowingly waive those protections. "
                    "I respectfully request that CMS open a federal No Surprises Act complaint and "
                    "initiate the Independent Dispute Resolution (IDR) process to resolve the "
                    "improper charges.\n\n"
                    "Please confirm receipt and advise me of the complaint and IDR next steps.\n\n"
                    "Sincerely,\n[Patient Name]"
                ),
                "key_facts": [
                    "Patient was balance-billed / charged a surprise out-of-network amount.",
                    "The charge appears to violate the federal No Surprises Act.",
                    "Patient did not knowingly waive No Surprises Act protections.",
                    "Requesting a federal NSA complaint and the IDR (Independent Dispute Resolution) process.",
                    f"Complaint drafting encountered an error: {exc}",
                ],
            }


# Module-level singleton
grok_service = GrokService()
