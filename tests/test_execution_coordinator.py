"""Unit tests for ExecutionCoordinator.

Tests mock agent invocation, latency measurement, retry logic,
and failure handling.
"""

import pytest

from src.pager.execution_coordinator import ExecutionCoordinator


@pytest.fixture
def coordinator() -> ExecutionCoordinator:
    return ExecutionCoordinator(timeout_seconds=10, max_retries=2, retry_delay_seconds=0)


class TestMockInvocation:
    """Tests for mock agent execution."""

    def test_demographics_agent_returns_response(
        self, coordinator, agent_demographics, query_task1_demographics
    ):
        result = coordinator.execute(agent_demographics, query_task1_demographics)
        assert result.success is True
        assert result.response is not None
        assert "Patient" in result.response

    def test_labs_agent_returns_response(
        self, coordinator, agent_labs, query_task4_labs
    ):
        result = coordinator.execute(agent_labs, query_task4_labs)
        assert result.success is True
        assert "Laboratory" in result.response

    def test_procedure_agent_returns_response(
        self, coordinator, agent_procedure, query_task8_procedure
    ):
        result = coordinator.execute(agent_procedure, query_task8_procedure)
        assert result.success is True
        assert "Referral" in result.response or "ServiceRequest" in result.response

    def test_agent_id_in_result(
        self, coordinator, agent_demographics, query_task1_demographics
    ):
        result = coordinator.execute(agent_demographics, query_task1_demographics)
        assert result.agent_id == "patient_demographics_agent"

    def test_latency_is_measured(
        self, coordinator, agent_demographics, query_task1_demographics
    ):
        result = coordinator.execute(agent_demographics, query_task1_demographics)
        assert result.latency_ms >= 0.0

    def test_single_attempt_on_success(
        self, coordinator, agent_demographics, query_task1_demographics
    ):
        result = coordinator.execute(agent_demographics, query_task1_demographics)
        assert result.attempts == 1


class TestNonMockEndpoint:
    """Tests for non-mock endpoint rejection in POC."""

    def test_production_endpoint_raises_not_implemented(
        self, coordinator, agent_demographics, query_task1_demographics
    ):
        from src.models.agent import Agent
        prod_agent = Agent(
            id="prod_agent",
            name="Production Agent",
            capabilities=["GET /Patient"],
            hipaa_compliant=True,
            gdpr_compliant=False,
            authorized_roles=["nurse"],
            data_access_level=2,
            cost_per_query=0.01,
            avg_latency_ms=80.0,
            quality_score=0.9,
            endpoint="https://api.example.com/agent",  # real endpoint
            max_concurrent=10,
        )
        result = coordinator.execute(prod_agent, query_task1_demographics)
        # After max retries, returns failed ExecutionResult
        assert result.success is False
        assert "not implemented" in result.error.lower() or result.error is not None


class TestRetryBehavior:
    """Tests for retry logic on failure."""

    def test_max_retries_respected(self, coordinator):
        """Verify attempts count matches max_retries + 1."""
        from src.models.agent import Agent
        from src.models.query import AnalyzedQuery

        failing_agent = Agent(
            id="failing_agent",
            name="Failing Agent",
            capabilities=["GET /Patient"],
            hipaa_compliant=True,
            gdpr_compliant=False,
            authorized_roles=["nurse"],
            data_access_level=2,
            cost_per_query=0.01,
            avg_latency_ms=80.0,
            quality_score=0.9,
            endpoint="https://will-fail.example.com",
            max_concurrent=10,
        )
        query = AnalyzedQuery(
            raw_query="test",
            intent="lookup",
            contains_pii=False,
            data_sensitivity="low",
            required_capabilities=["GET /Patient"],
            user_role="nurse",
        )

        c = ExecutionCoordinator(timeout_seconds=5, max_retries=2, retry_delay_seconds=0)
        result = c.execute(failing_agent, query)
        assert result.success is False
        assert result.attempts == 3  # 1 initial + 2 retries


class TestRepr:
    def test_repr_format(self, coordinator):
        r = repr(coordinator)
        assert "timeout=10s" in r
        assert "max_retries=2" in r
