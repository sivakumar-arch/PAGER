"""Run the H2 planner test over the 37 frozen H2 scenarios.

    python gate/run_h2.py --mode live      # calls the pinned planner, fills the cache
    python gate/run_h2.py --mode replay    # cache only

Outputs in gate/results/h2/: plans.jsonl, summary.json, summary.md, env.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gate.harness import env                                          # noqa: E402
from gate.harness.cache import Cache                                  # noqa: E402
from gate.harness.common import RESULTS, Resolver, load_pool, load_scenarios  # noqa: E402
from gate.harness.detectors import OllamaClient, presidio_deidentify  # noqa: E402
from gate.harness.planner import (call_planner, classify, consequence,  # noqa: E402
                                  h2_summary, perturbations, run_plan)


def evaluate(s, plan, resolver, caps, deid):
    gold = [(g["capability"], g["conditional"]) for g in s["gold_plan"]]
    cls = classify(gold, plan)
    run = run_plan(s, plan, cls["ops"], resolver, caps, deid)
    return cls, run, consequence(cls, run)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["live", "replay"], required=True)
    ap.add_argument("--out", default=str(RESULTS / "h2"))
    args = ap.parse_args()

    scenarios = [s for s in load_scenarios() if s["in_h2"]]
    caps, agents = load_pool()
    capabilities = sorted(caps)
    resolver = Resolver(agents)
    presidio_cache = Cache("presidio", args.mode)
    client = OllamaClient(Cache("llm", args.mode))
    digest = client.verify_model() if args.mode == "live" else None

    def deid(text): return presidio_deidentify(text, presidio_cache)

    items = []
    for i, s in enumerate(scenarios, 1):
        p = call_planner(client, s, capabilities)
        item = {"scenario": s["id"], "purpose": s.get("purpose"), "ok": p["ok"], "plan": p["plan"],
                "raw": p["raw"]}
        if p["ok"]:
            item["cls"], item["run"], item["consequence"] = evaluate(s, p["plan"], resolver, caps, deid)
        items.append(item)
        print(f"[{i}/{len(scenarios)}] {s['id']}: {item.get('consequence', 'UNPARSEABLE')}", flush=True)

    erroneous = sum(1 for x in items if x["ok"] and x["cls"]["erroneous"])
    perturbed = None
    if erroneous < 5:
        perturbed = []
        by_id = {s["id"]: s for s in scenarios}
        for pz in perturbations(scenarios, capabilities):
            cls, run, cons = evaluate(by_id[pz["scenario"]], pz["plan"], resolver, caps, deid)
            perturbed.append({**pz, "cls": cls, "run": run, "consequence": cons})
    summary = h2_summary(items, perturbed)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "plans.jsonl").open("w") as f:
        for x in items:
            f.write(json.dumps(x, default=list) + "\n")
    if perturbed is not None:
        with (out / "perturbations.jsonl").open("w") as f:
            for x in perturbed:
                f.write(json.dumps(x, default=list) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    md = [f"# H2 result: H2a **{summary['H2a']}**; H2b: {summary['H2b']['outcome']}", "",
          "```", json.dumps(summary, indent=1), "```"]
    (out / "summary.md").write_text("\n".join(md) + "\n")
    (out / "env.json").write_text(json.dumps(env.capture(digest), indent=1))
    print("\n".join(md))


if __name__ == "__main__":
    main()
