"""Base router interface for PAGER baselines.

All baseline routers implement this interface so the evaluation runner
can treat them uniformly alongside PAGER.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.models.agent import Agent
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RoutingDecision:
    """Uniform result structure for all routers (baselines + PAGER).

    Enables apples-to-apples metric computation across all systems.
    """
    router_name: str
    question_id: str
    task_type: int | None
    selected_agent_id: str
    ground_truth_agent_id: str
    user_role: str

    # Routing correctness
    is_correct: bool = field(init=False)

    # Policy compliance (baselines don't enforce)
    policy_enforced: bool = False
    has_violations: bool = False
    violation_messages: list[str] = field(default_factory=list)

    # Conflict resolution tracking
    # True only when 2+ agents were capable — real ConflictResolver scenario
    had_conflict: bool = False

    # Performance
    latency_ms: float = 0.0
    cost_per_query: float = 0.0

    # Metadata
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""

    def __post_init__(self):
        self.is_correct = self.selected_agent_id == self.ground_truth_agent_id


class BaseRouter(ABC):
    """Abstract base class for all routing systems."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Router name for reporting."""
        ...

    @abstractmethod
    def route(
        self,
        question: str,
        agents: list[Agent],
        task_type: int | None = None,
        user_role: str = "nurse",
        **kwargs,
    ) -> str:
        """Select an agent for the given question.

        Args:
            question: Raw question text.
            agents: Available agents to route to.
            task_type: MedAgentBench task type (1-10).
            user_role: Requesting user's role.
            **kwargs: Additional context (user_region, etc.)

        Returns:
            Selected agent ID.
        """
        ...
