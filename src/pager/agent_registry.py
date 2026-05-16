"""AgentRegistry: Static YAML-based agent configuration and capability management.

Loads agent definitions from YAML config files, validates them against the
Agent Pydantic model, and provides capability-based filtering for routing.

Design rationale (Section 4.4):
    Static YAML configuration simplifies POC evaluation and testing.
    Dynamic agent registration is explicitly out of scope — an engineering
    concern rather than a research contribution of PAGER.
"""

from pathlib import Path

from src.models.agent import Agent
from src.models.query import AnalyzedQuery
from src.utils.config_loader import load_agents_config
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AgentRegistry:
    """Manages the catalog of available agents and their capabilities.

    Loads agents from YAML config at initialization. All state is
    immutable after construction — consistent with static registry design.

    Usage:
        registry = AgentRegistry("configs/agents/healthcare_agents.yaml")
        capable = registry.get_capable_agents(analyzed_query)
    """

    def __init__(self, config_path: str | Path) -> None:
        """Initialize registry from YAML agent configuration.

        Args:
            config_path: Path to agents YAML file.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            ValidationError: If any agent definition fails Pydantic validation.
        """
        self._config_path = Path(config_path)
        self._agents: dict[str, Agent] = {}
        self._load_agents()

    def _load_agents(self) -> None:
        """Load and validate all agents from YAML config."""
        raw_agents = load_agents_config(self._config_path)
        for raw in raw_agents:
            agent = Agent(**raw)
            self._agents[agent.id] = agent

        logger.info(
            "AgentRegistry loaded",
            config=str(self._config_path),
            agent_count=len(self._agents),
            agent_ids=list(self._agents.keys()),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all_agents(self) -> list[Agent]:
        """Return all registered agents."""
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> Agent:
        """Return agent by ID.

        Args:
            agent_id: Unique agent identifier.

        Raises:
            KeyError: If agent_id is not registered.
        """
        if agent_id not in self._agents:
            raise KeyError(f"Agent not found in registry: {agent_id!r}")
        return self._agents[agent_id]

    def get_capable_agents(self, query: AnalyzedQuery) -> list[Agent]:
        """Return agents with at least one capability matching the query.

        An agent is considered capable if any of its listed capabilities
        matches any of the query's required_capabilities.

        Args:
            query: Analyzed query with required_capabilities list.

        Returns:
            List of capable agents (may be empty if none qualify).
        """
        if not query.required_capabilities:
            logger.warning(
                "Query has no required_capabilities — returning all agents",
                raw_query=query.raw_query[:80],
            )
            return self.get_all_agents()

        capable = [
            agent
            for agent in self._agents.values()
            if self._has_capability_overlap(agent, query.required_capabilities)
        ]

        logger.debug(
            "Capability filter applied",
            required=query.required_capabilities,
            capable_agents=[a.id for a in capable],
            total_agents=len(self._agents),
        )
        return capable

    def count(self) -> int:
        """Return total number of registered agents."""
        return len(self._agents)

    def agent_ids(self) -> list[str]:
        """Return all registered agent IDs."""
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _has_capability_overlap(
        agent: Agent, required: list[str]
    ) -> bool:
        """True if the agent supports at least one required capability."""
        agent_caps = set(agent.capabilities)
        return bool(agent_caps.intersection(required))

    def __repr__(self) -> str:
        return f"AgentRegistry(agents={list(self._agents.keys())})"
