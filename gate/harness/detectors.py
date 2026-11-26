"""Detectors (PROTOCOL.md section 5, PINNING.md) and the Ollama client shared with the planner.

Each detector returns Detection(score, ok). ok=False only for an LLM answer that still fails to parse
after one retry; its score is then 1.0 (AMENDMENTS.md 26 Nov) and the failure is reported.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib import metadata

from .cache import Cache, sha
from .common import (LLM_MODEL, LLM_MODEL_ID, LLM_SEED, LLM_TEMPERATURE, OLLAMA_URL, PIN_VERSIONS,
                     PRESIDIO_ENTITIES, ROOT, fill, read_prompt)


@dataclass
class Detection:
    score: float
    ok: bool = True
    detail: dict = field(default_factory=dict)


class Detector:
    name = "base"

    def score(self, text: str) -> Detection:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------- rule-based (author-written)
class RuleDetector(Detector):
    name = "rule"

    def __init__(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from src.pager.query_analyzer import QueryAnalyzer  # Paper 1 code, unchanged
        self._qa = QueryAnalyzer()

    def score(self, text: str) -> Detection:
        return Detection(1.0 if self._qa._detect_pii(text) else 0.0)


# ---------------------------------------------------------------- Presidio
def check_pinned_versions(packages: list[str]) -> None:
    """Refuse to make live Presidio calls with versions other than the pinned ones."""
    for p in packages:
        got = metadata.version(p)
        if got != PIN_VERSIONS[p]:
            raise RuntimeError(f"{p} {got} installed, but PINNING.md pins {PIN_VERSIONS[p]}")


class _PresidioEngines:
    analyzer = None
    anonymizer = None

    @classmethod
    def get(cls):
        if cls.analyzer is None:
            check_pinned_versions(["presidio-analyzer", "presidio-anonymizer", "spacy", "en_core_web_lg"])
            from presidio_analyzer import AnalyzerEngine
            from presidio_analyzer.nlp_engine import NlpEngineProvider
            from presidio_anonymizer import AnonymizerEngine
            nlp = NlpEngineProvider(nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}]}).create_engine()
            cls.analyzer = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en"])
            cls.anonymizer = AnonymizerEngine()
        return cls.analyzer, cls.anonymizer


def _presidio_key(kind: str, text: str) -> dict:
    return {"kind": kind, "versions": {k: PIN_VERSIONS[k] for k in
                                       ("presidio-analyzer", "presidio-anonymizer", "spacy", "en_core_web_lg")},
            "entities": PRESIDIO_ENTITIES, "text": text}


def presidio_analyze(text: str, cache: Cache) -> list[dict]:
    def call():
        analyzer, _ = _PresidioEngines.get()
        res = analyzer.analyze(text=text, language="en", entities=PRESIDIO_ENTITIES)
        return {"results": [{"entity_type": r.entity_type, "start": r.start, "end": r.end,
                             "score": float(r.score)} for r in res]}
    return cache.get_or_call(_presidio_key("presidio_analyze", text), call)["results"]


class PresidioDetector(Detector):
    name = "presidio"

    def __init__(self, cache: Cache):
        self.cache = cache

    def score(self, text: str) -> Detection:
        res = presidio_analyze(text, self.cache)
        s = max((r["score"] for r in res), default=0.0)
        return Detection(s, True, {"entities": res})


def presidio_deidentify(text: str, cache: Cache) -> str:
    """De-identification agent (PROTOCOL.md 5.4): default operators on the same analyzer configuration."""
    def call():
        from presidio_analyzer import RecognizerResult
        analyzer, anonymizer = _PresidioEngines.get()
        res = analyzer.analyze(text=text, language="en", entities=PRESIDIO_ENTITIES)
        out = anonymizer.anonymize(text=text, analyzer_results=[
            RecognizerResult(r.entity_type, r.start, r.end, r.score) for r in res])
        return {"output": out.text,
                "results": [{"entity_type": r.entity_type, "start": r.start, "end": r.end,
                             "score": float(r.score)} for r in res]}
    return cache.get_or_call(_presidio_key("presidio_anonymize", text), call)["output"]


# ---------------------------------------------------------------- Ollama
class OllamaClient:
    """Minimal client for /api/chat (no extra dependency). Verifies the pinned model ID before any live call."""

    def __init__(self, cache: Cache, url: str = OLLAMA_URL):
        self.cache, self.url = cache, url
        self._verified = False

    def _post(self, path: str, payload: dict | None = None, timeout: int = 1800) -> dict:
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="GET" if payload is None else "POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:      # show Ollama's own error message, then stop
            body = e.read().decode("utf-8", "replace")
            raise RuntimeError(f"Ollama {path} returned HTTP {e.code}: {body}") from None

    def verify_model(self) -> str:
        tags = self._post("/api/tags")
        for m in tags.get("models", []):
            if m.get("name") == LLM_MODEL:
                if not m.get("digest", "").startswith(LLM_MODEL_ID):
                    raise RuntimeError(f"{LLM_MODEL} digest {m.get('digest')} does not match pinned ID {LLM_MODEL_ID}")
                self._verified = True
                return m["digest"]
        raise RuntimeError(f"{LLM_MODEL} not found in Ollama")

    def chat_json(self, role: str, prompt_name: str, values: dict, schema: dict, think: bool,
                  validate) -> dict:
        """Return {'parsed': obj or None, 'ok': bool, 'attempts': [...]}; one retry with identical settings."""
        template = read_prompt(prompt_name)
        prompt = fill(template, **values)
        key = {"kind": "llm", "role": role, "model": LLM_MODEL, "model_id": LLM_MODEL_ID, "think": think,
               "temperature": LLM_TEMPERATURE, "seed": LLM_SEED, "prompt_sha": sha(template),
               "schema_sha": sha(schema), "values": values}

        def call():
            if not self._verified:
                self.verify_model()
            attempts = []
            for _ in range(2):
                resp = self._post("/api/chat", {
                    "model": LLM_MODEL, "stream": False, "think": think, "format": schema,
                    "messages": [{"role": "user", "content": prompt}],
                    "options": {"temperature": LLM_TEMPERATURE, "seed": LLM_SEED}})
                msg = resp.get("message", {})
                content = msg.get("content", "")
                attempt = {"content": content, "thinking": msg.get("thinking"), "model": resp.get("model"),
                           "eval_count": resp.get("eval_count"), "total_duration_ns": resp.get("total_duration"),
                           "done_reason": resp.get("done_reason")}
                parsed = _parse(content, validate)
                attempt["parsed_ok"] = parsed is not None
                attempts.append(attempt)
                if parsed is not None:
                    break
            return {"attempts": attempts}

        rec = self.cache.get_or_call(key, call)
        last = rec["attempts"][-1]
        parsed = _parse(last["content"], validate)
        return {"parsed": parsed, "ok": parsed is not None, "attempts": rec["attempts"]}


def _parse(content: str, validate):
    try:
        obj = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    return obj if validate(obj) else None


CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {"phi": {"type": "boolean"}, "p_phi": {"type": "number"},
                   "identifiers": {"type": "array", "items": {"type": "string"}}},
    "required": ["phi", "p_phi", "identifiers"],
}


def _valid_classifier(o) -> bool:
    return (isinstance(o, dict) and isinstance(o.get("phi"), bool)
            and isinstance(o.get("p_phi"), (int, float)) and not isinstance(o.get("p_phi"), bool)
            and 0.0 <= float(o["p_phi"]) <= 1.0 and isinstance(o.get("identifiers"), list))


class LLMDetector(Detector):
    def __init__(self, client: OllamaClient, think: bool):
        self.client, self.think = client, think
        self.name = "llm_on" if think else "llm_off"

    def score(self, text: str) -> Detection:
        r = self.client.chat_json("classifier", "phi_classifier.txt", {"text": text}, CLASSIFIER_SCHEMA,
                                  self.think, _valid_classifier)
        if not r["ok"]:
            return Detection(1.0, False, {"parse_failure": True})   # AMENDMENTS.md 26 Nov
        return Detection(float(r["parsed"]["p_phi"]), True, {"identifiers": r["parsed"]["identifiers"]})
