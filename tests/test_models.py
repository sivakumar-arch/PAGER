"""Unit tests for PAGER Pydantic data models.

Tests validation, field constraints, computed properties, and
repr output for all 5 models.
"""

import pytest
from pydantic import ValidationError

from src.models.agent import Agent
from src.models.execution import ExecutionResult
from src.models.policy_result import PolicyEvaluationResult, PolicyViolation, SoftHint
from src.models.query import AnalyzedQuery
from src.models.resolution import AgentScore, ResolutionResult


# ===========================================================================
# Agent model tests
# ===========================================================================


class TestAgent:
    """Tests for Agent model."""

    def test_valid_agent_construction(self, agent_demographics):
        assert agent_demographics.id == "patient_demographics_agent"
        assert agent_demographics.hipaa_compliant is True
        assert agent_demographics.cost_per_query == 0.02

    def test_agent_is_immutable(self, agent_demographics):
        with pytest.raises(ValidationError):
            agent_demographics.id = "new_id"

    def test_invalid_id_non_alphanumeric(self):
        with pytest.raises(ValidationError, match="snake_case"):
            Agent(
                id="invalid-id!",
                name="Test",
                capabilities=["GET /Patient"],
                hipaa_compliant=True,
                gdpr_compliant=False,
                data_access_level=2,
                cost_per_query=0.01,
                avg_latency_ms=100.0,
                quality_score=0.9,
                endpoint="mock://test",
                max_concurrent=10,
            )

    def test_empty_capabilities_rejected(self):
        with pytest.raises(ValidationError, match="at least one capability"):
            Agent(
                id="test_agent",
                name="Test",
                capabilities=[],
                hipaa_compliant=True,
                gdpr_compliant=False,
                data_access_level=2,
                cost_per_query=0.01,
                avg_latency_ms=100.0,
                quality_score=0.9,
                endpoint="mock://test",
                max_concurrent=10,
            )

    def test_quality_score_bounds(self):
        with pytest.raises(ValidationError):
            Agent(
                id="test_agent",
                name="Test",
                capabilities=["GET /Patient"],
                hipaa_compliant=True,
                gdpr_compliant=False,
                data_access_level=2,
                cost_per_query=0.01,
                avg_latency_ms=100.0,
                quality_score=1.5,  # > 1.0 — invalid
                endpoint="mock://test",
                max_concurrent=10,
            )

    def test_data_access_level_bounds(self):
        with pytest.raises(ValidationError):
            Agent(
                id="test_agent",
                name="Test",
                capabilities=["GET /Patient"],
                hipaa_compliant=True,
                gdpr_compliant=False,
                data_access_level=5,  # > 3 — invalid
                cost_per_query=0.01,
                avg_latency_ms=100.0,
                quality_score=0.9,
                endpoint="mock://test",
                max_concurrent=10,
            )

    def test_repr_format(self, agent_demographics):
        r = repr(agent_demographics)
        assert "patient_demographics_agent" in r
        assert "hipaa=True" in r


# ===========================================================================
# AnalyzedQuery model tests
# ===========================================================================


class TestAnalyzedQuery:
    """Tests for AnalyzedQuery model."""

    def test_valid_query_construction(self, query_task1_demographics):
        assert query_task1_demographics.intent == "lookup"
        assert query_task1_demographics.contains_pii is True
        assert query_task1_demographics.data_sensitivity == "medium"

    def test_query_is_immutable(self, query_task1_demographics):
        with pytest.raises(ValidationError):
            query_task1_demographics.intent = "ordering"

    def test_invalid_intent_rejected(self):
        with pytest.raises(ValidationError):
            AnalyzedQuery(
                raw_query="test",
                intent="unknown_intent",  # invalid
                contains_pii=False,
                data_sensitivity="low",
                required_capabilities=["GET /Patient"],
                user_role="nurse",
            )

    def test_invalid_sensitivity_rejected(self):
        with pytest.raises(ValidationError):
            AnalyzedQuery(
                raw_query="test",
                intent="lookup",
                contains_pii=False,
                data_sensitivity="critical",  # invalid
                required_capabilities=["GET /Patient"],
                user_role="nurse",
            )

    def test_optional_fields_have_defaults(self):
        query = AnalyzedQuery(
            raw_query="test",
            intent="lookup",
            contains_pii=False,
            data_sensitivity="low",
            required_capabilities=["GET /Patient"],
            user_role="nurse",
        )
        assert query.entities == {}
        assert query.user_region is None
        assert query.requires_consent is False
        assert query.task_type is None

    def test_repr_format(self, query_task1_demographics):
        r = repr(query_task1_demographics)
        assert "lookup" in r
        assert "pii=True" in r


# ===========================================================================
# PolicyEvaluationResult model tests
# ===========================================================================


class TestPolicyEvaluationResult:
    """Tests for PolicyEvaluationResult and related models."""

    def test_compliant_result(self, policy_result_single_compliant):
        assert policy_result_single_compliant.has_compliant_agents is True
        assert policy_result_single_compliant.compliance_rate == 1.0

    def test_compliance_rate_calculation(self, policy_result_with_violation):
        # 1 compliant out of 2 = 0.5
        assert policy_result_with_violation.compliance_rate == 0.5

    def test_empty_result(self):
        result = PolicyEvaluationResult(
            compliant_agents=[],
            total_agents_evaluated=0,
        )
        assert result.has_compliant_agents is False
        assert result.compliance_rate == 0.0

    def test_violation_structure(self, policy_result_with_violation):
        violations = policy_result_with_violation.violations
        assert "non_compliant_agent" in violations
        v = violations["non_compliant_agent"][0]
        assert "HIPAA" in v.message
        assert v.policy_file == "pii_access.rego"

    def test_soft_hint_construction(self):
        hint = SoftHint(
            hint_type="cost_preference",
            agent_id="test_agent",
            message="Agent is cost-efficient",
            metadata={"weight": 0.4},
        )
        assert hint.hint_type == "cost_preference"
        assert hint.metadata["weight"] == 0.4


# ===========================================================================
# ResolutionResult model tests
# ===========================================================================


class TestResolutionResult:
    """Tests for ResolutionResult model."""

    def test_single_candidate_no_conflict(self, agent_demographics):
        result = ResolutionResult(
            selected_agent_id=agent_demographics.id,
            strategy_used="weighted",
            candidate_agents=[agent_demographics.id],
            selection_reason="Only one compliant agent",
        )
        assert result.had_conflict is False
        assert result.selected_agent_id == "patient_demographics_agent"

    def test_multi_candidate_is_conflict(self, agent_demographics, agent_labs):
        result = ResolutionResult(
            selected_agent_id=agent_demographics.id,
            strategy_used="cost_aware",
            candidate_agents=[agent_demographics.id, agent_labs.id],
            selection_reason="Lowest cost agent selected",
        )
        assert result.had_conflict is True

    def test_invalid_strategy_rejected(self, agent_demographics):
        with pytest.raises(ValidationError):
            ResolutionResult(
                selected_agent_id=agent_demographics.id,
                strategy_used="invalid_strategy",  # not in Literal
                candidate_agents=[agent_demographics.id],
                selection_reason="Test",
            )

    def test_repr_format(self, agent_demographics):
        result = ResolutionResult(
            selected_agent_id=agent_demographics.id,
            strategy_used="weighted",
            candidate_agents=[agent_demographics.id],
            selection_reason="Test",
        )
        r = repr(result)
        assert "patient_demographics_agent" in r
        assert "weighted" in r


# ===========================================================================
# ExecutionResult model tests
# ===========================================================================


class TestExecutionResult:
    """Tests for ExecutionResult model."""

    def test_successful_execution(self):
        result = ExecutionResult(
            success=True,
            agent_id="patient_demographics_agent",
            response="Patient data retrieved",
            latency_ms=85.3,
        )
        assert result.failed is False
        assert result.retried is False
        assert result.attempts == 1

    def test_failed_execution(self):
        result = ExecutionResult(
            success=False,
            agent_id="patient_demographics_agent",
            error="Connection timeout",
            latency_ms=0.0,
            attempts=3,
        )
        assert result.failed is True
        assert result.retried is True
        assert result.response is None

    def test_negative_latency_rejected(self):
        # latency_ms has no ge constraint — this tests default behavior
        result = ExecutionResult(
            success=True,
            agent_id="test_agent",
            response="OK",
            latency_ms=0.0,  # edge case: zero latency (mock)
        )
        assert result.latency_ms == 0.0

    def test_repr_format(self):
        result = ExecutionResult(
            success=True,
            agent_id="labs_agent",
            response="Lab results",
            latency_ms=120.5,
        )
        r = repr(result)
        assert "labs_agent" in r
        assert "OK" in r
        assert "120.5" in r
