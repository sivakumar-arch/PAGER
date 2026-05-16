"""FeedbackCollector: Audit trail and routing outcome recording.

Records complete routing decisions — query, policy evaluation, conflict
resolution, and execution result — as structured JSON for analysis and
paper metrics computation.

Design rationale (Section 4.7):
    Implementing feedback infrastructure demonstrates architectural
    extensibility without over-committing to adaptive learning before
    empirical validation. The collected data supports:
      1. Evaluation metric calculation (Experiments 1-3)
      2. Policy compliance audit trail
      3. Foundation for future adaptive conflict resolution
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from src.models.execution import ExecutionResult
from src.models.policy_result import PolicyEvaluationResult
from src.models.query import AnalyzedQuery
from src.models.resolution import ResolutionResult
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FeedbackCollector:
    """Records routing decisions and outcomes for analysis.

    Each call to record() appends one FeedbackRecord to an in-memory
    list and optionally persists to a JSON Lines file.

    Usage:
        collector = FeedbackCollector(output_dir="data/feedback")
        collector.record(query, policy_result, resolution, execution)
        collector.flush()  # Persist to disk
        records = collector.get_records()  # For in-memory analysis
    """

    def __init__(
        self,
        output_dir: str | Path = "data/feedback",
        filename: str = "feedback.json",
        enabled: bool = True,
    ) -> None:
        """Initialize FeedbackCollector.

        Args:
            output_dir: Directory for persisting feedback records.
            filename: Output JSON file name.
            enabled: Set False to disable persistence (in-memory only).
        """
        self.output_dir = Path(output_dir)
        self.filename = filename
        self.enabled = enabled
        self._records: list[dict] = []

        if self.enabled:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "FeedbackCollector initialized",
                output=str(self.output_dir / self.filename),
            )
        else:
            logger.info("FeedbackCollector initialized (in-memory only, persistence disabled)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        query: AnalyzedQuery,
        policy_result: PolicyEvaluationResult,
        resolution: ResolutionResult,
        execution: ExecutionResult,
        ground_truth_agent: str | None = None,
    ) -> None:
        """Record a complete routing decision and outcome.

        Args:
            query: Analyzed query that was routed.
            policy_result: Output of PolicyEngine evaluation.
            resolution: Output of ConflictResolver selection.
            execution: Output of ExecutionCoordinator invocation.
            ground_truth_agent: Expected agent ID (evaluation only).
        """
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_type": query.task_type,
            "query": {
                "raw": query.raw_query,
                "intent": query.intent,
                "contains_pii": query.contains_pii,
                "data_sensitivity": query.data_sensitivity,
                "required_capabilities": query.required_capabilities,
                "user_role": query.user_role,
            },
            "policy_evaluation": {
                "compliant_agents": policy_result.compliant_agents,
                "denied_agents": list(policy_result.violations.keys()),
                "violations": {
                    agent_id: [
                        {"policy": v.policy_file, "message": v.message}
                        for v in violations
                    ]
                    for agent_id, violations in policy_result.violations.items()
                },
                "total_evaluated": policy_result.total_agents_evaluated,
                "compliance_rate": policy_result.compliance_rate,
            },
            "resolution": {
                "selected_agent": resolution.selected_agent_id,
                "strategy": resolution.strategy_used,
                "candidates": resolution.candidate_agents,
                "reason": resolution.selection_reason,
                "tie_broken": resolution.tie_broken,
                "strategy_overridden": resolution.strategy_overridden,
            },
            "execution": {
                "success": execution.success,
                "agent_invoked": execution.agent_id,
                "latency_ms": execution.latency_ms,
                "attempts": execution.attempts,
                "error": execution.error,
            },
            "evaluation": {
                "ground_truth_agent": ground_truth_agent,
                "routing_correct": (
                    resolution.selected_agent_id == ground_truth_agent
                    if ground_truth_agent
                    else None
                ),
                "policy_compliant": execution.success and not policy_result.violations.get(
                    resolution.selected_agent_id
                ),
            },
        }

        self._records.append(record)
        logger.debug(
            "Feedback recorded",
            task=query.task_type,
            selected=resolution.selected_agent_id,
            correct=record["evaluation"]["routing_correct"],
        )

    def flush(self) -> Path:
        """Persist all in-memory records to JSON file.

        Returns:
            Path to the written file.

        Raises:
            IOError: If file cannot be written.
        """
        if not self.enabled:
            logger.warning("FeedbackCollector persistence disabled — flush is a no-op")
            return self.output_dir / self.filename

        output_path = self.output_dir / self.filename
        with open(output_path, "w") as f:
            json.dump(self._records, f, indent=2, default=str)

        logger.info(
            "Feedback flushed to disk",
            records=len(self._records),
            path=str(output_path),
        )
        return output_path

    def get_records(self) -> list[dict]:
        """Return all in-memory feedback records (read-only copy)."""
        return list(self._records)

    def summary(self) -> dict:
        """Return aggregate metrics across all recorded routing decisions.

        Returns:
            Dict with routing accuracy, compliance rate, avg latency, etc.
        """
        if not self._records:
            return {"total_records": 0}

        total = len(self._records)
        correct = sum(
            1 for r in self._records
            if r["evaluation"]["routing_correct"] is True
        )
        compliant = sum(
            1 for r in self._records
            if r["evaluation"]["policy_compliant"] is True
        )
        latencies = [
            r["execution"]["latency_ms"]
            for r in self._records
            if r["execution"]["latency_ms"] > 0
        ]

        return {
            "total_records": total,
            "routing_accuracy": correct / total if total > 0 else 0.0,
            "policy_compliance_rate": compliant / total if total > 0 else 0.0,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
            "strategies_used": list(
                {r["resolution"]["strategy"] for r in self._records}
            ),
        }

    def clear(self) -> None:
        """Clear all in-memory records (does not delete persisted file)."""
        self._records.clear()
        logger.info("FeedbackCollector records cleared")

    def __len__(self) -> int:
        return len(self._records)

    def __repr__(self) -> str:
        return (
            f"FeedbackCollector("
            f"records={len(self._records)}, "
            f"output={self.output_dir / self.filename})"
        )
