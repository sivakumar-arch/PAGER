"""Package 1 tests: chain agent registry, its equivalence with the frozen gate pool, and config."""

from __future__ import annotations

import pytest
import yaml

from src.models.agent import Agent
from src.models.policy_result import PolicyEvaluationResult
from src.pager.agent_registry import AgentRegistry
from src.pager.conflict_resolver import VALID_STRATEGIES
from src.pager_chain.config import ChainConfig
from src.pager_chain.registry import ChainAgentRegistry
from src.utils.config_loader import ConfigLoadError

CHAIN_AGENTS = "configs/agents/chain_gate_agents.yaml"
GATE_AGENTS = "gate/agents/gate_agents.yaml"


@pytest.fixture
def reg() -> ChainAgentRegistry:
    return ChainAgentRegistry(CHAIN_AGENTS)


def test_chain_pool_matches_frozen_gate_pool_exactly(reg):
    gate = yaml.safe_load(open(GATE_AGENTS))
    expected = {a["id"]: (sorted(a["capabilities"]), a["hipaa_compliant"], a["cost"]) for a in gate["agents"]}
    got = {a.id: (sorted(a.capabilities), a.hipaa_compliant, a.cost_per_query) for a in reg.get_all_agents()}
    assert got == expected
    for name, spec in gate["capabilities"].items():
        c = reg.capability(name)
        assert c.record_access == spec["record_access"]
        assert c.declassifier == bool(spec.get("declassifier", False))
    assert reg.capabilities() == sorted(gate["capabilities"])


def test_neutral_fields_are_identical_across_agents(reg):
    vals = {(a.gdpr_compliant, tuple(a.authorized_roles), a.data_access_level, a.avg_latency_ms, a.quality_score)
            for a in reg.get_all_agents()}
    assert vals == {(False, (), 2, 100.0, 0.80)}


def test_lookup_by_capability(reg):
    assert [a.id for a in reg.agents_for_capability("text.summarize")] == ["summ_lite", "summ_secure"]
    assert [a.id for a in reg.agents_for_capability("text.translate")] == ["translate_ext"]
    assert reg.capability("text.deidentify").declassifier
    assert reg.capability("ehr.order_lab").touches_record and not reg.capability("knowledge.answer").touches_record
    with pytest.raises(KeyError):
        reg.capability("ehr.delete_patient")


def test_is_still_a_paper1_registry(reg):
    assert isinstance(reg, AgentRegistry) and reg.count() == 13
    assert isinstance(reg.get_agent("deid_presidio"), Agent)
    AgentRegistry("configs/agents/healthcare_agents.yaml")   # Paper 1 config still loads unchanged


def test_registry_rejects_bad_tables(tmp_path):
    agent = """
agents:
  - id: a_one
    name: "A"
    capabilities: ["x.do"]
    hipaa_compliant: true
    gdpr_compliant: false
    authorized_roles: []
    data_access_level: 2
    cost_per_query: 0.01
    avg_latency_ms: 1.0
    quality_score: 0.5
    endpoint: "mock://a"
    max_concurrent: 1
"""
    cases = {
        "missing": agent,
        "unknown_cap": agent + "capabilities:\n  y.do: {record_access: none}\n  x.dont: {record_access: none}\n",
        "bad_access": agent + "capabilities:\n  x.do: {record_access: sometimes}\n",
    }
    for name, text in cases.items():
        p = tmp_path / f"{name}.yaml"
        p.write_text(text)
        with pytest.raises(ConfigLoadError):
            ChainAgentRegistry(p)


def test_config_defaults_and_validation():
    cfg = ChainConfig.load()
    assert (cfg.label_policy, cfg.resolver_strategy) == ("SRC-FC", "cost_aware")
    assert cfg.agent_config == CHAIN_AGENTS and cfg.policy_dirs == ("policies/chain",)
    with pytest.raises(ValueError):
        ChainConfig(resolver_strategy="cheapest")
    with pytest.raises(ValueError):
        ChainConfig(label_policy="ORACLE")


@pytest.mark.parametrize("strategy", sorted(VALID_STRATEGIES))
def test_every_paper1_strategy_plugs_in(strategy, reg):
    resolver = ChainConfig(resolver_strategy=strategy).build_resolver()
    cands = reg.agents_for_capability("text.summarize")
    res = resolver.resolve(cands, PolicyEvaluationResult(compliant_agents=[a.id for a in cands], violations={},
                                                         soft_hints=[], policy_trace={},
                                                         total_agents_evaluated=len(cands)))
    assert res.selected_agent_id in {"summ_lite", "summ_secure"} and res.strategy_used == strategy


def test_cost_aware_picks_cheapest_compliant(reg):
    resolver = ChainConfig().build_resolver()
    cands = reg.agents_for_capability("text.summarize")
    both = PolicyEvaluationResult(compliant_agents=["summ_lite", "summ_secure"], violations={}, soft_hints=[],
                                  policy_trace={}, total_agents_evaluated=2)
    only_secure = PolicyEvaluationResult(compliant_agents=["summ_secure"], violations={}, soft_hints=[],
                                         policy_trace={}, total_agents_evaluated=2)
    assert resolver.resolve(cands, both).selected_agent_id == "summ_lite"
    assert resolver.resolve(cands, only_secure).selected_agent_id == "summ_secure"
