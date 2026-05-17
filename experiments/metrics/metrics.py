"""Metrics calculation for PAGER evaluation.

Computes all 6 metrics from paper Section 5.5:

Primary (Critical):
  1. Routing Accuracy              — % correctly routed
  2. Policy Compliance Rate        — % satisfying all policies
  3. Authorization Violation Rate  — % routed to unauthorized agents
  4. Conflict Resolution Effectiveness — % optimal when conflict exists

Secondary (Supporting):
  5. Average Cost per Query
  6. Average Latency per Query
"""

from dataclasses import dataclass, field
from experiments.baselines.base_router import RoutingDecision
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EvaluationMetrics:
    """All 6 paper metrics for one router on one experiment."""

    router_name: str
    total_questions: int

    # Primary metrics
    routing_accuracy: float        # %
    policy_compliance_rate: float  # %
    auth_violation_rate: float     # %
    conflict_resolution_effectiveness: float  # %

    # Secondary metrics
    avg_cost_per_query: float      # $
    avg_latency_ms: float          # ms

    # Supporting counts
    correct_count: int = 0
    compliant_count: int = 0
    violation_count: int = 0
    conflict_count: int = 0
    conflict_optimal_count: int = 0

    def to_dict(self) -> dict:
        return {
            "router": self.router_name,
            "total": self.total_questions,
            "routing_accuracy_pct": round(self.routing_accuracy, 1),
            "policy_compliance_pct": round(self.policy_compliance_rate, 1),
            "auth_violation_pct": round(self.auth_violation_rate, 1),
            "conflict_resolution_pct": round(self.conflict_resolution_effectiveness, 1),
            "avg_cost_usd": round(self.avg_cost_per_query, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
        }

    def __str__(self) -> str:
        return (
            f"{self.router_name}:\n"
            f"  Routing Accuracy:          {self.routing_accuracy:.1f}%\n"
            f"  Policy Compliance:         {self.policy_compliance_rate:.1f}%\n"
            f"  Auth Violations:           {self.auth_violation_rate:.1f}%\n"
            f"  Conflict Resolution:       {self.conflict_resolution_effectiveness:.1f}%\n"
            f"  Avg Cost:                  ${self.avg_cost_per_query:.4f}\n"
            f"  Avg Latency:               {self.avg_latency_ms:.1f}ms"
        )


def compute_metrics(
    decisions: list[RoutingDecision],
    router_name: str,
    agents_by_id: dict,
) -> EvaluationMetrics:
    """Compute all 6 metrics from a list of routing decisions.

    Args:
        decisions: List of RoutingDecision from one router's evaluation run.
        router_name: Display name of the router.
        agents_by_id: Dict of agent_id → Agent for cost/latency lookup.

    Returns:
        EvaluationMetrics with all 6 metrics computed.
    """
    total = len(decisions)
    if total == 0:
        raise ValueError("Cannot compute metrics on empty decisions list")

    correct = sum(1 for d in decisions if d.is_correct)
    compliant = sum(1 for d in decisions if not d.has_violations)
    violations = sum(1 for d in decisions if d.has_violations)

    # Conflict resolution: only queries where 2+ agents were capable
    # (genuine ConflictResolver scenario, not single-candidate routing)
    conflict_decisions = [d for d in decisions if d.had_conflict]
    conflict_optimal = sum(1 for d in conflict_decisions if d.is_correct)

    # Cost and latency from agent specs
    costs = []
    latencies = []
    for d in decisions:
        agent = agents_by_id.get(d.selected_agent_id)
        if agent:
            costs.append(agent.cost_per_query)
            latencies.append(agent.avg_latency_ms)

    avg_cost = sum(costs) / len(costs) if costs else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    conflict_eff = (
        (conflict_optimal / len(conflict_decisions) * 100)
        if conflict_decisions else 0.0
    )

    metrics = EvaluationMetrics(
        router_name=router_name,
        total_questions=total,
        routing_accuracy=correct / total * 100,
        policy_compliance_rate=compliant / total * 100,
        auth_violation_rate=violations / total * 100,
        conflict_resolution_effectiveness=conflict_eff,
        avg_cost_per_query=avg_cost,
        avg_latency_ms=avg_latency,
        correct_count=correct,
        compliant_count=compliant,
        violation_count=violations,
        conflict_count=len(conflict_decisions),
        conflict_optimal_count=conflict_optimal,
    )

    logger.info(
        f"Metrics computed for {router_name}",
        accuracy=f"{metrics.routing_accuracy:.1f}%",
        compliance=f"{metrics.policy_compliance_rate:.1f}%",
        violations=f"{metrics.auth_violation_rate:.1f}%",
    )
    return metrics


def print_results_table(all_metrics: list[EvaluationMetrics]) -> None:
    """Print a formatted comparison table matching paper Table format."""
    print("\n" + "=" * 85)
    print(f"{'Metric':<35} ", end="")
    for m in all_metrics:
        print(f"{m.router_name:>12}", end="")
    print()
    print("-" * 85)

    rows = [
        ("Routing Accuracy (%)", "routing_accuracy"),
        ("Policy Compliance (%)", "policy_compliance_rate"),
        ("Auth Violations (%)", "auth_violation_rate"),
        ("Conflict Resolution (%)", "conflict_resolution_effectiveness"),
        ("Avg Cost ($/query)", "avg_cost_per_query"),
        ("Avg Latency (ms)", "avg_latency_ms"),
    ]

    for label, attr in rows:
        print(f"{label:<35} ", end="")
        for m in all_metrics:
            val = getattr(m, attr)
            if attr in ("avg_cost_per_query",):
                print(f"{val:>12.4f}", end="")
            else:
                print(f"{val:>12.1f}", end="")
        print()

    print("=" * 85 + "\n")
