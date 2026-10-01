#!/usr/bin/env python3
"""Tier 2 held-out validation for PAGER Paper 1 (Tasks 5 and 9 paraphrases).

Place this file in the experiments/ folder of the PAGER repo and run from the
repo root, on the frozen code, with NO edits under src/:

    python experiments/run_tier2_heldout.py tier2_heldout_queries.json

It mirrors the PAGER path in experiments/run_evaluation.py
(QueryAnalyzer -> AgentRegistry.get_capable_agents -> PolicyEngine ->
ConflictResolver), using the same registry config, policy dir, default
weighted strategy, and the same user role the evaluation used for Tasks 5/9.
No API key or network access is needed.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from experiments.dataset import GROUND_TRUTH_MAP, TASK_USER_ROLES
from src.pager.agent_registry import AgentRegistry
from src.pager.conflict_resolver import ConflictResolver
from src.pager.policy_engine import PolicyEngine
from src.pager.query_analyzer import QueryAnalyzer

AGENT_CONFIG = "configs/agents/healthcare_agents.yaml"
POLICY_DIRS_HIPAA = ["policies/hipaa"]


def main(path: str) -> None:
    data = json.load(open(path))
    analyzer = QueryAnalyzer()
    registry = AgentRegistry(AGENT_CONFIG)
    engine = PolicyEngine(policy_dirs=POLICY_DIRS_HIPAA)
    resolver = ConflictResolver(default_strategy="weighted")  # 0.4/0.3/0.3

    rows = []
    per_task = {5: Counter(), 9: Counter()}
    for q in data["queries"]:
        task = q["task"]
        expected = GROUND_TRUTH_MAP[task]          # same ground truth as eval
        role = TASK_USER_ROLES[task]               # same role as eval
        analyzed = analyzer.analyze(q["text"], user_role=role, task_type=task)
        capable = registry.get_capable_agents(analyzed)
        policy = engine.evaluate(query=analyzed, agents=capable)
        if not policy.has_compliant_agents:
            got = "__no_compliant__"
        else:
            got = resolver.resolve(
                candidates=capable, policy_result=policy
            ).selected_agent_id
        ok = got == expected
        per_task[task]["ok" if ok else "fail"] += 1
        rows.append((q["id"], ok, got, analyzed.intent, q["text"]))

    print(f"{'ID':7}{'OK':4}{'routed_to':28}{'intent':14}query")
    for r in rows:
        print(f"{r[0]:7}{'Y' if r[1] else 'N':4}{r[2]:28}{r[3]:14}{r[4][:60]}")
    n_ok = sum(r[1] for r in rows)
    print(f"\nHeld-out routing accuracy: {n_ok}/{len(rows)} = {100*n_ok/len(rows):.1f}%")
    for t, c in per_task.items():
        print(f"  Task {t}: {c['ok']}/{c['ok'] + c['fail']}")
    # Failures are reported, never fixed: do not touch the pattern table.


if __name__ == "__main__":
    main(sys.argv[1])
