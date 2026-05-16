package pager.hipaa

# =============================================================================
# Policy 5: SLA Latency Requirements (Soft Hint)
# Prefer agents below the latency SLA threshold. Does NOT deny — produces a
# hint for ConflictResolver to prefer lower-latency agents.
#
# 200ms is an illustrative SLA threshold for enterprise evaluation.
# Production deployments configure this per operational SLA requirements.
# =============================================================================

latency_threshold_ms := 200

# Soft hint: flag agents that exceed the latency SLA
latency_hint[hint] {
    input.agent.avg_latency_ms > latency_threshold_ms
    hint := {
        "type": "sla_latency",
        "agent_id": input.agent.id,
        "avg_latency_ms": input.agent.avg_latency_ms,
        "threshold_ms": latency_threshold_ms,
        "message": sprintf(
            "Agent '%v' exceeds latency SLA (%vms > %vms) — prefer lower-latency alternatives",
            [input.agent.id, input.agent.avg_latency_ms, latency_threshold_ms],
        ),
    }
}
