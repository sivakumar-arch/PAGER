"""PolicyEvaluationResult data model.

Represents the structured output of PolicyEngine — which agents passed
all policies, which were denied and why, and soft hints for ConflictResolver.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class PolicyViolation(BaseModel):
    """A single policy violation for one agent."""

    model_config = {"frozen": True}

    agent_id: str = Field(description="ID of the agent that violated the policy")
    policy_file: str = Field(description="Rego policy file that produced the denial")
    message: str = Field(description="Human-readable violation explanation")


class SoftHint(BaseModel):
    """A soft policy preference hint for ConflictResolver.

    Soft hints do not deny agents — they signal ConflictResolver to
    prefer agents that satisfy cost or latency thresholds when resolving ties.
    """

    model_config = {"frozen": True}

    hint_type: str = Field(description="Hint category: 'cost_optimization' | 'sla_latency'")
    agent_id: str = Field(description="Agent this hint applies to")
    message: str = Field(description="Human-readable hint description")
    metadata: dict = Field(
        default_factory=dict,
        description="Additional hint data (e.g. threshold values)",
    )


class PolicyEvaluationResult(BaseModel):
    """Result of evaluating all agents against all applicable policies.

    Produced by PolicyEngine. Consumed by ConflictResolver.
    """

    model_config = {"frozen": True}

    # --- Core routing output ---
    compliant_agents: list[str] = Field(
        description="Agent IDs that passed all hard policy constraints"
    )
    violations: dict[str, list[PolicyViolation]] = Field(
        default_factory=dict,
        description="Map of agent_id → list of policy violations for denied agents",
    )

    # --- Soft guidance for ConflictResolver ---
    soft_hints: list[SoftHint] = Field(
        default_factory=list,
        description="Cost/SLA preference hints — do not deny agents, guide selection",
    )

    # --- Full audit record ---
    policy_trace: dict = Field(
        default_factory=dict,
        description=(
            "Complete OPA evaluation trace for all agents and policies. "
            "Stored in FeedbackCollector for audit and explainability."
        ),
    )

    # --- Metadata ---
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of policy evaluation (UTC)",
    )
    total_agents_evaluated: int = Field(
        description="Total number of agents evaluated against policies"
    )

    @property
    def has_compliant_agents(self) -> bool:
        """True if at least one agent passed all policy constraints."""
        return len(self.compliant_agents) > 0

    @property
    def compliance_rate(self) -> float:
        """Fraction of evaluated agents that are compliant [0.0, 1.0]."""
        if self.total_agents_evaluated == 0:
            return 0.0
        return len(self.compliant_agents) / self.total_agents_evaluated

    def __repr__(self) -> str:
        return (
            f"PolicyEvaluationResult("
            f"compliant={self.compliant_agents}, "
            f"denied={list(self.violations.keys())})"
        )
