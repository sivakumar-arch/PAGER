# Gate protocol amendments

Every change to `gate/PROTOCOL.md`, `gate/scenarios/*`, `gate/agents/*` or `gate/prompts/*` after the freeze commit is logged here, newest last. Results are reported under both the original and the amended rule.

| Date | Change | Reason | Results existed at the time? |
|---|---|---|---|
| 26 Nov 2026 | Sections 5 and 8: the LLM classifier is run in two configurations of the same pinned model, thinking off and thinking on (PINNING.md). Both are candidates for D*, alongside Presidio. | The protocol does not say whether the model's thinking mode is used, and picking one after the fact would be an unregistered choice. Taking the better of the two can only make FAIL or NARROW more likely, never PASS. | No |
| 26 Nov 2026 | Section 5 item 3: if the LLM's output does not parse as the required JSON after one retry with identical settings, the score is s = 1.0 (treated as PHI) and the event is counted and reported per configuration. | The protocol did not define this case. Treating an unusable answer as PHI matches how a deployed fail-safe gate would behave. | No |
| 26 Nov 2026 | Sections 7 and 8: every LLM configuration is reported twice, with parse failures scored as PHI (s = 1.0) and with those scenarios excluded. If parse failures exceed 3 of 70 scenarios for a configuration, it is flagged in the memo, D* is chosen under both versions, and if the two choices differ the H1 outcome is GRAY. | Scoring failures as PHI lowers false allows and raises false denials, so frequent failures could win the D* slot through the fallback rule rather than the model's judgment. | No |
| 26 Nov 2026 | Section 9: every raw LLM response (classifier and planner) is cached and committed with the results, and reruns read the cache. | Temperature 0 and a fixed seed do not guarantee identical output across hardware or Ollama versions. The cache is the reproducibility guarantee. | No |
