package pager.gdpr

import rego.v1


# Policy 6: Data Residency (Hard Constraint - GDPR)
# EU user data must be processed in EU region

deny contains msg if {
    input.query.user_region == "EU"
    input.agent.data_residency != "EU"
    input.agent.data_residency != "multi-region"
    msg := sprintf("GDPR violation: EU data must be processed in EU region. Agent '%v' residency: %v",
                   [input.agent.name, input.agent.data_residency])
}
