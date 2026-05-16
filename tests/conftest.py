"""Shared pytest fixtures for PAGER test suite."""

import pytest

from src.models.agent import Agent
from src.models.query import AnalyzedQuery
from src.models.policy_result import PolicyEvaluationResult, PolicyViolation
from src.models.resolution import ResolutionResult, AgentScore
from src.models.execution import ExecutionResult


# ---------------------------------------------------------------------------
# Agent fixtures (matching healthcare_agents.yaml)
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_demographics() -> Agent:
    return Agent(
        id="patient_demographics_agent",
        name="Patient Demographics Agent",
        capabilities=["GET /Patient", "patient_lookup", "demographics_retrieval"],
        hipaa_compliant=True,
        gdpr_compliant=False,
        authorized_roles=["nurse", "doctor", "admin", "receptionist"],
        data_access_level=2,
        cost_per_query=0.02,
        avg_latency_ms=80.0,
        quality_score=0.92,
        endpoint="mock://patient_demographics",
        max_concurrent=100,
    )


@pytest.fixture
def agent_labs() -> Agent:
    return Agent(
        id="labs_agent",
        name="Laboratory Results Agent",
        capabilities=["GET /Observation", "lab_results", "diagnostic_data", "lab_values"],
        hipaa_compliant=True,
        gdpr_compliant=False,
        authorized_roles=["nurse", "doctor", "lab_tech"],
        data_access_level=3,
        cost_per_query=0.04,
        avg_latency_ms=120.0,
        quality_score=0.95,
        endpoint="mock://labs",
        max_concurrent=60,
    )


@pytest.fixture
def agent_medication() -> Agent:
    return Agent(
        id="medication_agent",
        name="Medication Management Agent",
        capabilities=[
            "POST /MedicationRequest",
            "GET /MedicationRequest",
            "medication_ordering",
            "prescription_management",
        ],
        hipaa_compliant=True,
        gdpr_compliant=False,
        authorized_roles=["doctor", "pharmacist"],
        data_access_level=3,
        cost_per_query=0.05,
        avg_latency_ms=150.0,
        quality_score=0.93,
        endpoint="mock://medication",
        max_concurrent=50,
    )


@pytest.fixture
def agent_procedure() -> Agent:
    return Agent(
        id="procedure_agent",
        name="Procedure Ordering Agent",
        capabilities=[
            "POST /ServiceRequest",
            "procedure_ordering",
            "referral_management",
            "surgery_scheduling",
        ],
        hipaa_compliant=True,
        gdpr_compliant=False,
        authorized_roles=["doctor"],
        data_access_level=3,
        cost_per_query=0.06,
        avg_latency_ms=140.0,
        quality_score=0.91,
        endpoint="mock://procedure",
        max_concurrent=40,
    )


@pytest.fixture
def agent_non_hipaa() -> Agent:
    """Agent that is NOT HIPAA compliant — used to test policy denial."""
    return Agent(
        id="non_compliant_agent",
        name="Non-Compliant Agent",
        capabilities=["GET /Patient", "patient_lookup"],
        hipaa_compliant=False,
        gdpr_compliant=False,
        authorized_roles=["nurse", "doctor"],
        data_access_level=2,
        cost_per_query=0.01,
        avg_latency_ms=50.0,
        quality_score=0.80,
        endpoint="mock://non_compliant",
        max_concurrent=100,
    )


@pytest.fixture
def all_healthcare_agents(
    agent_demographics, agent_labs, agent_medication, agent_procedure
) -> list[Agent]:
    return [agent_demographics, agent_labs, agent_medication, agent_procedure]


# ---------------------------------------------------------------------------
# Query fixtures (MedAgentBench representative tasks)
# ---------------------------------------------------------------------------

@pytest.fixture
def query_task1_demographics() -> AnalyzedQuery:
    """Task 1: Patient MRN lookup — contains PII."""
    return AnalyzedQuery(
        raw_query="What is the MRN of patient Peter Stafford, DOB 1932-12-29?",
        intent="lookup",
        entities={"patient_name": "Peter Stafford", "dob": "1932-12-29"},
        contains_pii=True,
        data_sensitivity="medium",
        required_capabilities=["GET /Patient", "patient_lookup", "demographics_retrieval"],
        user_role="nurse",
        task_type=1,
    )


@pytest.fixture
def query_task4_labs() -> AnalyzedQuery:
    """Task 4: Lab result retrieval — high sensitivity."""
    return AnalyzedQuery(
        raw_query="What is the most recent magnesium level of patient S3032536?",
        intent="retrieval",
        entities={"mrn": "S3032536", "lab_test": "magnesium"},
        contains_pii=True,
        data_sensitivity="high",
        required_capabilities=["GET /Observation", "lab_results", "diagnostic_data"],
        user_role="nurse",
        task_type=4,
    )


@pytest.fixture
def query_task8_procedure() -> AnalyzedQuery:
    """Task 8: Procedure ordering — doctor only."""
    return AnalyzedQuery(
        raw_query="Order an orthopedic surgery referral for patient S2016972",
        intent="ordering",
        entities={"mrn": "S2016972", "procedure_type": "orthopedic"},
        contains_pii=True,
        data_sensitivity="high",
        required_capabilities=["POST /ServiceRequest", "procedure_ordering", "referral_management"],
        user_role="doctor",
        task_type=8,
    )


# ---------------------------------------------------------------------------
# Policy result fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def policy_result_single_compliant(agent_demographics) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        compliant_agents=[agent_demographics.id],
        violations={},
        soft_hints=[],
        policy_trace={},
        total_agents_evaluated=1,
    )


@pytest.fixture
def policy_result_multi_compliant(
    agent_demographics, agent_labs
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        compliant_agents=[agent_demographics.id, agent_labs.id],
        violations={},
        soft_hints=[],
        policy_trace={},
        total_agents_evaluated=2,
    )


@pytest.fixture
def policy_result_with_violation(
    agent_demographics, agent_non_hipaa
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        compliant_agents=[agent_demographics.id],
        violations={
            agent_non_hipaa.id: [
                PolicyViolation(
                    agent_id=agent_non_hipaa.id,
                    policy_file="pii_access.rego",
                    message="HIPAA violation: Agent 'Non-Compliant Agent' is not HIPAA-compliant",
                )
            ]
        },
        soft_hints=[],
        policy_trace={},
        total_agents_evaluated=2,
    )
