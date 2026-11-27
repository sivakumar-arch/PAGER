"""Package 1 tests: chain models and label policies.

The cross-check at the end compares the label rules with the frozen gate harness on all
76 gate scenarios (stub detectors, no Presidio or Ollama). It imports gate/ in tests only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.pager_chain.labels import POLICIES, TAU, TAU_LOW, HopContext, decide_label, get_policy
from src.pager_chain.models import (ChainPlan, ChainResult, ChainStep, Detection, HopDecision,
                                    Label, LabelSource)

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- models
def test_label_join_is_least_upper_bound():
    assert Label.NONPHI.join(Label.NONPHI) == Label.NONPHI
    assert Label.NONPHI.join(Label.PHI) == Label.PHI
    assert Label.PHI.join(Label.NONPHI) == Label.PHI
    assert Label.PHI.join(Label.PHI) == Label.PHI


def test_plan_requires_steps_and_detection_score_range():
    with pytest.raises(ValidationError):
        ChainPlan(request_text="x", steps=())
    with pytest.raises(ValidationError):
        Detection(score=1.2)


def test_chain_result_denied_at_and_completed():
    plan = ChainPlan(request_text="r", steps=(ChainStep(capability="a"), ChainStep(capability="b")))
    ok = HopDecision(hop=1, capability="a", label=Label.PHI, label_source=LabelSource.DECLARED, agent_id="x")
    den = HopDecision(hop=2, capability="b", label=Label.PHI, label_source=LabelSource.PROPAGATED)
    r = ChainResult(plan=plan, hops=[ok, den], label_policy="SRC-FC", resolver_strategy="cost_aware")
    assert den.denied and r.denied_at == 2 and not r.completed
    assert ChainResult(plan=plan, hops=[ok], label_policy="SRC", resolver_strategy="cost_aware").completed


# ---------------------------------------------------------------- label policies
def ctx(**kw):
    base = dict(hop=1, request_text="REQ", hop_input="IN", record_access=False, session_open=False,
                after_declassifier=False, upstream=None)
    return HopContext(**{**base, **kw})


def const(score, seen=None):
    def f(text):
        if seen is not None:
            seen.append(text)
        return Detection(score=score)
    return f


def test_thresholds_match_frozen_protocol():
    assert TAU == 0.5 and TAU_LOW == 0.2
    assert get_policy("SRC-FC").tau == TAU_LOW and get_policy("SRC").tau == TAU
    with pytest.raises(ValueError):
        get_policy("ORACLE")


def test_src_declares_record_hops_and_open_sessions():
    for name in ("SRC", "SRC-FC"):
        p = get_policy(name)
        assert decide_label(p, ctx(record_access=True), const(0.0))[:2] == (Label.PHI, LabelSource.DECLARED)
        assert decide_label(p, ctx(session_open=True), const(0.0))[:2] == (Label.PHI, LabelSource.DECLARED)
        # session record counts only at hop 1; later non-record hops propagate
        assert decide_label(p, ctx(hop=2, session_open=True, upstream=Label.NONPHI), const(1.0))[:2] == \
            (Label.NONPHI, LabelSource.PROPAGATED)


def test_prop_ignores_sources_and_propagates_root():
    p = get_policy("PROP")
    seen = []
    assert decide_label(p, ctx(record_access=True, session_open=True), const(0.0, seen))[:2] == \
        (Label.NONPHI, LabelSource.INFERRED)
    assert seen == ["REQ"]
    assert decide_label(p, ctx(hop=2, record_access=True, upstream=Label.NONPHI), const(1.0))[:2] == \
        (Label.NONPHI, LabelSource.PROPAGATED)


def test_redetect_scores_each_hop_input():
    p = get_policy("REDETECT")
    seen = []
    decide_label(p, ctx(), const(0.0, seen))
    decide_label(p, ctx(hop=2, upstream=Label.PHI), const(0.0, seen))
    assert seen == ["REQ", "IN"]


def test_fail_closed_threshold():
    assert decide_label(get_policy("SRC"), ctx(), const(0.3))[0] == Label.NONPHI
    assert decide_label(get_policy("SRC-FC"), ctx(), const(0.3))[0] == Label.PHI
    assert decide_label(get_policy("SRC-FC"), ctx(), const(0.19))[0] == Label.NONPHI


def test_after_declassifier_every_policy_rescores_the_output():
    for p in POLICIES.values():
        seen = []
        lab, src, d = decide_label(p, ctx(hop=3, upstream=Label.PHI, after_declassifier=True), const(0.0, seen))
        assert (lab, src) == (Label.NONPHI, LabelSource.INFERRED_DECLASS) and seen == ["IN"] and d.score == 0.0


def test_propagation_needs_upstream():
    with pytest.raises(ValueError):
        decide_label(get_policy("SRC"), ctx(hop=2, upstream=None), const(0.0))


# ---------------------------------------------------------------- cross-check with the frozen gate harness
gate_harness = pytest.importorskip("gate.harness.engine", reason="gate harness not importable")


def test_label_rules_match_gate_harness_on_all_scenarios():
    """Same label and label source at every hop, 76 scenarios x 4 policies x 3 stub detectors."""
    sys.path.insert(0, str(ROOT))
    from gate.harness.common import Resolver, load_pool, load_scenarios
    from gate.harness.detectors import Detection as GateDetection, Detector
    from gate.harness.engine import Scorer, run_h1, true_trace

    scenarios = load_scenarios()
    caps, agents = load_pool()
    resolver = Resolver(agents)

    def deid(text):   # stub: drop full names and digit runs
        return re.sub(r"\d[\d\-/(). ]*\d", "<NUM>", re.sub(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "<PERSON>", text))

    def score_fn(text, mode):
        if mode == "len":
            return 0.6 if len(text) % 3 == 0 else (0.3 if len(text) % 3 == 1 else 0.1)
        return {"zero": 0.0, "one": 1.0}[mode]

    for mode in ("zero", "one", "len"):
        class Stub(Detector):
            name = "presidio"
            def score(self, text, m=mode):
                return GateDetection(score_fn(text, m))
        scorer = Scorer(Stub())
        for s in scenarios:
            trace = true_trace(s, resolver, deid)
            for pname in POLICIES:
                ref = run_h1(s, pname, scorer, trace, resolver, caps)
                upstream, prev_declass = None, False
                for k, hop in enumerate(ref.hops, 1):
                    st = s["steps"][k - 1]
                    c = HopContext(hop=k, request_text=s["text"], hop_input=trace.inputs[k - 1],
                                   record_access=caps[st["capability"]]["record_access"] != "none",
                                   session_open=bool(s["session_record"]),
                                   after_declassifier=prev_declass, upstream=upstream)
                    lab, src, _ = decide_label(get_policy(pname), c,
                                               lambda t, m=mode: Detection(score=score_fn(t, m)))
                    assert (lab.value, src.value) == (hop.label, hop.source), (mode, s["id"], pname, k)
                    upstream = lab
                    prev_declass = caps[st["capability"]].get("declassifier", False)
