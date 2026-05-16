"""PAGER Core: Main orchestrator wiring all 6 components together.

Provides the primary public interface for the PAGER framework.
Routes a raw query through the full pipeline:

    QueryAnalyzer → AgentRegistry → PolicyEngine → ConflictResolver
    → ExecutionCoordinator → FeedbackCollector

Design rationale:
    This module is a thin orchestration layer — it wires components
    together and manages data flow. All domain logic lives in the
    individual components. This separation enables component-level
    unit testing and clean ablation studies (disable PolicyEngine
    or ConflictResolver to test baseline behaviors).
"""

from dataclasses import dataclass
from pathlib import Path

from src.models.execution import ExecutionResult
from src.models.policy_result import PolicyEvaluationResult
from src.models.query import AnalyzedQuery
from src.models.resolution import ResolutionResult
from src.pager.agent_registry import AgentRegistry
from src.pager.conflict_resolver import ConflictResolver
from src.pager.execution_coordinator import ExecutionCoordinator
from src.pager.feedback_collector import FeedbackCollector
from src.pager.policy_engine import PolicyEngine
from src.pager.query_analyzer import QueryAnalyzer
from src.utils.config_loader import load_yaml
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RoutingResult:
    """Complete output of a single PAGER routing decision.

    Bundles all pipeline outputs for inspection, testing, and metric collection.
    """

    query: AnalyzedQuery
    policy_result: PolicyEvaluationResult
    resolution: ResolutionResult
    execution: ExecutionResult

    @property
    def selected_agent_id(self) -> str:
        return self.resolution.selected_agent_id

    @property
    def success(self) -> bool:
        return self.execution.success

    @property
    def response(self) -> str | None:
        return self.execution.response

    @property
    def latency_ms(self) -> float:
        return self.execution.latency_ms

    def __repr__(self) -> str:
        return (
            f"RoutingResult("
            f"agent={self.selected_agent_id!r}, "
            f"success={self.success}, "
            f"latency={self.latency_ms:.1f}ms)"
        )


class PAGER:
    """Policy-Aware aGent RoutER — main orchestrator.

    Initializes and wires all 6 PAGER components from configuration.
    Provides a single route() method as the primary public interface.

    Usage:
        router = PAGER(config_path="configs/pager_config.yaml")
        result = router.route(
            query="What is the MRN of patient Peter Stafford, DOB 1932-12-29?",
            user_role="nurse",
        )
        print(result.selected_agent_id)
        print(result.response)
    """

    def __init__(
        self,
        config_path: str | Path = "configs/pager_config.yaml",
        agent_domain: str = "healthcare",
    ) -> None:
        """Initialize PAGER from configuration file.

        Args:
            config_path: Path to pager_config.yaml.
            agent_domain: Which agent domain to load ('healthcare' or 'gdpr').

        Raises:
            FileNotFoundError: If config file or agent configs don't exist.
            ValueError: If configuration is invalid.
        """
        config_path = Path(config_path)
        config = load_yaml(config_path)
        pager_cfg = config["pager"]

        logger.info(
            "Initializing PAGER",
            version=pager_cfg.get("version", "0.1.0"),
            domain=agent_domain,
        )

        # 1. QueryAnalyzer
        self.query_analyzer = QueryAnalyzer()

        # 2. AgentRegistry — load domain-specific agents
        agent_config_path = pager_cfg["agent_configs"][agent_domain]
        self.agent_registry = AgentRegistry(agent_config_path)

        # 3. PolicyEngine — load domain-specific policies
        policy_domain = "gdpr" if agent_domain == "gdpr" else "hipaa"
        policy_dir = pager_cfg["policy_dirs"][policy_domain]
        self.policy_engine = PolicyEngine(policy_dirs=[policy_dir])

        # 4. ConflictResolver
        weighted_cfg = pager_cfg.get("weighted_strategy", {})
        strategy = pager_cfg.get("default_conflict_strategy", "weighted")
        self.conflict_resolver = ConflictResolver(
            default_strategy=strategy,
            cost_weight=weighted_cfg.get("cost_weight", 0.4),
            latency_weight=weighted_cfg.get("latency_weight", 0.3),
            quality_weight=weighted_cfg.get("quality_weight", 0.3),
        )

        # 5. ExecutionCoordinator
        exec_cfg = pager_cfg.get("execution", {})
        self.execution_coordinator = ExecutionCoordinator(
            timeout_seconds=exec_cfg.get("timeout_seconds", 30),
            max_retries=exec_cfg.get("max_retries", 2),
            retry_delay_seconds=exec_cfg.get("retry_delay_seconds", 1),
        )

        # 6. FeedbackCollector
        feedback_cfg = pager_cfg.get("feedback", {})
        self.feedback_collector = FeedbackCollector(
            output_dir=feedback_cfg.get("output_dir", "data/feedback"),
            filename=feedback_cfg.get("filename", "feedback.json"),
            enabled=feedback_cfg.get("enabled", True),
        )

        logger.info(
            "PAGER initialized successfully",
            agents=self.agent_registry.count(),
            policies=self.policy_engine.policy_count(),
            strategy=strategy,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(
        self,
        query: str,
        user_role: str,
        user_region: str | None = None,
        requires_consent: bool = False,
        task_type: int | None = None,
        strategy_override: str | None = None,
        ground_truth_agent: str | None = None,
    ) -> RoutingResult:
        """Route a query through the full PAGER pipeline.

        Args:
            query: Raw natural language query string.
            user_role: Role of the requesting user (e.g. 'nurse', 'doctor').
            user_region: Data region for GDPR residency checks (e.g. 'EU').
            requires_consent: True for marketing queries requiring consent.
            task_type: MedAgentBench task number (1-10), if known.
            strategy_override: Override conflict resolution strategy for this query.
            ground_truth_agent: Expected agent ID for evaluation tracking.

        Returns:
            RoutingResult with all pipeline outputs.

        Raises:
            ValueError: If no compliant agents are available for the query.
        """
        logger.info(
            "Routing query",
            query=query[:80],
            user_role=user_role,
            task_type=task_type,
        )

        # Step 1: Analyze query
        analyzed_query = self.query_analyzer.analyze(
            raw_query=query,
            user_role=user_role,
            user_region=user_region,
            requires_consent=requires_consent,
            task_type=task_type,
        )

        # Step 2: Get capable agents from registry
        capable_agents = self.agent_registry.get_capable_agents(analyzed_query)

        # Step 3: Evaluate policy compliance
        policy_result = self.policy_engine.evaluate(
            query=analyzed_query,
            agents=capable_agents,
        )

        if not policy_result.has_compliant_agents:
            logger.error(
                "No compliant agents — all candidates denied by policy",
                denied=list(policy_result.violations.keys()),
            )
            raise ValueError(
                f"No policy-compliant agents available for query. "
                f"Denied agents: {list(policy_result.violations.keys())}"
            )

        # Step 4: Resolve conflicts
        resolution = self.conflict_resolver.resolve(
            candidates=capable_agents,
            policy_result=policy_result,
            strategy_override=strategy_override,
        )

        # Step 5: Execute selected agent
        selected_agent = self.agent_registry.get_agent(resolution.selected_agent_id)
        execution = self.execution_coordinator.execute(
            agent=selected_agent,
            query=analyzed_query,
        )

        # Step 6: Record feedback
        self.feedback_collector.record(
            query=analyzed_query,
            policy_result=policy_result,
            resolution=resolution,
            execution=execution,
            ground_truth_agent=ground_truth_agent,
        )

        result = RoutingResult(
            query=analyzed_query,
            policy_result=policy_result,
            resolution=resolution,
            execution=execution,
        )

        logger.info(
            "Routing complete",
            selected=result.selected_agent_id,
            success=result.success,
            latency_ms=f"{result.latency_ms:.1f}",
        )
        return result

    def flush_feedback(self) -> Path:
        """Persist all collected feedback records to disk."""
        return self.feedback_collector.flush()

    def feedback_summary(self) -> dict:
        """Return aggregate metrics from collected feedback."""
        return self.feedback_collector.summary()

    def __repr__(self) -> str:
        return (
            f"PAGER("
            f"agents={self.agent_registry.count()}, "
            f"policies={self.policy_engine.policy_count()}, "
            f"strategy={self.conflict_resolver.default_strategy!r})"
        )
