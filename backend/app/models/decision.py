"""Pydantic models for decisions, approvals, and audit entries."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DecisionType(str, Enum):
    APPROVE = "approve"
    DENY = "deny"
    ESCALATE = "escalate"


class ApprovalRequest(BaseModel):
    claim_id: str
    decision: DecisionType
    approver_name: str
    notes: str = ""


class DecisionReceipt(BaseModel):
    receipt_id: str
    claim_id: str
    action: str
    requested_by: str = "system"
    approved_by: str
    identity_confidence: float = 0.0
    fraud_score: float = 0.0
    policy_check: str = ""
    simulation_summary: str = ""
    payout_amount: float = 0.0
    timestamp: str = ""
    # Legacy field kept for backwards compatibility with existing data
    signature_hash: str = ""
    # Ed25519 signature fields
    signature: str = ""
    public_key: str = ""
    signature_algorithm: str = ""
    signing_key_id: str = ""


class AuditEntry(BaseModel):
    claim_id: str
    action: str
    actor: str = "system"
    details: dict[str, Any] | str | None = None
    timestamp: str = ""
