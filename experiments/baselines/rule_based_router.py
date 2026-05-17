"""Baseline 3: Rule-Based Routing.

Keyword matching to route queries to agents — no policy enforcement.
Purpose: represents current real-world practice (main comparison #1).

Uses same keyword patterns as PAGER's QueryAnalyzer but WITHOUT:
  - Policy enforcement (no HIPAA/GDPR compliance checks)
  - Authorization checks (no role-based access control)
  - Conflict resolution (first match wins)

Expected performance (paper Section 6.1):
    Routing Accuracy:    ~67%  (keyword matching works for clear queries)
    Policy Compliance:   ~58%  (accidental alignment, no guarantee)
    Auth Violations:     ~23%  (no authorization check)
"""

from src.models.agent import Agent
from src.utils.logger import get_logger
from experiments.baselines.base_router import BaseRouter

logger = get_logger(__name__)

# Keyword → agent_id mapping (mirrors QueryAnalyzer patterns)
# First match wins — order matters
_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    # Procedure/referral (check before vitals to avoid false matches)
    (
        ("referral", "procedure", "surgery", "operation", "orthopedic",
         "cardiology referral", "specialist", "service request",
         "post /servicerequest"),
        "procedure_agent",
    ),
    # Medications
    (
        ("medication", "drug", "prescription", "dose", "dosage",
         "medicine", "pill", "tablet", "antibiotic", "statin",
         "insulin", "metformin", "medicationrequest"),
        "medication_agent",
    ),
    # Lab results
    (
        ("lab", "magnesium", "glucose", "hba1c", "hemoglobin",
         "creatinine", "sodium", "potassium", "cholesterol",
         "lab result", "lab value", "most recent", "test result",
         "observation", "diagnostic"),
        "labs_agent",
    ),
    # Vital signs
    (
        ("vital", "blood pressure", "heart rate", "temperature",
         "respiratory", "oxygen saturation", "pulse", "weight", "height"),
        "vitals_agent",
    ),
    # Patient demographics (last — most generic)
    (
        ("patient", "mrn", "medical record", "demographics",
         "date of birth", "dob", "name", "address"),
        "patient_demographics_agent",
    ),
]


class RuleBasedRouter(BaseRouter):
    """Routes queries via keyword matching with no policy enforcement.

    Represents the current state of practice in enterprise routing:
    simple rules that work for clear cases but provide no compliance
    guarantees and no systematic conflict resolution.
    """

    def __init__(self) -> None:
        logger.info("RuleBasedRouter initialized", rules=len(_KEYWORD_RULES))

    @property
    def name(self) -> str:
        return "Rule-Based"

    def route(
        self,
        question: str,
        agents: list[Agent],
        task_type: int | None = None,
        user_role: str = "nurse",
        **kwargs,
    ) -> str:
        if not agents:
            raise ValueError("RuleBasedRouter: no agents available")

        agent_ids = {a.id for a in agents}
        question_lower = question.lower()

        # First matching rule wins
        for keywords, agent_id in _KEYWORD_RULES:
            if any(kw in question_lower for kw in keywords):
                if agent_id in agent_ids:
                    logger.debug(
                        "Rule-based match",
                        agent=agent_id,
                        matched_on=[kw for kw in keywords if kw in question_lower][0],
                    )
                    return agent_id

        # Fallback: first agent alphabetically
        fallback = sorted(agents, key=lambda a: a.id)[0]
        logger.debug("Rule-based fallback", agent=fallback.id)
        return fallback.id
