package pager.gdpr

# =============================================================================
# Policy 7: Consent Verification (Hard Constraint)
# Marketing queries require a consent-aware agent.
# =============================================================================

deny[msg] {
    input.query.requires_consent == true
    input.agent.consent_aware == false
    msg := sprintf(
        "GDPR: Agent '%v' is not consent-aware and cannot process marketing queries",
        [input.agent.id],
    )
}
