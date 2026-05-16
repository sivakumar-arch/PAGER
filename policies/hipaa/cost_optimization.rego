package pager.hipaa

import rego.v1


# Policy 4: Cost Optimization (Soft Constraint)
# Prefer agents below cost threshold when possible

default cost_threshold := 0.05

soft_hints contains hint if {
    input.agent.cost_per_query <= cost_threshold
    hint := {
        "type": "cost_preference",
        "message": sprintf("Agent '%v' is cost-efficient at $%v per query", [input.agent.name, input.agent.cost_per_query]),
        "weight": 0.4
    }
}

soft_hints contains hint if {
    input.agent.cost_per_query > cost_threshold
    hint := {
        "type": "cost_warning",
        "message": sprintf("Agent '%v' exceeds cost threshold ($%v > $%v)",
                          [input.agent.name, input.agent.cost_per_query, cost_threshold]),
        "weight": -0.2
    }
}
