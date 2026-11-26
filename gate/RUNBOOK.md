# Gate runbook (Day 3)

Run from the repository root with `.venv` active. Do not edit any file under `gate/` once a live run has started; log any needed change in AMENDMENTS.md first.

## 0. Before the first run

```
ollama list                         # gemma4:31b must show ID 92808281a855
python gate/scenarios/build_scenarios.py --check
python gate/oracle_residual.py
python -m pytest gate/tests -q      # 15 tests, stub detectors only
```
Keep the Ollama app (or `ollama serve`) running. The harness refuses to run if the model ID or the Presidio, spaCy or model versions differ from PINNING.md.

## 1. H1 matrix

```
python gate/run_h1.py --mode live
```
Runs ORACLE (self-check first; a failure stops the run as a harness bug), then rule, Presidio, LLM-off and LLM-on, each under PROP, REDETECT, SRC and SRC-FC. Every Presidio and LLM answer is written to `gate/results/cache/` as it arrives, so an interrupted run resumes where it stopped: run the same command again. Expect the thinking configuration (LLM-on) to take most of the time.

Then confirm the cache reproduces the result without any external call:
```
python gate/run_h1.py --mode replay
git diff --stat gate/results/h1/decision.json   # no change expected
```

## 2. H2 planner test

```
python gate/run_h2.py --mode live
python gate/run_h2.py --mode replay
```

## 3. Commit

Commit `gate/results/` (cache, results, decision, summaries, env.json) in one commit before any analysis.

Outputs: `gate/results/h1/summary.md` and `decision.json` (H1), `gate/results/h2/summary.md` and `summary.json` (H2).
