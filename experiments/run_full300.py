#!/usr/bin/env python3
"""Experiment A: all 300 MedAgentBench tasks with the frozen analyzer (main agent pool).

Run from the repo root with no edits under src/:
    python experiments/run_full300.py
Outputs experiments/results/full300_results.json and full300_results.txt.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.baselines.embedding_router import EmbeddingRouter
from experiments.baselines.random_router import RandomRouter
from experiments.baselines.round_robin_router import RoundRobinRouter
from experiments.baselines.rule_based_router import RuleBasedRouter
from experiments.dataset import GROUND_TRUTH_MAP
from experiments.oracle import oracle_violations
from experiments.revision_common import (DENY, MAIN_CONFIG, dev_questions_in_sample_order,
                                         load_questions, make_components, pager_decide,
                                         pct, wilson)

OUT = Path("experiments/results")


def score(rows, name):
    """rows: list of (q, selected). Accuracy and oracle-violation rate."""
    pool = {a.id: a for a in COMP.pool}
    n = len(rows)
    ok = sum(1 for q, s in rows if s == GROUND_TRUTH_MAP[q["task"]])
    viol = sum(1 for q, s in rows if s != DENY and oracle_violations(pool[s], q["task"]))
    lo, hi = wilson(ok, n)
    return {"router": name, "n": n, "correct": ok, "accuracy_pct": round(100 * ok / n, 1),
            "wilson95": [round(lo, 1), round(hi, 1)], "oracle_violations": viol,
            "oracle_violation_pct": round(100 * viol / n, 1)}


def run_router(router_name, questions, agents):
    if router_name == "PAGER":
        return [(q, pager_decide(COMP, q)[0]) for q in questions]
    r = {"Random": lambda: RandomRouter(seed=42), "Round-Robin": RoundRobinRouter,
         "Rule-Based": RuleBasedRouter, "TF-IDF": EmbeddingRouter}[router_name]()
    return [(q, r.route(question=q["text"], agents=agents, task_type=q["task"],
                        user_role=q["role"])) for q in questions]


if __name__ == "__main__":
    COMP = make_components(MAIN_CONFIG)
    agents = COMP.pool
    allq = load_questions()
    devq = dev_questions_in_sample_order()
    ROUTERS = ["PAGER", "Random", "Round-Robin", "Rule-Based", "TF-IDF"]
    res = {"dev77_sample_order": [], "all300": [], "non_dev223": [], "per_task_accuracy": {}}

    for name in ROUTERS:  # reproduce the 77-query numbers with the oracle scoring
        res["dev77_sample_order"].append(score(run_router(name, devq, agents), name))

    timings, feat = [], Counter()
    full = {}
    for name in ROUTERS:
        if name == "PAGER":
            rows = []
            for q in allq:
                sel, a, ncap, ms = pager_decide(COMP, q)
                rows.append((q, sel)); timings.append((ms, ncap))
                feat["pii_agree"] += int(a.contains_pii is True)
                feat["sens_agree"] += int(a.data_sensitivity ==
                                          __import__("experiments.oracle", fromlist=["x"]).TASK_SENSITIVITY[q["task"]])
        else:
            rows = run_router(name, allq, agents)
        full[name] = rows
        res["all300"].append(score(rows, name))
        res["non_dev223"].append(score([(q, s) for q, s in rows if not q["dev"]], name))
        pt = defaultdict(lambda: [0, 0])
        for q, s in rows:
            pt[q["task"]][1] += 1
            pt[q["task"]][0] += int(s == GROUND_TRUTH_MAP[q["task"]])
        res["per_task_accuracy"][name] = {str(t): f"{v[0]}/{v[1]}" for t, v in sorted(pt.items())}

    ms = [t[0] for t in timings]
    res["pager_overhead_ms"] = {"n": len(ms), "mean": round(sum(ms) / len(ms), 1),
                                "p50": round(pct(ms, 50), 1), "p95": round(pct(ms, 95), 1),
                                "p99": round(pct(ms, 99), 1), "max": round(max(ms), 1),
                                "mean_capable_agents": round(sum(t[1] for t in timings) / len(timings), 2),
                                "queries_with_more_than_one_capable": sum(1 for t in timings if t[1] > 1)}
    res["analyzer_feature_agreement_with_oracle"] = {
        "contains_pii": f"{feat['pii_agree']}/300", "sensitivity": f"{feat['sens_agree']}/300"}
    res["note"] = ("Query text = instruction field only. Oracle violation = oracle P1/P2/P3 check "
                   "(experiments/oracle.py), independent of the QueryAnalyzer and OPA.")
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(OUT / "full300_results.json", "w"), indent=2)

    lines = ["EXPERIMENT A: full 300 tasks, frozen analyzer, main pool", ""]
    for key in ("dev77_sample_order", "all300", "non_dev223"):
        lines.append(f"[{key}]")
        for r in res[key]:
            lines.append(f"  {r['router']:12} acc {r['accuracy_pct']:5.1f}% ({r['correct']}/{r['n']}) "
                         f"Wilson95 {r['wilson95']}  oracle violations {r['oracle_violation_pct']}% "
                         f"({r['oracle_violations']})")
        lines.append("")
    lines.append("Per-task accuracy (300 run):")
    for k, v in res["per_task_accuracy"].items():
        lines.append(f"  {k:12} " + " ".join(f"T{t}:{c}" for t, c in v.items()))
    lines.append("")
    lines.append(f"PAGER end-to-end routing overhead (analysis+registry+OPA+resolver), ms: {res['pager_overhead_ms']}")
    lines.append(f"Analyzer feature agreement with oracle: {res['analyzer_feature_agreement_with_oracle']}")
    open(OUT / "full300_results.txt", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
