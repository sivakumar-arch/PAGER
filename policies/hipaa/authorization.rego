package pager.hipaa

import rego.v1


# Policy 2: Role-Based Authorization (Hard Constraint)
# User role must be in agent's authorized roles list

deny contains msg if {
    count(input.agent.authorized_roles) > 0
    not role_authorized
    msg := sprintf("Authorization violation: User role '%v' is not authorized for agent '%v'. Authorized roles: %v",
                   [input.context.user_role, input.agent.name, input.agent.authorized_roles])
}

role_authorized if {
    some role in input.agent.authorized_roles
    role == input.context.user_role
}
