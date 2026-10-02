# Evaluation results

Files in this folder are the corrected results reported in the paper, produced by experiments/run_evaluation.py.

v1_original/ holds the console outputs of the first run. That run had two issues, corrected here:
1. The PAGER-NoConflict ablation passed the full agent pool to the PolicyEngine, skipping the AgentRegistry capability pre-filter used by every other variant. Corrected: NoConflict routing accuracy 55.8% -> 94.8%.
2. had_conflict was not recorded in the NoPolicy, NoConflict and weight-sweep loops, so conflict-resolution effectiveness showed 0.0 there. Corrected: NoPolicy 100.0, NoConflict 42.9, weight sweep matches the strategy table.

Experiment 1 (main comparison) and the strategy comparison are unchanged. The MedAgentBench dataset is not redistributed; place test_data_v2.json in data/medagentbench/ to reproduce.