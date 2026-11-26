# Day 2 pinning (committed before any run)

Date: 26 Nov 2026. Fills in the items PROTOCOL.md section 9 leaves open. One rule change made at the same time is logged in AMENDMENTS.md.

## Machine and runtime

- Apple M5 Pro, 48 GB unified memory, macOS 26.5.2.
- Ollama 0.40.8.
- Recorded automatically by the harness at run time, in every results file: Python version, `pip freeze`, `ollama --version`, and the model ID returned for each call.

## Detectors

| Detector | Pinned as |
|---|---|
| Rule-based | `src/pager/query_analyzer.py`, unchanged since tag `v1.0.0-paper1` (commit 725fbf7) |
| Presidio | presidio-analyzer 2.2.359, spaCy 3.8.18, en_core_web_lg 3.8.0; configuration as in PROTOCOL.md section 5 item 2 |
| LLM classifier | Ollama tag `gemma4:31b`, ID `92808281a855` (Gemma 4 31B, dense, 31.7B parameters as reported by Ollama; NVFP4 4-bit floating-point quantisation). Two configurations of the same model, both candidates for D* (AMENDMENTS.md, 26 Nov): **LLM-off** with `think: false`, **LLM-on** with `think: true` |

LLM call settings (classifier and planner): `temperature: 0`, `seed: 20261126`, `format` set to the JSON schema stated in the prompt file, prompt sent as a single user message with no system message. With thinking on, only the final JSON content is scored; the thinking text is stored in the results for audit.

## De-identification agent

presidio-anonymizer 2.2.363, default operators, analyzer configuration as above.

## Planner (H2)

Same model and ID as the classifier, `gemma4:31b` (`92808281a855`), with `think: true`. The strongest qualifying model available is used, so that a weak planner cannot inflate planner errors or over-access (H2b).

## Not used

`mistral-small3.2:24b` (dense 24B, Q4_K_M) qualifies but is weaker, so it is not used for either role. `qwen3:30b` and `gpt-oss:20b` are mixture-of-experts models with about 3B to 4B active parameters and do not meet section 5 item 3.

## Limitations of the pinned configuration

- The LLM runs in a 4-bit format (NVFP4). Quantization may weaken the detector slightly, which leans the gate toward PASS. The thinking-mode configuration and Presidio partly offset this. Reported as a limitation in the memo.
