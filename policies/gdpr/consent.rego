package pager.gdpr

import rego.v1


# Policy 7: Consent Verification (Hard Constraint - GDPR)
# Operations requiring consent must use consent-aware agents

deny contains msg if {
    input.query.requires_consent
    not input.agent.consent_aware
    msg := sprintf("GDPR violation: Consent-required operations need consent-aware agents. Agent '%v' is not consent-aware",
                   [input.agent.name])
}
