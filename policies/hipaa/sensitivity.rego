package pager.hipaa

# =============================================================================
# Policy 3: Data Sensitivity Enforcement (Hard Constraint)
# High-sensitivity queries require agents with restricted or clinical access.
# =============================================================================

# Deny if query sensitivity is high but agent access level is insufficient
deny[msg] {
    input.query.data_sensitivity == "high"
    not sufficient_access_level
    msg := sprintf(
        "HIPAA: Agent '%v' has insufficient data access level '%v' for high-sensitivity query",
        [input.agent.id, input.agent.data_access_level],
    )
}

# Sufficient access: clinical or restricted level handles high-sensitivity data
sufficient_access_level {
    input.agent.data_access_level == "clinical"
}

sufficient_access_level {
    input.agent.data_access_level == "restricted"
}
