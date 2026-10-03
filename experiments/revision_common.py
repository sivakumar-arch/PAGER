"""Shared helpers for the Paper 1 revision experiments (A: 300 tasks, B: adversarial pool)."""

import math
import time
from dataclasses import dataclass

from experiments.dataset import (GROUND_TRUTH_MAP, TASK_USER_ROLES,
                                 load_dataset, sample_questions)
from src.models.policy_result import PolicyEvaluationResult
from src.pager.agent_registry import AgentRegistry
from src.pager.conflict_resolver import ConflictResolver
from src.pager.policy_engine import PolicyEngine
from src.pager.query_analyzer import QueryAnalyzer

DATA_PATH = "data/medagentbench/test_data_v2.json"
MAIN_CONFIG = "configs/agents/healthcare_agents.yaml"
ADV_CONFIG = "configs/agents/healthcare_agents_adversarial.yaml"
POLICY_DIRS = ["policies/hipaa"]
DENY = "__deny__"
import random as _random
_TIE_RNG = _random.Random(42)  # seeded neutral tie-break for gate-less baselines


def load_questions():
    """All 300 tasks (question text = instruction field, as in the main evaluation)."""
    data = load_dataset(DATA_PATH)
    dev_ids = {q["id"] for q in sample_questions(data)}  # the 77 development queries
    out = []
    for r in data:
        t = r["task_type"]
        out.append({"id": r["id"], "task": t, "text": r["question"],
                    "role": TASK_USER_ROLES[t], "dev": r["id"] in dev_ids})
    return out


def dev_questions_in_sample_order():
    data = load_dataset(DATA_PATH)
    s = sample_questions(data)
    return [{"id": r["id"], "task": r["task_type"], "text": r["question"],
             "role": TASK_USER_ROLES[r["task_type"]], "dev": True} for r in s]


@dataclass
class Components:
    analyzer: QueryAnalyzer
    registry: AgentRegistry
    engine: PolicyEngine
    resolver: ConflictResolver

    @property
    def pool(self):
        return self.registry.get_all_agents()


def make_components(config: str) -> Components:
    return Components(QueryAnalyzer(), AgentRegistry(config),
                      PolicyEngine(policy_dirs=POLICY_DIRS),
                      ConflictResolver(default_strategy="weighted"))


def pager_decide(c: Components, q: dict, gate: bool = True):
    """Full PAGER path (or no-gate ablation). Returns (selected_id | DENY, analyzed, n_capable, ms)."""
    t0 = time.perf_counter()
    a = c.analyzer.analyze(q["text"], user_role=q["role"], task_type=q["task"])
    cap = c.registry.get_capable_agents(a)
    if gate:
        ok = c.engine.evaluate(query=a, agents=cap).compliant_agents
    else:
        ok = [x.id for x in cap]
    if not ok:
        sel = DENY
    else:
        pr = PolicyEvaluationResult(compliant_agents=ok, total_agents_evaluated=len(cap))
        sel = c.resolver.resolve(candidates=cap, policy_result=pr).selected_agent_id
    return sel, a, len(cap), (time.perf_counter() - t0) * 1000


def family_decide(c: Components, base_router, canonical_agents, q, tiebreak, gate):
    """Baseline picks a capability family; a tie-break picks a member of that family.

    tiebreak: "cheapest", "first" (registry order) or "random" (seed 42). gate=True filters family members
    through the OPA PolicyEngine first and denies when none remain.
    """
    fam = base_router.route(question=q["text"], agents=canonical_agents,
                            task_type=q["task"], user_role=q["role"])
    from experiments.oracle import FAMILY
    members = [a for a in c.pool if FAMILY.get(a.id, a.id) == fam]
    if gate:
        a = c.analyzer.analyze(q["text"], user_role=q["role"], task_type=q["task"])
        ok = set(c.engine.evaluate(query=a, agents=members).compliant_agents)
        members = [m for m in members if m.id in ok]
    if not members:
        return DENY
    if tiebreak == "cheapest":
        members = sorted(members, key=lambda m: (m.cost_per_query, m.id))
    elif tiebreak == "random":
        return _TIE_RNG.choice(sorted(members, key=lambda m: m.id)).id
    return members[0].id


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * max(0.0, centre - half), 100 * min(1.0, centre + half))


def pct(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * p / 100
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)
