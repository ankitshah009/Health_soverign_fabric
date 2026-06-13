"""Unit tests for YutoriService helpers."""

from __future__ import annotations

from app.models.claim import ExtractedData
from app.services.yutori_service import YutoriService


def _make_extracted_data(**overrides) -> ExtractedData:
    payload = {
        "damage_type": "vehicle collision",
        "estimated_cost": 7500.0,
        "vehicle_info": "2020 Toyota Camry",
        "incident_details": "Rear-end collision on Market Street.",
        "document_type": "damage photo",
        "key_findings": ["front bumper cracked"],
    }
    payload.update(overrides)
    return ExtractedData(**payload)


def test_pending_verification_results_includes_all_research_vectors():
    service = YutoriService()

    results = service.pending_verification_results(
        _make_extracted_data(),
        "Sarah Chen",
        incident_description="Rear-end collision on Market Street.",
    )

    assert len(results) == 5
    assert {result["entity_type"] for result in results} == {
        "claimant_history",
        "vehicle_property",
        "incident_corroboration",
        "repair_provider",
        "financial_stress",
    }
    assert all(result["status"] == "verification_pending" for result in results)


def test_pending_verification_results_uses_custom_summary():
    service = YutoriService()

    results = service.pending_verification_results(
        _make_extracted_data(vehicle_info="", incident_details=""),
        "Sarah Chen",
        summary="Verification timed out during live processing. Research is still pending.",
    )

    assert len(results) == 4
    assert all(
        result["results"]["summary"] == "Verification timed out during live processing. Research is still pending."
        for result in results
    )
