"""Unit tests for AgentRegistry.

Tests YAML loading, agent lookup, capability-based filtering,
and validation error handling.
"""

import pytest

from src.models.agent import Agent
from src.models.query import AnalyzedQuery
from src.pager.agent_registry import AgentRegistry
from src.utils.config_loader import ConfigLoadError


@pytest.fixture
def registry(tmp_path) -> AgentRegistry:
    """AgentRegistry loaded from the real healthcare agents config."""
    return AgentRegistry("configs/agents/healthcare_agents.yaml")


@pytest.fixture
def minimal_yaml(tmp_path):
    """Create a minimal YAML file for testing validation."""
    yaml_content = """
agents:
  - id: test_agent_one
    name: "Test Agent One"
    capabilities:
      - "GET /Patient"
    hipaa_compliant: true
    gdpr_compliant: false
    authorized_roles:
      - nurse
    data_access_level: 2
    cost_per_query: 0.01
    avg_latency_ms: 50.0
    quality_score: 0.90
    endpoint: "mock://test_one"
    max_concurrent: 10

  - id: test_agent_two
    name: "Test Agent Two"
    capabilities:
      - "GET /Observation"
      - "lab_results"
    hipaa_compliant: true
    gdpr_compliant: false
    authorized_roles:
      - doctor
    data_access_level: 3
    cost_per_query: 0.04
    avg_latency_ms: 100.0
    quality_score: 0.95
    endpoint: "mock://test_two"
    max_concurrent: 20
"""
    config_file = tmp_path / "test_agents.yaml"
    config_file.write_text(yaml_content)
    return str(config_file)


class TestRegistryLoading:
    """Tests for YAML loading and agent validation."""

    def test_loads_all_healthcare_agents(self, registry):
        assert registry.count() == 5

    def test_all_expected_agent_ids_present(self, registry):
        ids = registry.agent_ids()
        assert "patient_demographics_agent" in ids
        assert "vitals_agent" in ids
        assert "labs_agent" in ids
        assert "medication_agent" in ids
        assert "procedure_agent" in ids

    def test_file_not_found_raises(self):
        with pytest.raises(ConfigLoadError):
            AgentRegistry("nonexistent/path/agents.yaml")

    def test_missing_agents_key_raises(self, tmp_path):
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("not_agents:\n  - id: test\n")
        with pytest.raises(ConfigLoadError, match="missing required top-level"):
            AgentRegistry(str(bad_yaml))

    def test_agents_are_pydantic_validated(self, minimal_yaml):
        registry = AgentRegistry(minimal_yaml)
        agents = registry.get_all_agents()
        assert all(isinstance(a, Agent) for a in agents)


class TestAgentLookup:
    """Tests for agent retrieval by ID."""

    def test_get_existing_agent(self, registry):
        agent = registry.get_agent("patient_demographics_agent")
        assert agent.id == "patient_demographics_agent"
        assert agent.hipaa_compliant is True

    def test_get_missing_agent_raises(self, registry):
        with pytest.raises(KeyError, match="not found in registry"):
            registry.get_agent("nonexistent_agent")

    def test_get_all_agents_returns_list(self, registry):
        agents = registry.get_all_agents()
        assert isinstance(agents, list)
        assert len(agents) == 5


class TestCapabilityFiltering:
    """Tests for capability-based agent filtering."""

    def test_demographics_query_returns_demographics_agent(self, registry, query_task1_demographics):
        capable = registry.get_capable_agents(query_task1_demographics)
        capable_ids = [a.id for a in capable]
        assert "patient_demographics_agent" in capable_ids

    def test_labs_query_returns_labs_agent(self, registry, query_task4_labs):
        capable = registry.get_capable_agents(query_task4_labs)
        capable_ids = [a.id for a in capable]
        assert "labs_agent" in capable_ids

    def test_procedure_query_returns_procedure_agent(self, registry, query_task8_procedure):
        capable = registry.get_capable_agents(query_task8_procedure)
        capable_ids = [a.id for a in capable]
        assert "procedure_agent" in capable_ids

    def test_wrong_capability_excluded(self, registry, query_task8_procedure):
        """Demographics agent should not match procedure query."""
        capable = registry.get_capable_agents(query_task8_procedure)
        capable_ids = [a.id for a in capable]
        assert "patient_demographics_agent" not in capable_ids

    def test_no_capabilities_returns_all(self, registry):
        """Query with no required capabilities returns all agents."""
        query = AnalyzedQuery(
            raw_query="General query",
            intent="retrieval",
            contains_pii=False,
            data_sensitivity="low",
            required_capabilities=[],
            user_role="nurse",
        )
        capable = registry.get_capable_agents(query)
        assert len(capable) == registry.count()

    def test_unknown_capability_returns_empty(self, registry):
        """Query with unrecognized capability returns no agents."""
        query = AnalyzedQuery(
            raw_query="Unknown operation",
            intent="retrieval",
            contains_pii=False,
            data_sensitivity="low",
            required_capabilities=["UNKNOWN /Operation"],
            user_role="nurse",
        )
        capable = registry.get_capable_agents(query)
        assert len(capable) == 0
