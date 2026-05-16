"""PolicyEngine: OPA/Rego-based policy evaluation for agent routing.

Evaluates all registered agents against applicable Rego policies,
producing compliant agent lists and audit trails for ConflictResolver.

Implementation approach (POC):
    Uses OPA CLI via subprocess (`opa eval`) for policy evaluation.
    This avoids requiring a persistent OPA server process, keeping the
    POC self-contained. Production deployment would use OPA server mode
    with opa-python-client for better performance and policy hot-reload.

    OPA CLI is invoked per (agent, policy) pair with structured JSON input.
    Fail-closed: OPA errors are treated as policy violations.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from src.models.agent import Agent
from src.models.policy_result import PolicyEvaluationResult, PolicyViolation, SoftHint
from src.models.query import AnalyzedQuery
from src.utils.logger import get_logger

logger = get_logger(__name__)


class PolicyEngine:
    """Evaluates agents against OPA/Rego policies for a given query.

    Loads all .rego files from specified policy directories at init.
    Evaluates each (agent, policy) pair using OPA CLI and collects:
      - Hard violations  → deny the agent entirely
      - Soft hints       → guide ConflictResolver (cost/SLA preferences)

    Usage:
        engine = PolicyEngine(policy_dirs=["policies/hipaa"])
        result = engine.evaluate(query=analyzed_query, agents=capable_agents)
        compliant = result.compliant_agents
    """

    def __init__(self, policy_dirs: list[str | Path]) -> None:
        """Initialize PolicyEngine and load all .rego policy files.

        Args:
            policy_dirs: List of directories containing .rego policy files.

        Raises:
            FileNotFoundError: If any policy directory doesn't exist.
            RuntimeError: If OPA CLI is not installed/accessible.
        """
        self._policy_dirs = [Path(d) for d in policy_dirs]
        self._policies: dict[str, str] = {}  # policy_name → rego content
        self._verify_opa_installed()
        self._load_policies()

    def _verify_opa_installed(self) -> None:
        """Verify OPA CLI is available on PATH."""
        try:
            result = subprocess.run(
                ["opa", "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise RuntimeError("OPA CLI returned non-zero exit code")
            logger.info("OPA CLI verified", version=result.stdout.split("\n")[0].strip())
        except FileNotFoundError:
            raise RuntimeError(
                "OPA CLI not found. Install OPA: https://www.openpolicyagent.org/docs/latest/#running-opa\n"
                "macOS: brew install opa\n"
                "Linux: curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static && chmod +x opa && sudo mv opa /usr/local/bin/"
            )

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
                logger.debug("Policy loaded", policy=rego_file.stem)

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

        compliant_agents = [a.id for a in agents if a.id not in violations]

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
        """Evaluate a single agent against all loaded policies."""
        violations: list[PolicyViolation] = []
        hints: list[SoftHint] = []
        trace: dict = {}

        opa_input = self._build_opa_input(query, agent)

        for policy_name, rego_content in self._policies.items():
            try:
                raw_result = self._run_opa_eval(opa_input, rego_content, policy_name)
                trace[policy_name] = raw_result

                # Extract deny messages (hard violations)
                deny_messages = raw_result.get("deny", [])
                if isinstance(deny_messages, list):
                    for msg in deny_messages:
                        violations.append(
                            PolicyViolation(
                                agent_id=agent.id,
                                policy_file=f"{policy_name}.rego",
                                message=str(msg),
                            )
                        )

                # Extract soft hints
                for hint_data in raw_result.get("soft_hints", []):
                    if isinstance(hint_data, dict):
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
                # Fail closed — OPA errors are treated as violations
                violations.append(
                    PolicyViolation(
                        agent_id=agent.id,
                        policy_file=f"{policy_name}.rego",
                        message=f"Policy evaluation error: {e}",
                    )
                )

        return violations, hints, trace

    def _run_opa_eval(
        self,
        opa_input: dict,
        rego_content: str,
        policy_name: str,
    ) -> dict:
        """Run OPA eval via CLI and return structured result dict.

        Queries deny and soft_hints rules separately to reliably extract
        each rule's output regardless of OPA output format variations.
        """
        package_name = self._extract_package(rego_content)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".rego", delete=False
        ) as policy_file:
            policy_file.write(rego_content)
            policy_path = policy_file.name

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as input_file:
            json.dump(opa_input, input_file)  # OPA --input flag reads file AS input directly
            input_path = input_file.name

        try:
            result = {
                "deny": self._eval_rule(policy_path, input_path, package_name, "deny", policy_name),
                "soft_hints": self._eval_rule(policy_path, input_path, package_name, "soft_hints", policy_name),
            }
            return result
        finally:
            Path(policy_path).unlink(missing_ok=True)
            Path(input_path).unlink(missing_ok=True)

    def _eval_rule(
        self,
        policy_path: str,
        input_path: str,
        package_name: str,
        rule_name: str,
        policy_name: str,
    ) -> list:
        """Evaluate a single rule and return its value as a list.

        OPA --format raw returns the rule value directly:
        - A set/array → JSON array
        - undefined (rule not defined in this policy) → empty output
        - false/true → boolean
        """
        query = f"data.{package_name}.{rule_name}"

        result = subprocess.run(
            [
                "opa", "eval",
                "--data", policy_path,
                "--input", input_path,
                "--format", "raw",
                query,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Undefined rule is not an error — policy just doesn't define this rule
            if "undefined" in stderr.lower():
                return []
            raise RuntimeError(
                f"OPA eval failed for policy {policy_name!r} rule {rule_name!r}: {stderr}"
            )

        output = result.stdout.strip()

        # undefined = rule not defined in this policy file → no violations
        if not output or output == "undefined":
            return []

        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return []

        # OPA returns sets as JSON arrays
        if isinstance(parsed, list):
            return parsed
        # Single value wrapped — shouldn't happen for set rules but handle gracefully
        if isinstance(parsed, (str, dict)):
            return [parsed]
        return []

    @staticmethod
    def _extract_package(rego_content: str) -> str:
        """Extract package path from Rego content and convert to dot notation.

        E.g. 'package pager.hipaa' → 'pager.hipaa'
        """
        for line in rego_content.splitlines():
            line = line.strip()
            if line.startswith("package "):
                return line.split("package ", 1)[1].strip()
        return "pager"

    @staticmethod
    def _build_opa_input(query: AnalyzedQuery, agent: Agent) -> dict:
        """Build the OPA input document for a (query, agent) pair."""
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
        return len(self._policies)

    def policy_names(self) -> list[str]:
        return list(self._policies.keys())

    def __repr__(self) -> str:
        return f"PolicyEngine(policies={list(self._policies.keys())})"
