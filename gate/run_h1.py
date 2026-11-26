"""Run the H1 matrix: 4 policies x 4 detectors + ORACLE over the 76 frozen scenarios.

    python gate/run_h1.py --mode live      # first run: calls Presidio and Ollama, fills the cache
    python gate/run_h1.py --mode replay    # reruns and reviewers: cache only, no external calls

Outputs in gate/results/h1/: results.jsonl (one line per scenario x policy x detector, with hops),
decision.json (metrics, D*, outcome), summary.md, env.json. Cache in gate/results/cache/.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate.harness import env                                    # noqa: E402
from gate.harness.cache import Cache                            # noqa: E402
from gate.harness.common import DETECTORS, POLICIES, RESULTS, Resolver, load_pool, load_scenarios  # noqa: E402
from gate.harness.detectors import (LLMDetector, OllamaClient, PresidioDetector,  # noqa: E402
                                    RuleDetector, presidio_deidentify)
from gate.harness.engine import Scorer, run_h1, true_trace       # noqa: E402
from gate.harness.metrics import h1_decision                     # noqa: E402


def build_detectors(names, presidio_cache, client):
    out = {}
    for n in names:
        if n == "rule":
            out[n] = RuleDetector()
        elif n == "presidio":
            out[n] = PresidioDetector(presidio_cache)
        elif n in ("llm_off", "llm_on"):
            out[n] = LLMDetector(client, think=(n == "llm_on"))
    return out


def oracle_self_check(results) -> None:
    """The ORACLE policy must be perfect; anything else is a harness bug."""
    bad = [r.scenario for r in results if r.policy == "ORACLE" and
           (r.fa_hop or (r.feasible and not r.completed) or r.or_hop)]
    if bad:
        raise SystemExit(f"ORACLE self-check failed on {bad}: harness bug, stop before reading any result")


def summary_md(dec: dict) -> str:
    m = dec["metrics"]["phi"]
    lines = [f"# H1 result: **{dec['outcome']}**", "", f"Reason: {dec['reason']}"]
    if dec["override"]:
        lines.append(f"Override: {dec['override']}")
    lines += [f"D* (primary): {dec['dstar']['phi']}; D* (parse failures excluded): {dec['dstar']['excluded']}",
              f"Outcome under the excluded version: {dec['outcome_excluded_version']}", "",
              "| Policy / detector | FA full | FA std | FD_neg full | FD_neg std | FD_all | OR full | OR std | D hop-3 FA/FD/OR |",
              "|---|---|---|---|---|---|---|---|---|"]
    for key, g in m.items():
        def c(x): return f"{x['k']}/{x['n']}"
        dd = g["D_downstream"]
        lines.append(f"| {key} | {c(g['FA']['full'])} | {c(g['FA']['standard'])} | {c(g['FD_neg']['full'])} | "
                     f"{c(g['FD_neg']['standard'])} | {c(g['FD_all'])} | {c(g['OR']['full'])} | "
                     f"{c(g['OR']['standard'])} | {dd['FA']}/{dd['FD']}/{dd['OR']} |")
    lines += ["", "Parse failures per LLM configuration: " + json.dumps(
        {k: v["count"] for k, v in dec["parse_failures"].items()})]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["live", "replay"], required=True)
    ap.add_argument("--detectors", default=",".join(DETECTORS))
    ap.add_argument("--out", default=str(RESULTS / "h1"))
    args = ap.parse_args()
    names = [d.strip() for d in args.detectors.split(",")]

    scenarios = load_scenarios()
    caps, agents = load_pool()
    resolver = Resolver(agents)
    presidio_cache = Cache("presidio", args.mode)
    client = OllamaClient(Cache("llm", args.mode))
    digest = client.verify_model() if args.mode == "live" and any(n.startswith("llm") for n in names) else None

    def deid(text): return presidio_deidentify(text, presidio_cache)
    traces = {s["id"]: true_trace(s, resolver, deid) for s in scenarios}

    results = [run_h1(s, "ORACLE", None, traces[s["id"]], resolver, caps) for s in scenarios]
    oracle_self_check(results)
    for dname, det in build_detectors(names, presidio_cache, client).items():
        scorer = Scorer(det)
        for p in POLICIES:
            for i, s in enumerate(scenarios, 1):
                results.append(run_h1(s, p, scorer, traces[s["id"]], resolver, caps))
            print(f"{dname:9s} {p:9s} done ({len(scenarios)} scenarios)", flush=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "results.jsonl").open("w") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")
    dec = h1_decision([r for r in results if r.policy != "ORACLE"])
    dec["oracle_trace"] = {sid: {"labels": t.labels, "feasible": t.feasible, "residual": t.residual,
                                 "deid_output": t.deid_output} for sid, t in traces.items() if t.deid_output}
    (out / "decision.json").write_text(json.dumps(dec, indent=1))
    (out / "summary.md").write_text(summary_md(dec))
    (out / "env.json").write_text(json.dumps(env.capture(digest), indent=1))
    print(summary_md(dec))


if __name__ == "__main__":
    main()
