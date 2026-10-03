# Evaluation results

Files in this folder are the results reported in the paper.

## Original experiments (produced by experiments/run_evaluation.py)

experiment1_results.json, experiment2_ablation.json, experiment3_strategies.json and the main, ablation and strategies rerun text files hold the corrected results for the 77 query development sample. v1_original/ holds the console outputs of the first run. That run had two issues, corrected here:
1. The PAGER-NoConflict ablation passed the full agent pool to the PolicyEngine, skipping the AgentRegistry capability pre-filter used by every other variant. Corrected: NoConflict routing accuracy 55.8% -> 94.8%.
2. had_conflict was not recorded in the NoPolicy, NoConflict and weight-sweep loops, so conflict-resolution effectiveness showed 0.0 there. Corrected: NoPolicy 100.0, NoConflict 42.9, weight sweep matches the strategy table.

Experiment 1 (main comparison) and the strategy comparison are unchanged.

## Revision experiments (October 2026)

Both scripts run from the repository root, need OPA on the PATH, and make no edits under src/.

Experiment A: python experiments/run_full300.py
Runs the frozen pipeline on all 300 MedAgentBench tasks (main agent pool). Outputs full300_results.json and full300_results.txt: accuracy for PAGER and the four baselines on the 77 query development sample (sample order, reproduces the paper table), on all 300 tasks, and on the 223 tasks outside the sample; per-task accuracy; end-to-end routing overhead (p50, p95, p99) measured on the machine that runs the script; agreement of the analyzer features with the task annotations.

Experiment B: python experiments/run_adversarial.py
Runs the adversarial pool (configs/agents/healthcare_agents_adversarial.yaml): four original agents, five capability equivalent non-compliant clones, and no compliant Procedure agent, so the 30 Task 8 queries must be denied. Outputs adversarial_results.json and adversarial_results.txt (accuracy, violations, violations among queries sent to the right family, false denials, correct denials for PAGER, PAGER without the gate, the baselines under three tie-break rules, and the baselines with an OPA gate), adversarial_decisions.csv (every decision), and adversarial_heldout20_decisions.csv (the 20 held-out paraphrases in the adversarial pool).

Scoring uses experiments/oracle.py, an oracle that applies written versions of policies P1 to P3 to task level annotations and the agent attributes. It does not use the QueryAnalyzer or OPA code. It is independent of the implementation but not of the annotations, which were assigned by the authors. Its rules match policies/hipaa/*.rego exactly (an empty authorized_roles list imposes no role restriction; there is no rule for low sensitivity). The annotation rule is documented at the top of that file.

The MedAgentBench dataset is not redistributed; place test_data_v2.json in data/medagentbench/ to reproduce. Routing outputs are deterministic. Timing values depend on the machine.

## Notes added in revision r3

- Gated baselines (run_adversarial.py, family_decide with gate=True) evaluate P1 to P3 in OPA on the features extracted by the frozen QueryAnalyzer, the same features PAGER uses. They do not receive the oracle annotations.
- The analyzer's contains_pii and sensitivity features agree with the oracle annotations on 300 of 300 tasks (full300_results.txt, last line). On the 300 benchmark tasks, zero PAGER violations is therefore expected from the design; the held-out run is the only test in which extracted features and annotations differ.
- On the 223 non-sample tasks the order of PAGER, rule-based and TF-IDF is unchanged; random (18.8%) and round-robin (21.5%) swap places relative to the all-300 run (20.3% and 20.0%).
- Under registry-order tie-breaking the rule-based router's 60 violations are the 30 Task 8 queries (no compliant option) plus 30 Task 6 misroutes (see adversarial_decisions.csv).
- Ablation (Experiment 2): both variants ran on the same 7 queries, so the paired exact McNemar test applies (4 discordant pairs, p = 0.125, two-sided), not Fisher's exact test.
- Timing in the released run: mean 152.0, p50 140.3, p95 265.8, p99 292.2, max 309.7 ms; values vary by about 10 ms between runs.
