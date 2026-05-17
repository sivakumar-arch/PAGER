"""Baseline 2: Round-Robin Routing.

Distributes queries evenly across agents in fixed rotation.
Purpose: load balancing baseline — sequential distribution with no intelligence.

Expected performance (paper Section 6.1):
    Routing Accuracy:    ~21%  (slightly better than random due to fixed order)
    Policy Compliance:   ~44%
    Auth Violations:     ~36%
"""

from src.models.agent import Agent
from src.utils.logger import get_logger
from experiments.baselines.base_router import BaseRouter

logger = get_logger(__name__)


class RoundRobinRouter(BaseRouter):
    """Rotates sequentially through agents regardless of query content."""

    def __init__(self) -> None:
        self._index: int = 0
        logger.info("RoundRobinRouter initialized")

    @property
    def name(self) -> str:
        return "Round-Robin"

    def route(
        self,
        question: str,
        agents: list[Agent],
        task_type: int | None = None,
        user_role: str = "nurse",
        **kwargs,
    ) -> str:
        if not agents:
            raise ValueError("RoundRobinRouter: no agents available")

        # Sort by ID for deterministic ordering
        sorted_agents = sorted(agents, key=lambda a: a.id)
        selected = sorted_agents[self._index % len(sorted_agents)]
        self._index += 1

        logger.debug(
            "Round-robin selection",
            selected=selected.id,
            position=self._index,
        )
        return selected.id

    def reset(self) -> None:
        """Reset rotation index — call between evaluation runs."""
        self._index = 0
