"""Chat API — streaming Grok conversation with function calling for claims."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.config import XAI_API_KEY, XAI_BASE_URL, XAI_MODEL
from app.database import (
    add_audit_entry,
    get_claim,
    list_claims as db_list_claims,
    update_claim,
)
from app.models.claim import ClaimData
from app.models.decision import DecisionType
from app.aubric.approval_engine import approval_engine
from app.aubric.intent_normalizer import intent_normalizer
from app.aubric.receipt_engine import receipt_engine
from app.aubric.risk_engine import risk_engine
from app.models.claim import FraudScore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

# ── Constants ────────────────────────────────────────────────────────────────

MAX_TOOL_CALLS_PER_TURN = 5

SYSTEM_PROMPT = (
    "You are Aubric ClaimGuard, an AI insurance claims agent. You help claimants "
    "file claims and adjusters review them. You can submit claims, check their "
    "status, approve/deny/escalate them, and retrieve evidence. Be professional "
    "but empathetic. Always show fraud scores and risk levels clearly. When a "
    "claim is being processed, offer to check its status. For demo, use realistic "
    "policy numbers such as POL-2024-47721, POL-2024-881093, and POL-2025-102847."
)

# ── Tool definitions (OpenAI function calling format) ────────────────────────

CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "submit_claim",
            "description": (
                "Submit a new insurance claim for processing. This creates a claim "
                "record and starts the automated investigation pipeline including "
                "document analysis, fraud detection, and payout recommendation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the claim document/image file on the server.",
                    },
                    "claimant_name": {
                        "type": "string",
                        "description": "Full name of the person filing the claim.",
                    },
                    "incident_description": {
                        "type": "string",
                        "description": "Detailed description of the incident.",
                    },
                    "policy_number": {
                        "type": "string",
                        "description": "Insurance policy number (e.g., POL-2024-47721).",
                    },
                },
                "required": ["claimant_name", "incident_description", "policy_number"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_claim_status",
            "description": (
                "Check the current status and details of an existing insurance claim "
                "by its claim ID."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID (e.g., CLM-12345).",
                    },
                },
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_claims",
            "description": "List all insurance claims in the system with their current statuses.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "approve_claim",
            "description": (
                "Approve an insurance claim for payout. Only adjusters can approve claims. "
                "This triggers the Aubric approval engine and generates a decision receipt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID to approve.",
                    },
                    "approver_name": {
                        "type": "string",
                        "description": "Name of the adjuster approving the claim.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes or justification for the approval.",
                    },
                },
                "required": ["claim_id", "approver_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deny_claim",
            "description": (
                "Deny an insurance claim. Only adjusters can deny claims. "
                "This triggers the Aubric approval engine and generates a decision receipt."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID to deny.",
                    },
                    "approver_name": {
                        "type": "string",
                        "description": "Name of the adjuster denying the claim.",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional notes or justification for the denial.",
                    },
                },
                "required": ["claim_id", "approver_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_evidence",
            "description": (
                "Retrieve all evidence and analysis results for a claim, including "
                "extracted document data, fraud assessment, coverage, payout recommendation, "
                "simulation results, and risk assessment."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {
                        "type": "string",
                        "description": "The claim ID to get evidence for.",
                    },
                },
                "required": ["claim_id"],
            },
        },
    },
]


# ── Request / response models ────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    claim_id: str | None = None


# ── Tool execution ───────────────────────────────────────────────────────────

async def _execute_submit_claim(args: dict[str, Any]) -> dict[str, Any]:
    """Submit a claim via the intake skill and start the pipeline."""
    from app.skills.claim_intake import claim_intake_skill
    from app.routes.claims import _run_pipeline, _running_tasks
    from app.main import consume_pending_file
    from fastapi import UploadFile
    import io

    file_path = args.get("file_path", "")
    claimant_name = args["claimant_name"]
    incident_description = args["incident_description"]
    policy_number = args.get("policy_number", "")

    # Try pending file first, then file_path arg, then placeholder
    fallback_content = b"Claim submitted via chat agent."
    fallback_filename = "chat_submission.txt"
    content, filename, content_type = consume_pending_file(fallback_content, fallback_filename)

    # If no pending file was consumed, check the file_path argument
    if filename == fallback_filename and file_path:
        from pathlib import Path
        from app.config import UPLOAD_DIR
        p = Path(file_path)
        # Validate file_path resolves within UPLOAD_DIR to prevent arbitrary file read
        if p.resolve().is_relative_to(UPLOAD_DIR.resolve()) and p.exists():
            content = p.read_bytes()
            filename = p.name
            from app.main import _guess_content_type
            content_type = _guess_content_type(p.name)

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

        # Kick off the background pipeline
        claim_record = (await get_claim(claim_data.id)) or claim_data.model_dump()
        task = asyncio.create_task(_run_pipeline(claim_data.id, claim_record))
        _running_tasks[claim_data.id] = task

        return {
            "success": True,
            "claim_id": claim_data.id,
            "status": "submitted",
            "message": f"Claim {claim_data.id} submitted successfully. Processing pipeline started.",
            "claimant_name": claimant_name,
            "policy_number": policy_number,
        }
    except Exception as exc:
        logger.error("Chat submit_claim failed: %s", exc)
        return {"success": False, "error": str(exc)}


async def _execute_check_claim_status(args: dict[str, Any]) -> dict[str, Any]:
    """Check the status of a claim."""
    claim_id = args["claim_id"]
    claim = await get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim {claim_id} not found."}

    result: dict[str, Any] = {
        "claim_id": claim_id,
        "status": claim.get("status"),
        "claimant_name": claim.get("claimant_name"),
        "incident_description": claim.get("incident_description"),
        "policy_number": claim.get("policy_number"),
        "created_at": claim.get("created_at"),
        "fraud_score": claim.get("fraud_score"),
        "risk_level": claim.get("risk_level"),
        "decision": claim.get("decision"),
        "decision_by": claim.get("decision_by"),
    }

    # Include payout recommendation summary if available
    payout_rec = claim.get("payout_recommendation")
    if isinstance(payout_rec, dict):
        result["recommended_payout"] = payout_rec.get("recommended_amount", 0.0)
        result["payout_confidence"] = payout_rec.get("confidence", 0.0)

    return result


async def _execute_list_claims(_args: dict[str, Any]) -> dict[str, Any]:
    """List all claims."""
    claims = await db_list_claims()
    summary = []
    for c in claims:
        summary.append({
            "claim_id": c.get("id"),
            "status": c.get("status"),
            "claimant_name": c.get("claimant_name"),
            "policy_number": c.get("policy_number"),
            "fraud_score": c.get("fraud_score"),
            "risk_level": c.get("risk_level"),
            "created_at": c.get("created_at"),
        })
    return {"total": len(summary), "claims": summary}


async def _execute_approval_decision(
    claim_id: str,
    decision: DecisionType,
    approver_name: str,
    notes: str = "",
) -> dict[str, Any]:
    """Shared logic for approve/deny — mirrors routes/approvals.py flow."""
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

    # Run Aubric approval engine
    approval_result = await approval_engine.process_approval(
        claim_id=claim_id,
        decision=decision.value,
        approver=approver_name,
        risk_assessment=risk_assessment,
    )

    final_decision = approval_result["decision"]

    # Execute payout if approved
    payout_receipt = None
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

    # Generate decision receipt
    claim = await get_claim(claim_id) or claim
    payout_amount = 0.0
    if payout_receipt:
        payout_amount = payout_receipt.payout_amount or 0.0
    elif final_decision == "approve":
        pr = claim.get("payout_recommendation", {})
        if isinstance(pr, dict):
            payout_amount = pr.get("recommended_amount", 0.0)

    receipt = await receipt_engine.generate_receipt(
        claim_id=claim_id,
        action=final_decision,
        approver=approver_name,
        risk_assessment=risk_assessment,
        claim_data=claim,
        payout_amount=payout_amount,
    )

    # Update claim status
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
            {"notes": notes, "decision": final_decision},
        )

    return {
        "success": approval_result.get("approved", False),
        "claim_id": claim_id,
        "decision": final_decision,
        "status": new_status,
        "reason": approval_result.get("reason", ""),
        "receipt_id": receipt.receipt_id,
        "payout_amount": payout_amount,
    }


async def _execute_approve_claim(args: dict[str, Any]) -> dict[str, Any]:
    """Approve a claim."""
    return await _execute_approval_decision(
        claim_id=args["claim_id"],
        decision=DecisionType.APPROVE,
        approver_name=args["approver_name"],
        notes=args.get("notes", ""),
    )


async def _execute_deny_claim(args: dict[str, Any]) -> dict[str, Any]:
    """Deny a claim."""
    return await _execute_approval_decision(
        claim_id=args["claim_id"],
        decision=DecisionType.DENY,
        approver_name=args["approver_name"],
        notes=args.get("notes", ""),
    )


async def _execute_get_evidence(args: dict[str, Any]) -> dict[str, Any]:
    """Retrieve all evidence for a claim."""
    claim_id = args["claim_id"]
    claim = await get_claim(claim_id)
    if claim is None:
        return {"error": f"Claim {claim_id} not found."}

    extracted_data = claim.get("extracted_data")
    coverage_result = claim.get("coverage_result")
    payout_recommendation = claim.get("payout_recommendation")
    simulation_result = claim.get("simulation_result")
    risk_assessment = claim.get("risk_assessment")

    fraud_details: dict[str, Any] = {
        "overall_score": claim.get("fraud_score"),
        "risk_level": claim.get("risk_level"),
    }
    if isinstance(risk_assessment, dict):
        fraud_details["fraud_concern_level"] = risk_assessment.get("fraud_concern_level")
        fraud_details["identity_confidence"] = risk_assessment.get("identity_confidence")
        fraud_details["document_authenticity_confidence"] = risk_assessment.get(
            "document_authenticity_confidence"
        )

    return {
        "claim_id": claim_id,
        "status": claim.get("status"),
        "claimant_name": claim.get("claimant_name"),
        "incident_description": claim.get("incident_description"),
        "policy_number": claim.get("policy_number"),
        "extracted_data": extracted_data,
        "fraud_assessment": fraud_details,
        "coverage_result": coverage_result,
        "payout_recommendation": payout_recommendation,
        "simulation_result": simulation_result,
        "risk_assessment": risk_assessment,
        "decision": claim.get("decision"),
        "decision_by": claim.get("decision_by"),
        "decision_at": claim.get("decision_at"),
    }


# ── Tool dispatcher ──────────────────────────────────────────────────────────

_TOOL_HANDLERS: dict[str, Any] = {
    "submit_claim": _execute_submit_claim,
    "check_claim_status": _execute_check_claim_status,
    "list_claims": _execute_list_claims,
    "approve_claim": _execute_approve_claim,
    "deny_claim": _execute_deny_claim,
    "get_evidence": _execute_get_evidence,
}


async def _execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool by name and return the result."""
    handler = _TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        result = await handler(arguments)
        return result
    except Exception as exc:
        logger.error("Tool %s execution failed: %s", name, exc)
        return {"error": f"Tool execution failed: {exc}"}


# ── Streaming Grok API helper ────────────────────────────────────────────────

def _build_grok_body(
    messages: list[dict[str, Any]],
    *,
    stream: bool = True,
) -> dict[str, Any]:
    """Build the request body for the Grok chat completions API."""
    return {
        "model": XAI_MODEL,
        "messages": messages,
        "tools": CHAT_TOOLS,
        "tool_choice": "auto",
        "stream": stream,
        "temperature": 0.4,
        "max_tokens": 4096,
    }


def _grok_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {XAI_API_KEY}",
        "Content-Type": "application/json",
    }


async def _parse_sse_line(line: str) -> dict[str, Any] | None:
    """Parse a single SSE data line from the Grok streaming response."""
    if not line.startswith("data: "):
        return None
    payload = line[6:].strip()
    if payload == "[DONE]":
        return {"_done": True}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Failed to parse SSE payload: %s", payload[:200])
        return None


# ── Main streaming endpoint ──────────────────────────────────────────────────

@router.post("")
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    """Streaming chat endpoint with Grok function calling for claims management.

    Request body:
        {
            "messages": [{"role": "user", "content": "..."}],
            "claim_id": "optional-claim-id"
        }

    Response: SSE stream of events:
        - {"type": "text_delta", "content": "word "}
        - {"type": "tool_call", "name": "...", "arguments": {...}}
        - {"type": "tool_result", "name": "...", "result": {...}}
        - {"type": "done"}
    """

    async def event_generator():
        # Build the messages array with system prompt
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]

        # If a claim_id was provided, inject context about that claim
        if request.claim_id:
            claim = await get_claim(request.claim_id)
            if claim:
                context = (
                    f"[Context: Currently discussing claim {request.claim_id}. "
                    f"Status: {claim.get('status')}. "
                    f"Claimant: {claim.get('claimant_name')}. "
                    f"Policy: {claim.get('policy_number')}. "
                    f"Fraud score: {claim.get('fraud_score')}. "
                    f"Risk level: {claim.get('risk_level')}.]"
                )
                messages.append({"role": "system", "content": context})

        # Add user conversation history
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        tool_call_count = 0

        # Outer loop: handles tool-calling rounds
        while tool_call_count < MAX_TOOL_CALLS_PER_TURN:
            body = _build_grok_body(messages, stream=True)

            # Track accumulated tool calls from this streaming round
            pending_tool_calls: dict[int, dict[str, Any]] = {}
            assistant_text_parts: list[str] = []
            finish_reason: str | None = None

            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                    async with client.stream(
                        "POST",
                        f"{XAI_BASE_URL}/chat/completions",
                        headers=_grok_headers(),
                        json=body,
                        timeout=60.0,
                    ) as response:
                        if response.status_code != 200:
                            error_body = await response.aread()
                            logger.error(
                                "Grok API error %d: %s",
                                response.status_code,
                                error_body[:500],
                            )
                            yield {
                                "event": "error",
                                "data": json.dumps({
                                    "type": "error",
                                    "message": f"Grok API returned status {response.status_code}",
                                }),
                            }
                            return

                        async for line in response.aiter_lines():
                            parsed = await _parse_sse_line(line)
                            if parsed is None:
                                continue
                            if parsed.get("_done"):
                                break

                            choices = parsed.get("choices", [])
                            if not choices:
                                continue

                            delta = choices[0].get("delta", {})
                            choice_finish = choices[0].get("finish_reason")
                            if choice_finish:
                                finish_reason = choice_finish

                            # Handle text content streaming
                            content = delta.get("content")
                            if content:
                                assistant_text_parts.append(content)
                                yield {
                                    "data": json.dumps({
                                        "type": "text_delta",
                                        "content": content,
                                    }),
                                }

                            # Handle tool call deltas
                            tool_calls = delta.get("tool_calls")
                            if tool_calls:
                                for tc in tool_calls:
                                    idx = tc.get("index", 0)
                                    if idx not in pending_tool_calls:
                                        pending_tool_calls[idx] = {
                                            "id": tc.get("id", ""),
                                            "name": "",
                                            "arguments": "",
                                        }
                                    entry = pending_tool_calls[idx]
                                    if tc.get("id"):
                                        entry["id"] = tc["id"]
                                    func = tc.get("function", {})
                                    if func.get("name"):
                                        entry["name"] = func["name"]
                                    if func.get("arguments"):
                                        entry["arguments"] += func["arguments"]

            except httpx.ReadTimeout:
                logger.error("Grok streaming read timeout")
                yield {
                    "data": json.dumps({
                        "type": "error",
                        "message": "Request timed out. Please try again.",
                    }),
                }
                return
            except Exception as exc:
                logger.error("Grok streaming error: %s", exc)
                yield {
                    "data": json.dumps({
                        "type": "error",
                        "message": f"Streaming error: {exc}",
                    }),
                }
                return

            # If no tool calls were made, we are done
            if not pending_tool_calls:
                break

            # Process tool calls
            # First, add the assistant message with tool_calls to the conversation
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if assistant_text_parts:
                assistant_msg["content"] = "".join(assistant_text_parts)
            else:
                assistant_msg["content"] = None

            tool_calls_list: list[dict[str, Any]] = []
            for idx in sorted(pending_tool_calls.keys()):
                tc_data = pending_tool_calls[idx]
                tool_calls_list.append({
                    "id": tc_data["id"],
                    "type": "function",
                    "function": {
                        "name": tc_data["name"],
                        "arguments": tc_data["arguments"],
                    },
                })
            assistant_msg["tool_calls"] = tool_calls_list
            messages.append(assistant_msg)

            # Execute each tool call and add results
            for tc_data in [pending_tool_calls[i] for i in sorted(pending_tool_calls.keys())]:
                tool_name = tc_data["name"]
                tool_call_id = tc_data["id"]
                raw_args = tc_data["arguments"]

                # Parse arguments
                try:
                    tool_args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    tool_args = {}

                # Notify frontend about the tool call
                yield {
                    "data": json.dumps({
                        "type": "tool_call",
                        "name": tool_name,
                        "arguments": tool_args,
                    }),
                }

                # Execute the tool
                tool_result = await _execute_tool(tool_name, tool_args)
                tool_call_count += 1

                # Notify frontend about the tool result
                yield {
                    "data": json.dumps({
                        "type": "tool_result",
                        "name": tool_name,
                        "result": tool_result,
                    }),
                }

                # Add tool result to messages for next Grok call
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(tool_result, default=str),
                })

            # If we've hit the tool call limit, add a note and break
            if tool_call_count >= MAX_TOOL_CALLS_PER_TURN:
                messages.append({
                    "role": "system",
                    "content": (
                        "You have reached the maximum number of tool calls for this turn. "
                        "Please summarize what you've done so far and let the user know "
                        "if more actions are needed."
                    ),
                })
                # Do one final streaming call without tools to get the summary
                final_body = {
                    "model": XAI_MODEL,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.4,
                    "max_tokens": 2048,
                }
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
                        async with client.stream(
                            "POST",
                            f"{XAI_BASE_URL}/chat/completions",
                            headers=_grok_headers(),
                            json=final_body,
                            timeout=60.0,
                        ) as response:
                            async for line in response.aiter_lines():
                                parsed = await _parse_sse_line(line)
                                if parsed is None:
                                    continue
                                if parsed.get("_done"):
                                    break
                                choices = parsed.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                content = delta.get("content")
                                if content:
                                    yield {
                                        "data": json.dumps({
                                            "type": "text_delta",
                                            "content": content,
                                        }),
                                    }
                except Exception as exc:
                    logger.error("Final summary stream error: %s", exc)
                break

            # Otherwise, loop back — Grok will continue after seeing tool results

        # Signal completion
        yield {
            "data": json.dumps({"type": "done"}),
        }

    return EventSourceResponse(event_generator())
