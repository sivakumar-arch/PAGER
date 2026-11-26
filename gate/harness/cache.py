"""Append-only, content-addressed cache for every external call (AMENDMENTS.md 26 Nov, raw response cache).

One JSONL file per namespace under gate/results/cache/. Each record keeps the full raw response.
Modes:
  live    read the cache; on a miss, make the call and append the record
  replay  read the cache only; a miss is an error (this is how reruns and reviewers reproduce results)
The cache files are committed with the results.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from .common import RESULTS

CACHE_DIR = RESULTS / "cache"


def sha(obj: Any) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class CacheMiss(RuntimeError):
    pass


class Cache:
    def __init__(self, namespace: str, mode: str = "live", directory: Path | None = None):
        assert mode in ("live", "replay"), mode
        self.mode = mode
        self.path = (directory or CACHE_DIR) / f"{namespace}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.store: dict[str, dict] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.store[rec["key"]] = rec

    def get_or_call(self, key_material: dict, call: Callable[[], dict]) -> dict:
        key = sha(key_material)
        if key in self.store:
            return self.store[key]
        if self.mode == "replay":
            raise CacheMiss(f"{self.path.name}: no cached response for key {key[:12]} ({key_material.get('kind')})")
        payload = call()
        rec = {"key": key, "key_material": key_material, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               **payload}
        with self.path.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.store[key] = rec
        return rec
