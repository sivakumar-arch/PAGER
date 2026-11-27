"""Chain gate configuration.

The resolver strategy goes through Paper 1's ConflictResolver interface, so any of its
strategies can be selected; cost-aware is the default because the gate used it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.pager.conflict_resolver import VALID_STRATEGIES, ConflictResolver
from src.pager_chain.labels import POLICIES
from src.utils.config_loader import ConfigLoadError, load_yaml

DEFAULT_CONFIG = Path("configs/chain/pager_chain.yaml")


@dataclass(frozen=True)
class ChainConfig:
    agent_config: str = "configs/agents/chain_gate_agents.yaml"
    policy_dirs: tuple[str, ...] = ("policies/chain",)
    label_policy: str = "SRC-FC"
    resolver_strategy: str = "cost_aware"
    resolver_weights: dict = field(default_factory=lambda: {
        "cost_weight": 0.4, "latency_weight": 0.3, "quality_weight": 0.3})

    def __post_init__(self) -> None:
        if self.resolver_strategy not in VALID_STRATEGIES:
            raise ValueError(f"resolver_strategy must be one of {sorted(VALID_STRATEGIES)}, "
                             f"got {self.resolver_strategy!r}")
        if self.label_policy not in POLICIES:
            raise ValueError(f"label_policy must be one of {sorted(POLICIES)}, got {self.label_policy!r}")

    def build_resolver(self) -> ConflictResolver:
        """Paper 1's resolver with the configured default strategy."""
        return ConflictResolver(default_strategy=self.resolver_strategy, **self.resolver_weights)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG) -> "ChainConfig":
        raw = load_yaml(path).get("pager_chain")
        if not isinstance(raw, dict):
            raise ConfigLoadError(f"Missing top-level 'pager_chain' key: {path}")
        if "policy_dirs" in raw:
            raw = {**raw, "policy_dirs": tuple(raw["policy_dirs"])}
        return cls(**raw)
