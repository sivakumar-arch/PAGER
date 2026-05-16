package pager.gdpr

# =============================================================================
# Policy 6: Data Residency (Hard Constraint)
# EU user data must be processed by an agent with EU or multi-region residency.
# =============================================================================

deny[msg] {
    input.query.user_region == "EU"
    input.agent.data_residency != "EU"
    input.agent.data_residency != "multi-region"
    msg := sprintf(
        "GDPR: EU user data cannot be processed by agent '%v' with residency '%v'",
        [input.agent.id, input.agent.data_residency],
    )
}
