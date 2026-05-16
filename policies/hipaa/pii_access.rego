package pager.hipaa

# =============================================================================
# Policy 1: PII Access Control (Hard Constraint)
# Queries containing PII require a HIPAA-compliant agent.
# =============================================================================

# Deny non-compliant agents for PII queries
deny[msg] {
    input.query.contains_pii == true
    input.agent.hipaa_compliant == false
    msg := sprintf(
        "HIPAA: Agent '%v' is not HIPAA-compliant and cannot process PII data",
        [input.agent.id],
    )
}
