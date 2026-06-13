"""Pydantic models for insurance claims data."""

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


# ── Extracted Data (from Grok vision) ────────────────────────────────────────

class ExtractedData(BaseModel):
    damage_type: str = ""
    estimated_cost: float = 0.0
    vehicle_info: str = ""
    incident_details: str = ""
    document_type: str = ""
    key_findings: list[str] = Field(default_factory=list)


# ── Fraud ─────────────────────────────────────────────────────────────────────

class FraudSignal(BaseModel):
    signal_name: str
    description: str
    severity: Severity = Severity.LOW
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


class FraudScore(BaseModel):
    overall_score: float = Field(ge=0.0, le=100.0, default=0.0)
    risk_level: RiskLevel = RiskLevel.LOW
    signals: list[FraudSignal] = Field(default_factory=list)
    explanation: str = ""


# ── Coverage ──────────────────────────────────────────────────────────────────

class CoverageResult(BaseModel):
    policy_number: str = ""
    coverage_type: str = ""
    coverage_limit: float = 0.0
    deductible: float = 0.0
    covered: bool = False
    explanation: str = ""


# ── Payout ────────────────────────────────────────────────────────────────────

class PayoutRecommendation(BaseModel):
    recommended_amount: float = 0.0
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    rationale: str = ""
    comparable_claims: list[str] = Field(default_factory=list)


# ── Simulation ────────────────────────────────────────────────────────────────

class SimulationResult(BaseModel):
    approval_probability: float = 0.0
    dispute_risk: float = 0.0
    fraud_escalation_likelihood: float = 0.0
    financial_exposure: float = 0.0
    historical_comparison: str = ""
    recommended_action: str = ""


# ── Claim Submission (what the frontend sends) ───────────────────────────────
# Note: actual multipart parsing happens in the route; this is for docs.

class ClaimSubmission(BaseModel):
    claimant_name: str
    incident_description: str
    policy_number: str = ""


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
