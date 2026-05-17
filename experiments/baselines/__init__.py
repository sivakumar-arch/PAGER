"""PAGER baseline routers for comparative evaluation."""

from experiments.baselines.base_router import BaseRouter, RoutingDecision
from experiments.baselines.random_router import RandomRouter
from experiments.baselines.round_robin_router import RoundRobinRouter
from experiments.baselines.rule_based_router import RuleBasedRouter
from experiments.baselines.embedding_router import EmbeddingRouter

__all__ = [
    "BaseRouter",
    "RoutingDecision",
    "RandomRouter",
    "RoundRobinRouter",
    "RuleBasedRouter",
    "EmbeddingRouter",
]
