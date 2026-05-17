"""Baseline 1: Random Routing.

Randomly selects from available agents with no intelligence.
Purpose: sanity check — any intelligent routing should beat random.

Expected performance (paper Section 6.1):
    Routing Accuracy:    ~18%  (1/5 agents = 20% theoretical)
    Policy Compliance:   ~42%  (no enforcement)
    Auth Violations:     ~38%  (no authorization check)
"""

import random

from src.models.agent import Agent
from src.utils.logger import get_logger
from experiments.baselines.base_router import BaseRouter

logger = get_logger(__name__)


class RandomRouter(BaseRouter):
    """Randomly selects an agent from all available agents.

    No awareness of query content, policies, or capabilities.
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        logger.info("RandomRouter initialized", seed=seed)

    @property
    def name(self) -> str:
        return "Random"

    def route(
        self,
        question: str,
        agents: list[Agent],
        task_type: int | None = None,
        user_role: str = "nurse",
        **kwargs,
    ) -> str:
        if not agents:
            raise ValueError("RandomRouter: no agents available")
        selected = self._rng.choice(agents)
        logger.debug("Random selection", selected=selected.id)
        return selected.id
