"""Shared constants and loaders. Every number here is taken from the frozen protocol or the pinning file."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "gate"
SCENARIOS = GATE / "scenarios/scenarios_v1.json"
AGENTS = GATE / "agents/gate_agents.yaml"
PROMPTS = GATE / "prompts"
RESULTS = GATE / "results"

PHI, NONPHI, RUNTIME = "PHI", "NONPHI", "RUNTIME"

# PROTOCOL.md section 5
TAU = 0.5
TAU_LOW = 0.2
PRESIDIO_ENTITIES = [
    "PERSON", "LOCATION", "DATE_TIME", "PHONE_NUMBER", "EMAIL_ADDRESS", "US_SSN",
    "US_DRIVER_LICENSE", "MEDICAL_LICENSE", "IP_ADDRESS", "URL",
]

# PINNING.md
OLLAMA_URL = "http://localhost:11434"
LLM_MODEL = "gemma4:31b"
LLM_MODEL_ID = "92808281a855"
LLM_SEED = 20261126
LLM_TEMPERATURE = 0
PIN_VERSIONS = {
    "presidio-analyzer": "2.2.359",
    "presidio-anonymizer": "2.2.363",
    "spacy": "3.8.18",
    "en_core_web_lg": "3.8.0",
    "ollama": "0.40.8",
}

POLICIES = ["PROP", "REDETECT", "SRC", "SRC-FC"]          # each run with every detector
DETECTORS = ["rule", "presidio", "llm_off", "llm_on"]     # rule = author-written
NON_AUTHOR = ["presidio", "llm_off", "llm_on"]            # D* candidates (AMENDMENTS 26 Nov)
LLM_DETECTORS = ["llm_off", "llm_on"]

# AMENDMENTS.md 26 Nov: flag threshold for parse failures (more than 3 scenarios)
PARSE_FAIL_FLAG = 3

# PROTOCOL.md section 8, H2 perturbation seed
PERTURB_SEED = 20261126


@dataclass(frozen=True)
class Agent:
    id: str
    capabilities: tuple[str, ...]
    hipaa_compliant: bool
    cost: float


def load_scenarios() -> list[dict]:
    return json.loads(SCENARIOS.read_text())["scenarios"]


def load_pool() -> tuple[dict, list[Agent]]:
    pool = yaml.safe_load(AGENTS.read_text())
    agents = [Agent(a["id"], tuple(a["capabilities"]), bool(a["hipaa_compliant"]), float(a["cost"]))
              for a in pool["agents"]]
    return pool["capabilities"], agents


class Resolver:
    """PROTOCOL.md section 4: cheapest agent allowed by the label, ties by id; deny if none."""

    def __init__(self, agents: list[Agent]):
        self.agents = agents
        self.by_id = {a.id: a for a in agents}

    def candidates(self, cap: str) -> list[Agent]:
        return sorted((a for a in self.agents if cap in a.capabilities), key=lambda a: (a.cost, a.id))

    def resolve(self, cap: str, label: str) -> Agent | None:
        allowed = [a for a in self.candidates(cap) if label == NONPHI or a.hipaa_compliant]
        return allowed[0] if allowed else None


def read_prompt(name: str) -> str:
    return (PROMPTS / name).read_text()


def fill(template: str, **values: str) -> str:
    """PROTOCOL.md section 9: substitute by string replacement, never str.format (templates contain JSON braces)."""
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out
