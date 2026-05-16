"""ConflictResolver: Selects optimal agent from policy-compliant candidates.

Implements 5 configurable strategies for agent selection when multiple
candidates pass all policy constraints. Each strategy is deterministic
and fully auditable.

Design rationale (Section 4.5):
    Multiple strategies demonstrate framework flexibility and enable
    comparative evaluation. Per-query override supports context-dependent
    routing (e.g. critical queries prioritize quality over cost).

    Weights are fully configurable per deployment context. For general
    enterprise evaluation, we use w_c=0.4, w_l=0.3, w_q=0.3, reflecting
    typical enterprise priorities where cost efficiency is primary.
    See Section 6.3 for sensitivity analysis across weight configurations.
"""

from src.models.agent import Agent
from src.models.policy_result import PolicyEvaluationResult
from src.models.resolution import AgentScore, ResolutionResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Valid strategy names
VALID_STRATEGIES = frozenset(
    {"cost_aware", "latency_aware", "quality_aware", "weighted", "round_robin"}
)


class ConflictResolver:
    """Resolves agent selection conflicts using configurable strategies.

    When PolicyEngine returns multiple compliant agents, ConflictResolver
    applies a scoring strategy to select the single best candidate.

    Strategies:
        cost_aware:     Minimize cost_per_query
        latency_aware:  Minimize avg_latency_ms
        quality_aware:  Maximize quality_score
        weighted:       Composite of cost + latency + quality (configurable weights)
        round_robin:    Rotate across agents for load distribution

    Usage:
        resolver = ConflictResolver(default_strategy="weighted")
        result = resolver.resolve(candidates, policy_result)
    """

    def __init__(
        self,
        default_strategy: str = "weighted",
        cost_weight: float = 0.4,
        latency_weight: float = 0.3,
        quality_weight: float = 0.3,
    ) -> None:
        """Initialize ConflictResolver with strategy and weights.

        Args:
            default_strategy: Strategy to use when no per-query override given.
            cost_weight: Weight for cost in weighted strategy (w_c).
            latency_weight: Weight for latency in weighted strategy (w_l).
            quality_weight: Weight for quality in weighted strategy (w_q).

        Raises:
            ValueError: If strategy is invalid or weights don't sum to ~1.0.
        """
        if default_strategy not in VALID_STRATEGIES:
            raise ValueError(
                f"Invalid strategy {default_strategy!r}. "
                f"Must be one of: {sorted(VALID_STRATEGIES)}"
            )

        weight_sum = cost_weight + latency_weight + quality_weight
        if not (0.99 <= weight_sum <= 1.01):
            raise ValueError(
                f"Weighted strategy weights must sum to 1.0, got {weight_sum:.3f}"
            )

        self.default_strategy = default_strategy
        self.cost_weight = cost_weight
        self.latency_weight = latency_weight
        self.quality_weight = quality_weight
        self._round_robin_index: int = 0

        logger.info(
            "ConflictResolver initialized",
            strategy=default_strategy,
            weights=f"cost={cost_weight}/lat={latency_weight}/qual={quality_weight}",
        )

    def resolve(
        self,
        candidates: list[Agent],
        policy_result: PolicyEvaluationResult,
        strategy_override: str | None = None,
    ) -> ResolutionResult:
        """Select the best agent from policy-compliant candidates.

        Args:
            candidates: Full agent list from AgentRegistry.
            policy_result: Output of PolicyEngine with compliant agent IDs.
            strategy_override: Per-query strategy override (optional).

        Returns:
            ResolutionResult with selected agent and audit trail.

        Raises:
            ValueError: If no compliant agents are available.
        """
        # Filter to compliant candidates only
        compliant_ids = set(policy_result.compliant_agents)
        compliant = [a for a in candidates if a.id in compliant_ids]

        if not compliant:
            raise ValueError(
                "No compliant agents available for resolution. "
                "PolicyEngine must return at least one compliant agent."
            )

        # Determine effective strategy
        strategy = strategy_override or self.default_strategy
        strategy_overridden = strategy_override is not None

        if strategy not in VALID_STRATEGIES:
            logger.warning(
                f"Invalid override strategy {strategy!r}, falling back to default",
                default=self.default_strategy,
            )
            strategy = self.default_strategy
            strategy_overridden = False

        # Single candidate — no resolution needed
        if len(compliant) == 1:
            agent = compliant[0]
            return ResolutionResult(
                selected_agent_id=agent.id,
                strategy_used=strategy,
                candidate_agents=[a.id for a in compliant],
                agent_scores=[
                    AgentScore(
                        agent_id=agent.id,
                        score=1.0,
                        cost_per_query=agent.cost_per_query,
                        avg_latency_ms=agent.avg_latency_ms,
                        quality_score=agent.quality_score,
                        rank=1,
                    )
                ],
                selection_reason=(
                    f"Only one compliant agent available: {agent.id!r}"
                ),
                strategy_overridden=strategy_overridden,
            )

        # Multi-candidate resolution
        logger.info(
            "Resolving conflict",
            strategy=strategy,
            candidates=[a.id for a in compliant],
        )

        dispatch = {
            "cost_aware": self._resolve_cost_aware,
            "latency_aware": self._resolve_latency_aware,
            "quality_aware": self._resolve_quality_aware,
            "weighted": self._resolve_weighted,
            "round_robin": self._resolve_round_robin,
        }

        selected, scores, reason, tie_broken = dispatch[strategy](compliant)

        result = ResolutionResult(
            selected_agent_id=selected.id,
            strategy_used=strategy,
            candidate_agents=[a.id for a in compliant],
            agent_scores=scores,
            selection_reason=reason,
            tie_broken=tie_broken,
            strategy_overridden=strategy_overridden,
            override_reason=f"Per-query override to {strategy!r}" if strategy_overridden else None,
        )

        logger.info(
            "Conflict resolved",
            selected=selected.id,
            strategy=strategy,
            candidates=len(compliant),
            tie_broken=tie_broken,
        )
        return result

    # ------------------------------------------------------------------
    # Strategy implementations
    # ------------------------------------------------------------------

    def _resolve_cost_aware(
        self, agents: list[Agent]
    ) -> tuple[Agent, list[AgentScore], str, bool]:
        """Select agent with minimum cost_per_query."""
        sorted_agents = sorted(agents, key=lambda a: (a.cost_per_query, a.id))
        tie_broken = sorted_agents[0].cost_per_query == sorted_agents[1].cost_per_query
        selected = sorted_agents[0]

        scores = [
            AgentScore(
                agent_id=a.id,
                score=-a.cost_per_query,  # negative = higher is better
                cost_per_query=a.cost_per_query,
                avg_latency_ms=a.avg_latency_ms,
                quality_score=a.quality_score,
                rank=i + 1,
            )
            for i, a in enumerate(sorted_agents)
        ]

        reason = (
            f"Selected {selected.id!r}: lowest cost "
            f"(${selected.cost_per_query:.3f}) among "
            f"{len(agents)} compliant candidates using cost_aware strategy."
        )
        return selected, scores, reason, tie_broken

    def _resolve_latency_aware(
        self, agents: list[Agent]
    ) -> tuple[Agent, list[AgentScore], str, bool]:
        """Select agent with minimum avg_latency_ms."""
        sorted_agents = sorted(agents, key=lambda a: (a.avg_latency_ms, a.id))
        tie_broken = sorted_agents[0].avg_latency_ms == sorted_agents[1].avg_latency_ms
        selected = sorted_agents[0]

        scores = [
            AgentScore(
                agent_id=a.id,
                score=-a.avg_latency_ms,
                cost_per_query=a.cost_per_query,
                avg_latency_ms=a.avg_latency_ms,
                quality_score=a.quality_score,
                rank=i + 1,
            )
            for i, a in enumerate(sorted_agents)
        ]

        reason = (
            f"Selected {selected.id!r}: lowest latency "
            f"({selected.avg_latency_ms}ms) among "
            f"{len(agents)} compliant candidates using latency_aware strategy."
        )
        return selected, scores, reason, tie_broken

    def _resolve_quality_aware(
        self, agents: list[Agent]
    ) -> tuple[Agent, list[AgentScore], str, bool]:
        """Select agent with maximum quality_score."""
        sorted_agents = sorted(
            agents, key=lambda a: (-a.quality_score, a.id)
        )
        tie_broken = sorted_agents[0].quality_score == sorted_agents[1].quality_score
        selected = sorted_agents[0]

        scores = [
            AgentScore(
                agent_id=a.id,
                score=a.quality_score,
                cost_per_query=a.cost_per_query,
                avg_latency_ms=a.avg_latency_ms,
                quality_score=a.quality_score,
                rank=i + 1,
            )
            for i, a in enumerate(sorted_agents)
        ]

        reason = (
            f"Selected {selected.id!r}: highest quality "
            f"({selected.quality_score:.2f}) among "
            f"{len(agents)} compliant candidates using quality_aware strategy."
        )
        return selected, scores, reason, tie_broken

    def _resolve_weighted(
        self, agents: list[Agent]
    ) -> tuple[Agent, list[AgentScore], str, bool]:
        """Select agent using weighted composite score.

        Score = w_c * (1 - norm_cost) + w_l * (1 - norm_latency) + w_q * norm_quality

        Higher score = better agent. Cost and latency are inverted so that
        lower values produce higher scores (normalized to [0,1]).
        """
        costs = [a.cost_per_query for a in agents]
        latencies = [a.avg_latency_ms for a in agents]
        qualities = [a.quality_score for a in agents]

        min_cost, max_cost = min(costs), max(costs)
        min_lat, max_lat = min(latencies), max(latencies)
        min_qual, max_qual = min(qualities), max(qualities)

        def norm(value: float, lo: float, hi: float) -> float:
            """Normalize value to [0,1]. Returns 1.0 if range is zero."""
            return 1.0 if hi == lo else (value - lo) / (hi - lo)

        scored: list[tuple[float, Agent]] = []
        agent_scores: list[AgentScore] = []

        for agent in agents:
            norm_cost = norm(agent.cost_per_query, min_cost, max_cost)
            norm_lat = norm(agent.avg_latency_ms, min_lat, max_lat)
            norm_qual = norm(agent.quality_score, min_qual, max_qual)

            composite = (
                self.cost_weight * (1 - norm_cost)
                + self.latency_weight * (1 - norm_lat)
                + self.quality_weight * norm_qual
            )
            scored.append((composite, agent))

        scored.sort(key=lambda x: (-x[0], x[1].id))
        tie_broken = len(scored) > 1 and abs(scored[0][0] - scored[1][0]) < 1e-9

        for rank, (score, agent) in enumerate(scored, start=1):
            norm_cost = norm(agent.cost_per_query, min_cost, max_cost)
            norm_lat = norm(agent.avg_latency_ms, min_lat, max_lat)
            norm_qual = norm(agent.quality_score, min_qual, max_qual)
            agent_scores.append(
                AgentScore(
                    agent_id=agent.id,
                    score=score,
                    cost_per_query=agent.cost_per_query,
                    avg_latency_ms=agent.avg_latency_ms,
                    cost_score=1 - norm_cost,
                    latency_score=1 - norm_lat,
                    quality_score=norm_qual,
                    rank=rank,
                )
            )

        selected = scored[0][1]
        final_score = scored[0][0]

        reason = (
            f"Selected {selected.id!r}: highest weighted score "
            f"({final_score:.4f}) using w_c={self.cost_weight}/"
            f"w_l={self.latency_weight}/w_q={self.quality_weight} among "
            f"{len(agents)} compliant candidates."
        )
        return selected, agent_scores, reason, tie_broken

    def _resolve_round_robin(
        self, agents: list[Agent]
    ) -> tuple[Agent, list[AgentScore], str, bool]:
        """Distribute load evenly across compliant agents using round-robin."""
        # Sort by ID for deterministic ordering
        sorted_agents = sorted(agents, key=lambda a: a.id)
        idx = self._round_robin_index % len(sorted_agents)
        self._round_robin_index += 1
        selected = sorted_agents[idx]

        scores = [
            AgentScore(
                agent_id=a.id,
                score=1.0 if a.id == selected.id else 0.0,
                cost_per_query=a.cost_per_query,
                avg_latency_ms=a.avg_latency_ms,
                quality_score=a.quality_score,
                rank=1 if a.id == selected.id else 2,
            )
            for a in sorted_agents
        ]

        reason = (
            f"Selected {selected.id!r}: round-robin position {idx + 1} "
            f"(rotation {self._round_robin_index}) among "
            f"{len(agents)} compliant candidates."
        )
        return selected, scores, reason, False

    def __repr__(self) -> str:
        return (
            f"ConflictResolver(strategy={self.default_strategy!r}, "
            f"weights=({self.cost_weight}/{self.latency_weight}/{self.quality_weight}))"
        )
