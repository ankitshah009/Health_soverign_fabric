"""Pydantic models for patient medical-billing cases.

Field NAMES are intentionally kept stable (the frontend and pipeline persist/read
them by name), but their MEANING is patient-side medical billing. Notably:
  - ExtractedData.damage_type      → document category (itemized_bill / EOB / denial_letter)
  - ExtractedData.estimated_cost   → total amount billed on the document
  - ExtractedData.vehicle_info     → (unused; kept for schema compatibility)
  - FraudScore.overall_score       → OVERCHARGE / billing-error SEVERITY (0=clean, 100=severe)
  - CoverageResult.coverage_limit  → the plan's out-of-pocket maximum
  - PayoutRecommendation.recommended_amount → dollars the PATIENT can recover
  - SimulationResult.approval_probability   → probability the patient's APPEAL succeeds
  - SimulationResult.fraud_escalation_likelihood → likelihood external escalation (regulator/NSA) is needed
  - claimant_name                  → the PATIENT's name
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ── Extracted Data (from Grok vision over the medical bill / EOB / denial) ────

class ExtractedData(BaseModel):
    damage_type: str = ""          # document category: itemized_bill / EOB / denial_letter
    estimated_cost: float = 0.0    # total amount billed on the document
    vehicle_info: str = ""         # unused; kept for schema/back-compat
    incident_details: str = ""     # plain-English summary of the document
    document_type: str = ""        # same document category as damage_type
    key_findings: list[str] = Field(default_factory=list)  # notable line items / codes / charges


# ── Overcharge / Billing-Error Signal (field names kept for compatibility) ────

class FraudSignal(BaseModel):
    signal_name: str               # e.g. duplicate_charge / upcoding / balance_billing
    description: str               # cites the line/code + estimated overcharge $ + fair-price benchmark
    severity: Severity = Severity.LOW
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class FraudScore(BaseModel):
    # overall_score is the OVERCHARGE / billing-error severity (0=clean, 100=severe overcharge)
    overall_score: float = Field(ge=0.0, le=100.0, default=0.0)
    risk_level: RiskLevel = RiskLevel.LOW
    signals: list[FraudSignal] = Field(default_factory=list)
    explanation: str = ""          # patient-facing ("you appear to have been overcharged...")


# ── Coverage (the patient's medical plan) ─────────────────────────────────────

class CoverageResult(BaseModel):
    policy_number: str = ""        # the patient's member/policy id
    coverage_type: str = ""        # e.g. PPO / HDHP / EPO (in-network)
    coverage_limit: float = 0.0    # the plan's out-of-pocket maximum
    deductible: float = 0.0
    covered: bool = False
    explanation: str = ""


# ── Recovery Estimate (field names kept for compatibility) ────────────────────

class PayoutRecommendation(BaseModel):
    recommended_amount: float = 0.0  # dollars the PATIENT can recover (overcharges + wrongful denial)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str = ""
    comparable_claims: list[str] = Field(default_factory=list)  # comparable patient dispute outcomes


# ── Simulation (appeal / billing-dispute outcome) ─────────────────────────────

class SimulationResult(BaseModel):
    approval_probability: float = 0.0          # probability the patient's appeal/dispute succeeds
    dispute_risk: float = 0.0                  # risk the insurer/provider resists the correction
    fraud_escalation_likelihood: float = 0.0   # likelihood external escalation (regulator/NSA) is needed
    financial_exposure: float = 0.0            # dollars at stake for the patient
    historical_comparison: str = ""
    recommended_action: str = ""               # file_appeal / negotiate_bill / request_itemization / file_nsa_complaint / pay_corrected_amount


# ── Case Submission (what the frontend sends) ────────────────────────────────
# Note: actual multipart parsing happens in the route; this is for docs.

class ClaimSubmission(BaseModel):
    claimant_name: str             # the patient's name
    incident_description: str      # what the bill / denial is about
    policy_number: str = ""        # the patient's insurance member/policy id


# ── Full Claim Record ────────────────────────────────────────────────────────

class ClaimData(BaseModel):
    id: str
    status: str = "submitted"
    claimant_name: str
    incident_description: str
    policy_number: str | None = None
    file_path: str | None = None
    file_type: str | None = None
    created_at: str = ""
    extracted_data: ExtractedData | dict[str, Any] | None = None
    fraud_score: float | None = None
    risk_level: str | None = None
    coverage_result: CoverageResult | dict[str, Any] | None = None
    payout_recommendation: PayoutRecommendation | dict[str, Any] | None = None
    simulation_result: SimulationResult | dict[str, Any] | None = None
    risk_assessment: dict[str, Any] | None = None
    decision: str | None = None
    decision_by: str | None = None
    decision_at: str | None = None
    receipt: dict[str, Any] | None = None


# ── API Response ──────────────────────────────────────────────────────────────

class ClaimResponse(BaseModel):
    success: bool = True
    claim_id: str
    status: str = "submitted"
    message: str = ""
    data: ClaimData | None = None
