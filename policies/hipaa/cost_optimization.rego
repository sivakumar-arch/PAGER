package pager.hipaa

# =============================================================================
# Policy 4: Cost Optimization (Soft Hint)
# Prefer agents below the cost threshold. Does NOT deny — produces a hint
# for ConflictResolver to prefer lower-cost agents when resolving ties.
#
# $0.05 is an illustrative threshold for enterprise evaluation.
# Production deployments configure this per SLA/budget requirements.
# =============================================================================

cost_threshold := 0.05

# Soft hint: flag agents that exceed the cost threshold
cost_hint[hint] {
    input.agent.cost_per_query > cost_threshold
    hint := {
        "type": "cost_optimization",
        "agent_id": input.agent.id,
        "cost_per_query": input.agent.cost_per_query,
        "threshold": cost_threshold,
        "message": sprintf(
            "Agent '%v' exceeds cost threshold ($%.2f > $%.2f) — prefer lower-cost alternatives",
            [input.agent.id, input.agent.cost_per_query, cost_threshold],
        ),
    }
}
