#!/usr/bin/env python3
"""Experiment B: adversarial pool, denial queries, and baselines with an OPA gate.

Run from the repo root with no edits under src/:
    python experiments/run_adversarial.py
Outputs experiments/results/adversarial_results.json and adversarial_results.txt.

Pool: configs/agents/healthcare_agents_adversarial.yaml (4 original agents plus 5
capability-equivalent non-compliant clones; Task 8 has only a non-compliant agent, so
the correct outcome for Task 8 is DENIAL). All outcomes are scored by the independent
oracle in experiments/oracle.py, not by the QueryAnalyzer or OPA.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.baselines.embedding_router import EmbeddingRouter
from experiments.baselines.random_router import RandomRouter
from experiments.baselines.round_robin_router import RoundRobinRouter
from experiments.baselines.rule_based_router import RuleBasedRouter
from experiments.dataset import GROUND_TRUTH_MAP
from experiments.oracle import FAMILY, TASK_CONTAINS_PII, TASK_SENSITIVITY, oracle_ok_set, oracle_violations
from experiments.revision_common import (ADV_CONFIG, DENY, MAIN_CONFIG, load_questions,
                                         make_components, pager_decide, family_decide, wilson)
from src.pager.agent_registry import AgentRegistry

OUT = Path("experiments/results")


def evaluate(rows, pool_by_id, pool):
    """rows: list of (q, selected). Returns metric dict scored by the oracle."""
    n = len(rows)
    correct = viol = false_allow = false_deny = misroute = 0
    n_deny_expected = n_deny_got_correct = 0
    viol_given_right_family = right_family = 0
    for q, s in rows:
        ok_set = oracle_ok_set(pool, q["task"])
        expect_deny = len(ok_set) == 0
        if expect_deny:
            n_deny_expected += 1
        if s == DENY:
            if expect_deny:
                correct += 1
                n_deny_got_correct += 1
            else:
                false_deny += 1
            continue
        a = pool_by_id[s]
        v = bool(oracle_violations(a, q["task"]))
        viol += int(v)
        if expect_deny:
            false_allow += 1
        fam_ok = FAMILY.get(s, s) == GROUND_TRUTH_MAP[q["task"]]
        right_family += int(fam_ok)
        if fam_ok:
            viol_given_right_family += int(v)
        else:
            misroute += 1
        if s in ok_set:
            correct += 1
    lo, hi = wilson(correct, n)
    return {
        "n": n, "correct": correct, "accuracy_pct": round(100 * correct / n, 1),
        "wilson95": [round(lo, 1), round(hi, 1)],
        "oracle_violations": viol, "violation_pct": round(100 * viol / n, 1),
        "wrong_family": misroute,
        "queries_in_right_family": right_family,
        "violations_among_right_family": viol_given_right_family,
        "denial_expected": n_deny_expected, "denial_correct": n_deny_got_correct,
        "false_allow": false_allow, "false_deny": false_deny,
    }


if __name__ == "__main__":
    comp = make_components(ADV_CONFIG)
    pool = comp.pool
    pool_by_id = {a.id: a for a in pool}
    canonical = AgentRegistry(MAIN_CONFIG).get_all_agents()  # the 5 original agents (families)
    questions = load_questions()

    rr = RoundRobinRouter()
    rnd = RandomRouter(seed=42)
    rule, tfidf = RuleBasedRouter(), EmbeddingRouter()

    decisions = {}
    decisions["PAGER"] = [(q, pager_decide(comp, q, gate=True)[0]) for q in questions]
    decisions["PAGER-NoPolicy"] = [(q, pager_decide(comp, q, gate=False)[0]) for q in questions]
    decisions["Random"] = [(q, rnd.route(question=q["text"], agents=pool, task_type=q["task"],
                                         user_role=q["role"])) for q in questions]
    decisions["Round-Robin"] = [(q, rr.route(question=q["text"], agents=pool, task_type=q["task"],
                                             user_role=q["role"])) for q in questions]
    for label, base in (("Rule-Based", rule), ("TF-IDF", tfidf)):
        decisions[f"{label} (cheapest tie-break)"] = [
            (q, family_decide(comp, base, canonical, q, "cheapest", False)) for q in questions]
        decisions[f"{label} (registry-order tie-break)"] = [
            (q, family_decide(comp, base, canonical, q, "first", False)) for q in questions]
        decisions[f"{label} (random tie-break)"] = [
            (q, family_decide(comp, base, canonical, q, "random", False)) for q in questions]
        decisions[f"{label} + OPA gate"] = [
            (q, family_decide(comp, base, canonical, q, "cheapest", True)) for q in questions]

    results = {name: evaluate(rows, pool_by_id, pool) for name, rows in decisions.items()}

    # Held-out paraphrases (Tasks 5 and 9) in the adversarial pool, scored by the oracle,
    # plus analyzer feature agreement (PII flag) on those queries.
    held = json.load(open("experiments/heldout/tier2_heldout_queries.json"))["queries"]
    from experiments.dataset import TASK_USER_ROLES
    hq = [{"id": h["id"], "task": h["task"], "text": h["text"], "role": TASK_USER_ROLES[h["task"]]}
          for h in held]
    hrows, pii_missed = [], 0
    for q in hq:
        sel, a, _, _ = pager_decide(comp, q, gate=True)
        hrows.append((q, sel))
        pii_missed += int(not a.contains_pii and TASK_CONTAINS_PII[q["task"]])
    results["_heldout20_PAGER"] = evaluate(hrows, pool_by_id, pool)
    results["_heldout20_PAGER"]["pii_flag_missed_by_analyzer"] = f"{pii_missed}/{len(hq)}"
    results["_heldout20_PAGER"]["selected"] = dict(Counter(s for _, s in hrows))
    results["_heldout20_PAGER"]["violating_ids"] = [
        q["id"] for q, s in hrows if s != DENY and oracle_violations(pool_by_id[s], q["task"])]
    import csv
    with open(OUT / "adversarial_heldout20_decisions.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["id", "task", "selected", "oracle_violations", "analyzer_pii_flag"])
        for (q, s) in hrows:
            a = comp.analyzer.analyze(q["text"], user_role=q["role"], task_type=q["task"])
            w.writerow([q["id"], q["task"], s,
                        "+".join(oracle_violations(pool_by_id[s], q["task"])) if s != DENY else "",
                        a.contains_pii])
    with open(OUT / "adversarial_decisions.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["id", "task", "router", "selected"])
        for name, rows in decisions.items():
            for q, s in rows:
                w.writerow([q["id"], q["task"], name, s])

    # Analyzer features vs oracle annotation on the 300 tasks
    agree = Counter()
    for q in questions:
        a = comp.analyzer.analyze(q["text"], user_role=q["role"], task_type=q["task"])
        agree["pii"] += int(a.contains_pii == TASK_CONTAINS_PII[q["task"]])
        agree["sens"] += int(a.data_sensitivity == TASK_SENSITIVITY[q["task"]])
    results["_feature_agreement_300"] = {"contains_pii": f"{agree['pii']}/300",
                                         "sensitivity": f"{agree['sens']}/300"}
    results["_pool"] = {"agents": [a.id for a in pool],
                        "denial_queries": sum(1 for q in questions if not oracle_ok_set(pool, q["task"]))}

    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(results, open(OUT / "adversarial_results.json", "w"), indent=2)

    hdr = f"{'Router':44}{'Acc%':>6}{'Viol':>6}{'WrongFam':>9}{'Viol|RightFam':>14}{'FalseAllow':>11}{'FalseDeny':>10}{'DenyOK':>8}"
    lines = ["EXPERIMENT B: adversarial pool, 300 tasks, oracle-scored", f"Pool: {results['_pool']}", "", hdr]
    for name, r in results.items():
        if name.startswith("_"):
            continue
        lines.append(f"{name:44}{r['accuracy_pct']:>6}{r['oracle_violations']:>6}{r['wrong_family']:>9}"
                     f"{str(r['violations_among_right_family'])+'/'+str(r['queries_in_right_family']):>14}"
                     f"{r['false_allow']:>11}{r['false_deny']:>10}"
                     f"{str(r['denial_correct'])+'/'+str(r['denial_expected']):>8}")
    lines += ["", f"Held-out 20 in adversarial pool (PAGER): {results['_heldout20_PAGER']}",
              f"Analyzer feature agreement with oracle (300 tasks): {results['_feature_agreement_300']}"]
    open(OUT / "adversarial_results.txt", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
