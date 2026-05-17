"""PAGER Main Evaluation Runner.

Runs all 3 experiments from the paper:
  Experiment 1: Main Evaluation (PAGER vs 4 baselines, 77 questions)
  Experiment 2: Ablation Study (PAGER-NoPolicy, PAGER-NoConflict, PAGER-Full)
  Experiment 3: Strategy Comparison (5 strategies + 5 weight configs)

Usage:
    python experiments/run_evaluation.py --experiment all
    python experiments/run_evaluation.py --experiment main
    python experiments/run_evaluation.py --experiment ablation
    python experiments/run_evaluation.py --experiment strategies
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pager.agent_registry import AgentRegistry
from src.pager.core import PAGER
from src.pager.conflict_resolver import ConflictResolver
from src.pager.execution_coordinator import ExecutionCoordinator
from src.pager.feedback_collector import FeedbackCollector
from src.pager.policy_engine import PolicyEngine
from src.pager.query_analyzer import QueryAnalyzer
from src.models.query import AnalyzedQuery
from experiments.baselines.base_router import RoutingDecision
from experiments.baselines.random_router import RandomRouter
from experiments.baselines.round_robin_router import RoundRobinRouter
from experiments.baselines.rule_based_router import RuleBasedRouter
from experiments.baselines.embedding_router import EmbeddingRouter
from experiments.dataset import (
    load_dataset,
    sample_questions,
    get_gdpr_scenarios,
    GROUND_TRUTH_MAP,
    TASK_USER_ROLES,
)
from experiments.metrics.metrics import (
    compute_metrics,
    print_results_table,
    EvaluationMetrics,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Paths
DATASET_PATH = Path("data/medagentbench/test_data_v2.json")
RESULTS_DIR = Path("data/results")
AGENT_CONFIG = "configs/agents/healthcare_agents.yaml"
POLICY_DIRS_HIPAA = ["policies/hipaa"]


# ---------------------------------------------------------------------------
# PAGER routing wrapper — produces RoutingDecision for metric computation
# ---------------------------------------------------------------------------

def run_pager(
    pager: PAGER,
    questions: list[dict],
    strategy_override: str | None = None,
) -> list[RoutingDecision]:
    """Run PAGER on all questions and return RoutingDecision list."""
    decisions = []
    for q in questions:
        raw_query = q.get("question") or q.get("query", "")
        task_type = q.get("task_type")
        user_role = q.get("user_role", TASK_USER_ROLES.get(task_type, "nurse"))
        ground_truth = q.get("ground_truth_agent", GROUND_TRUTH_MAP.get(task_type, ""))

        try:
            result = pager.route(
                query=raw_query,
                user_role=user_role,
                task_type=task_type,
                strategy_override=strategy_override,
                ground_truth_agent=ground_truth,
            )
            decision = RoutingDecision(
                router_name=pager.conflict_resolver.default_strategy,
                question_id=str(q.get("id", "")),
                task_type=task_type,
                selected_agent_id=result.selected_agent_id,
                ground_truth_agent_id=ground_truth,
                user_role=user_role,
                policy_enforced=True,
                has_violations=len(result.policy_result.violations) > 0,
                violation_messages=[
                    v.message
                    for vs in result.policy_result.violations.values()
                    for v in vs
                ],
                latency_ms=result.latency_ms,
            )
        except Exception as e:
            logger.error("PAGER routing failed", error=str(e), query=raw_query[:60])
            # Routing failure — mark as incorrect with no agent selected
            decision = RoutingDecision(
                router_name="PAGER",
                question_id=str(q.get("id", "")),
                task_type=task_type,
                selected_agent_id="__error__",
                ground_truth_agent_id=ground_truth,
                user_role=user_role,
                policy_enforced=True,
                has_violations=True,
                violation_messages=[str(e)],
            )
        decisions.append(decision)
    return decisions


def run_baseline(
    router,
    questions: list[dict],
    agents: list,
) -> list[RoutingDecision]:
    """Run a baseline router on all questions."""
    decisions = []
    for q in questions:
        raw_query = q.get("question") or q.get("query", "")
        task_type = q.get("task_type")
        user_role = q.get("user_role", TASK_USER_ROLES.get(task_type, "nurse"))
        ground_truth = q.get("ground_truth_agent", GROUND_TRUTH_MAP.get(task_type, ""))

        try:
            selected_id = router.route(
                question=raw_query,
                agents=agents,
                task_type=task_type,
                user_role=user_role,
            )
        except Exception as e:
            logger.error(f"{router.name} routing failed", error=str(e))
            selected_id = agents[0].id if agents else "__error__"

        decision = RoutingDecision(
            router_name=router.name,
            question_id=str(q.get("id", "")),
            task_type=task_type,
            selected_agent_id=selected_id,
            ground_truth_agent_id=ground_truth,
            user_role=user_role,
            policy_enforced=False,  # Baselines don't enforce policy
            has_violations=False,   # We don't check — baselines ignore policy
        )
        decisions.append(decision)
    return decisions


# ---------------------------------------------------------------------------
# Experiment 1: Main Evaluation
# ---------------------------------------------------------------------------

def run_experiment1(questions: list[dict], agents_by_id: dict) -> list[EvaluationMetrics]:
    """Experiment 1: PAGER vs 4 baselines on all 77 questions."""
    logger.info("=" * 60)
    logger.info("EXPERIMENT 1: Main Evaluation (PAGER vs 4 baselines)")
    logger.info("=" * 60)

    agents = list(agents_by_id.values())
    all_metrics = []

    # --- PAGER ---
    pager = PAGER(config_path="configs/pager_config.yaml", agent_domain="healthcare")
    pager_decisions = run_pager(pager, questions)
    pager_decisions_labeled = [
        RoutingDecision(**{**d.__dict__, "router_name": "PAGER"})
        for d in pager_decisions
    ]
    # Recompute with router_name fixed
    for d in pager_decisions:
        d.router_name = "PAGER"
    pager_metrics = compute_metrics(pager_decisions, "PAGER", agents_by_id)
    all_metrics.append(pager_metrics)

    # --- Random ---
    random_router = RandomRouter(seed=42)
    random_decisions = run_baseline(random_router, questions, agents)
    all_metrics.append(compute_metrics(random_decisions, "Random", agents_by_id))

    # --- Round-Robin ---
    rr_router = RoundRobinRouter()
    rr_decisions = run_baseline(rr_router, questions, agents)
    all_metrics.append(compute_metrics(rr_decisions, "Round-Robin", agents_by_id))

    # --- Rule-Based ---
    rb_router = RuleBasedRouter()
    rb_decisions = run_baseline(rb_router, questions, agents)
    all_metrics.append(compute_metrics(rb_decisions, "Rule-Based", agents_by_id))

    # --- Embedding ---
    emb_router = EmbeddingRouter()
    emb_decisions = run_baseline(emb_router, questions, agents)
    all_metrics.append(compute_metrics(emb_decisions, "Embedding", agents_by_id))

    # Save results
    save_results("experiment1_results.json", [m.to_dict() for m in all_metrics])

    # Print table
    print_results_table(all_metrics)

    # Save feedback
    pager.flush_feedback()

    return all_metrics


# ---------------------------------------------------------------------------
# Experiment 2: Ablation Study
# ---------------------------------------------------------------------------

def run_experiment2(questions: list[dict], agents_by_id: dict) -> list[EvaluationMetrics]:
    """Experiment 2: PAGER-NoPolicy vs PAGER-NoConflict vs PAGER-Full."""
    logger.info("=" * 60)
    logger.info("EXPERIMENT 2: Ablation Study")
    logger.info("=" * 60)

    agents = list(agents_by_id.values())
    all_metrics = []

    # --- PAGER-Full (baseline for ablation) ---
    pager_full = PAGER(config_path="configs/pager_config.yaml", agent_domain="healthcare")
    full_decisions = run_pager(pager_full, questions)
    for d in full_decisions:
        d.router_name = "PAGER-Full"
    all_metrics.append(compute_metrics(full_decisions, "PAGER-Full", agents_by_id))

    # --- PAGER-NoPolicy: ConflictResolver only, no PolicyEngine ---
    # Simulate by using RuleBasedRouter + ConflictResolver (no policy filter)
    # All agents pass "policy" — ConflictResolver picks best by weighted score
    resolver = ConflictResolver(default_strategy="weighted")
    analyzer = QueryAnalyzer()
    no_policy_decisions = []

    for q in questions:
        raw_query = q.get("question") or q.get("query", "")
        task_type = q.get("task_type")
        user_role = q.get("user_role", TASK_USER_ROLES.get(task_type, "nurse"))
        ground_truth = q.get("ground_truth_agent", GROUND_TRUTH_MAP.get(task_type, ""))

        from src.models.policy_result import PolicyEvaluationResult
        # No policy filtering — all agents are "compliant"
        fake_policy_result = PolicyEvaluationResult(
            compliant_agents=[a.id for a in agents],
            violations={},
            soft_hints=[],
            policy_trace={},
            total_agents_evaluated=len(agents),
        )
        try:
            resolution = resolver.resolve(
                candidates=agents,
                policy_result=fake_policy_result,
            )
            selected_id = resolution.selected_agent_id
        except Exception:
            selected_id = agents[0].id

        no_policy_decisions.append(RoutingDecision(
            router_name="PAGER-NoPolicy",
            question_id=str(q.get("id", "")),
            task_type=task_type,
            selected_agent_id=selected_id,
            ground_truth_agent_id=ground_truth,
            user_role=user_role,
            policy_enforced=False,
            has_violations=False,
        ))

    all_metrics.append(compute_metrics(no_policy_decisions, "PAGER-NoPolicy", agents_by_id))

    # --- PAGER-NoConflict: PolicyEngine only, random from compliant ---
    import random
    policy_engine = PolicyEngine(policy_dirs=POLICY_DIRS_HIPAA)
    no_conflict_decisions = []
    rng = random.Random(42)

    for q in questions:
        raw_query = q.get("question") or q.get("query", "")
        task_type = q.get("task_type")
        user_role = q.get("user_role", TASK_USER_ROLES.get(task_type, "nurse"))
        ground_truth = q.get("ground_truth_agent", GROUND_TRUTH_MAP.get(task_type, ""))

        analyzed = analyzer.analyze(
            raw_query=raw_query,
            user_role=user_role,
            task_type=task_type,
        )
        try:
            policy_result = policy_engine.evaluate(query=analyzed, agents=agents)
            compliant_ids = policy_result.compliant_agents
            compliant_agents = [a for a in agents if a.id in compliant_ids]
            selected_id = rng.choice(compliant_agents).id if compliant_agents else agents[0].id
            has_violations = bool(policy_result.violations)
        except Exception:
            selected_id = agents[0].id
            has_violations = False

        no_conflict_decisions.append(RoutingDecision(
            router_name="PAGER-NoConflict",
            question_id=str(q.get("id", "")),
            task_type=task_type,
            selected_agent_id=selected_id,
            ground_truth_agent_id=ground_truth,
            user_role=user_role,
            policy_enforced=True,
            has_violations=has_violations,
        ))

    all_metrics.append(compute_metrics(no_conflict_decisions, "PAGER-NoConflict", agents_by_id))

    save_results("experiment2_ablation.json", [m.to_dict() for m in all_metrics])
    print_results_table(all_metrics)

    return all_metrics


# ---------------------------------------------------------------------------
# Experiment 3: Strategy Comparison + Sensitivity Analysis
# ---------------------------------------------------------------------------

def run_experiment3(questions: list[dict], agents_by_id: dict) -> dict:
    """Experiment 3: 5 strategies + 5 weight configurations."""
    logger.info("=" * 60)
    logger.info("EXPERIMENT 3: Strategy Comparison + Sensitivity Analysis")
    logger.info("=" * 60)

    # Filter to conflict scenarios (multiple capable agents)
    conflict_questions = questions[:25]  # first 25 = conflict scenarios

    strategy_metrics = []

    # --- 5 Strategies ---
    strategies = ["cost_aware", "latency_aware", "quality_aware", "weighted", "round_robin"]

    for strategy in strategies:
        pager = PAGER(config_path="configs/pager_config.yaml", agent_domain="healthcare")
        decisions = run_pager(pager, conflict_questions, strategy_override=strategy)
        for d in decisions:
            d.router_name = strategy
        metrics = compute_metrics(decisions, strategy, agents_by_id)
        strategy_metrics.append(metrics)

    print("\n--- Strategy Comparison ---")
    print_results_table(strategy_metrics)

    # --- 5 Weight Configurations (sensitivity analysis) ---
    weight_configs = [
        ("Cost-heavy",    0.60, 0.20, 0.20),
        ("Balanced",      0.33, 0.33, 0.34),
        ("Default",       0.40, 0.30, 0.30),
        ("Quality-heavy", 0.20, 0.20, 0.60),
        ("Latency-heavy", 0.20, 0.60, 0.20),
    ]

    weight_metrics = []
    for label, wc, wl, wq in weight_configs:
        registry = AgentRegistry(AGENT_CONFIG)
        policy_engine = PolicyEngine(policy_dirs=POLICY_DIRS_HIPAA)
        resolver = ConflictResolver(
            default_strategy="weighted",
            cost_weight=wc,
            latency_weight=wl,
            quality_weight=wq,
        )
        executor = ExecutionCoordinator()
        collector = FeedbackCollector(enabled=False)
        analyzer = QueryAnalyzer()

        decisions = []
        for q in conflict_questions:
            raw_query = q.get("question") or q.get("query", "")
            task_type = q.get("task_type")
            user_role = q.get("user_role", TASK_USER_ROLES.get(task_type, "nurse"))
            ground_truth = q.get("ground_truth_agent", "")

            analyzed = analyzer.analyze(raw_query, user_role=user_role, task_type=task_type)
            capable = registry.get_capable_agents(analyzed)
            policy_result = policy_engine.evaluate(query=analyzed, agents=capable)

            if not policy_result.has_compliant_agents:
                selected_id = "__no_compliant__"
            else:
                resolution = resolver.resolve(
                    candidates=capable,
                    policy_result=policy_result,
                )
                selected_id = resolution.selected_agent_id

            decisions.append(RoutingDecision(
                router_name=label,
                question_id=str(q.get("id", "")),
                task_type=task_type,
                selected_agent_id=selected_id,
                ground_truth_agent_id=ground_truth,
                user_role=user_role,
                policy_enforced=True,
                has_violations=bool(policy_result.violations),
            ))

        metrics = compute_metrics(decisions, label, agents_by_id)
        weight_metrics.append(metrics)

    print("\n--- Weight Sensitivity Analysis ---")
    print_results_table(weight_metrics)

    results = {
        "strategy_comparison": [m.to_dict() for m in strategy_metrics],
        "weight_sensitivity": [m.to_dict() for m in weight_metrics],
    }
    save_results("experiment3_strategies.json", results)
    return results


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def save_results(filename: str, data) -> None:
    """Save results to data/results/."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info(f"Results saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="PAGER Evaluation Runner")
    parser.add_argument(
        "--experiment",
        choices=["main", "ablation", "strategies", "all"],
        default="all",
        help="Which experiment to run",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    # Load dataset
    logger.info("Loading MedAgentBench dataset...")
    dataset = load_dataset(DATASET_PATH)
    questions = sample_questions(dataset, seed=args.seed)
    gdpr_scenarios = get_gdpr_scenarios()
    all_questions = questions + gdpr_scenarios
    logger.info(f"Evaluation set: {len(all_questions)} questions ({len(questions)} MedAgentBench + {len(gdpr_scenarios)} GDPR)")

    # Load agents
    registry = AgentRegistry(AGENT_CONFIG)
    agents_by_id = {a.id: a for a in registry.get_all_agents()}

    # Run experiments
    if args.experiment in ("main", "all"):
        run_experiment1(all_questions, agents_by_id)

    if args.experiment in ("ablation", "all"):
        run_experiment2(all_questions, agents_by_id)

    if args.experiment in ("strategies", "all"):
        run_experiment3(all_questions, agents_by_id)

    logger.info("Evaluation complete. Results saved to data/results/")


if __name__ == "__main__":
    main()
