"""Unit tests for the CoverageLookupSkill and supporting helpers.

All tests exercise pure in-process logic against the mock policy database;
no external services or mocks are required.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.skills.coverage_lookup import (
    CoverageLookupSkill,
    _is_damage_covered,
    MOCK_POLICIES,
    _DEFAULT_POLICY,
)
from app.models.claim import CoverageResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def skill() -> CoverageLookupSkill:
    return CoverageLookupSkill()


# ---------------------------------------------------------------------------
# _is_damage_covered — unit tests (pure function, no async)
# ---------------------------------------------------------------------------

class TestIsDamageCovered:
    def test_exact_match_in_covered_list(self):
        policy = MOCK_POLICIES["AUTO-12345"]
        assert _is_damage_covered(policy, "theft") is True

    def test_substring_match_damage_in_covered(self):
        # "collision" is in the covered_damages list of AUTO-12345 as "collision"
        policy = MOCK_POLICIES["AUTO-12345"]
        assert _is_damage_covered(policy, "collision") is True

    def test_substring_match_covered_in_damage(self):
        # "vehicle collision" is in AUTO-12345; the broader string contains it
        policy = MOCK_POLICIES["AUTO-12345"]
        assert _is_damage_covered(policy, "major vehicle collision on highway") is True

    def test_partial_word_match(self):
        # "fire" word shared between "fire damage" (covered) and "fire"
        policy = MOCK_POLICIES["HOME-67890"]
        assert _is_damage_covered(policy, "fire") is True

    def test_case_insensitive(self):
        policy = MOCK_POLICIES["AUTO-12345"]
        assert _is_damage_covered(policy, "VANDALISM") is True

    def test_not_covered_returns_false(self):
        # HOME-67890 does not cover "vehicle collision"
        policy = MOCK_POLICIES["HOME-67890"]
        assert _is_damage_covered(policy, "vehicle collision") is False

    def test_completely_unrelated_damage_returns_false(self):
        # "earthquake" has no word overlap with any AUTO-12345 covered damage.
        # Note: "damage" alone would word-match "bumper damage" etc., so we use
        # a string with no shared words at all.
        policy = MOCK_POLICIES["AUTO-12345"]
        assert _is_damage_covered(policy, "earthquake") is False


# ---------------------------------------------------------------------------
# CoverageLookupSkill.execute — async tests
# ---------------------------------------------------------------------------

class TestCoverageLookupSkillExecute:

    # -- AUTO-12345 covered cases --

    @pytest.mark.asyncio
    async def test_known_policy_matching_damage_covered_true(self, skill):
        result = await skill.execute("AUTO-12345", "vehicle collision", 3000.00)
        assert isinstance(result, CoverageResult)
        assert result.covered is True
        assert result.policy_number == "AUTO-12345"
        assert result.coverage_type == "comprehensive_auto"

    @pytest.mark.asyncio
    async def test_known_policy_matching_damage_explanation_contains_payout(self, skill):
        result = await skill.execute("AUTO-12345", "vehicle collision", 3000.00)
        # Net payout = 3000 - 500 deductible = 2500
        assert "2,500.00" in result.explanation

    @pytest.mark.asyncio
    async def test_known_policy_non_matching_damage_covered_false(self, skill):
        # AUTO-12345 does not cover "flooding"
        result = await skill.execute("AUTO-12345", "flooding", 1000.00)
        assert result.covered is False
        assert result.policy_number == "AUTO-12345"

    @pytest.mark.asyncio
    async def test_known_policy_non_matching_damage_explanation_mentions_not_covered(self, skill):
        # "flooding" has no word overlap with AUTO-12345 covered damages.
        result = await skill.execute("AUTO-12345", "flooding", 5000.00)
        assert result.covered is False
        # Explanation should mention the damage type
        assert "flooding" in result.explanation

    # -- Default fallback for unknown policy --

    @pytest.mark.asyncio
    async def test_unknown_policy_uses_default_fallback(self, skill):
        result = await skill.execute("NONEXISTENT-99999", "fire damage", 1000.00)
        # _DEFAULT_POLICY covers "fire damage"
        assert result.covered is True
        assert result.policy_number == "NONEXISTENT-99999"

    @pytest.mark.asyncio
    async def test_empty_policy_number_uses_default_fallback(self, skill):
        result = await skill.execute("", "theft", 500.00)
        assert result.policy_number == "UNKNOWN"
        assert result.covered is True

    @pytest.mark.asyncio
    async def test_whitespace_policy_number_stripped_and_uses_default(self, skill):
        result = await skill.execute("   ", "fire damage", 200.00)
        assert result.policy_number == "UNKNOWN"

    # -- Fuzzy matching --

    @pytest.mark.asyncio
    async def test_fuzzy_match_collision_matches_vehicle_collision(self, skill):
        # "collision" alone should match "vehicle collision" via word overlap
        result = await skill.execute("AUTO-12345", "collision", 2000.00)
        assert result.covered is True

    @pytest.mark.asyncio
    async def test_fuzzy_match_bumper_matches_front_bumper(self, skill):
        result = await skill.execute("AUTO-12345", "bumper", 800.00)
        assert result.covered is True

    @pytest.mark.asyncio
    async def test_fuzzy_match_case_insensitive_fire_damage(self, skill):
        result = await skill.execute("HOME-67890", "FIRE DAMAGE", 5000.00)
        assert result.covered is True

    # -- Cost exceeds coverage limit --

    @pytest.mark.asyncio
    async def test_cost_exceeds_coverage_limit_explanation_mentions_limit(self, skill):
        # AUTO-12345 limit is 50,000; send 60,000
        result = await skill.execute("AUTO-12345", "vehicle collision", 60000.00)
        assert result.covered is True
        assert "coverage limit" in result.explanation.lower() or "exceeds" in result.explanation.lower()

    @pytest.mark.asyncio
    async def test_cost_exceeds_limit_explanation_contains_limit_value(self, skill):
        result = await skill.execute("AUTO-12345", "vehicle collision", 60000.00)
        # Limit is 50,000
        assert "50,000.00" in result.explanation

    @pytest.mark.asyncio
    async def test_cost_exceeds_limit_explanation_contains_max_payout(self, skill):
        # Max payout = limit - deductible = 50000 - 500 = 49500
        result = await skill.execute("AUTO-12345", "vehicle collision", 60000.00)
        assert "49,500.00" in result.explanation

    # -- HOME-67890 fire damage --

    @pytest.mark.asyncio
    async def test_home_67890_fire_damage_covered_true(self, skill):
        result = await skill.execute("HOME-67890", "fire damage", 10000.00)
        assert result.covered is True
        assert result.policy_number == "HOME-67890"
        assert result.coverage_type == "homeowners"

    @pytest.mark.asyncio
    async def test_home_67890_fire_damage_coverage_limit(self, skill):
        result = await skill.execute("HOME-67890", "fire damage", 10000.00)
        assert result.coverage_limit == 350000.00
        assert result.deductible == 1000.00

    @pytest.mark.asyncio
    async def test_home_67890_fire_damage_net_payout_in_explanation(self, skill):
        # Net = 10000 - 1000 deductible = 9000
        result = await skill.execute("HOME-67890", "fire damage", 10000.00)
        assert "9,000.00" in result.explanation

    # -- Policy number normalisation (lowercase input) --

    @pytest.mark.asyncio
    async def test_policy_number_normalised_to_uppercase(self, skill):
        result = await skill.execute("auto-12345", "theft", 500.00)
        assert result.policy_number == "AUTO-12345"
        assert result.covered is True

    @pytest.mark.asyncio
    async def test_policy_number_matches_hyphenless_realistic_demo_id(self, skill):
        result = await skill.execute("pol202447721", "vehicle collision", 5000.00)
        assert result.policy_number == "POL-2024-47721"
        assert result.covered is True

    # -- Return type is always CoverageResult --

    @pytest.mark.asyncio
    async def test_returns_coverage_result_instance(self, skill):
        result = await skill.execute("POL-001", "theft", 1000.00)
        assert isinstance(result, CoverageResult)

    # -- Coverage limit and deductible values --

    @pytest.mark.asyncio
    async def test_coverage_result_contains_correct_limit_and_deductible(self, skill):
        result = await skill.execute("AUTO-12345", "dent", 200.00)
        assert result.coverage_limit == 50000.00
        assert result.deductible == 500.00

    # -- Cost below deductible: net payout is 0 --

    @pytest.mark.asyncio
    async def test_cost_below_deductible_net_payout_zero(self, skill):
        # Cost 100 < deductible 500 → net = max(0, 100-500) = 0
        result = await skill.execute("AUTO-12345", "scratch", 100.00)
        assert result.covered is True
        assert "0.00" in result.explanation
