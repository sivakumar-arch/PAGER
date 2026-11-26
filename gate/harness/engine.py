"""Policy labelling and plan execution for H1 (PROTOCOL.md sections 3, 4, 6, 7).

The oracle side (true labels, feasibility, oracle agents) never calls a detector.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from oracle_residual import residual  # gate/oracle_residual.py (frozen)

from .common import NONPHI, PHI, RUNTIME, TAU, TAU_LOW, Resolver
from .detectors import Detection, Detector

TAUS = {"PROP": TAU, "REDETECT": TAU, "SRC": TAU, "SRC-FC": TAU_LOW}


# ---------------------------------------------------------------- oracle trace
@dataclass
class TrueTrace:
    labels: list[str]               # true label per hop, RUNTIME resolved
    inputs: list[str]               # input text per hop, RUNTIME resolved
    oracle_agents: list[str | None]
    feasible: bool
    phi_flow: bool
    deid_output: str | None = None
    residual: list[str] = field(default_factory=list)


def true_trace(s: dict, resolver: Resolver, deid) -> TrueTrace:
    labels, inputs, oracle_agents = [], [], []
    deid_out, resid = None, []
    for st in s["steps"]:
        inp = deid_out if st["input_text"] == RUNTIME else st["input_text"]
        if st["true_label"] == RUNTIME:
            resid = residual(s["identifiers"], deid_out)
            lab = PHI if resid else NONPHI
        else:
            lab = st["true_label"]
        agent = resolver.resolve(st["capability"], lab)
        labels.append(lab)
        inputs.append(inp)
        oracle_agents.append(agent.id if agent else None)
        if st["capability"] == "text.deidentify":
            deid_out = deid(inp)
    return TrueTrace(labels, inputs, oracle_agents, all(a is not None for a in oracle_agents),
                     PHI in labels, deid_out, resid)


# ---------------------------------------------------------------- policies
class Scorer:
    """Memoises detector calls and records which texts failed to parse."""

    def __init__(self, detector: Detector):
        self.det = detector
        self.memo: dict[str, Detection] = {}

    def __call__(self, text: str) -> Detection:
        if text not in self.memo:
            self.memo[text] = self.det.score(text)
        return self.memo[text]


@dataclass
class Hop:
    hop: int
    capability: str
    label: str
    source: str              # declared | inferred | inferred-declass | propagated | oracle
    score: float | None
    parse_ok: bool
    true_label: str
    agent: str | None
    oracle_agent: str | None
    fa: bool
    over: bool
    inferred_relevant: bool   # flipping this inferred label would change agent or allow/deny


@dataclass
class Result:
    scenario: str
    stratum: str
    policy: str
    detector: str
    hops: list[Hop]
    denied_at: int | None
    fa_hop: int | None
    or_hop: int | None
    completed: bool
    feasible: bool
    phi_flow: bool
    trap: bool
    hard: bool
    parse_failure: bool

    def row(self) -> dict:
        d = asdict(self)
        d["hops"] = len(self.hops)
        return d


def run_h1(s: dict, policy: str, scorer: Scorer | None, trace: TrueTrace, resolver: Resolver,
           caps: dict) -> Result:
    tau = TAUS.get(policy)
    hops: list[Hop] = []
    current = None          # label carried by the data entering the next hop
    prev_was_deid = False
    parse_failure = False
    denied_at = fa_hop = or_hop = None

    def detect(text: str):
        nonlocal parse_failure
        d = scorer(text)
        if not d.ok:
            parse_failure = True
        return (PHI if d.score >= tau else NONPHI), d.score, d.ok

    for k, st in enumerate(s["steps"], 1):
        cap = st["capability"]
        inp = trace.inputs[k - 1]
        true = trace.labels[k - 1]
        record = caps[cap]["record_access"] != "none"
        score, ok = None, True

        if policy == "ORACLE":
            label, source = true, "oracle"
        elif prev_was_deid:                                   # section 6, last column
            label, score, ok = detect(inp)
            source = "inferred-declass"
        elif policy == "PROP":
            if k == 1:
                label, score, ok = detect(s["text"])
                source = "inferred"
            else:
                label, source = current, "propagated"
        elif policy == "REDETECT":
            label, score, ok = detect(s["text"] if k == 1 else inp)
            source = "inferred"
        elif policy in ("SRC", "SRC-FC"):
            if record or (k == 1 and s["session_record"]):
                label, source = PHI, "declared"
            elif k == 1:
                label, score, ok = detect(s["text"])
                source = "inferred"
            else:
                label, source = current, "propagated"
        else:
            raise ValueError(policy)

        agent = resolver.resolve(cap, label)
        flipped = resolver.resolve(cap, NONPHI if label == PHI else PHI)
        relevant = source.startswith("inferred") and (
            (agent.id if agent else None) != (flipped.id if flipped else None))
        oracle_agent = trace.oracle_agents[k - 1]
        fa = bool(agent and true == PHI and not agent.hipaa_compliant)
        over = bool(agent and oracle_agent and agent.cost > resolver.by_id[oracle_agent].cost)
        hops.append(Hop(k, cap, label, source, score, ok, true, agent.id if agent else None,
                        oracle_agent, fa, over, relevant))
        if fa and fa_hop is None:
            fa_hop = k
        if agent is None:
            denied_at = k
            break
        if over and or_hop is None:
            or_hop = k
        current = label
        prev_was_deid = cap == "text.deidentify"

    completed = denied_at is None
    return Result(s["id"], s["stratum"], policy, scorer.det.name if scorer else "oracle", hops, denied_at,
                  fa_hop, or_hop if completed and trace.feasible else None, completed, trace.feasible,
                  trace.phi_flow, s["trap"], s["hard"], parse_failure)
