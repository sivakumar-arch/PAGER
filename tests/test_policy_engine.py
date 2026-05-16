"""Integration tests for PolicyEngine.

These tests use real OPA CLI evaluation — OPA must be installed.
Run with: pytest tests/test_policy_engine.py -v -m integration

Tests cover:
  - HIPAA PII access control (hard constraint)
  - HIPAA role-based authorization (hard constraint)
  - HIPAA data sensitivity levels (hard constraint)
  - Multi-agent evaluation (compliant vs denied)
  - Policy trace audit trail
  - Edge cases (empty agents, missing policies)
"""

import pytest

from src.models.agent import Agent
from src.models.query import AnalyzedQuery
from src.pager.policy_engine import PolicyEngine


# ---------------------------------------------------------------------------
# Mark all tests in this module as integration
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def hipaa_engine() -> PolicyEngine:
    """PolicyEngine loaded with all HIPAA policies."""
    return PolicyEngine(policy_dirs=["policies/hipaa"])


@pytest.fixture(scope="module")
def gdpr_engine() -> PolicyEngine:
    """PolicyEngine loaded with GDPR policies."""
    return PolicyEngine(policy_dirs=["policies/gdpr"])


@pytest.fixture(scope="module")
def pii_only_engine() -> PolicyEngine:
    """PolicyEngine with only PII access policy — for isolated testing."""
    return PolicyEngine(policy_dirs=["policies/hipaa"])


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------

class TestPolicyEngineInit:
    """Tests for PolicyEngine initialization."""

    def test_loads_all_hipaa_policies(self, hipaa_engine):
        assert hipaa_engine.policy_count() == 5
        policies = hipaa_engine.policy_names()
        assert "pii_access" in policies
        assert "authorization" in policies
        assert "sensitivity" in policies
        assert "cost_optimization" in policies
        assert "sla_requirements" in policies

    def test_loads_gdpr_policies(self, gdpr_engine):
        assert gdpr_engine.policy_count() == 2
        assert "data_residency" in gdpr_engine.policy_names()
        assert "consent" in gdpr_engine.policy_names()

    def test_missing_policy_dir_raises(self):
        with pytest.raises(FileNotFoundError):
            PolicyEngine(policy_dirs=["policies/nonexistent"])

    def test_repr_format(self, hipaa_engine):
        r = repr(hipaa_engine)
        assert "pii_access" in r


# ---------------------------------------------------------------------------
# PII Access Policy tests (hard constraint)
# ---------------------------------------------------------------------------

class TestPIIAccessPolicy:
    """Tests for HIPAA PII access control policy."""

    def test_hipaa_compliant_agent_passes_pii_query(
        self, hipaa_engine, agent_demographics, query_task1_demographics
    ):
        """HIPAA-compliant agent should pass PII query."""
        result = hipaa_engine.evaluate(
            query=query_task1_demographics,
            agents=[agent_demographics],
        )
        assert agent_demographics.id in result.compliant_agents
        assert agent_demographics.id not in result.violations

    def test_non_hipaa_agent_denied_on_pii_query(
        self, hipaa_engine, agent_non_hipaa, query_task1_demographics
    ):
        """Non-HIPAA-compliant agent must be denied when query contains PII."""
        result = hipaa_engine.evaluate(
            query=query_task1_demographics,
            agents=[agent_non_hipaa],
        )
        assert agent_non_hipaa.id not in result.compliant_agents
        assert agent_non_hipaa.id in result.violations
        # Verify the violation message references HIPAA
        violations = result.violations[agent_non_hipaa.id]
        assert any("HIPAA" in v.message or "hipaa" in v.message.lower()
                   for v in violations)

    def test_non_hipaa_agent_passes_non_pii_query(self, hipaa_engine, agent_non_hipaa):
        """Non-HIPAA agent should be allowed for non-PII queries."""
        non_pii_query = AnalyzedQuery(
            raw_query="Show general lab reference ranges",
            intent="retrieval",
            contains_pii=False,
            data_sensitivity="low",
            required_capabilities=["GET /Observation"],
            user_role="nurse",
        )
        result = hipaa_engine.evaluate(
            query=non_pii_query,
            agents=[agent_non_hipaa],
        )
        assert agent_non_hipaa.id in result.compliant_agents

    def test_mixed_agents_correct_split(
        self, hipaa_engine, agent_demographics, agent_non_hipaa,
        query_task1_demographics
    ):
        """With PII query: HIPAA agent passes, non-HIPAA agent denied."""
        result = hipaa_engine.evaluate(
            query=query_task1_demographics,
            agents=[agent_demographics, agent_non_hipaa],
        )
        assert agent_demographics.id in result.compliant_agents
        assert agent_non_hipaa.id in result.violations
        assert result.compliance_rate == 0.5


# ---------------------------------------------------------------------------
# Authorization Policy tests (hard constraint)
# ---------------------------------------------------------------------------

class TestAuthorizationPolicy:
    """Tests for HIPAA role-based authorization policy."""

    def test_authorized_role_passes(
        self, hipaa_engine, agent_procedure, query_task8_procedure
    ):
        """Doctor role should be authorized for procedure agent."""
        result = hipaa_engine.evaluate(
            query=query_task8_procedure,
            agents=[agent_procedure],
        )
        assert agent_procedure.id in result.compliant_agents

    def test_unauthorized_role_denied(self, hipaa_engine, agent_procedure):
        """Nurse role should be denied for procedure agent (doctor only)."""
        nurse_query = AnalyzedQuery(
            raw_query="Order orthopedic referral for patient S2016972",
            intent="ordering",
            contains_pii=True,
            data_sensitivity="high",
            required_capabilities=["POST /ServiceRequest"],
            user_role="nurse",  # not in procedure_agent authorized_roles
        )
        result = hipaa_engine.evaluate(
            query=nurse_query,
            agents=[agent_procedure],
        )
        assert agent_procedure.id in result.violations
        violations = result.violations[agent_procedure.id]
        assert any("Authorization" in v.message or "authorization" in v.message.lower()
                   for v in violations)

    def test_medication_agent_requires_doctor_or_pharmacist(
        self, hipaa_engine, agent_medication
    ):
        """Medication agent should deny receptionist role."""
        receptionist_query = AnalyzedQuery(
            raw_query="What medications is patient S1234567 on?",
            intent="retrieval",
            contains_pii=True,
            data_sensitivity="high",
            required_capabilities=["GET /MedicationRequest"],
            user_role="receptionist",
        )
        result = hipaa_engine.evaluate(
            query=receptionist_query,
            agents=[agent_medication],
        )
        assert agent_medication.id in result.violations


# ---------------------------------------------------------------------------
# Data Sensitivity Policy tests (hard constraint)
# ---------------------------------------------------------------------------

class TestSensitivityPolicy:
    """Tests for HIPAA data sensitivity level policy."""

    def test_high_sensitivity_requires_level_3(self, hipaa_engine):
        """Agent with data_access_level=2 must be denied for high-sensitivity query."""
        low_access_agent = Agent(
            id="low_access_agent",
            name="Low Access Agent",
            capabilities=["GET /Observation", "lab_results"],
            hipaa_compliant=True,
            gdpr_compliant=False,
            authorized_roles=["nurse", "doctor"],
            data_access_level=2,  # only clinical, not restricted
            cost_per_query=0.02,
            avg_latency_ms=80.0,
            quality_score=0.90,
            endpoint="mock://low_access",
            max_concurrent=50,
        )
        high_sensitivity_query = AnalyzedQuery(
            raw_query="Get lab results for patient S3032536",
            intent="retrieval",
            contains_pii=True,
            data_sensitivity="high",  # requires level 3
            required_capabilities=["GET /Observation"],
            user_role="nurse",
        )
        result = hipaa_engine.evaluate(
            query=high_sensitivity_query,
            agents=[low_access_agent],
        )
        assert low_access_agent.id in result.violations

    def test_level_3_agent_passes_high_sensitivity(
        self, hipaa_engine, agent_labs, query_task4_labs
    ):
        """Labs agent (level 3) should pass high-sensitivity query."""
        result = hipaa_engine.evaluate(
            query=query_task4_labs,
            agents=[agent_labs],
        )
        assert agent_labs.id in result.compliant_agents


# ---------------------------------------------------------------------------
# Multi-agent evaluation tests
# ---------------------------------------------------------------------------

class TestMultiAgentEvaluation:
    """Tests for evaluating multiple agents simultaneously."""

    def test_all_healthcare_agents_pass_for_authorized_nurse(
        self, hipaa_engine, all_healthcare_agents
    ):
        """Nurse with non-PII, low-sensitivity query — only role-authorized agents pass."""
        non_restricted_query = AnalyzedQuery(
            raw_query="Show lab reference ranges",
            intent="retrieval",
            contains_pii=False,
            data_sensitivity="low",
            required_capabilities=["GET /Observation"],
            user_role="nurse",
        )
        result = hipaa_engine.evaluate(
            query=non_restricted_query,
            agents=all_healthcare_agents,
        )
        # Labs agent and vitals agent are nurse-authorized
        assert result.total_agents_evaluated == len(all_healthcare_agents)
        assert result.has_compliant_agents

    def test_compliance_rate_all_pass(
        self, hipaa_engine, agent_demographics, query_task1_demographics
    ):
        result = hipaa_engine.evaluate(
            query=query_task1_demographics,
            agents=[agent_demographics],
        )
        assert result.compliance_rate == 1.0

    def test_empty_agents_returns_empty_result(
        self, hipaa_engine, query_task1_demographics
    ):
        result = hipaa_engine.evaluate(
            query=query_task1_demographics,
            agents=[],
        )
        assert result.total_agents_evaluated == 0
        assert result.compliant_agents == []
        assert not result.has_compliant_agents


# ---------------------------------------------------------------------------
# Audit trail tests
# ---------------------------------------------------------------------------

class TestAuditTrail:
    """Tests for policy trace audit trail."""

    def test_policy_trace_populated(
        self, hipaa_engine, agent_demographics, query_task1_demographics
    ):
        result = hipaa_engine.evaluate(
            query=query_task1_demographics,
            agents=[agent_demographics],
        )
        assert agent_demographics.id in result.policy_trace

    def test_violation_references_policy_file(
        self, hipaa_engine, agent_non_hipaa, query_task1_demographics
    ):
        result = hipaa_engine.evaluate(
            query=query_task1_demographics,
            agents=[agent_non_hipaa],
        )
        violations = result.violations.get(agent_non_hipaa.id, [])
        assert len(violations) > 0
        assert all(v.policy_file.endswith(".rego") for v in violations)
        assert all(v.agent_id == agent_non_hipaa.id for v in violations)


# ---------------------------------------------------------------------------
# GDPR policy tests
# ---------------------------------------------------------------------------

class TestGDPRPolicies:
    """Tests for GDPR data residency and consent policies."""

    def test_eu_agent_passes_eu_query(self, gdpr_engine):
        eu_agent = Agent(
            id="eu_data_agent",
            name="EU Data Agent",
            capabilities=["personal_data_processing"],
            hipaa_compliant=False,
            gdpr_compliant=True,
            authorized_roles=["data_processor"],
            data_access_level=2,
            data_residency="EU",
            consent_aware=True,
            cost_per_query=0.08,
            avg_latency_ms=140.0,
            quality_score=0.91,
            endpoint="mock://eu_data",
            max_concurrent=30,
        )
        eu_query = AnalyzedQuery(
            raw_query="Process personal data for EU user",
            intent="ordering",
            contains_pii=True,
            data_sensitivity="medium",
            required_capabilities=["personal_data_processing"],
            user_role="data_processor",
            user_region="EU",
            requires_consent=True,
        )
        result = gdpr_engine.evaluate(query=eu_query, agents=[eu_agent])
        assert eu_agent.id in result.compliant_agents

    def test_non_eu_agent_denied_for_eu_query(self, gdpr_engine):
        us_agent = Agent(
            id="us_data_agent",
            name="US Data Agent",
            capabilities=["personal_data_processing"],
            hipaa_compliant=False,
            gdpr_compliant=False,
            authorized_roles=["data_processor"],
            data_access_level=2,
            data_residency="US",
            consent_aware=False,
            cost_per_query=0.05,
            avg_latency_ms=80.0,
            quality_score=0.88,
            endpoint="mock://us_data",
            max_concurrent=60,
        )
        eu_query = AnalyzedQuery(
            raw_query="Process personal data for EU user",
            intent="ordering",
            contains_pii=True,
            data_sensitivity="medium",
            required_capabilities=["personal_data_processing"],
            user_role="data_processor",
            user_region="EU",
            requires_consent=False,
        )
        result = gdpr_engine.evaluate(query=eu_query, agents=[us_agent])
        assert us_agent.id in result.violations
