package pager.hipaa

import rego.v1


# Policy 3: Data Sensitivity Levels (Hard Constraint)
# Agent's data access level must meet query sensitivity requirements

deny contains msg if {
    input.query.data_sensitivity == "high"
    input.agent.data_access_level < 3
    msg := sprintf("Data sensitivity violation: Agent '%v' (level %v) cannot access high-sensitivity data (requires level 3)",
                   [input.agent.name, input.agent.data_access_level])
}

deny contains msg if {
    input.query.data_sensitivity == "medium"
    input.agent.data_access_level < 2
    msg := sprintf("Data sensitivity violation: Agent '%v' (level %v) cannot access medium-sensitivity data (requires level 2)",
                   [input.agent.name, input.agent.data_access_level])
}
