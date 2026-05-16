package pager.hipaa

import rego.v1


# Policy 5: SLA Requirements (Soft Constraint)
# Prefer agents meeting latency SLA when possible

default latency_sla_ms := 100

soft_hints contains hint if {
    input.agent.avg_latency_ms <= latency_sla_ms
    hint := {
        "type": "sla_compliant",
        "message": sprintf("Agent '%v' meets SLA (%vms <= %vms)",
                          [input.agent.name, input.agent.avg_latency_ms, latency_sla_ms]),
        "weight": 0.3
    }
}

soft_hints contains hint if {
    input.agent.avg_latency_ms > latency_sla_ms
    hint := {
        "type": "sla_warning",
        "message": sprintf("Agent '%v' exceeds SLA (%vms > %vms)",
                          [input.agent.name, input.agent.avg_latency_ms, latency_sla_ms]),
        "weight": -0.15
    }
}
