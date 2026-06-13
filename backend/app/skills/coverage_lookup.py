"""Coverage Lookup Skill — mock policy database for demo purposes."""

from __future__ import annotations

import logging

from app.models.claim import CoverageResult

logger = logging.getLogger(__name__)

SKILL_METADATA = {
    "skill_name": "coverage_lookup_skill",
    "action_category": "claims_processing",
    "read_or_write": "read",
    "money_movement": False,
    "reversible": True,
}

# ── Mock Policy Database ──────────────────────────────────────────────────────

MOCK_POLICIES: dict[str, dict] = {
    "AUTO-12345": {
        "policy_number": "AUTO-12345",
        "coverage_type": "comprehensive_auto",
        "coverage_limit": 50000.00,
        "deductible": 500.00,
        "covered_damages": [
            "vehicle collision", "bumper damage", "parking lot damage",
            "theft", "vandalism", "weather damage", "fire damage",
            "animal collision", "front bumper", "rear bumper",
            "fender bender", "collision", "dent", "scratch",
        ],
        "holder_name": "John Smith - Comprehensive Auto",
    },
    "HOME-67890": {
        "policy_number": "HOME-67890",
        "coverage_type": "homeowners",
        "coverage_limit": 350000.00,
        "deductible": 1000.00,
        "covered_damages": [
            "fire damage", "water damage", "theft", "vandalism",
            "weather damage", "structural damage", "roof damage",
            "flooding", "pipe burst",
        ],
        "holder_name": "Jane Doe - Premium Homeowners",
    },
    "POL-001": {
        "policy_number": "POL-001",
        "coverage_type": "comprehensive_auto",
        "coverage_limit": 50000.00,
        "deductible": 500.00,
        "covered_damages": [
            "vehicle collision", "theft", "vandalism", "weather damage",
            "fire damage", "animal collision",
        ],
        "holder_name": "Standard Auto Policy",
    },
    "POL-002": {
        "policy_number": "POL-002",
        "coverage_type": "homeowners",
        "coverage_limit": 250000.00,
        "deductible": 1000.00,
        "covered_damages": [
            "fire damage", "water damage", "theft", "vandalism",
            "weather damage", "structural damage",
        ],
        "holder_name": "Premium Homeowners Policy",
    },
    "POL-003": {
        "policy_number": "POL-003",
        "coverage_type": "liability_auto",
        "coverage_limit": 25000.00,
        "deductible": 250.00,
        "covered_damages": [
            "vehicle collision", "property damage", "bodily injury",
        ],
        "holder_name": "Basic Liability Auto",
    },
    "POL-004": {
        "policy_number": "POL-004",
        "coverage_type": "commercial_property",
        "coverage_limit": 500000.00,
        "deductible": 2500.00,
        "covered_damages": [
            "fire damage", "water damage", "theft", "vandalism",
            "structural damage", "equipment damage", "business interruption",
        ],
        "holder_name": "Commercial Property Premier",
    },
    "POL-005": {
        "policy_number": "POL-005",
        "coverage_type": "health",
        "coverage_limit": 100000.00,
        "deductible": 750.00,
        "covered_damages": [
            "medical injury", "hospitalization", "surgery",
            "emergency care", "rehabilitation",
        ],
        "holder_name": "Health Plus Policy",
    },
    "POL-006": {
        "policy_number": "POL-006",
        "coverage_type": "renters",
        "coverage_limit": 30000.00,
        "deductible": 500.00,
        "covered_damages": [
            "theft", "fire damage", "water damage", "vandalism",
            "personal property loss",
        ],
        "holder_name": "Renters Essential Policy",
    },
    # ── Demo claim policies ──────────────────────────────────────────
    "POL-2024-447231": {
        "policy_number": "POL-2024-447231",
        "coverage_type": "comprehensive_auto",
        "coverage_limit": 50000.00,
        "deductible": 500.00,
        "covered_damages": [
            "vehicle collision", "bumper damage", "front-end damage",
            "fender damage", "theft", "vandalism", "weather damage",
            "fire damage", "animal collision", "collision", "hit and run",
        ],
        "holder_name": "Sarah Chen",
    },
    "POL-2024-47721": {
        "policy_number": "POL-2024-47721",
        "coverage_type": "comprehensive_auto",
        "coverage_limit": 50000.00,
        "deductible": 500.00,
        "covered_damages": [
            "vehicle collision", "bumper damage", "front-end damage",
            "fender damage", "theft", "vandalism", "weather damage",
            "fire damage", "animal collision", "collision", "hit and run",
        ],
        "holder_name": "Sarah Chen",
    },
    "POL-2024-881093": {
        "policy_number": "POL-2024-881093",
        "coverage_type": "standard_auto",
        "coverage_limit": 35000.00,
        "deductible": 750.00,
        "covered_damages": [
            "vehicle collision", "door damage", "mirror damage",
            "quarter panel damage", "hit and run", "parking damage",
            "vandalism", "theft", "collision",
        ],
        "holder_name": "Marcus Rivera",
    },
    "POL-2025-102847": {
        "policy_number": "POL-2025-102847",
        "coverage_type": "premium_auto",
        "coverage_limit": 75000.00,
        "deductible": 1000.00,
        "covered_damages": [
            "vehicle collision", "hood damage", "door damage",
            "roof damage", "quarter panel damage", "hit and run",
            "theft", "vandalism", "weather damage", "collision",
        ],
        "holder_name": "Derek Thompson",
    },
}

# Default fallback policy for unknown policy numbers
_DEFAULT_POLICY = {
    "policy_number": "UNKNOWN",
    "coverage_type": "general",
    "coverage_limit": 25000.00,
    "deductible": 500.00,
    "covered_damages": [
        "vehicle collision", "fire damage", "water damage", "theft",
    ],
    "holder_name": "Default Coverage",
}


def _normalize_policy_number(policy_number: str) -> str:
    """Normalize policy IDs so demo-friendly variants still match."""
    return "".join(ch for ch in policy_number.upper() if ch.isalnum())


_NORMALIZED_POLICY_KEYS = {
    _normalize_policy_number(policy_key): policy_key
    for policy_key in MOCK_POLICIES
}


def _is_damage_covered(policy: dict, damage_type: str) -> bool:
    """Check if a damage type is covered by fuzzy matching against policy."""
    damage_lower = damage_type.lower()
    for covered in policy["covered_damages"]:
        if covered in damage_lower or damage_lower in covered:
            return True
        # Partial word matching
        covered_words = set(covered.split())
        damage_words = set(damage_lower.split())
        if covered_words & damage_words:
            return True
    return False


class CoverageLookupSkill:
    """Looks up policy coverage for a claim."""

    async def execute(
        self,
        policy_number: str,
        damage_type: str,
        estimated_cost: float,
    ) -> CoverageResult:
        policy_number = (policy_number or "").strip().upper()
        normalized_policy_number = _normalize_policy_number(policy_number)
        canonical_key = _NORMALIZED_POLICY_KEYS.get(normalized_policy_number, policy_number)
        fallback_policy = {
            **_DEFAULT_POLICY,
            "policy_number": policy_number or _DEFAULT_POLICY["policy_number"],
        }
        policy = MOCK_POLICIES.get(canonical_key, fallback_policy)

        is_covered = _is_damage_covered(policy, damage_type)

        if not is_covered:
            explanation = (
                f"The damage type '{damage_type}' is not covered under "
                f"policy {policy['policy_number']} ({policy['coverage_type']}). "
                f"Covered damage types: {', '.join(policy['covered_damages'])}."
            )
        elif estimated_cost > policy["coverage_limit"]:
            explanation = (
                f"Damage type '{damage_type}' is covered. However, the estimated cost "
                f"(${estimated_cost:,.2f}) exceeds the coverage limit "
                f"(${policy['coverage_limit']:,.2f}). Maximum payout after deductible: "
                f"${policy['coverage_limit'] - policy['deductible']:,.2f}."
            )
        else:
            net_payout = max(0, estimated_cost - policy["deductible"])
            explanation = (
                f"Damage type '{damage_type}' is fully covered under "
                f"policy {policy['policy_number']} ({policy['coverage_type']}). "
                f"Estimated cost: ${estimated_cost:,.2f}. "
                f"After deductible (${policy['deductible']:,.2f}): ${net_payout:,.2f} eligible."
            )

        logger.info(
            "Coverage lookup: %s | %s | covered=%s",
            policy_number, damage_type, is_covered,
        )

        return CoverageResult(
            policy_number=policy["policy_number"],
            coverage_type=policy["coverage_type"],
            coverage_limit=policy["coverage_limit"],
            deductible=policy["deductible"],
            covered=is_covered,
            explanation=explanation,
        )


# Module-level singleton
coverage_lookup_skill = CoverageLookupSkill()
