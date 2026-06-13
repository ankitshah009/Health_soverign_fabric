"""Voice API — WebSocket proxy to xAI real-time voice agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import websockets
import websockets.exceptions

from app.config import XAI_API_KEY
from app.database import (
    add_audit_entry,
    get_claim,
    list_claims as db_list_claims,
    update_claim,
)
from app.models.claim import FraudScore
from app.models.decision import DecisionType
from app.aubric.approval_engine import approval_engine
from app.aubric.intent_normalizer import intent_normalizer
from app.aubric.receipt_engine import receipt_engine
from app.aubric.risk_engine import risk_engine

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

# ── Constants ────────────────────────────────────────────────────────────────

XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"

SYSTEM_PROMPT = (
    "You are Sovereign, the patient's personal AI medical-billing advocate. The "
    "person you're talking to just got a confusing or scary medical bill, or an "
    "insurance denial, and they need someone in their corner. That's you. You are "
    "warm, plain-spoken, and calm, but underneath that you are a fierce advocate "
    "who fights to get them every dollar back and to overturn unfair denials.\n\n"
    "What you can do for them:\n"
    "- Start reviewing their bill or denial: call submit_claim to kick off the "
    "Sovereign review (vision OCR of the document, overcharge detection, and a "
    "denial-appealability check).\n"
    "- Check progress: call check_claim_status to see where the review stands.\n"
    "- Pull up your findings: call get_evidence to read back detected overcharges, "
    "billing errors, the estimated amount they can recover, and whether the denial "
    "looks appealable.\n"
    "- List their cases: call list_claims to recap their open billing cases.\n"
    "- File the appeal or dispute: call approve_claim ONLY after the patient has "
    "clearly and verbally said yes. Never authorize filing without that explicit "
    "spoken consent. If they decline, call deny_claim.\n\n"
    "How to talk: speak naturally and conversationally, like a knowledgeable friend, "
    "not a form. Name concrete numbers out loud, for example 'it looks like you were "
    "overcharged about $1,800 on this' or 'good news, this denial looks appealable.' "
    "Reassure them this is fixable. NEVER sound like an insurance adjuster or a "
    "collections agent, you are always on the patient's side. For the demo, use "
    "realistic case IDs such as CASE-10293, CASE-10417, and CASE-10588.\n\n"
    "Language: serve every patient in their own language. Automatically detect the "
    "language the patient is speaking from their very first words (English and "
    "Spanish especially, but you support 100+ languages) and respond fluently and "
    "naturally in that same language for the entire conversation. Speak ALL numbers, "
    "dollar amounts, and case IDs in that language too (for example, in Spanish say "
    "'mil ochocientos dolares' rather than reading digits in English). The consent "
    "question, where you ask whether they want you to file the appeal or dispute, "
    "must also be asked in the patient's language so they fully understand what they "
    "are agreeing to. If the patient switches languages mid-conversation, follow them "
    "and switch too. Never make a patient struggle in a second language to get help."
)

# Optional default opening language. xAI auto-detects the spoken language, but this
# lets the very first greeting be spoken in the configured language. "es" => Spanish.
SOVEREIGN_VOICE_LANG = os.getenv("SOVEREIGN_VOICE_LANG", "en")

# ── Voice tool definitions ───────────────────────────────────────────────────
# These follow the xAI real-time API tool format

VOICE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "submit_claim",
        "description": (
            "Start reviewing the patient's medical bill or insurance denial; begins "
            "the Sovereign review (vision OCR + overcharge detection + denial "
            "appealability check). Params: claimant_name is the patient's name, "
            "incident_description is what the bill or denial is about, policy_number "
            "is the insurance member/policy id."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "claimant_name": {
                    "type": "string",
                    "description": "The patient's full name.",
                },
                "incident_description": {
                    "type": "string",
                    "description": "What the medical bill or insurance denial is about.",
                },
                "policy_number": {
                    "type": "string",
                    "description": "Insurance member or policy ID (e.g., the number on their insurance card).",
                },
            },
            "required": ["claimant_name", "incident_description", "policy_number"],
        },
    },
    {
        "type": "function",
        "name": "check_claim_status",
        "description": "Check the status or result of the patient's bill review.",
        "parameters": {
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The case ID (e.g., CASE-10293).",
                },
            },
            "required": ["claim_id"],
        },
    },
    {
        "type": "function",
        "name": "list_claims",
        "description": "List the patient's open billing cases with their current statuses.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "approve_claim",
        "description": (
            "Record the patient's explicit consent and authorize Sovereign to file "
            "the appeal or dispute on their behalf. Only call after the patient has "
            "verbally agreed to proceed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The case ID to file the appeal/dispute for.",
                },
                "approver_name": {
                    "type": "string",
                    "description": "The patient's name, recorded as giving consent.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about the patient's consent.",
                },
            },
            "required": ["claim_id", "approver_name"],
        },
    },
    {
        "type": "function",
        "name": "deny_claim",
        "description": "The patient declines to proceed with the appeal or dispute.",
        "parameters": {
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The case ID the patient is declining to proceed with.",
                },
                "approver_name": {
                    "type": "string",
                    "description": "The patient's name, recorded as declining.",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about why the patient declined.",
                },
            },
            "required": ["claim_id", "approver_name"],
        },
    },
    {
        "type": "function",
        "name": "get_evidence",
        "description": (
            "Get Sovereign findings: detected overcharges, billing errors, estimated "
            "recoverable amount, and whether the denial is appealable."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "claim_id": {
                    "type": "string",
                    "description": "The case ID to get Sovereign findings for.",
                },
            },
            "required": ["claim_id"],
        },
    },
    {
        "type": "function",
        "name": "web_search",
        "description": (
            "Research information that helps the patient, such as fair/typical prices "
            "for a procedure, what a billing or CPT code means, or the patient's "
            "rights around medical bills and insurance appeals."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to research (fair prices, billing codes, or patient rights).",
                },
            },
            "required": ["query"],
        },
    },
]


# ── Tool execution (reused from chat, but adapted for voice) ─────────────────

async def _execute_voice_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool and return the result as a JSON string for xAI."""
    try:
        result = await _dispatch_tool(name, arguments)
        return json.dumps(result, default=str)
    except Exception as exc:
        logger.error("Voice tool %s execution failed: %s", name, exc)
        return json.dumps({"error": f"Tool execution failed: {exc}"})


async def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch tool call to the appropriate handler."""
    if name == "submit_claim":
        return await _voice_submit_claim(args)
    elif name == "check_claim_status":
        return await _voice_check_claim_status(args)
    elif name == "list_claims":
        return await _voice_list_claims(args)
    elif name == "approve_claim":
        return await _voice_approve_claim(args)
    elif name == "deny_claim":
        return await _voice_deny_claim(args)
    elif name == "get_evidence":
        return await _voice_get_evidence(args)
    elif name == "web_search":
        # web_search is handled natively by xAI; this is a fallback
        return {"message": "Web search is handled by the xAI platform."}
    else:
        return {"error": f"Unknown tool: {name}"}


async def _voice_submit_claim(args: dict[str, Any]) -> dict[str, Any]:
    """Submit a claim via voice — uses pending photo if available."""
    from app.skills.claim_intake import claim_intake_skill
    from app.routes.claims import _run_pipeline, _running_tasks
    from app.models.claim import ClaimData
    from app.main import consume_pending_file
    from fastapi import UploadFile
    import io

    claimant_name = args.get("claimant_name", "Voice Caller")
    incident_description = args.get("incident_description", "")
    policy_number = args.get("policy_number", "")

    fallback = f"Claim submitted via voice agent.\nDescription: {incident_description}".encode()
    content, filename, content_type = consume_pending_file(fallback, "voice_submission.txt")

    upload = UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},
    )

    try:
        claim_data: ClaimData = await claim_intake_skill.execute(
            file=upload,
            claimant_name=claimant_name,
            incident_description=incident_description,
            policy_number=policy_number,
        )

        # Kick off background pipeline
        claim_record = (await get_claim(claim_data.id)) or claim_data.model_dump()
        task = asyncio.create_task(_run_pipeline(claim_data.id, claim_record))
        _running_tasks[claim_data.id] = task

        return {
            "success": True,
            "claim_id": claim_data.id,
            "status": "submitted",
            "message": f"Claim {claim_data.id} submitted. Processing has started.",
        }
    except Exception as exc:
        logger.error("Voice submit_claim failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def _voice_check_claim_status(args: dict[str, Any]) -> dict[str, Any]:
    """Check claim status."""
    claim_id = args.get("claim_id", "")
    claim = await get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim {claim_id} not found."}

    result: dict[str, Any] = {
        "claim_id": claim_id,
        "status": claim.get("status"),
        "claimant_name": claim.get("claimant_name"),
        "policy_number": claim.get("policy_number"),
        "fraud_score": claim.get("fraud_score"),
        "risk_level": claim.get("risk_level"),
        "decision": claim.get("decision"),
    }

    payout_rec = claim.get("payout_recommendation")
    if isinstance(payout_rec, dict):
        result["recommended_payout"] = payout_rec.get("recommended_amount", 0.0)

    return result


async def _voice_list_claims(args: dict[str, Any]) -> dict[str, Any]:
    """List all claims."""
    claims = await db_list_claims()
    summary = []
    for c in claims:
        summary.append({
            "claim_id": c.get("id"),
            "status": c.get("status"),
            "claimant_name": c.get("claimant_name"),
            "fraud_score": c.get("fraud_score"),
            "risk_level": c.get("risk_level"),
        })
    return {"total": len(summary), "claims": summary}


async def _voice_approve_claim(args: dict[str, Any]) -> dict[str, Any]:
    """Approve a claim."""
    claim_id = args.get("claim_id", "")
    approver_name = args.get("approver_name", "Voice Adjuster")
    notes = args.get("notes", "Approved via voice agent")

    claim = await get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim {claim_id} not found."}

    # Get or recompute risk assessment
    risk_assessment = claim.get("risk_assessment")
    if risk_assessment is None:
        fraud_score_val = claim.get("fraud_score", 0.0)
        payout_rec = claim.get("payout_recommendation", {})
        monetary_value = 0.0
        if isinstance(payout_rec, dict):
            monetary_value = payout_rec.get("recommended_amount", 0.0)

        fraud_score = FraudScore(
            overall_score=fraud_score_val or 0.0,
            risk_level=claim.get("risk_level", "medium"),
        )

        normalized = intent_normalizer.normalize({
            "skill_metadata": {
                "skill_name": "payout_execution_skill",
                "action_category": "claims_payout",
                "read_or_write": "write",
                "money_movement": True,
                "reversible": False,
                "required_approval_role": "adjuster",
            },
            "claim_id": claim_id,
            "monetary_value": monetary_value,
        })

        risk_assessment = await risk_engine.evaluate(normalized, fraud_score, claim)

    approval_result = await approval_engine.process_approval(
        claim_id=claim_id,
        decision=DecisionType.APPROVE.value,
        approver=approver_name,
        risk_assessment=risk_assessment,
    )

    final_decision = approval_result["decision"]

    # Execute payout if approved
    payout_amount = 0.0
    if final_decision == "approve" and approval_result.get("approved"):
        from app.skills.payout_execution import payout_execution_skill
        payout_rec = claim.get("payout_recommendation", {})
        amount = 0.0
        if isinstance(payout_rec, dict):
            amount = payout_rec.get("recommended_amount", 0.0)
        if amount > 0:
            payout_receipt = await payout_execution_skill.execute(
                claim_id=claim_id,
                approved_by=approver_name,
                amount=amount,
            )
            payout_amount = payout_receipt.payout_amount or 0.0

    # Generate receipt
    claim = await get_claim(claim_id) or claim
    receipt = await receipt_engine.generate_receipt(
        claim_id=claim_id,
        action=final_decision,
        approver=approver_name,
        risk_assessment=risk_assessment,
        claim_data=claim,
        payout_amount=payout_amount,
    )

    status_map = {"approve": "approved", "deny": "denied", "escalate": "escalated"}
    new_status = status_map.get(final_decision, "pending_review")

    await update_claim(
        claim_id,
        status=new_status,
        decision=final_decision,
        decision_by=approver_name,
        decision_at=receipt.timestamp,
    )

    if notes:
        await add_audit_entry(
            claim_id, "decision_notes", approver_name,
            {"notes": notes, "decision": final_decision, "via": "voice"},
        )

    return {
        "success": approval_result.get("approved", False),
        "claim_id": claim_id,
        "decision": final_decision,
        "status": new_status,
        "payout_amount": payout_amount,
    }


async def _voice_deny_claim(args: dict[str, Any]) -> dict[str, Any]:
    """Deny a claim."""
    claim_id = args.get("claim_id", "")
    approver_name = args.get("approver_name", "Voice Adjuster")
    notes = args.get("notes", "Denied via voice agent")

    claim = await get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim {claim_id} not found."}

    risk_assessment = claim.get("risk_assessment")
    if risk_assessment is None:
        fraud_score_val = claim.get("fraud_score", 0.0)
        fraud_score = FraudScore(
            overall_score=fraud_score_val or 0.0,
            risk_level=claim.get("risk_level", "medium"),
        )

        normalized = intent_normalizer.normalize({
            "skill_metadata": {
                "skill_name": "payout_execution_skill",
                "action_category": "claims_payout",
                "read_or_write": "write",
                "money_movement": True,
                "reversible": False,
                "required_approval_role": "adjuster",
            },
            "claim_id": claim_id,
            "monetary_value": 0.0,
        })

        risk_assessment = await risk_engine.evaluate(normalized, fraud_score, claim)

    approval_result = await approval_engine.process_approval(
        claim_id=claim_id,
        decision=DecisionType.DENY.value,
        approver=approver_name,
        risk_assessment=risk_assessment,
    )

    final_decision = approval_result["decision"]

    claim = await get_claim(claim_id) or claim
    receipt = await receipt_engine.generate_receipt(
        claim_id=claim_id,
        action=final_decision,
        approver=approver_name,
        risk_assessment=risk_assessment,
        claim_data=claim,
        payout_amount=0.0,
    )

    status_map = {"approve": "approved", "deny": "denied", "escalate": "escalated"}
    new_status = status_map.get(final_decision, "pending_review")

    await update_claim(
        claim_id,
        status=new_status,
        decision=final_decision,
        decision_by=approver_name,
        decision_at=receipt.timestamp,
    )

    if notes:
        await add_audit_entry(
            claim_id, "decision_notes", approver_name,
            {"notes": notes, "decision": final_decision, "via": "voice"},
        )

    return {
        "success": True,
        "claim_id": claim_id,
        "decision": final_decision,
        "status": new_status,
    }


async def _voice_get_evidence(args: dict[str, Any]) -> dict[str, Any]:
    """Retrieve claim evidence."""
    claim_id = args.get("claim_id", "")
    claim = await get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim {claim_id} not found."}

    fraud_details: dict[str, Any] = {
        "overall_score": claim.get("fraud_score"),
        "risk_level": claim.get("risk_level"),
    }

    return {
        "claim_id": claim_id,
        "status": claim.get("status"),
        "claimant_name": claim.get("claimant_name"),
        "extracted_data": claim.get("extracted_data"),
        "fraud_assessment": fraud_details,
        "coverage_result": claim.get("coverage_result"),
        "payout_recommendation": claim.get("payout_recommendation"),
        "simulation_result": claim.get("simulation_result"),
        "risk_assessment": claim.get("risk_assessment"),
    }


# ── Auto-greeting / proactive opener ─────────────────────────────────────────

def _has_pending_bill() -> bool:
    """Return True if a bill is waiting to be reviewed.

    Guarded import: voice.py must never crash if app.main isn't importable yet
    (e.g. during partial startup or circular-import timing).
    """
    try:
        from app.main import pending_files

        return "latest" in pending_files
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Could not check pending files for opener: %s", exc)
        return False


def _build_greeting_instruction() -> str:
    """Build the steering text for the agent's very first turn.

    - If a bill just arrived, Sovereign opens PROACTIVELY: it announces the new
      bill, says it already started reviewing it, and offers to walk the patient
      through what it found.
    - Otherwise it gives the normal warm greeting.

    The SOVEREIGN_VOICE_LANG default controls the language of this first turn;
    "es" makes the opener Spanish. (The agent still auto-detects and adapts to
    whatever language the patient actually speaks after this.)
    """
    spanish = SOVEREIGN_VOICE_LANG.lower().startswith("es")

    if _has_pending_bill():
        # PROACTIVE opener — Sovereign speaks first about the bill that just arrived.
        if spanish:
            return (
                "[Sistema: Acaba de llegar una nueva factura medica del paciente y ya "
                "empezaste a revisarla. Habla TU primero, en espanol, de forma calida y "
                "concreta. Dile algo como: 'Hola, soy Sovereign, su defensor personal de "
                "facturas medicas. Acaba de llegar su nueva factura de la sala de "
                "emergencias y ya empece a revisarla; veo un par de cobros que podrian "
                "estar de mas. Si quiere, le explico paso a paso lo que encontre.' "
                "Mantenlo en 2 o 3 frases, calido y tranquilizador. No pidas consentimiento "
                "para presentar nada todavia; primero ofrece explicarle los hallazgos.]"
            )
        return (
            "[System: A new medical bill from the patient just arrived and you have "
            "already started reviewing it. YOU speak first, warmly and concretely. "
            "Say something like: 'Hi, I'm Sovereign, your personal medical-billing "
            "advocate. Your new ER bill just came in and I've already started going "
            "through it. I'm spotting a couple of charges that look like possible "
            "overcharges. Want me to walk you through what I found?' Keep it to 2-3 "
            "sentences, warm and reassuring. Do NOT ask for consent to file anything "
            "yet; first offer to walk them through the findings.]"
        )

    # No pending bill — normal warm greeting.
    if spanish:
        return (
            "[Sistema: El paciente se acaba de conectar al agente de voz. Saludalo de "
            "forma calida y breve, en espanol. Di algo como: 'Hola, soy Sovereign, su "
            "defensor personal de facturas medicas. Si tiene una factura confusa o un "
            "reclamo denegado, cuenteme que paso y me pongo a investigarlo.' Manten el "
            "saludo en menos de 2 frases. Se calido, tranquilo y reconfortante.]"
        )
    return (
        "[System: The patient just connected to the voice agent. "
        "Greet them warmly and briefly. Say something like: "
        "'Hi, I'm Sovereign, your personal medical-billing advocate. "
        "If you've got a confusing bill or a denied claim, tell me what "
        "happened and I'll dig in.' "
        "Keep it under 2 sentences. Be warm, calm, and reassuring.]"
    )


# ── WebSocket endpoint ───────────────────────────────────────────────────────

@router.websocket("/api/voice")
async def voice_proxy(ws: WebSocket) -> None:
    """WebSocket proxy between the browser and xAI's real-time voice API.

    Flow:
    1. Browser opens WebSocket to /api/voice
    2. Backend opens WebSocket to wss://api.x.ai/v1/realtime
    3. Backend sends session.update with voice config, tools, and system prompt
    4. All messages are proxied bidirectionally
    5. When xAI sends a tool call, it is executed locally and the result is sent back
    """
    await ws.accept()
    logger.info("Voice WebSocket client connected")

    xai_ws = None
    try:
        # Connect to xAI real-time API
        xai_ws = await websockets.connect(
            XAI_REALTIME_URL,
            additional_headers={"Authorization": f"Bearer {XAI_API_KEY}"},
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
        )
        logger.info("Connected to xAI real-time API")

        # Send session configuration.
        # NOTE on multilingual: xAI's realtime API auto-detects the spoken
        # language and Grok Voice speaks 100+ languages, so language is driven
        # entirely via the SYSTEM_PROMPT "Language" instruction and the first-turn
        # greeting (see _build_greeting_instruction / SOVEREIGN_VOICE_LANG). xAI's
        # session schema does not document a dedicated language-hint field, so we
        # intentionally do NOT inject one here to avoid breaking session.update.
        session_config = {
            "type": "session.update",
            "session": {
                "voice": "Eve",
                "instructions": SYSTEM_PROMPT,
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.85,
                },
                "tools": VOICE_TOOLS,
                "input_audio_transcription": {
                    "model": "grok-2-audio",
                },
                "audio": {
                    "input": {
                        "format": {
                            "type": "audio/pcm",
                            "rate": 24000,
                        },
                    },
                    "output": {
                        "format": {
                            "type": "audio/pcm",
                            "rate": 24000,
                        },
                    },
                },
            },
        }
        await xai_ws.send(json.dumps(session_config))
        logger.info("Sent session config to xAI")

        # Auto-greet: trigger the agent to speak first so the user
        # doesn't have to awkwardly say "hi" into silence. If a bill is already
        # pending, this becomes a proactive opener; language follows
        # SOVEREIGN_VOICE_LANG for the first turn.
        greeting_text = _build_greeting_instruction()
        await xai_ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": greeting_text,
                    }
                ],
            },
        }))
        await xai_ws.send(json.dumps({"type": "response.create"}))
        logger.info(
            "Triggered auto-greeting (lang=%s, proactive=%s)",
            SOVEREIGN_VOICE_LANG,
            _has_pending_bill(),
        )

        # Bidirectional proxy
        async def browser_to_xai() -> None:
            """Forward messages from the browser WebSocket to xAI."""
            try:
                while True:
                    try:
                        msg = await ws.receive_text()
                        await xai_ws.send(msg)
                    except WebSocketDisconnect:
                        logger.info("Browser WebSocket disconnected")
                        break
                    except Exception as exc:
                        logger.warning("Error receiving from browser: %s", exc)
                        break
            finally:
                pass  # xAI cleanup handled by the outer finally block

        async def xai_to_browser() -> None:
            """Forward messages from xAI to the browser, intercepting tool calls."""
            try:
                async for msg in xai_ws:
                    if isinstance(msg, bytes):
                        # Binary audio data — forward directly
                        try:
                            await ws.send_bytes(msg)
                        except WebSocketDisconnect:
                            break
                        continue

                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        logger.warning("Non-JSON message from xAI: %s", str(msg)[:200])
                        try:
                            await ws.send_text(msg)
                        except WebSocketDisconnect:
                            break
                        continue

                    event_type = data.get("type", "")

                    # Handle function call completion — execute tool locally
                    if event_type == "response.function_call_arguments.done":
                        call_id = data.get("call_id", "")
                        fn_name = data.get("name", "")
                        raw_args = data.get("arguments", "{}")

                        try:
                            fn_args = json.loads(raw_args) if raw_args else {}
                        except json.JSONDecodeError:
                            fn_args = {}

                        logger.info("Voice tool call: %s(%s)", fn_name, fn_args)

                        # Execute the tool
                        tool_result = await _execute_voice_tool(fn_name, fn_args)

                        # Send the tool result back to xAI
                        tool_response = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": tool_result,
                            },
                        }
                        await xai_ws.send(json.dumps(tool_response))
                        logger.info("Sent tool result for %s back to xAI", fn_name)

                        # Tell xAI to continue generating a response
                        await xai_ws.send(json.dumps({
                            "type": "response.create",
                        }))

                    # Forward all messages to browser (including tool call events
                    # so the frontend can display tool activity)
                    try:
                        await ws.send_text(json.dumps(data))
                    except WebSocketDisconnect:
                        break

            except websockets.exceptions.ConnectionClosed:
                logger.info("xAI WebSocket connection closed")
            except Exception as exc:
                logger.error("Error in xAI-to-browser proxy: %s", exc)
            finally:
                # Close browser WebSocket when xAI disconnects
                try:
                    await ws.close()
                except Exception:
                    pass

        # Run both directions concurrently
        # When either task completes (due to disconnect), cancel the other
        browser_task = asyncio.create_task(browser_to_xai())
        xai_task = asyncio.create_task(xai_to_browser())

        done, pending = await asyncio.wait(
            [browser_task, xai_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel any remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Check for exceptions in completed tasks
        for task in done:
            try:
                task.result()
            except Exception as exc:
                logger.error("Voice proxy task error: %s", exc)

    except websockets.exceptions.InvalidStatusCode as exc:
        logger.error("Failed to connect to xAI real-time API: %s", exc)
        try:
            await ws.send_text(json.dumps({
                "type": "error",
                "message": f"Failed to connect to voice service: {exc}",
            }))
            await ws.close(code=1011, reason="Failed to connect to voice service")
        except Exception:
            pass
    except websockets.exceptions.WebSocketException as exc:
        logger.error("xAI WebSocket error: %s", exc)
        try:
            await ws.send_text(json.dumps({
                "type": "error",
                "message": f"Voice service connection error: {exc}",
            }))
            await ws.close(code=1011, reason="Voice service error")
        except Exception:
            pass
    except WebSocketDisconnect:
        logger.info("Browser disconnected before xAI connection established")
    except Exception as exc:
        logger.error("Voice proxy unexpected error: %s", exc)
        try:
            await ws.close(code=1011, reason="Internal error")
        except Exception:
            pass
    finally:
        # Ensure xAI WebSocket is closed
        if xai_ws is not None:
            try:
                await xai_ws.close()
            except Exception:
                pass
        logger.info("Voice WebSocket session ended")
