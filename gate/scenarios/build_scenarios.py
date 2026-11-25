"""Build the frozen Paper 2 gate scenario set (gate/scenarios/scenarios_v1.json).

Inputs (all pinned by SHA-256 in PINNED below; the build refuses to run if any differ):
  * data/medagentbench/test_data_v2.json   MedAgentBench (MIT), not tracked in git
  * experiments/heldout/tier2_heldout_queries.json   Paper 1 held-out paraphrases
  * gate/scenarios/spec_v1.json            hand-written inputs (strata A to E)
  * gate/agents/gate_agents.yaml           gate agent pool

True labels are assigned here mechanically from the annotation rules in
gate/PROTOCOL.md section 3. No detector, analyzer or LLM is used.

Usage (from the repository root):
    python gate/scenarios/build_scenarios.py            # build and verify
    python gate/scenarios/build_scenarios.py --check    # verify inputs and the committed output hash only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MAB = ROOT / "data/medagentbench/test_data_v2.json"
HELDOUT = ROOT / "experiments/heldout/tier2_heldout_queries.json"
SPEC = ROOT / "gate/scenarios/spec_v1.json"
AGENTS = ROOT / "gate/agents/gate_agents.yaml"
OUT = ROOT / "gate/scenarios/scenarios_v1.json"

# Filled in at freeze time; any later change to an input must go through gate/AMENDMENTS.md.
PINNED = {
    "data/medagentbench/test_data_v2.json": "b6e89b2ef82f1bef27c5778a644a8a66c7b25738bbd6a48d03ab3e5182df6ca8",
}

PHI, NONPHI, RUNTIME = "PHI", "NONPHI", "RUNTIME"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def step(cap, cond, input_text, label, basis, output):
    return {"capability": cap, "conditional": cond, "input_text": input_text,
            "true_label": label, "label_basis": basis, "mock_output": output}


def build() -> dict:
    for path, digest in PINNED.items():
        got = sha256(ROOT / path)
        if got != digest:
            sys.exit(f"Pinned input changed: {path}\n  expected {digest}\n  got      {got}")

    mab = {r["id"]: r for r in json.loads(MAB.read_text())}
    heldout = json.loads(HELDOUT.read_text())
    spec = json.loads(SPEC.read_text())
    pool = yaml.safe_load(AGENTS.read_text())
    caps = pool["capabilities"]
    pay = spec["order_payloads"]
    scenarios: list[dict] = []

    # ---- Stratum A: record-sourced MedAgentBench originals --------------------
    A = spec["A_record_sourced"]
    for it in A["items"]:
        src = mab[it["source_id"]]
        mrn = src["eval_MRN"]
        text = src["instruction"].rstrip() + ("" if it.get("native") else A["append_sentence"])
        steps, prev_out = [], None
        for i, (cap, cond, out) in enumerate(it["plan"]):
            if i == 0:
                inp, basis = text, "record access by plan; identifier in text"
            elif cap == "ehr.order_medication":
                key = {"A09": "magnesium_1.3", "A10": "magnesium_1.7",
                       "A11": "potassium_3.1", "A12": "potassium_3.3"}[it["id"]]
                inp, basis = pay[key].format(mrn=mrn), "record write; conditioned on PHI (implicit flow)"
            elif cap == "ehr.order_lab":
                inp = pay["a1c" if it["id"] == "A08" else "k_recheck"].format(mrn=mrn)
                basis = "record write; conditioned on PHI (implicit flow)"
            else:
                inp, basis = prev_out, "derived from a PHI-labelled step (taint)"
            steps.append(step(cap, cond, inp, PHI, basis, out))
            prev_out = out
        scenarios.append({"id": it["id"], "stratum": "A", "source_id": it["source_id"],
                          "text": text, "context": src.get("context", ""),
                          "session_record": None, "patient_mrn": mrn,
                          "patient_context": True, "trap": False, "hard": False,
                          "purpose": "treatment", "steps": steps})

    # ---- Stratum B: Paper 1 held-out paraphrases in a session -----------------
    t5 = [mab[f"task5_{i}"]["eval_MRN"] for i in range(1, 11)]
    t9 = [mab[f"task9_{i}"]["eval_MRN"] for i in range(1, 11)]
    with_lab = set(spec["B_heldout"]["t9_with_followup_lab"])
    for q in heldout["queries"]:
        n = int(q["id"].split("-")[1])
        m = re.search(r"\bS\d{7}\b", q["text"])
        mrn = m.group(0) if m else (t5 if q["task"] == 5 else t9)[n - 1]
        if q["task"] == 5:
            plan = [("ehr.read_observation", False, None, "1.3"),
                    ("ehr.order_medication", True, pay["magnesium_1.3"], "MedicationRequest created")]
        else:
            plan = [("ehr.read_observation", False, None, "3.1"),
                    ("ehr.order_medication", True, pay["potassium_3.1"], "MedicationRequest created")]
            if q["id"] in with_lab:
                plan.append(("ehr.order_lab", True, pay["k_recheck"], "ServiceRequest created (LOINC 2823-3)"))
        steps = []
        for i, (cap, cond, payload, out) in enumerate(plan):
            if i == 0:
                steps.append(step(cap, cond, q["text"], PHI,
                                  "record access by plan; open session record (no identifier needed in text)", out))
            else:
                steps.append(step(cap, cond, payload.format(mrn=mrn), PHI,
                                  "record write; conditioned on PHI (implicit flow)", out))
        scenarios.append({"id": f"B-{q['id']}", "stratum": "B", "source_id": q["id"],
                          "text": q["text"], "context": "", "session_record": mrn, "patient_mrn": mrn,
                          "patient_context": True, "trap": False, "hard": False,
                          "purpose": "treatment", "identifier_in_text": bool(m), "steps": steps})

    # ---- Stratum C: pasted free text, no record access ------------------------
    for it in spec["C_free_text"]["items"]:
        for ident in it["identifiers"]:
            assert ident in it["text"], f"{it['id']}: identifier not in text: {ident}"
        assert it["phi"] == bool(it["identifiers"]), f"{it['id']}: phi flag disagrees with identifiers"
        lab = PHI if it["phi"] else NONPHI
        basis0 = ("Safe Harbor identifier(s) with health information: " + "; ".join(it["identifiers"])
                  if it["phi"] else "no identifier of an individual")
        steps, prev_out = [], None
        for i, (cap, cond, out) in enumerate(it["plan"]):
            inp = it["text"] if i == 0 else prev_out
            basis = basis0 if i == 0 else ("derived from a PHI-labelled step (taint)" if it["phi"]
                                           else "derived from a non-PHI step")
            steps.append(step(cap, cond, inp, lab, basis, out))
            prev_out = out
        scenarios.append({"id": it["id"], "stratum": "C", "source_id": None, "text": it["text"],
                          "context": "", "session_record": None, "patient_mrn": None,
                          "patient_context": it["phi"], "trap": it["trap"],
                          "hard": it.get("hard", False), "purpose": None,
                          "identifiers": it["identifiers"], "steps": steps})

    # ---- Stratum D: declassification chains -----------------------------------
    for it in spec["D_declassification"]["items"]:
        for ident in it["identifiers"]:
            assert ident in it["export"], f"{it['id']}: identifier not in export: {ident}"
        assert it["mrn"] in it["text"]
        steps = [
            step("ehr.read_document", False, it["text"], PHI, "record access by plan; identifier in text", it["export"]),
            step("text.deidentify", False, it["export"], PHI, "record document (taint)", RUNTIME),
            step(it["final"], False, RUNTIME, RUNTIME,
                 "decided at run time by the residual-identifier check (PROTOCOL 3.4)", None),
        ]
        scenarios.append({"id": it["id"], "stratum": "D", "source_id": None, "text": it["text"],
                          "context": "", "session_record": None, "patient_mrn": it["mrn"],
                          "patient_context": True, "trap": False, "hard": it["hard"],
                          "purpose": it["purpose"], "identifiers": it["identifiers"], "steps": steps})

    # ---- Stratum E: no patient context ----------------------------------------
    for it in spec["E_no_patient_context"]["items"]:
        steps = [step("knowledge.answer", False, it["text"], NONPHI, "no patient context", it["answer"])]
        if it.get("translate"):
            steps.append(step("text.translate", False, it["answer"], NONPHI, "derived from a non-PHI step", None))
        scenarios.append({"id": it["id"], "stratum": "E", "source_id": None, "text": it["text"],
                          "context": "", "session_record": None, "patient_mrn": None,
                          "patient_context": False, "trap": it["trap"], "hard": False,
                          "purpose": None, "steps": steps})

    # ---- Oracle feasibility and oracle-optimal agents --------------------------
    agents = pool["agents"]

    def candidates(cap):
        return sorted((a for a in agents if cap in a["capabilities"]), key=lambda a: (a["cost"], a["id"]))

    for s in scenarios:
        feas = True
        for st in s["steps"]:
            cands = candidates(st["capability"])
            assert cands, f"{s['id']}: no agent for {st['capability']}"
            ok_phi = [a["id"] for a in cands if a["hipaa_compliant"]]
            if st["true_label"] == PHI:
                st["oracle_agent"] = ok_phi[0] if ok_phi else None
                if not ok_phi:
                    feas = False
            elif st["true_label"] == NONPHI:
                st["oracle_agent"] = cands[0]["id"]
            else:
                st["oracle_agent"] = {"if_PHI": ok_phi[0] if ok_phi else None, "if_NONPHI": cands[0]["id"]}
                if feas and not ok_phi:
                    feas = "runtime"
        s["oracle_feasible"] = feas
        s["entry_label"] = s["steps"][0]["true_label"]
        s["n_steps"] = len(s["steps"])

    # ---- H2 membership ---------------------------------------------------------
    h2 = set(spec["H2_ids"]["ids"]) | {s["id"] for s in scenarios
                                       if s["stratum"] in spec["H2_ids"]["plus_all_of"]}
    for s in scenarios:
        s["in_h2"] = s["id"] in h2
        s["gold_plan"] = [{"capability": st["capability"], "conditional": st["conditional"]} for st in s["steps"]]

    return {
        "version": "scenarios_v1",
        "inputs_sha256": {rel(p): sha256(p) for p in (MAB, HELDOUT, SPEC, AGENTS)},
        "capabilities": sorted(caps),
        "scenarios": scenarios,
    }


def validate(d: dict) -> list[str]:
    S = d["scenarios"]
    caps = set(d["capabilities"])
    ids = [s["id"] for s in S]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for s in S:
        for st in s["steps"]:
            assert st["capability"] in caps, f"{s['id']}: unknown capability {st['capability']}"
    by = {k: [s for s in S if s["stratum"] == k] for k in "ABCDE"}
    no_ctx = [s for s in S if not s["patient_context"]]
    phi_flow = [s for s in S if any(st["true_label"] != NONPHI for st in s["steps"])]
    feasible = [s for s in S if s["oracle_feasible"] is True]
    report = [
        f"total scenarios: {len(S)}",
        "per stratum: " + ", ".join(f"{k}={len(v)}" for k, v in by.items()),
        f"no patient context: {len(no_ctx)} ({len(no_ctx)/len(S):.0%}); of which stratum E: {len(by['E'])} ({len(by['E'])/len(S):.0%})",
        f"scenarios with a PHI flow (false-allow denominator): {len(phi_flow)}",
        f"oracle-infeasible (correct denials): {[s['id'] for s in S if s['oracle_feasible'] is False]}",
        f"runtime feasibility (stratum D): {[s['id'] for s in S if s['oracle_feasible'] == 'runtime']}",
        f"feasible at build time: {len(feasible)}",
        f"trap items (negatives): {[s['id'] for s in S if s['trap']]}",
        f"hard items (positives): {[s['id'] for s in S if s['hard']]}",
        f"standard subset: PHI-flow {sum(1 for s in phi_flow if not s['hard'])}, "
        f"non-PHI {sum(1 for s in no_ctx if not s['trap'])}",
        f"stratum D: {len(by['D'])} ({sum(s['hard'] for s in by['D'])} hard); "
        f"final step translate {sum(s['steps'][-1]['capability']=='text.translate' for s in by['D'])}",
        f"B paraphrases with an identifier in the text: {[s['id'] for s in by['B'] if s['identifier_in_text']]}",
        f"plan lengths: " + ", ".join(f"{n} steps={sum(1 for s in S if s['n_steps']==n)}" for n in (1, 2, 3)),
        f"conditional steps: {sum(st['conditional'] for s in S for st in s['steps'])}",
        f"H2 set size: {sum(s['in_h2'] for s in S)}",
    ]
    assert len(by["B"]) == 20 and sum(not s["identifier_in_text"] for s in by["B"]) == 18
    assert sum(s["in_h2"] for s in S) == 37
    assert not any(s["trap"] and s["hard"] for s in S)
    assert all(not s["trap"] for s in phi_flow) and all(not s["hard"] for s in no_ctx)
    assert 0.25 <= len(by["E"]) / len(S) <= 0.35, "stratum E must be about 30% of scenarios"
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="rebuild in memory and compare with the committed file")
    args = ap.parse_args()
    d = build()
    text = json.dumps(d, indent=1, ensure_ascii=False, sort_keys=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text() == text
        print("committed scenarios_v1.json matches a fresh build" if same else "MISMATCH with committed file")
        sys.exit(0 if same else 1)
    for line in validate(d):
        print(line)
    OUT.write_text(text)
    print(f"wrote {rel(OUT)}  sha256={sha256(OUT)}")


if __name__ == "__main__":
    main()
