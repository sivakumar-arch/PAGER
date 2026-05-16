"""PAGER: Policy-Aware aGent RoutER."""

from src.pager.agent_registry import AgentRegistry
from src.pager.conflict_resolver import ConflictResolver
from src.pager.core import PAGER, RoutingResult
from src.pager.execution_coordinator import ExecutionCoordinator
from src.pager.feedback_collector import FeedbackCollector
from src.pager.policy_engine import PolicyEngine
from src.pager.query_analyzer import QueryAnalyzer

__version__ = "0.1.0"
__author__ = "Siva Kumar Chintham"

__all__ = [
    "PAGER",
    "RoutingResult",
    "QueryAnalyzer",
    "AgentRegistry",
    "PolicyEngine",
    "ConflictResolver",
    "ExecutionCoordinator",
    "FeedbackCollector",
]
