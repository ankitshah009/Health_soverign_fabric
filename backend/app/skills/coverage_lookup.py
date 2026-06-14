"""Coverage Lookup Skill — mock MEDICAL insurance plan lookup for demo purposes.

Given a patient's plan id and the kind of care on the bill, returns what their
plan actually covers and what the patient *should* truly owe (deductible +
coinsurance, capped at the out-of-pocket max). The point for the patient: the
care is almost always covered, so a denial of it is usually appealable, and
anything billed above their true cost-share is disputable.
"""

from __future__ import annotations

import logging

from app.models.claim import CoverageResult

logger = logging.getLogger(__name__)

SKILL_METADATA = {
    "skill_name": "coverage_lookup_skill",
    "action_category": "bill_review",
    "read_or_write": "read",
    "money_movement": False,
    "reversible": True,
}

# Service categories a typical major-medical plan covers. A real itemized bill,
# EOB, or denial letter is almost always for one of these.
_COVERED_SERVICES = [
    "emergency", "emergency room", "er visit", "er", "hospital", "hospitalization",
    "inpatient", "outpatient", "surgery", "surgical", "anesthesia", "imaging",
    "radiology", "ct", "mri", "x-ray", "xray", "laboratory", "lab", "diagnostic",
    "office visit", "specialist", "primary care", "urgent care", "ambulance",
    "physical therapy", "maternity", "prescription", "itemized_bill", "eob",
    "denial_letter", "medical", "bill", "statement",
]

# Clear plan exclusions (the rare "not covered" case).
_EXCLUSIONS = ("cosmetic", "elective cosmetic", "experimental", "investigational")

# ── Mock medical plan database (keyed by member / policy id) ─────────────────

MOCK_PLANS: dict[str, dict] = {
    "BCBS-PPO-2026": {
        "policy_number": "BCBS-PPO-2026",
        "coverage_type": "PPO (in-network)",
        "coverage_limit": 9450.00,   # individual out-of-pocket maximum
        "deductible": 1500.00,
        "coinsurance": 0.20,
        "holder_name": "Blue Cross PPO",
    },
    "AETNA-HDHP-2026": {
        "policy_number": "AETNA-HDHP-2026",
        "coverage_type": "HDHP + HSA (in-network)",
        "coverage_limit": 7050.00,
        "deductible": 3000.00,
        "coinsurance": 0.10,
        "holder_name": "Aetna HDHP",
    },
    "UHC-EPO-2026": {
        "policy_number": "UHC-EPO-2026",
        "coverage_type": "EPO (in-network)",
        "coverage_limit": 8700.00,
        "deductible": 2000.00,
        "coinsurance": 0.20,
        "holder_name": "UnitedHealthcare EPO",
    },
}

# Default plan for any unknown member id — a typical ACA major-medical plan.
_DEFAULT_PLAN = {
    "policy_number": "MEMBER",
    "coverage_type": "PPO (in-network)",
    "coverage_limit": 9100.00,   # ACA individual out-of-pocket max (ballpark)
    "deductible": 1600.00,
    "coinsurance": 0.20,
    "holder_name": "Major Medical Plan",
}


def _normalize_policy_number(policy_number: str) -> str:
    """Normalize member ids so demo-friendly variants still match."""
    return "".join(ch for ch in policy_number.upper() if ch.isalnum())


_NORMALIZED_PLAN_KEYS = {
    _normalize_policy_number(plan_key): plan_key for plan_key in MOCK_PLANS
}


def _is_service_covered(service: str) -> bool:
    """A medical bill/EOB/denial is for covered care unless clearly excluded."""
    s = (service or "").lower()
    if any(x in s for x in _EXCLUSIONS):
        return False
    if not s.strip():
        return True
    for covered in _COVERED_SERVICES:
        if covered in s or s in covered:
            return True
        if set(covered.split()) & set(s.split()):
            return True
    # Default: a real medical bill is for covered care.
    return True


class CoverageLookupSkill:
    """Looks up the patient's medical plan coverage for a bill."""

    async def execute(
        self,
        policy_number: str,
        damage_type: str,         # now: the service category / document type on the bill
        estimated_cost: float,
    ) -> CoverageResult:
        policy_number = (policy_number or "").strip().upper()
        normalized = _normalize_policy_number(policy_number)
        canonical_key = _NORMALIZED_PLAN_KEYS.get(normalized, policy_number)
        fallback = {**_DEFAULT_PLAN, "policy_number": policy_number or _DEFAULT_PLAN["policy_number"]}
        plan = MOCK_PLANS.get(canonical_key, fallback)

        service = damage_type or "medical care"
        is_covered = _is_service_covered(service)
        deductible = plan["deductible"]
        coinsurance = plan.get("coinsurance", 0.20)
        oop_max = plan["coverage_limit"]

        if is_covered:
            # Patient's true responsibility = deductible + coinsurance on the
            # remainder, capped at the out-of-pocket maximum.
            if estimated_cost > 0:
                after_deductible = max(0.0, estimated_cost - deductible)
                patient_owes = min(oop_max, deductible + after_deductible * coinsurance)
            else:
                patient_owes = 0.0
            explanation = (
                f"Plan {plan['policy_number']} ({plan['coverage_type']}): this care IS covered. "
                f"Deductible ${deductible:,.0f}, {int(coinsurance * 100)}% coinsurance, "
                f"out-of-pocket max ${oop_max:,.0f}. On a ${estimated_cost:,.0f} bill the patient's "
                f"true responsibility is about ${patient_owes:,.0f} — anything billed above that is "
                f"disputable, and a denial of covered care is appealable."
            )
        else:
            explanation = (
                f"Plan {plan['policy_number']} ({plan['coverage_type']}): this service may fall under "
                f"a plan exclusion (e.g., cosmetic or experimental). Request the plan's written "
                f"coverage determination and the specific exclusion cited before paying anything."
            )

        logger.info(
            "Coverage lookup: %s | service=%s | covered=%s",
            policy_number, service, is_covered,
        )

        return CoverageResult(
            policy_number=plan["policy_number"],
            coverage_type=plan["coverage_type"],
            coverage_limit=oop_max,
            deductible=deductible,
            covered=is_covered,
            explanation=explanation,
        )


# Module-level singleton
coverage_lookup_skill = CoverageLookupSkill()
