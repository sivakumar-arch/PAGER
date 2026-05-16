"""Unit tests for FeedbackCollector.

Tests record accumulation, summary computation, persistence, and clearing.
"""

import json

import pytest

from src.models.execution import ExecutionResult
from src.models.resolution import ResolutionResult
from src.pager.feedback_collector import FeedbackCollector


@pytest.fixture
def collector(tmp_path) -> FeedbackCollector:
    return FeedbackCollector(
        output_dir=str(tmp_path / "feedback"),
        filename="test_feedback.json",
        enabled=True,
    )


@pytest.fixture
def resolution_result(agent_demographics) -> ResolutionResult:
    return ResolutionResult(
        selected_agent_id=agent_demographics.id,
        strategy_used="weighted",
        candidate_agents=[agent_demographics.id],
        selection_reason="Only one compliant agent",
    )


@pytest.fixture
def execution_result() -> ExecutionResult:
    return ExecutionResult(
        success=True,
        agent_id="patient_demographics_agent",
        response="Patient demographics retrieved",
        latency_ms=85.5,
    )


class TestRecording:
    """Tests for feedback record accumulation."""

    def test_record_added(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
        )
        assert len(collector) == 1

    def test_multiple_records(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        for _ in range(5):
            collector.record(
                query=query_task1_demographics,
                policy_result=policy_result_single_compliant,
                resolution=resolution_result,
                execution=execution_result,
            )
        assert len(collector) == 5

    def test_ground_truth_tracked(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
            ground_truth_agent="patient_demographics_agent",
        )
        records = collector.get_records()
        assert records[0]["evaluation"]["ground_truth_agent"] == "patient_demographics_agent"
        assert records[0]["evaluation"]["routing_correct"] is True

    def test_incorrect_routing_tracked(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
            ground_truth_agent="labs_agent",  # wrong agent
        )
        records = collector.get_records()
        assert records[0]["evaluation"]["routing_correct"] is False

    def test_record_structure(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
        )
        record = collector.get_records()[0]
        assert "timestamp" in record
        assert "query" in record
        assert "policy_evaluation" in record
        assert "resolution" in record
        assert "execution" in record
        assert "evaluation" in record


class TestSummary:
    """Tests for summary aggregation."""

    def test_empty_summary(self, collector):
        summary = collector.summary()
        assert summary["total_records"] == 0

    def test_routing_accuracy_calculation(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        # Record 2 correct, 1 wrong
        for _ in range(2):
            collector.record(
                query=query_task1_demographics,
                policy_result=policy_result_single_compliant,
                resolution=resolution_result,
                execution=execution_result,
                ground_truth_agent="patient_demographics_agent",
            )
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
            ground_truth_agent="labs_agent",  # wrong
        )
        summary = collector.summary()
        assert summary["total_records"] == 3
        assert abs(summary["routing_accuracy"] - 2/3) < 1e-6

    def test_avg_latency_computed(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
        )
        summary = collector.summary()
        assert summary["avg_latency_ms"] == 85.5


class TestPersistence:
    """Tests for JSON file persistence."""

    def test_flush_writes_file(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result, tmp_path
    ):
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
        )
        path = collector.flush()
        assert path.exists()
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 1

    def test_flush_disabled_is_noop(
        self, tmp_path, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        disabled = FeedbackCollector(
            output_dir=str(tmp_path / "disabled"),
            enabled=False,
        )
        disabled.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
        )
        path = disabled.flush()
        assert not path.exists()


class TestClear:
    """Tests for record clearing."""

    def test_clear_empties_records(
        self, collector, query_task1_demographics,
        policy_result_single_compliant, resolution_result, execution_result
    ):
        collector.record(
            query=query_task1_demographics,
            policy_result=policy_result_single_compliant,
            resolution=resolution_result,
            execution=execution_result,
        )
        assert len(collector) == 1
        collector.clear()
        assert len(collector) == 0
