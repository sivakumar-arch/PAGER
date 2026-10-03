"""Independent compliance oracle for the Paper 1 revision experiments.

The oracle does NOT use the QueryAnalyzer or OPA. It encodes the written policy
specification (P1 PII access, P2 role authorization, P3 data sensitivity) as
plain Python over (a) task-level annotations assigned by reading the query
templates and (b) the agent attributes in the registry YAML.

Annotation rule (fixed before any run):
  * contains_pii: every MedAgentBench query concerns one identified patient
    (MRN, or name plus date of birth), so PHI is involved: True for all tasks.
  * sensitivity: demographic identity data and routine vital-sign recording are
    "medium"; laboratory results, medication orders and procedure or referral
    orders are "high" (restricted clinical data).
  * user role per task: the experiment's existing TASK_USER_ROLES.

Policy specification:
  P1: if contains_pii, the agent must be HIPAA compliant.
  P2: if the agent lists any authorized roles, the user's role must be in the list
      (an empty list imposes no role restriction, as in policies/hipaa/authorization.rego).
  P3: sensitivity high requires data_access_level >= 3, medium requires >= 2
      (as in policies/hipaa/sensitivity.rego; no rule applies to low sensitivity).
"""

from experiments.dataset import GROUND_TRUTH_MAP, TASK_USER_ROLES

TASK_SENSITIVITY: dict[int, str] = {
    1: "medium", 2: "medium", 3: "medium",
    4: "high", 5: "high", 6: "high", 7: "high", 8: "high", 9: "high", 10: "high",
}
TASK_CONTAINS_PII: dict[int, bool] = {t: True for t in range(1, 11)}
_MIN_LEVEL = {"medium": 2, "high": 3}

# Capability family of every agent id in the adversarial pool.
FAMILY: dict[str, str] = {
    "patient_demographics_agent": "patient_demographics_agent",
    "vitals_agent": "vitals_agent",
    "labs_agent": "labs_agent",
    "medication_agent": "medication_agent",
    "procedure_agent": "procedure_agent",
    "demographics_agent_uncert": "patient_demographics_agent",
    "vitals_agent_uncert": "vitals_agent",
    "labs_agent_lowclear": "labs_agent",
    "medication_agent_norole": "medication_agent",
    "procedure_agent_uncert": "procedure_agent",
}


def oracle_violations(agent, task: int, role: str | None = None) -> list[str]:
    role = role or TASK_USER_ROLES[task]
    out = []
    if TASK_CONTAINS_PII[task] and not agent.hipaa_compliant:
        out.append("P1")
    if agent.authorized_roles and role not in agent.authorized_roles:
        out.append("P2")
    if agent.data_access_level < _MIN_LEVEL[TASK_SENSITIVITY[task]]:
        out.append("P3")
    return out


def oracle_ok_set(pool, task: int) -> list[str]:
    """Agents in `pool` that belong to the task's ground-truth family and comply."""
    fam = GROUND_TRUTH_MAP[task]
    return [a.id for a in pool
            if FAMILY.get(a.id, a.id) == fam and not oracle_violations(a, task)]
