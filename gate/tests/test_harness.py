"""Harness tests with stub detectors and a stub de-identifier (no Presidio or Ollama needed).

    python -m pytest gate/tests -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from gate.harness.cache import Cache, CacheMiss
from gate.harness.common import NONPHI, PHI, POLICIES, Resolver, load_pool, load_scenarios
from gate.harness.detectors import Detection, Detector, OllamaClient, LLMDetector
from gate.harness.engine import Scorer, run_h1, true_trace
from gate.harness.metrics import all_metrics, choose_dstar, h1_decision, h1_rule, parse_failure_flags
from gate.harness.planner import align, classify, perturbations, run_plan, consequence

S = load_scenarios()
BY = {s["id"]: s for s in S}
CAPS, AGENTS = load_pool()
R = Resolver(AGENTS)


def deid_leaky(text: str) -> str:
    """Stub de-identifier: removes full names, numbers and emails, but leaves bare surnames."""
    import re
    out = re.sub(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", "<PERSON>", text)
    out = re.sub(r"[\w.]+@[\w.]+", "<EMAIL_ADDRESS>", out)
    return re.sub(r"\d[\d\-/(). ]*\d", "<NUM>", out)


def deid_perfect(text: str) -> str:
    out = text
    for s in S:
        for x in sorted(s.get("identifiers", []), key=len, reverse=True):
            out = out.replace(x, "<X>")
    return out


class Const(Detector):
    def __init__(self, value, name="presidio", ok=True):
        self.value, self.name, self.ok = value, name, ok

    def score(self, text):
        return Detection(self.value, self.ok)


class Truthful(Detector):
    """Returns the oracle label for request texts it knows, else 0."""
    name = "presidio"

    def __init__(self):
        self.known = {s["text"]: (1.0 if s["entry_label"] == PHI else 0.0) for s in S}

    def score(self, text):
        return Detection(self.known.get(text, 0.0))


TR_LEAKY = {s["id"]: true_trace(s, R, deid_leaky) for s in S}
TR_PERFECT = {s["id"]: true_trace(s, R, deid_perfect) for s in S}


def run_all(det, traces=TR_PERFECT, policies=POLICIES):
    sc = Scorer(det)
    return [run_h1(s, p, sc, traces[s["id"]], R, CAPS) for p in policies for s in S]


# ---------------------------------------------------------------- oracle and denominators
def test_oracle_is_perfect_and_denominators_match_protocol():
    for traces in (TR_LEAKY, TR_PERFECT):
        rs = [run_h1(s, "ORACLE", None, traces[s["id"]], R, CAPS) for s in S]
        assert not any(r.fa_hop or r.or_hop or (r.feasible and not r.completed) for r in rs)
    phi = [s for s in S if TR_PERFECT[s["id"]].phi_flow]
    assert len(phi) == 50 and len([s for s in phi if not s["hard"]]) == 43
    non = [s for s in S if not TR_PERFECT[s["id"]].phi_flow]
    assert len(non) == 26 and len([s for s in non if not s["trap"]]) == 16
    assert sorted(s["id"] for s in S if not TR_PERFECT[s["id"]].feasible) == ["C02", "C05", "C06"]


def test_leaky_deid_makes_translate_chains_infeasible_and_phi():
    t = TR_LEAKY["D01"]                     # "Mr. Stafford" survives the stub
    assert "Stafford" in t.residual and t.labels[2] == PHI and not t.feasible
    t2 = TR_LEAKY["D02"]                    # summarise chain stays feasible (summ_secure exists)
    assert t2.labels[2] == PHI and t2.feasible


# ---------------------------------------------------------------- policy behaviour
def test_prop_with_blind_detector_violates_on_paraphrases_at_hop1():
    rs = {(r.policy, r.scenario): r for r in run_all(Const(0.0))}
    assert rs[("PROP", "B-T5-01")].fa_hop == 1
    assert rs[("SRC", "B-T5-01")].fa_hop is None and rs[("SRC-FC", "B-T5-01")].fa_hop is None


def test_redetect_violates_at_hop2_on_bare_values():
    class Txt(Detector):
        name = "presidio"
        def score(self, text): return Detection(1.0 if text == BY["A04"]["text"] else 0.0)
    rs = {(r.policy, r.scenario): r for r in run_all(Txt())}
    assert rs[("REDETECT", "A04")].fa_hop == 2      # "1.9" goes to summ_lite
    assert rs[("SRC", "A04")].fa_hop is None


def test_fail_closed_threshold_and_overrestriction():
    rs = {(r.policy, r.scenario): r for r in run_all(Const(0.3))}
    assert rs[("SRC", "C07")].completed and rs[("SRC", "C07")].or_hop is None       # 0.3 < 0.5
    assert rs[("SRC-FC", "C07")].or_hop == 1                                          # summ_secure, costlier
    assert rs[("SRC-FC", "E01")].denied_at == 1                                       # kb_public only
    assert rs[("SRC-FC", "C02")].denied_at == 1 and not rs[("SRC-FC", "C02")].feasible  # correct denial


def test_downstream_violation_after_leaky_deid():
    rs = {(r.policy, r.scenario): r for r in run_all(Const(0.0), TR_LEAKY)}
    r = rs[("SRC-FC", "D01")]
    assert [h.source for h in r.hops] == ["declared", "propagated", "inferred-declass"]
    assert r.fa_hop == 3 and r.hops[2].agent == "translate_ext"


# ---------------------------------------------------------------- metrics, D*, decision, dual reporting
def test_decision_fail_when_detector_is_truthful_and_deid_perfect():
    dec = h1_decision(run_all(Truthful()))
    g = dec["metrics"]["phi"][f"SRC-FC|{dec['dstar']['phi']}"]
    assert g["FA"]["full"]["k"] == 0 and dec["outcome"] == "FAIL"


def test_decision_narrow_and_pass_rules():
    base = {"FA": {"full": {"k": 3, "n": 50, "rate": .06}, "standard": {"k": 2, "n": 43, "rate": .05}},
            "FD_neg": {"full": {"k": 0, "n": 26, "rate": 0}, "standard": {"k": 0, "n": 16, "rate": 0}},
            "OR": {"full": {"k": 0, "n": 60, "rate": 0}, "standard": {"k": 0, "n": 40, "rate": 0}},
            "D_downstream": {"n": 12, "FA": 0, "FD": 0, "OR": 1}}
    assert h1_rule(base)[0] == "NARROW"
    base["D_downstream"]["FA"] = 1
    assert h1_rule(base)[0] == "PASS"
    base["FA"]["standard"]["k"] = 1          # price must hold in the standard subset too
    assert h1_rule(base)[0] == "GRAY"


def test_parse_failure_dual_reporting_and_gray_override():
    good = run_all(Const(0.6, "presidio"))
    bad = run_all(Const(0.0, "llm_off", ok=False))   # every LLM call fails to parse
    rs = good + bad
    flags = parse_failure_flags(rs)
    assert flags["llm_off"]["flagged"] and flags["llm_off"]["count"] > 3
    m = all_metrics(rs)
    excl = m["excluded"]["SRC-FC|llm_off"]
    assert excl["FA"]["full"]["n"] < m["phi"]["SRC-FC|llm_off"]["FA"]["full"]["n"]
    dec = h1_decision(rs)
    assert set(dec["dstar"]) == {"phi", "excluded"}
    if dec["dstar"]["phi"] != dec["dstar"]["excluded"]:
        assert dec["outcome"] == "GRAY" and dec["override"]


# ---------------------------------------------------------------- cache and Ollama client
def test_cache_live_then_replay(tmp_path):
    c = Cache("t", "live", tmp_path)
    calls = []
    rec = c.get_or_call({"kind": "x", "v": 1}, lambda: calls.append(1) or {"out": 42})
    assert rec["out"] == 42 and calls == [1]
    r = Cache("t", "replay", tmp_path)
    assert r.get_or_call({"kind": "x", "v": 1}, lambda: 1 / 0)["out"] == 42
    with pytest.raises(CacheMiss):
        r.get_or_call({"kind": "x", "v": 2}, lambda: {"out": 0})


def test_ollama_retry_parse_failure_and_cache(tmp_path, monkeypatch):
    client = OllamaClient(Cache("llm", "live", tmp_path))
    client._verified = True
    answers = iter(["not json", '{"phi": true, "p_phi": 0.9, "identifiers": ["x"]}',
                    "still not json", "nope"])
    monkeypatch.setattr(client, "_post", lambda path, payload=None, timeout=900:
                        {"message": {"content": next(answers)}, "model": "gemma4:31b"})
    det = LLMDetector(client, think=False)
    d1 = det.score("first")                          # fails once, retry succeeds
    assert d1.ok and d1.score == 0.9
    d2 = det.score("second")                         # fails twice -> s = 1.0, ok False
    assert not d2.ok and d2.score == 1.0
    lines = [json.loads(x) for x in (tmp_path / "llm.jsonl").read_text().splitlines()]
    assert [len(x["attempts"]) for x in lines] == [2, 2]
    replay = LLMDetector(OllamaClient(Cache("llm", "replay", tmp_path)), think=False)
    assert replay.score("first").score == 0.9 and not replay.score("second").ok


# ---------------------------------------------------------------- H2
def test_alignment_taxonomy():
    g = [("ehr.read_observation", False), ("ehr.order_medication", True), ("ehr.order_lab", True)]
    assert not classify(g, g)["erroneous"]
    assert classify(g, g[:1] + g[2:])["errors"] == {"missing_step": 1}
    assert classify(g, [g[1], g[0], g[2]])["errors"] == {"wrong_order": 1}
    c = classify(g, [("ehr.read_document", False)] + g[1:])
    assert c["errors"] == {"wrong_capability": 1} and c["over_access"] == ["ehr.read_document"]
    c = classify(g, [("ehr.patient_lookup", False)] + g)
    assert c["errors"] == {"extra_step": 1} and c["over_access"] == ["ehr.patient_lookup"]
    assert classify(g, [g[0], ("ehr.order_medication", False), g[2]])["errors"] == {"condition_error": 1}


def test_h2_no_violation_under_complete_mediation_for_any_perturbation():
    h2 = [s for s in S if s["in_h2"]]
    assert len(h2) == 37
    pz = perturbations(h2, sorted(CAPS))
    assert len(pz) == 37 * 5
    assert pz == perturbations(h2, sorted(CAPS))            # seeded, reproducible
    for deid in (deid_leaky, deid_perfect):
        for x in pz:
            s = BY[x["scenario"]]
            cls = classify([(g["capability"], g["conditional"]) for g in s["gold_plan"]], x["plan"])
            run = run_plan(s, x["plan"], cls["ops"], R, CAPS, deid)
            assert run["fa_hop"] is None, (x, run)
            assert consequence(cls, run) in ("correct", "denial", "utility_only")


def test_gold_plans_execute_correctly_in_h2():
    for s in S:
        if s["in_h2"]:
            gold = [(g["capability"], g["conditional"]) for g in s["gold_plan"]]
            cls = classify(gold, gold)
            run = run_plan(s, gold, cls["ops"], R, CAPS, deid_perfect)
            assert consequence(cls, run) == "correct" and run["completed"]


def test_gray_override_when_dstar_differs_between_versions(monkeypatch):
    import gate.harness.metrics as M
    rs = run_all(Const(0.6, "presidio")) + run_all(Const(0.0, "llm_off", ok=False))
    monkeypatch.setattr(M, "choose_dstar", lambda m, v: "presidio" if v == "phi" else "llm_off")
    dec = M.h1_decision(rs)
    assert dec["outcome"] == "GRAY" and "differs" in dec["override"]
