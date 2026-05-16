"""ExecutionCoordinator: Invokes the selected agent and captures results.

Handles mock agent execution for POC evaluation and provides the interface
for production agent invocation. Measures actual latency, handles timeouts,
and implements retry logic.

Design rationale (Section 4.6):
    PAGER's evaluation focuses on routing correctness — whether the
    framework selects the policy-compliant optimal agent — rather than
    agent response quality. Mock agents with deterministic behavior enable
    clean attribution of routing decisions to PolicyEngine and
    ConflictResolver, eliminating confounding variables from agent
    execution variability.
"""

import time

from src.models.agent import Agent
from src.models.execution import ExecutionResult
from src.models.query import AnalyzedQuery
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Mock response templates keyed by FHIR capability
_MOCK_RESPONSES: dict[str, str] = {
    "GET /Patient": (
        "Patient demographics retrieved successfully. "
        "Record includes name, MRN, DOB, address, and contact information."
    ),
    "POST /Observation": (
        "Vital signs recorded successfully. "
        "Observation stored in FHIR R4 format."
    ),
    "GET /Observation": (
        "Laboratory results retrieved successfully. "
        "Most recent values returned for requested analyte."
    ),
    "POST /MedicationRequest": (
        "Medication order created successfully. "
        "Prescription submitted for pharmacist review."
    ),
    "GET /MedicationRequest": (
        "Medication list retrieved successfully. "
        "Active prescriptions returned for patient."
    ),
    "POST /ServiceRequest": (
        "Referral/procedure order created successfully. "
        "ServiceRequest submitted for scheduling."
    ),
}

_DEFAULT_MOCK_RESPONSE = (
    "Request processed successfully by mock agent. "
    "Production deployment would return actual FHIR resource data."
)


class ExecutionCoordinator:
    """Invokes the selected agent and captures execution results.

    POC mode: Executes mock agents with deterministic responses.
    Production mode: Replace _invoke_mock() with real HTTP/API calls.

    The interface (execute() method signature and ExecutionResult model)
    is identical in both modes — only the invocation mechanism changes.

    Usage:
        coordinator = ExecutionCoordinator(timeout_seconds=30, max_retries=2)
        result = coordinator.execute(agent=selected_agent, query=analyzed_query)
    """

    def __init__(
        self,
        timeout_seconds: int = 30,
        max_retries: int = 2,
        retry_delay_seconds: float = 1.0,
    ) -> None:
        """Initialize ExecutionCoordinator.

        Args:
            timeout_seconds: Maximum seconds to wait for agent response.
            max_retries: Maximum retry attempts on failure (0 = no retries).
            retry_delay_seconds: Seconds to wait between retry attempts.
        """
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_delay_seconds = retry_delay_seconds

        logger.info(
            "ExecutionCoordinator initialized",
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    def execute(
        self,
        agent: Agent,
        query: AnalyzedQuery,
    ) -> ExecutionResult:
        """Invoke the selected agent and return structured execution result.

        Measures actual wall-clock latency. Retries on failure up to
        max_retries times. Returns ExecutionResult regardless of success/failure.

        Args:
            agent: The selected agent to invoke.
            query: The analyzed query to pass to the agent.

        Returns:
            ExecutionResult with response, latency, and attempt count.
        """
        last_error: str | None = None

        for attempt in range(1, self.max_retries + 2):  # +2: attempt 1 + retries
            start_time = time.perf_counter()
            try:
                response = self._invoke(agent, query)
                latency_ms = (time.perf_counter() - start_time) * 1000

                logger.info(
                    "Agent execution succeeded",
                    agent=agent.id,
                    latency_ms=f"{latency_ms:.1f}",
                    attempt=attempt,
                )

                return ExecutionResult(
                    success=True,
                    agent_id=agent.id,
                    response=response,
                    error=None,
                    latency_ms=round(latency_ms, 2),
                    attempts=attempt,
                )

            except Exception as e:
                latency_ms = (time.perf_counter() - start_time) * 1000
                last_error = str(e)
                logger.warning(
                    "Agent execution failed",
                    agent=agent.id,
                    attempt=attempt,
                    max_retries=self.max_retries,
                    error=last_error,
                )

                if attempt <= self.max_retries:
                    time.sleep(self.retry_delay_seconds)

        # All attempts exhausted
        final_latency = 0.0
        logger.error(
            "Agent execution failed after all retries",
            agent=agent.id,
            attempts=self.max_retries + 1,
            error=last_error,
        )
        return ExecutionResult(
            success=False,
            agent_id=agent.id,
            response=None,
            error=last_error,
            latency_ms=final_latency,
            attempts=self.max_retries + 1,
        )

    # ------------------------------------------------------------------
    # Invocation layer (swap this for production)
    # ------------------------------------------------------------------

    def _invoke(self, agent: Agent, query: AnalyzedQuery) -> str:
        """Invoke the agent and return its response string.

        POC: Returns deterministic mock response based on agent capability.
        Production: Replace with HTTP call to agent.endpoint.
        """
        if agent.endpoint.startswith("mock://"):
            return self._invoke_mock(agent, query)

        # Production path (not implemented in POC)
        raise NotImplementedError(
            f"Non-mock endpoint invocation not implemented in POC: {agent.endpoint}"
        )

    @staticmethod
    def _invoke_mock(agent: Agent, query: AnalyzedQuery) -> str:
        """Return deterministic mock response for evaluation.

        Selects response template based on agent's primary FHIR capability.
        """
        for capability in agent.capabilities:
            if capability in _MOCK_RESPONSES:
                return _MOCK_RESPONSES[capability]
        return _DEFAULT_MOCK_RESPONSE

    def __repr__(self) -> str:
        return (
            f"ExecutionCoordinator("
            f"timeout={self.timeout_seconds}s, "
            f"max_retries={self.max_retries})"
        )
