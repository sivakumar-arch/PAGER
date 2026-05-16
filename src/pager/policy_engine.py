"""PolicyEngine: OPA/Rego-based policy evaluation for agent routing.

Evaluates all registered agents against applicable Rego policies,
producing compliant agent lists and audit trails for ConflictResolver.

Design rationale (Section 4.3):
    OPA is an industry-standard declarative policy engine used in
    enterprise systems. Static policy loading is sufficient for POC
    where policies do not change at runtime. Dynamic policy reloading
    represents a production deployment enhancement, not a PAGER
    research contribution.
"""

import json
from pathlib import Path

from opa_client.opa import OpaClient

from src.models.agent import Agent
from src.models.policy_result import PolicyEvaluationResult, PolicyViolation, SoftHint
from src.models.query import AnalyzedQuery
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Soft hint policy names (do not deny — only guide ConflictResolver)
_SOFT_POLICIES: frozenset[str] = frozenset(
    {"cost_optimization", "sla_requirements", "consent", "data_residency"}
    - {"pii_access", "authorization", "sensitivity"}
)


class PolicyEngine:
    """Evaluates agents against OPA/Rego policies for a given query.

    Loads all .rego files from specified policy directories at init.
    Evaluates each (agent, policy) pair and collects:
      - Hard violations  → deny the agent entirely
      - Soft hints       → guide ConflictResolver (cost/SLA preferences)

    Usage:
        engine = PolicyEngine(policy_dirs=["policies/hipaa"])
        result = engine.evaluate(query=analyzed_query, agents=capable_agents)
        compliant = result.compliant_agents
    """

    def __init__(self, policy_dirs: list[str | Path]) -> None:
        """Initialize PolicyEngine with OPA client and load policies.

        Args:
            policy_dirs: List of directories containing .rego policy files.

        Raises:
            FileNotFoundError: If any policy directory doesn't exist.
        """
        self._policy_dirs = [Path(d) for d in policy_dirs]
        self._policies: dict[str, str] = {}  # filename → rego content
        self._opa = OpaClient()
        self._load_policies()

    def _load_policies(self) -> None:
        """Load all .rego files from configured policy directories."""
        for policy_dir in self._policy_dirs:
            if not policy_dir.exists():
                raise FileNotFoundError(
                    f"Policy directory not found: {policy_dir}"
                )
            for rego_file in sorted(policy_dir.glob("*.rego")):
                content = rego_file.read_text()
                self._policies[rego_file.stem] = content
                logger.debug(
                    "Policy loaded", policy=rego_file.stem, file=str(rego_file)
                )

        logger.info(
            "PolicyEngine initialized",
            policy_count=len(self._policies),
            policies=list(self._policies.keys()),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        query: AnalyzedQuery,
        agents: list[Agent],
    ) -> PolicyEvaluationResult:
        """Evaluate all agents against all loaded policies for this query.

        Args:
            query: Analyzed query with PII flags, sensitivity, user context.
            agents: Candidate agents from AgentRegistry.

        Returns:
            PolicyEvaluationResult with compliant agents, violations, and hints.
        """
        if not agents:
            logger.warning("PolicyEngine received empty agent list")
            return PolicyEvaluationResult(
                compliant_agents=[],
                violations={},
                soft_hints=[],
                policy_trace={},
                total_agents_evaluated=0,
            )

        violations: dict[str, list[PolicyViolation]] = {}
        soft_hints: list[SoftHint] = []
        policy_trace: dict = {}

        for agent in agents:
            agent_violations, agent_hints, agent_trace = self._evaluate_agent(
                query, agent
            )
            policy_trace[agent.id] = agent_trace

            if agent_violations:
                violations[agent.id] = agent_violations
            soft_hints.extend(agent_hints)

        compliant_agents = [
            a.id for a in agents if a.id not in violations
        ]

        result = PolicyEvaluationResult(
            compliant_agents=compliant_agents,
            violations=violations,
            soft_hints=soft_hints,
            policy_trace=policy_trace,
            total_agents_evaluated=len(agents),
        )

        logger.info(
            "Policy evaluation complete",
            total=len(agents),
            compliant=len(compliant_agents),
            denied=len(violations),
            hints=len(soft_hints),
        )
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evaluate_agent(
        self,
        query: AnalyzedQuery,
        agent: Agent,
    ) -> tuple[list[PolicyViolation], list[SoftHint], dict]:
        """Evaluate a single agent against all loaded policies.

        Returns:
            Tuple of (violations, soft_hints, trace_record)
        """
        violations: list[PolicyViolation] = []
        hints: list[SoftHint] = []
        trace: dict = {}

        # Build OPA input document
        opa_input = self._build_opa_input(query, agent)

        for policy_name, rego_content in self._policies.items():
            try:
                result = self._query_opa(opa_input, rego_content, policy_name)
                trace[policy_name] = result

                # Hard violations — deny the agent
                deny_messages = result.get("deny", [])
                for msg in deny_messages:
                    violations.append(
                        PolicyViolation(
                            agent_id=agent.id,
                            policy_file=f"{policy_name}.rego",
                            message=msg,
                        )
                    )

                # Soft hints — guide ConflictResolver, don't deny
                for hint_data in result.get("soft_hints", []):
                    hints.append(
                        SoftHint(
                            hint_type=hint_data.get("type", policy_name),
                            agent_id=agent.id,
                            message=hint_data.get("message", ""),
                            metadata={"weight": hint_data.get("weight", 0.0)},
                        )
                    )

            except Exception as e:
                logger.error(
                    "OPA evaluation error",
                    policy=policy_name,
                    agent=agent.id,
                    error=str(e),
                )
                # Fail closed — treat OPA errors as violations
                violations.append(
                    PolicyViolation(
                        agent_id=agent.id,
                        policy_file=f"{policy_name}.rego",
                        message=f"Policy evaluation failed: {e}",
                    )
                )

        return violations, hints, trace

    def _query_opa(
        self, opa_input: dict, rego_content: str, policy_name: str
    ) -> dict:
        """Query OPA with input document and Rego policy.

        Returns the raw OPA result dict.
        """
        result = self._opa.check_policy_rule(
            input_data=opa_input,
            package_path=f"pager/hipaa",
            rule_name="deny",
        )
        return result if isinstance(result, dict) else {}

    @staticmethod
    def _build_opa_input(query: AnalyzedQuery, agent: Agent) -> dict:
        """Build the OPA input document for a (query, agent) pair.

        The input schema is consumed by all Rego policies.
        """
        return {
            "query": {
                "raw": query.raw_query,
                "intent": query.intent,
                "contains_pii": query.contains_pii,
                "data_sensitivity": query.data_sensitivity,
                "required_capabilities": query.required_capabilities,
                "user_region": query.user_region,
                "requires_consent": query.requires_consent,
            },
            "agent": {
                "id": agent.id,
                "name": agent.name,
                "hipaa_compliant": agent.hipaa_compliant,
                "gdpr_compliant": agent.gdpr_compliant,
                "authorized_roles": agent.authorized_roles,
                "data_access_level": agent.data_access_level,
                "cost_per_query": agent.cost_per_query,
                "avg_latency_ms": agent.avg_latency_ms,
                "quality_score": agent.quality_score,
                "data_residency": agent.data_residency,
                "consent_aware": agent.consent_aware,
            },
            "context": {
                "user_role": query.user_role,
                "user_region": query.user_region,
            },
        }

    def policy_count(self) -> int:
        """Return number of loaded policies."""
        return len(self._policies)

    def policy_names(self) -> list[str]:
        """Return names of all loaded policies."""
        return list(self._policies.keys())

    def __repr__(self) -> str:
        return f"PolicyEngine(policies={list(self._policies.keys())})"
