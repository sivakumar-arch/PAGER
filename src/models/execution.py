"""ExecutionResult data model.

Represents the structured output of ExecutionCoordinator — the agent's
response, measured latency, and success/error status.
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    """Result of invoking the selected agent.

    Produced by ExecutionCoordinator. Consumed by FeedbackCollector and
    returned as the final PAGER routing response.

    Note: PAGER evaluates routing correctness, not response quality.
    The response field is stored for audit purposes; evaluation metrics
    focus on whether the correct agent was selected, not what it returned.
    """

    model_config = {"frozen": True}

    # --- Outcome ---
    success: bool = Field(description="True if agent invocation completed without error")
    agent_id: str = Field(description="ID of the agent that was invoked")

    # --- Response ---
    response: str | None = Field(
        default=None,
        description="Agent response payload (None if execution failed)",
    )
    error: str | None = Field(
        default=None,
        description="Error message if execution failed (None on success)",
    )

    # --- Performance measurement ---
    latency_ms: float = Field(
        description="Actual measured latency from invocation to response (ms)"
    )

    # --- Retry tracking ---
    attempts: int = Field(
        default=1,
        ge=1,
        description="Number of invocation attempts (1 = no retries needed)",
    )

    # --- Metadata ---
    executed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when execution began (UTC)",
    )

    @property
    def failed(self) -> bool:
        """True if execution did not succeed."""
        return not self.success

    @property
    def retried(self) -> bool:
        """True if at least one retry was needed."""
        return self.attempts > 1

    def __repr__(self) -> str:
        status = "OK" if self.success else f"ERROR({self.error})"
        return (
            f"ExecutionResult("
            f"agent={self.agent_id!r}, "
            f"status={status}, "
            f"latency={self.latency_ms:.1f}ms)"
        )
