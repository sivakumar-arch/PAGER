"""Unit tests for ConflictResolver.

Tests all 5 resolution strategies, weight validation, tie-breaking,
per-query overrides, and round-robin rotation.
"""

import pytest

from src.pager.conflict_resolver import ConflictResolver, VALID_STRATEGIES


@pytest.fixture
def resolver_weighted() -> ConflictResolver:
    return ConflictResolver(default_strategy="weighted")


@pytest.fixture
def resolver_cost() -> ConflictResolver:
    return ConflictResolver(default_strategy="cost_aware")


@pytest.fixture
def resolver_latency() -> ConflictResolver:
    return ConflictResolver(default_strategy="latency_aware")


@pytest.fixture
def resolver_quality() -> ConflictResolver:
    return ConflictResolver(default_strategy="quality_aware")


@pytest.fixture
def resolver_rr() -> ConflictResolver:
    return ConflictResolver(default_strategy="round_robin")


class TestInitialization:
    """Tests for ConflictResolver initialization and validation."""

    def test_valid_strategies_accepted(self):
        for strategy in VALID_STRATEGIES:
            resolver = ConflictResolver(default_strategy=strategy)
            assert resolver.default_strategy == strategy

    def test_invalid_strategy_raises(self):
        with pytest.raises(ValueError, match="Invalid strategy"):
            ConflictResolver(default_strategy="random")

    def test_weights_must_sum_to_one(self):
        with pytest.raises(ValueError, match="must sum to 1.0"):
            ConflictResolver(
                default_strategy="weighted",
                cost_weight=0.5,
                latency_weight=0.5,
                quality_weight=0.5,  # sum = 1.5
            )

    def test_default_weights_valid(self):
        resolver = ConflictResolver()
        assert abs(resolver.cost_weight + resolver.latency_weight + resolver.quality_weight - 1.0) < 1e-6


class TestSingleCandidate:
    """Tests for single compliant agent (no actual conflict)."""

    def test_single_agent_selected_immediately(
        self, resolver_weighted, agent_demographics, policy_result_single_compliant
    ):
        result = resolver_weighted.resolve(
            candidates=[agent_demographics],
            policy_result=policy_result_single_compliant,
        )
        assert result.selected_agent_id == "patient_demographics_agent"
        assert result.had_conflict is False

    def test_single_agent_reason_explains_no_conflict(
        self, resolver_weighted, agent_demographics, policy_result_single_compliant
    ):
        result = resolver_weighted.resolve(
            candidates=[agent_demographics],
            policy_result=policy_result_single_compliant,
        )
        assert "Only one compliant agent" in result.selection_reason


class TestCostAwareStrategy:
    """Tests for cost_aware strategy."""

    def test_selects_cheapest_agent(
        self, resolver_cost, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        # demographics: $0.02, labs: $0.04 → demographics wins
        result = resolver_cost.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        assert result.selected_agent_id == "patient_demographics_agent"

    def test_reason_mentions_cost(
        self, resolver_cost, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        result = resolver_cost.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        assert "cost" in result.selection_reason.lower()
        assert "cost_aware" in result.strategy_used


class TestLatencyAwareStrategy:
    """Tests for latency_aware strategy."""

    def test_selects_fastest_agent(
        self, resolver_latency, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        # demographics: 80ms, labs: 120ms → demographics wins
        result = resolver_latency.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        assert result.selected_agent_id == "patient_demographics_agent"

    def test_reason_mentions_latency(
        self, resolver_latency, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        result = resolver_latency.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        assert "latency" in result.selection_reason.lower()


class TestQualityAwareStrategy:
    """Tests for quality_aware strategy."""

    def test_selects_highest_quality_agent(
        self, resolver_quality, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        # demographics: 0.92, labs: 0.95 → labs wins
        result = resolver_quality.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        assert result.selected_agent_id == "labs_agent"


class TestWeightedStrategy:
    """Tests for weighted composite strategy."""

    def test_weighted_produces_valid_result(
        self, resolver_weighted, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        result = resolver_weighted.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        assert result.selected_agent_id in ["patient_demographics_agent", "labs_agent"]
        assert result.strategy_used == "weighted"

    def test_weighted_scores_populated(
        self, resolver_weighted, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        result = resolver_weighted.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        assert len(result.agent_scores) == 2
        assert result.agent_scores[0].rank == 1
        assert result.agent_scores[1].rank == 2

    def test_cost_heavy_weights_prefer_cheaper(self, agent_demographics, agent_labs, policy_result_multi_compliant):
        """Cost-heavy config (0.6/0.2/0.2) should prefer the cheaper agent."""
        resolver = ConflictResolver(
            default_strategy="weighted",
            cost_weight=0.6,
            latency_weight=0.2,
            quality_weight=0.2,
        )
        result = resolver.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        # demographics is cheaper ($0.02 vs $0.04) and faster (80ms vs 120ms)
        assert result.selected_agent_id == "patient_demographics_agent"


class TestRoundRobinStrategy:
    """Tests for round_robin strategy."""

    def test_round_robin_rotates(
        self, agent_demographics, agent_labs, policy_result_multi_compliant
    ):
        resolver = ConflictResolver(default_strategy="round_robin")
        first = resolver.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        ).selected_agent_id

        second = resolver.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        ).selected_agent_id

        # Two consecutive calls should select different agents
        assert first != second

    def test_round_robin_cycles_back(
        self, agent_demographics, agent_labs, policy_result_multi_compliant
    ):
        resolver = ConflictResolver(default_strategy="round_robin")
        first = resolver.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        ).selected_agent_id
        # Skip second
        resolver.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        )
        third = resolver.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
        ).selected_agent_id
        assert first == third


class TestStrategyOverride:
    """Tests for per-query strategy overrides."""

    def test_override_changes_strategy(
        self, resolver_weighted, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        result = resolver_weighted.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
            strategy_override="quality_aware",
        )
        assert result.strategy_used == "quality_aware"
        assert result.strategy_overridden is True

    def test_invalid_override_falls_back(
        self, resolver_weighted, agent_demographics, agent_labs,
        policy_result_multi_compliant
    ):
        result = resolver_weighted.resolve(
            candidates=[agent_demographics, agent_labs],
            policy_result=policy_result_multi_compliant,
            strategy_override="invalid_strategy",
        )
        assert result.strategy_used == "weighted"
        assert result.strategy_overridden is False


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_no_compliant_agents_raises(self, resolver_weighted, agent_demographics):
        from src.models.policy_result import PolicyEvaluationResult
        empty_result = PolicyEvaluationResult(
            compliant_agents=[],
            total_agents_evaluated=1,
        )
        with pytest.raises(ValueError, match="No compliant agents"):
            resolver_weighted.resolve(
                candidates=[agent_demographics],
                policy_result=empty_result,
            )
