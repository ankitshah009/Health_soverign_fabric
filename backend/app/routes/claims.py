"""Billing-case API routes — submit, list, get, and SSE event stream.

Pipeline Architecture (optimized), all patient-side:
    Vision over the bill/EOB/denial (3-8s) → [Coverage + Web research] (parallel, 0-20s)
    → Overcharge/billing-error review (2-5s)
    → Recoverable-amount estimate (2-5s) → Consent/risk gate (<10ms)
    → Appeal-outcome simulation (async, off critical path)
    → Receipt (after simulation completes)

A high overcharge-severity score is the PATIENT's strongest case, so the pipeline
never short-circuits or blocks on it — it always runs the full recovery + appeal-odds path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sse_starlette.sse import EventSourceResponse

from app.aubric.intent_normalizer import intent_normalizer
from app.aubric.risk_engine import risk_engine
from app.aubric.simulation import simulation_engine
from app.database import (
    add_investigation_event,
    get_claim,
    get_investigation_events,
    list_claims,
    update_claim,
)
from app.models.claim import (
    ClaimData,
    ClaimResponse,
    CoverageResult,
    ExtractedData,
    FraudScore,
    PayoutRecommendation,
    SimulationResult,
)
from app.services.grok_service import grok_service
from app.services.event_bus import event_bus
from app.services.telemetry import (
    record_exception,
    set_span_attributes,
    trace_coverage_lookup,
    trace_document_analysis,
    trace_fraud_assessment,
    trace_pipeline,
    trace_risk_evaluation,
    trace_web_investigation,
)
from app.services.yutori_service import yutori_service
from app.config import MAX_CONCURRENT_PIPELINES
from app.services.webhook_dispatcher import (
    check_and_fire_threshold,
    clear_threshold_state,
    fire_event,
    EVENT_CLAIM_COMPLETED,
    EVENT_CLAIM_SUBMITTED,
)
from app.skills.claim_intake import claim_intake_skill
from app.skills.coverage_lookup import coverage_lookup_skill
from app.skills.fraud_signal import fraud_signal_skill
from app.skills.payout_recommendation import payout_recommendation_skill

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claims", tags=["claims"])

# ── Background pipeline tasks (in-flight) ────────────────────────────────────
_running_tasks: dict[str, asyncio.Task[None]] = {}


def _cleanup_running_task(claim_id: str, task: asyncio.Task[None]) -> None:
    """Remove completed pipeline tasks from the in-flight registry."""
    _running_tasks.pop(claim_id, None)

    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("Pipeline task cancelled for %s", claim_id)
    except Exception:
        logger.exception("Pipeline task failed for %s", claim_id)


async def _emit(claim_id: str, event_type: str, message: str, status: str = "info", data: Any = None) -> None:
    """Persist an investigation event AND push to the in-memory event bus."""
    await add_investigation_event(claim_id, event_type, message, status, data)
    # Push to event bus for near-instant SSE delivery
    event_bus.push(claim_id, {
        "event_type": event_type,
        "message": message,
        "status": status,
        "data": data,
        "timestamp": None,  # Will be set by DB; SSE uses the event_type for display
    })


async def _run_pipeline(claim_id: str, claim_record: dict[str, Any]) -> None:
    """Full patient-side case processing pipeline — runs as a background task.

    Optimized pipeline flow:
        Vision over the bill/EOB/denial (3-8s) → [Coverage + Web research] (parallel, 0-20s)
        → Overcharge/billing-error review (2-5s)
        → Recoverable-amount estimate (2-5s) → Consent/risk gate (<10ms)
        → Appeal-outcome simulation (ASYNC, off critical path)

    A high overcharge-severity score is never a reason to skip steps — it is the
    patient's strongest case and always runs the full recovery + appeal-odds path.
    """
    pipeline_start = time.monotonic()
    stage_timings: dict[str, float] = {}

    with trace_pipeline(claim_id) as pipeline_span:
        try:
            file_path = claim_record.get("file_path", "")
            file_type = claim_record.get("file_type", "")
            claimant_name = claim_record.get("claimant_name", "")
            incident_description = claim_record.get("incident_description", "")
            policy_number = claim_record.get("policy_number", "")

            # ── Step 1: Update status to processing ──────────────────────────
            await update_claim(claim_id, status="processing")
            await _emit(claim_id, "pipeline_start", "Claim processing pipeline started.", "processing")

            # ── Step 2: Document analysis via Grok vision ────────────────────
            await _emit(claim_id, "document_analysis", "Analyzing uploaded document with AI vision...", "processing")

            t0 = time.monotonic()
            extracted_data: ExtractedData
            with trace_document_analysis(claim_id) as doc_span:
                if file_path:
                    extracted_data = await grok_service.analyze_document(file_path, file_type)
                else:
                    extracted_data = ExtractedData(
                        damage_type="unknown",  # document category (itemized_bill/EOB/denial_letter)
                        incident_details=incident_description,
                        document_type="none",
                        key_findings=["No document uploaded"],
                    )
                doc_span.set_attribute("document.damage_type", extracted_data.damage_type)
                doc_span.set_attribute("document.estimated_cost", extracted_data.estimated_cost)
                doc_span.set_attribute("document.type", extracted_data.document_type)

            stage_timings["vision"] = time.monotonic() - t0

            await update_claim(claim_id, extracted_data=extracted_data.model_dump())
            await _emit(
                claim_id, "document_analyzed",
                f"Document analyzed: {extracted_data.damage_type} — "
                f"total billed ${extracted_data.estimated_cost:,.2f} "
                f"({stage_timings['vision']:.1f}s)",
                "completed",
                {**extracted_data.model_dump(), "_stage_time": stage_timings["vision"]},
            )

            # ── Step 3: Coverage + Yutori IN PARALLEL (both depend on Vision output) ──
            await _emit(claim_id, "parallel_start", "Running coverage lookup and web investigation in parallel...", "processing")

            t0 = time.monotonic()

            # Coverage is instant (mock lookup) — run alongside Yutori
            async def _run_coverage() -> CoverageResult:
                with trace_coverage_lookup(claim_id) as cov_span:
                    result = await coverage_lookup_skill.execute(
                        policy_number=policy_number,
                        damage_type=extracted_data.damage_type,
                        estimated_cost=extracted_data.estimated_cost,
                    )
                    cov_span.set_attribute("coverage.covered", result.covered)
                    cov_span.set_attribute("coverage.type", result.coverage_type)
                    cov_span.set_attribute("coverage.limit", result.coverage_limit)
                    return result

            async def _run_yutori() -> list:
                with trace_web_investigation(claim_id) as web_span:
                    try:
                        results = await asyncio.wait_for(
                            yutori_service.verify_claim_entities(
                                extracted_data, claimant_name, incident_description=incident_description,
                            ),
                            timeout=20.0,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Yutori verification timed out for %s", claim_id)
                        web_span.set_attribute("investigation.timed_out", True)
                        results = yutori_service.pending_verification_results(
                            extracted_data, claimant_name,
                            incident_description=incident_description,
                            summary="Verification timed out during live processing.",
                        )
                    except Exception as yutori_exc:
                        logger.error("Yutori verification failed for %s: %s", claim_id, yutori_exc)
                        web_span.record_exception(yutori_exc)
                        results = yutori_service.pending_verification_results(
                            extracted_data, claimant_name,
                            incident_description=incident_description,
                            summary=f"Verification failed: {yutori_exc}",
                        )

                    completed = sum(1 for r in results if r.get("status") == "completed")
                    total = len(results)
                    pending = sum(1 for r in results if r.get("status") == "verification_pending")
                    web_span.set_attribute("investigation.vectors_total", total)
                    web_span.set_attribute("investigation.vectors_completed", completed)
                    web_span.set_attribute("investigation.vectors_pending", pending)
                    return results

            # Run both in parallel
            coverage_task = asyncio.create_task(_run_coverage())
            yutori_task = asyncio.create_task(_run_yutori())
            coverage_result, yutori_results = await asyncio.gather(
                coverage_task, yutori_task, return_exceptions=True,
            )

            # Handle exceptions
            if isinstance(coverage_result, Exception):
                logger.error("Coverage lookup failed: %s", coverage_result)
                coverage_result = CoverageResult()
            if isinstance(yutori_results, Exception):
                logger.error("Yutori verification failed: %s", yutori_results)
                yutori_results = []

            stage_timings["coverage_yutori"] = time.monotonic() - t0

            await update_claim(claim_id, coverage_result=coverage_result.model_dump())
            await _emit(
                claim_id, "coverage_checked",
                f"Coverage: {'Covered' if coverage_result.covered else 'Not covered'} — "
                f"{coverage_result.coverage_type} (limit ${coverage_result.coverage_limit:,.2f})",
                "completed",
                coverage_result.model_dump(),
            )

            completed_count = sum(1 for r in yutori_results if r.get("status") == "completed") if isinstance(yutori_results, list) else 0
            total_count = len(yutori_results) if isinstance(yutori_results, list) else 0
            pending_count = sum(1 for r in yutori_results if r.get("status") == "verification_pending") if isinstance(yutori_results, list) else 0

            if total_count == 0:
                verification_message = "Web investigation: unavailable — proceeding with AI analysis"
            elif completed_count == 0 and pending_count == total_count:
                verification_message = f"Web investigation: {pending_count}/{total_count} vectors still pending"
            else:
                verification_message = f"Web investigation: {completed_count}/{total_count} vectors returned results"
            await _emit(
                claim_id, "entity_verification",
                f"{verification_message} ({stage_timings['coverage_yutori']:.1f}s)",
                "completed",
                yutori_results,
            )

            # ── Step 4: Overcharge / billing-error assessment ────────────────
            await _emit(claim_id, "fraud_assessment", "Scanning the bill for overcharges and billing errors...", "processing")

            t0 = time.monotonic()
            with trace_fraud_assessment(claim_id) as fraud_span:
                fraud_score: FraudScore = await fraud_signal_skill.execute(
                    extracted_data, incident_description, yutori_results if isinstance(yutori_results, list) else [],
                )
                fraud_span.set_attribute("fraud.score", fraud_score.overall_score)
                fraud_span.set_attribute("fraud.risk_level", fraud_score.risk_level)
                fraud_span.set_attribute("fraud.signals_count", len(fraud_score.signals))

            stage_timings["fraud"] = time.monotonic() - t0

            await update_claim(
                claim_id,
                fraud_score=fraud_score.overall_score,
                fraud_signals=[s.model_dump() if hasattr(s, 'model_dump') else s for s in fraud_score.signals],
                risk_level=fraud_score.risk_level,
            )
            await _emit(
                claim_id, "fraud_assessed",
                f"Overcharge review complete: severity {fraud_score.overall_score:.0f}/100 "
                f"({fraud_score.risk_level}) ({stage_timings['fraud']:.1f}s)",
                "completed",
                {**fraud_score.model_dump(), "_stage_time": stage_timings["fraud"]},
            )

            # Fire webhook if overcharge-severity score crosses 50 or 70 thresholds
            check_and_fire_threshold(claim_id, fraud_score.overall_score)

            # ── SHORT-CIRCUIT (DISABLED for the patient side) ────────────────
            if False:  # Sovereign (patient-side): never short-circuit. A high overcharge-severity score is the patient's STRONGEST case — it must run the full recovery + appeal-odds simulation below, not get marked "blocked".
                logger.info("Short-circuit path is disabled for %s (overcharge severity %.0f)", claim_id, fraud_score.overall_score)
                await _emit(
                    claim_id, "short_circuit",
                    f"High overcharge severity ({fraud_score.overall_score:.0f}/100) — (disabled path).",
                    "completed",
                    {"reason": "overcharge_severity_high", "fraud_score": fraud_score.overall_score},
                )

                # Run risk engine directly — it only needs fraud_score + monetary_value
                normalized = intent_normalizer.normalize({
                    "skill_metadata": {
                        "skill_name": "payout_execution_skill",
                        "action_category": "claims_payout",
                        "read_or_write": "write",
                        "money_movement": True,
                        "reversible": False,
                        "required_approval_role": "patient",
                    },
                    "claim_id": claim_id,
                    "monetary_value": 0.0,
                })
                claim_snapshot = await get_claim(claim_id) or claim_record
                risk_assessment = await risk_engine.evaluate(normalized, fraud_score, claim_snapshot)

                await update_claim(claim_id, risk_assessment=risk_assessment, status="blocked")
                await _emit(
                    claim_id, "risk_evaluated",
                    f"Risk evaluation: {risk_assessment['recommended_action']} (risk level: {risk_assessment['action_risk_level']})",
                    "completed",
                    risk_assessment,
                )

                stage_timings["total"] = time.monotonic() - pipeline_start
                await _emit(
                    claim_id, "pipeline_complete",
                    f"Processing complete (disabled path). ({stage_timings['total']:.1f}s total)",
                    "completed",
                    {"status": "blocked", "recommended_action": "block", "stage_timings": stage_timings},
                )

                fire_event(EVENT_CLAIM_COMPLETED, {
                    "claim_id": claim_id, "status": "blocked",
                    "fraud_score": fraud_score.overall_score, "risk_level": fraud_score.risk_level,
                    "recommended_action": "block", "payout_amount": 0.0,
                })
                pipeline_span.set_attribute("pipeline.final_status", "blocked")
                pipeline_span.set_attribute("pipeline.short_circuited", True)
                pipeline_span.set_attribute("pipeline.fraud_score", fraud_score.overall_score)
                return  # Skip payout, simulation, and receipt

            # ── Step 5: Recoverable-amount estimate ──────────────────────────
            await _emit(claim_id, "payout_analysis", "Estimating how much the patient can recover...", "processing")

            t0 = time.monotonic()
            payout_rec: PayoutRecommendation = await payout_recommendation_skill.execute(
                extracted_data, coverage_result, fraud_score,
            )
            stage_timings["payout"] = time.monotonic() - t0

            await update_claim(claim_id, payout_recommendation=payout_rec.model_dump())
            await _emit(
                claim_id, "payout_recommended",
                f"Estimated recoverable for the patient: ${payout_rec.recommended_amount:,.2f} "
                f"(confidence: {payout_rec.confidence:.0%}) ({stage_timings['payout']:.1f}s)",
                "completed",
                {**payout_rec.model_dump(), "_stage_time": stage_timings["payout"]},
            )

            # ── Step 6: Aubric risk engine evaluation ────────────────────────
            await _emit(claim_id, "risk_evaluation", "Evaluating authorization requirements...", "processing")

            with trace_risk_evaluation(claim_id) as risk_span:
                normalized = intent_normalizer.normalize({
                    "skill_metadata": {
                        "skill_name": "payout_execution_skill",
                        "action_category": "claims_payout",
                        "read_or_write": "write",
                        "money_movement": True,
                        "reversible": False,
                        "required_approval_role": "patient",
                    },
                    "claim_id": claim_id,
                    "monetary_value": payout_rec.recommended_amount,
                })

                claim_snapshot = await get_claim(claim_id) or claim_record
                risk_assessment = await risk_engine.evaluate(
                    normalized, fraud_score, claim_snapshot,
                )
                risk_span.set_attribute("risk.recommended_action", risk_assessment["recommended_action"])
                risk_span.set_attribute("risk.action_risk_level", risk_assessment["action_risk_level"])

            await update_claim(claim_id, risk_assessment=risk_assessment)
            await _emit(
                claim_id, "risk_evaluated",
                f"Risk evaluation: {risk_assessment['recommended_action']} "
                f"(risk level: {risk_assessment['action_risk_level']})",
                "completed",
                risk_assessment,
            )

            # ── Step 7: Determine status (simulation is NOT needed for this) ──
            final_status = "analyzed"
            if risk_assessment["recommended_action"] == "auto_approve":
                final_status = "ready"
            elif risk_assessment["recommended_action"] == "require_consent":
                final_status = "needs_consent"

            await update_claim(claim_id, status=final_status)

            # ── Step 8: Simulation (ASYNC — off critical path) ───────────────
            # Simulation is informational context for the receipt, not a gate
            # for the trust decision. risk_engine.evaluate() only needs
            # fraud_score + payout amount.
            await _emit(claim_id, "simulation_start", "Running outcome simulation (async)...", "processing")

            t0 = time.monotonic()
            try:
                sim_result: SimulationResult = await simulation_engine.simulate(
                    claim_snapshot, fraud_score, payout_rec,
                )
            except Exception as sim_exc:
                logger.error("Simulation failed for %s: %s", claim_id, sim_exc)
                sim_result = SimulationResult()

            stage_timings["simulation"] = time.monotonic() - t0

            await update_claim(claim_id, simulation_result=sim_result.model_dump())
            await _emit(
                claim_id, "simulation_complete",
                f"Outcome analysis: {sim_result.recommended_action.replace('_', ' ')} "
                f"(approval likelihood: {sim_result.approval_probability:.0%}, "
                f"dispute risk: {sim_result.dispute_risk:.0%}) ({stage_timings['simulation']:.1f}s)",
                "completed",
                {**sim_result.model_dump(), "_stage_time": stage_timings["simulation"]},
            )

            # ── Step 9: Pipeline complete ────────────────────────────────────
            stage_timings["total"] = time.monotonic() - pipeline_start
            await _emit(
                claim_id, "pipeline_complete",
                f"Processing complete. Status: {final_status}. "
                f"Awaiting {risk_assessment['recommended_action'].replace('_', ' ')}. "
                f"({stage_timings['total']:.1f}s total)",
                "completed",
                {"status": final_status, "recommended_action": risk_assessment["recommended_action"],
                 "stage_timings": stage_timings},
            )

            # Fire webhook: claim processing completed
            fire_event(
                EVENT_CLAIM_COMPLETED,
                {
                    "claim_id": claim_id,
                    "status": final_status,
                    "fraud_score": fraud_score.overall_score,
                    "risk_level": fraud_score.risk_level,
                    "recommended_action": risk_assessment["recommended_action"],
                    "payout_amount": payout_rec.recommended_amount,
                },
            )

            # Set summary attributes on the parent pipeline span
            pipeline_span.set_attribute("pipeline.final_status", final_status)
            pipeline_span.set_attribute("pipeline.fraud_score", fraud_score.overall_score)
            pipeline_span.set_attribute("pipeline.risk_level", fraud_score.risk_level)
            pipeline_span.set_attribute("pipeline.recommended_action", risk_assessment["recommended_action"])
            pipeline_span.set_attribute("pipeline.payout_amount", payout_rec.recommended_amount)
            pipeline_span.set_attribute("pipeline.total_time", stage_timings["total"])

        except Exception as exc:
            logger.exception("Pipeline error for %s: %s", claim_id, exc)
            record_exception(exc)
            pipeline_span.set_attribute("pipeline.final_status", "error")
            await update_claim(claim_id, status="error")
            await _emit(
                claim_id, "pipeline_error",
                f"Pipeline encountered an error: {exc}",
                "error",
                {"error": str(exc)},
            )
        finally:
            clear_threshold_state(claim_id)
            event_bus.complete(claim_id)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/submit", response_model=ClaimResponse)
async def submit_claim(
    file: UploadFile = File(...),
    claimant_name: str = Form(...),
    incident_description: str = Form(...),
    policy_number: str = Form(""),
) -> ClaimResponse:
    """Submit a new medical bill / EOB / denial for review. Starts the processing pipeline in background."""
    # Backpressure: reject if already at max concurrent pipelines
    if len(_running_tasks) >= MAX_CONCURRENT_PIPELINES:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Server is at capacity ({MAX_CONCURRENT_PIPELINES} concurrent pipelines). "
                "Please retry after 30 seconds."
            ),
            headers={"Retry-After": "30"},
        )

    # Step 1: Intake — save file and create DB record
    claim_data = await claim_intake_skill.execute(
        file=file,
        claimant_name=claimant_name,
        incident_description=incident_description,
        policy_number=policy_number,
    )

    # Fire webhook: claim submitted
    fire_event(
        EVENT_CLAIM_SUBMITTED,
        {
            "claim_id": claim_data.id,
            "claimant_name": claimant_name,
            "policy_number": policy_number,
            "status": "submitted",
        },
    )

    # Step 2: Kick off the background pipeline
    claim_record = (await get_claim(claim_data.id)) or claim_data.model_dump()
    task = asyncio.create_task(_run_pipeline(claim_data.id, claim_record))
    _running_tasks[claim_data.id] = task
    task.add_done_callback(lambda finished_task, cid=claim_data.id: _cleanup_running_task(cid, finished_task))

    return ClaimResponse(
        success=True,
        claim_id=claim_data.id,
        status="submitted",
        message="Claim submitted successfully. Processing pipeline started.",
        data=claim_data,
    )


@router.get("", response_model=list[dict[str, Any]])
async def get_all_claims() -> list[dict[str, Any]]:
    """List all claims."""
    return await list_claims()


@router.get("/{claim_id}")
async def get_claim_by_id(claim_id: str) -> dict[str, Any]:
    """Get full claim data by ID."""
    claim = await get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found.")
    return claim


@router.get("/{claim_id}/events")
async def stream_claim_events(claim_id: str) -> EventSourceResponse:
    """SSE endpoint — streams investigation events for a claim in real time."""
    await get_claim_by_id(claim_id)

    async def event_generator():
        # First, send any existing events from DB (handles reconnects)
        last_id = 0
        seen_types: set[str] = set()
        existing = await get_investigation_events(claim_id, after_id=0)
        for evt in existing:
            eid = evt["id"]
            seen_types.add(f"{eid}")
            yield {
                "id": str(eid),
                "data": json.dumps({
                    "event_type": evt["event_type"],
                    "message": evt["message"],
                    "status": evt["status"],
                    "data": evt.get("data"),
                    "timestamp": evt["timestamp"],
                }),
            }
            last_id = eid
            if evt["event_type"] in ("pipeline_complete", "pipeline_error"):
                return

        # Try event bus for near-instant delivery (replaces 300ms polling)
        if event_bus.has_active_queue(claim_id):
            async for event in event_bus.subscribe(claim_id):
                yield {
                    "data": json.dumps({
                        "event_type": event.get("event_type", "unknown"),
                        "message": event.get("message", ""),
                        "status": event.get("status", "info"),
                        "data": event.get("data"),
                        "timestamp": event.get("timestamp"),
                    }),
                }
                if event.get("event_type") in ("pipeline_complete", "pipeline_error"):
                    return
        else:
            # Fallback to DB polling for claims without an active event bus queue
            retries = 0
            max_idle_retries = 500
            terminal_statuses = ("approved", "auto_approved", "denied", "blocked", "error")
            while retries < max_idle_retries:
                new_events = await get_investigation_events(claim_id, after_id=last_id)
                if new_events:
                    retries = 0
                    for evt in new_events:
                        eid = evt["id"]
                        yield {
                            "id": str(eid),
                            "data": json.dumps({
                                "event_type": evt["event_type"],
                                "message": evt["message"],
                                "status": evt["status"],
                                "data": evt.get("data"),
                                "timestamp": evt["timestamp"],
                            }),
                        }
                        last_id = eid
                        if evt["event_type"] in ("pipeline_complete", "pipeline_error"):
                            return
                else:
                    retries += 1
                if retries % 10 == 0:
                    claim = await get_claim(claim_id)
                    if claim and claim.get("status") in terminal_statuses:
                        return
                await asyncio.sleep(0.3)

    return EventSourceResponse(event_generator())
