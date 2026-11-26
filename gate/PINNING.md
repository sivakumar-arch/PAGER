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
| LLM classifier | Ollama tag `gemma4:31b-it-q8_0`, ID `ac97b596ee1f` (Gemma 4 31B instruction-tuned, dense, 30.7B parameters as reported by Ollama; Q8_0 8-bit quantisation; llama.cpp runner; Ollama default context of 32768 tokens). The harness refuses to call the model unless the digest reported by Ollama starts with this ID. Two configurations of the same model, both candidates for D* (AMENDMENTS.md, 26 Nov): **LLM-off** with `think: false`, **LLM-on** with `think: true` |

LLM call settings (classifier and planner): `temperature: 0`, `seed: 20261126`, `format` set to the JSON schema stated in the prompt file, prompt sent as a single user message with no system message. With thinking on, only the final JSON content is scored; the thinking text is stored in the results for audit.

## De-identification agent

presidio-anonymizer 2.2.363, default operators, analyzer configuration as above.

## Planner (H2)

Same model and ID as the classifier, `gemma4:31b-it-q8_0` (`ac97b596ee1f`), with `think: true`. The strongest qualifying model available is used, so that a weak planner cannot inflate planner errors or over-access (H2b).

## Not used

`gemma4:31b` (ID `92808281a855`, NVFP4) was pinned first but cannot be used: Ollama returns "structured output is unavailable" (HTTP 501) for it (AMENDMENTS.md, 26 Nov). `mistral-small3.2:24b` (dense 24B, Q4_K_M) qualifies but is weaker, so it is not used for either role. `qwen3:30b` and `gpt-oss:20b` are mixture-of-experts models with about 3B to 4B active parameters and do not meet section 5 item 3.

## Limitations of the pinned configuration

- The LLM runs at 8-bit (Q8_0), not full precision. The quality loss from 8-bit quantisation is usually small, but it is reported in the memo; any weakening of the detector would lean the gate toward PASS.
- The GPU/CPU split of the loaded model and the GPU memory limit are recorded in env.json for every run.
