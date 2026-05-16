"""ResolutionResult data model.

Represents the structured output of ConflictResolver — which agent was
selected, which strategy was used, and why.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AgentScore(BaseModel):
    """Scoring details for one candidate agent during conflict resolution."""

    model_config = {"frozen": True}

    agent_id: str
    score: float = Field(description="Composite score used for ranking")
    cost_per_query: float
    avg_latency_ms: float
    quality_score: float
    rank: int = Field(description="Final rank among candidates (1 = best)")


class ResolutionResult(BaseModel):
    """Result of conflict resolution across compliant agent candidates.

    Produced by ConflictResolver. Consumed by ExecutionCoordinator.
    """

    model_config = {"frozen": True}

    # --- Selection outcome ---
    selected_agent_id: str = Field(
        description="ID of the agent selected for query execution"
    )
    strategy_used: Literal[
        "cost_aware", "latency_aware", "quality_aware", "weighted", "round_robin"
    ] = Field(description="Conflict resolution strategy applied")

    # --- Candidate context ---
    candidate_agents: list[str] = Field(
        description="All compliant agent IDs that were candidates for selection"
    )
    agent_scores: list[AgentScore] = Field(
        default_factory=list,
        description="Per-agent scoring details (populated for weighted strategy)",
    )

    # --- Explainability ---
    selection_reason: str = Field(
        description=(
            "Human-readable explanation of why this agent was selected. "
            "Example: 'Selected patient_demographics_agent: lowest cost ($0.03) "
            "among 2 compliant candidates using cost_aware strategy.'"
        )
    )
    tie_broken: bool = Field(
        default=False,
        description=(
            "True if lexicographic tie-breaking was applied "
            "(scores were equal across candidates)"
        ),
    )

    # --- Override tracking ---
    strategy_overridden: bool = Field(
        default=False,
        description="True if per-query override changed the default strategy",
    )
    override_reason: str | None = Field(
        default=None,
        description="Reason for strategy override (e.g. 'urgent=true → latency_aware')",
    )

    @property
    def had_conflict(self) -> bool:
        """True if more than one candidate was available (actual conflict)."""
        return len(self.candidate_agents) > 1

    def __repr__(self) -> str:
        return (
            f"ResolutionResult("
            f"selected={self.selected_agent_id!r}, "
            f"strategy={self.strategy_used!r}, "
            f"candidates={len(self.candidate_agents)})"
        )
