package pager.hipaa

import rego.v1


# Policy 1: PII Access Control (Hard Constraint)
# Queries containing PII require HIPAA-compliant agents

deny contains msg if {
    input.query.contains_pii
    not input.agent.hipaa_compliant
    msg := sprintf("HIPAA violation: Agent '%v' is not HIPAA-compliant and cannot access PII data", [input.agent.name])
}
