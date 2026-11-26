"""Run provenance recorded in every results folder (PINNING.md, 'recorded automatically')."""

from __future__ import annotations

import platform
import subprocess
import sys
import time

from .common import ROOT


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=ROOT).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def capture(model_digest: str | None = None) -> dict:
    return {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "git_commit": _run(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(_run(["git", "status", "--porcelain", "--untracked-files=no"])),
        "ollama_version": _run(["ollama", "--version"]),
        "ollama_model_digest": model_digest,
        "ollama_ps": _run(["ollama", "ps"]),                       # GPU/CPU split of the loaded model
        "gpu_wired_limit_mb": _run(["sysctl", "-n", "iogpu.wired_limit_mb"]),
        "pip_freeze": (_run([sys.executable, "-m", "pip", "freeze"]) or "").splitlines(),
    }
