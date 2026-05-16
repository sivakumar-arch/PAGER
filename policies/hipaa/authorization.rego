package pager.hipaa

# =============================================================================
# Policy 2: Role-Based Authorization (Hard Constraint)
# Users may only access agents their role is authorized to use.
# =============================================================================

# Deny if user role is not in the agent's authorized_roles list
deny[msg] {
    input.agent.authorized_roles != []
    not role_authorized
    msg := sprintf(
        "HIPAA: Role '%v' is not authorized to use agent '%v'",
        [input.user.role, input.agent.id],
    )
}

# Helper: check if user's role appears in agent's authorized_roles
role_authorized {
    input.user.role == input.agent.authorized_roles[_]
}
