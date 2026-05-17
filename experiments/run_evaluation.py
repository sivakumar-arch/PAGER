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

        # Determine if this is a genuine conflict scenario (2+ capable agents)
        from src.pager.agent_registry import AgentRegistry as _AR
        from src.pager.query_analyzer import QueryAnalyzer as _QA
        _analyzer_tmp = _QA()
        _registry_tmp = _AR(AGENT_CONFIG)
        _analyzed_tmp = _analyzer_tmp.analyze(raw_query, user_role=user_role, task_type=task_type)
        _capable_tmp = _registry_tmp.get_capable_agents(_analyzed_tmp)
        had_conflict = len(_capable_tmp) > 1

        try:
            result = pager.route(
                query=raw_query,
                user_role=user_role,
                task_type=task_type,
                strategy_override=strategy_override,
                ground_truth_agent=ground_truth,
            )
            selected_denied = result.selected_agent_id in result.policy_result.violations
            decision = RoutingDecision(
                router_name="PAGER",
                question_id=str(q.get("id", "")),
                task_type=task_type,
                selected_agent_id=result.selected_agent_id,
                ground_truth_agent_id=ground_truth,
                user_role=user_role,
                policy_enforced=True,
                has_violations=selected_denied,
                had_conflict=had_conflict,
                violation_messages=[
                    v.message
                    for vs in result.policy_result.violations.values()
                    for v in vs
                ] if selected_denied else [],
                latency_ms=result.latency_ms,
            )
        except ValueError as e:
            logger.warning("PAGER: no compliant agents", error=str(e), query=raw_query[:60])
            decision = RoutingDecision(
                router_name="PAGER",
                question_id=str(q.get("id", "")),
                task_type=task_type,
                selected_agent_id="__no_compliant__",
                ground_truth_agent_id=ground_truth,
                user_role=user_role,
                policy_enforced=True,
                has_violations=False,
                had_conflict=had_conflict,
                violation_messages=[],
            )
        except Exception as e:
            logger.error("PAGER routing error", error=str(e), query=raw_query[:60])
            decision = RoutingDecision(
                router_name="PAGER",
                question_id=str(q.get("id", "")),
                task_type=task_type,
                selected_agent_id="__error__",
                ground_truth_agent_id=ground_truth,
                user_role=user_role,
                policy_enforced=True,
                has_violations=False,
                had_conflict=had_conflict,
                violation_messages=[],
            )
        decisions.append(decision)
    return decisions


def run_baseline(
    router,
    questions: list[dict],
    agents: list,
    policy_engine: "PolicyEngine | None" = None,
    analyzer: "QueryAnalyzer | None" = None,
) -> list[RoutingDecision]:
    """Run a baseline router on all questions with post-hoc policy checking.

    Baselines don't enforce policies during routing, but we check post-hoc
    whether their selected agent would violate policies. This gives a fair
    apples-to-apples comparison of what baselines WOULD produce in a
    policy-aware enterprise environment.
    """
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

        # Post-hoc policy check: would this decision violate policies?
        has_violations = False
        violation_msgs = []
        if policy_engine and analyzer:
            try:
                analyzed = analyzer.analyze(
                    raw_query=raw_query,
                    user_role=user_role,
                    task_type=task_type,
                )
                selected_agent = next((a for a in agents if a.id == selected_id), None)
                if selected_agent:
                    policy_result = policy_engine.evaluate(
                        query=analyzed, agents=[selected_agent]
                    )
                    has_violations = selected_id in policy_result.violations
                    if has_violations:
                        violation_msgs = [
                            v.message
                            for v in policy_result.violations.get(selected_id, [])
                        ]
            except Exception as e:
                logger.debug(f"Post-hoc policy check failed: {e}")

        # Track whether this was a conflict scenario (2+ capable agents)
        had_conflict = False
        if analyzer:
            try:
                from src.pager.agent_registry import AgentRegistry as _AR2
                _reg2 = _AR2(AGENT_CONFIG)
                _analyzed2 = analyzer.analyze(raw_query, user_role=user_role, task_type=task_type)
                _capable2 = _reg2.get_capable_agents(_analyzed2)
                had_conflict = len(_capable2) > 1
            except Exception:
                pass

        decision = RoutingDecision(
            router_name=router.name,
            question_id=str(q.get("id", "")),
            task_type=task_type,
            selected_agent_id=selected_id,
            ground_truth_agent_id=ground_truth,
            user_role=user_role,
            policy_enforced=False,
            has_violations=has_violations,
            had_conflict=had_conflict,
            violation_messages=violation_msgs,
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
    for d in pager_decisions:
        d.router_name = "PAGER"
    pager_metrics = compute_metrics(pager_decisions, "PAGER", agents_by_id)
    all_metrics.append(pager_metrics)

    # Shared policy engine + analyzer for post-hoc baseline policy checking
    baseline_policy_engine = PolicyEngine(policy_dirs=POLICY_DIRS_HIPAA)
    baseline_analyzer = QueryAnalyzer()

    # --- Random ---
    random_router = RandomRouter(seed=42)
    random_decisions = run_baseline(random_router, questions, agents,
                                    baseline_policy_engine, baseline_analyzer)
    all_metrics.append(compute_metrics(random_decisions, "Random", agents_by_id))

    # --- Round-Robin ---
    rr_router = RoundRobinRouter()
    rr_decisions = run_baseline(rr_router, questions, agents,
                                baseline_policy_engine, baseline_analyzer)
    all_metrics.append(compute_metrics(rr_decisions, "Round-Robin", agents_by_id))

    # --- Rule-Based ---
    rb_router = RuleBasedRouter()
    rb_decisions = run_baseline(rb_router, questions, agents,
                                baseline_policy_engine, baseline_analyzer)
    all_metrics.append(compute_metrics(rb_decisions, "Rule-Based", agents_by_id))

    # --- Embedding ---
    emb_router = EmbeddingRouter()
    emb_decisions = run_baseline(emb_router, questions, agents,
                                 baseline_policy_engine, baseline_analyzer)
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

    # --- PAGER-NoPolicy: QueryAnalyzer + ConflictResolver, no PolicyEngine ---
    # Uses capability-based filtering (QueryAnalyzer) but skips policy enforcement.
    # ConflictResolver picks best from ALL capable agents regardless of compliance.
    # Demonstrates: without PolicyEngine, routing is accurate but unsafe.
    from src.models.policy_result import PolicyEvaluationResult
    resolver_nopolicy = ConflictResolver(default_strategy="weighted")
    analyzer_nopolicy = QueryAnalyzer()
    registry_nopolicy = AgentRegistry(AGENT_CONFIG)
    no_policy_decisions = []
    nopolicy_policy_engine = PolicyEngine(policy_dirs=POLICY_DIRS_HIPAA)

    for q in questions:
        raw_query = q.get("question") or q.get("query", "")
        task_type = q.get("task_type")
        user_role = q.get("user_role", TASK_USER_ROLES.get(task_type, "nurse"))
        ground_truth = q.get("ground_truth_agent", GROUND_TRUTH_MAP.get(task_type, ""))

        analyzed = analyzer_nopolicy.analyze(
            raw_query=raw_query, user_role=user_role, task_type=task_type
        )
        capable = registry_nopolicy.get_capable_agents(analyzed)
        if not capable:
            capable = agents

        # No policy filtering — all capable agents treated as compliant
        fake_policy_result = PolicyEvaluationResult(
            compliant_agents=[a.id for a in capable],
            violations={},
            soft_hints=[],
            policy_trace={},
            total_agents_evaluated=len(capable),
        )
        try:
            resolution = resolver_nopolicy.resolve(
                candidates=capable,
                policy_result=fake_policy_result,
            )
            selected_id = resolution.selected_agent_id
        except Exception:
            selected_id = capable[0].id if capable else agents[0].id

        # Post-hoc: check if selected agent would have been denied by policy
        try:
            selected_agent = next(a for a in capable if a.id == selected_id)
            check_result = nopolicy_policy_engine.evaluate(
                query=analyzed, agents=[selected_agent]
            )
            has_violations = selected_id in check_result.violations
        except Exception:
            has_violations = False

        no_policy_decisions.append(RoutingDecision(
            router_name="PAGER-NoPolicy",
            question_id=str(q.get("id", "")),
            task_type=task_type,
            selected_agent_id=selected_id,
            ground_truth_agent_id=ground_truth,
            user_role=user_role,
            policy_enforced=False,
            has_violations=has_violations,
        ))

    all_metrics.append(compute_metrics(no_policy_decisions, "PAGER-NoPolicy", agents_by_id))

    # --- PAGER-NoConflict: PolicyEngine only, random from compliant ---
    import random
    policy_engine = PolicyEngine(policy_dirs=POLICY_DIRS_HIPAA)
    analyzer_noconflict = QueryAnalyzer()
    no_conflict_decisions = []
    rng = random.Random(42)

    for q in questions:
        raw_query = q.get("question") or q.get("query", "")
        task_type = q.get("task_type")
        user_role = q.get("user_role", TASK_USER_ROLES.get(task_type, "nurse"))
        ground_truth = q.get("ground_truth_agent", GROUND_TRUTH_MAP.get(task_type, ""))

        analyzed = analyzer_noconflict.analyze(
            raw_query=raw_query,
            user_role=user_role,
            task_type=task_type,
        )
        try:
            policy_result = policy_engine.evaluate(query=analyzed, agents=agents)
            compliant_ids = policy_result.compliant_agents
            compliant_agents = [a for a in agents if a.id in compliant_ids]
            selected_id = rng.choice(compliant_agents).id if compliant_agents else agents[0].id
            # Violation = selected agent was denied (not: ANY agent was denied)
            has_violations = selected_id in policy_result.violations
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

    # Filter to genuine conflict scenarios — queries where multiple agents
    # are capable (Task 3: vitals + labs both have POST /Observation).
    # This is the only task type in our 5-agent configuration that produces
    # a real capability conflict requiring ConflictResolver to arbitrate.
    registry_check = AgentRegistry(AGENT_CONFIG)
    analyzer_check = QueryAnalyzer()
    conflict_questions = []
    for q in questions:
        raw = q.get("question", "")
        analyzed = analyzer_check.analyze(
            raw_query=raw,
            user_role=q.get("user_role", "nurse"),
            task_type=q.get("task_type"),
        )
        capable = registry_check.get_capable_agents(analyzed)
        if len(capable) > 1:
            conflict_questions.append(q)

    # Debug: show task distribution in sampled questions
    task_counts = {}
    for q in questions:
        t = q.get("task_type")
        task_counts[t] = task_counts.get(t, 0) + 1
    logger.info(f"Task distribution in sampled questions: {dict(sorted(task_counts.items()))}")

    # Debug: show first Task 3 question analysis
    task3_qs = [q for q in questions if q.get("task_type") == 3]
    if task3_qs:
        q = task3_qs[0]
        raw = q.get("question", "")
        analyzed_debug = analyzer_check.analyze(
            raw_query=raw,
            user_role=q.get("user_role", "nurse"),
            task_type=q.get("task_type"),
        )
        capable_debug = registry_check.get_capable_agents(analyzed_debug)
        logger.info(f"Task 3 sample query: {raw[:80]}")
        logger.info(f"Task 3 capabilities: {analyzed_debug.required_capabilities}")
        logger.info(f"Task 3 capable agents: {[a.id for a in capable_debug]}")

    logger.info(
        f"Conflict questions identified: {len(conflict_questions)} "
        f"(queries with 2+ capable agents)"
    )
    if not conflict_questions:
        logger.warning("No conflict questions found — strategy comparison will be trivial")
        conflict_questions = questions[:10]  # fallback

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
    logger.info(
        f"Evaluation set: {len(questions)} MedAgentBench + "
        f"{len(gdpr_scenarios)} GDPR = {len(questions) + len(gdpr_scenarios)} total"
    )

    # Load healthcare agents (used for Experiments 1-3)
    registry = AgentRegistry(AGENT_CONFIG)
    agents_by_id = {a.id: a for a in registry.get_all_agents()}

    # Note: GDPR scenarios use a separate domain — Experiment 1 runs on
    # MedAgentBench questions only. GDPR validation is a separate cross-domain check.
    # Baselines also run on MedAgentBench only for fair comparison.
    eval_questions = questions  # 75 MedAgentBench questions

    # Run experiments
    if args.experiment in ("main", "all"):
        run_experiment1(eval_questions, agents_by_id)

    if args.experiment in ("ablation", "all"):
        run_experiment2(eval_questions, agents_by_id)

    if args.experiment in ("strategies", "all"):
        run_experiment3(eval_questions, agents_by_id)

    logger.info("Evaluation complete. Results saved to data/results/")

    logger.info("Evaluation complete. Results saved to data/results/")


if __name__ == "__main__":
    main()
