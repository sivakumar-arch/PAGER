"""Chain agent registry: Paper 1's AgentRegistry plus capability-level lookup.

The YAML keeps Paper 1's `agents` list unchanged in format and adds a `capabilities`
table that says, for each capability, whether it touches a patient record and whether
it is a declassifier. Paper 1's loader reads only `agents`, so the extra key is invisible
to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.models.agent import Agent
from src.pager.agent_registry import AgentRegistry
from src.utils.config_loader import ConfigLoadError, load_yaml

RECORD_ACCESS = {"none", "read", "write"}


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    record_access: str          # none | read | write
    declassifier: bool = False

    @property
    def touches_record(self) -> bool:
        return self.record_access != "none"


class ChainAgentRegistry(AgentRegistry):
    """AgentRegistry with a capability table and lookup by capability name."""

    def __init__(self, config_path: str | Path) -> None:
        super().__init__(config_path)
        raw = load_yaml(config_path).get("capabilities")
        if not isinstance(raw, dict) or not raw:
            raise ConfigLoadError(f"Chain agent config needs a non-empty 'capabilities' table: {config_path}")
        self._caps: dict[str, CapabilitySpec] = {}
        for name, spec in raw.items():
            access = (spec or {}).get("record_access")
            if access not in RECORD_ACCESS:
                raise ConfigLoadError(f"Capability {name!r}: record_access must be one of {sorted(RECORD_ACCESS)}")
            self._caps[name] = CapabilitySpec(name, access, bool((spec or {}).get("declassifier", False)))
        unknown = {c for a in self.get_all_agents() for c in a.capabilities} - set(self._caps)
        if unknown:
            raise ConfigLoadError(f"Agents use capabilities missing from the table: {sorted(unknown)}")
        unserved = [c for c in self._caps if not self.agents_for_capability(c)]
        if unserved:
            raise ConfigLoadError(f"Capabilities with no agent: {unserved}")

    def capability(self, name: str) -> CapabilitySpec:
        try:
            return self._caps[name]
        except KeyError:
            raise KeyError(f"Unknown capability {name!r}") from None

    def capabilities(self) -> list[str]:
        return sorted(self._caps)

    def agents_for_capability(self, name: str) -> list[Agent]:
        """All agents offering this capability, sorted by id (the resolver applies its own ordering)."""
        return sorted((a for a in self.get_all_agents() if name in a.capabilities), key=lambda a: a.id)
