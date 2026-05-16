# PAGER: Policy-Aware aGent RoutER

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**PAGER** is a research framework for policy-aware routing and conflict resolution in enterprise multi-agent systems.

---

## Research Contributions

**Gap 1 — Enterprise Governance Integration**: Existing routing systems ignore compliance policies. PAGER integrates HIPAA/GDPR policies as first-class routing constraints using Open Policy Agent (OPA/Rego).

**Gap 2 — Intelligent Conflict Resolution**: When multiple agents satisfy policy constraints, existing systems use ad-hoc selection. PAGER applies configurable strategies (cost-aware, latency-aware, quality-aware, weighted, round-robin) to select the optimal agent.

---

## Architecture

```
Query → QueryAnalyzer → PolicyEngine → ConflictResolver → ExecutionCoordinator → Response
                            ↑                ↑
                       AgentRegistry    AgentRegistry
                                ↓
                         FeedbackCollector
```

| Component | Responsibility |
|-----------|---------------|
| **QueryAnalyzer** | Rule-based intent extraction, entity recognition, PII detection |
| **PolicyEngine** | OPA/Rego policy evaluation — filters non-compliant agents |
| **AgentRegistry** | Static YAML agent configurations with FHIR capabilities |
| **ConflictResolver** | 5 configurable strategies for optimal agent selection |
| **ExecutionCoordinator** | Agent invocation, timeout, retry, latency measurement |
| **FeedbackCollector** | Audit trails and routing outcome logging |

---

## Scope

**PAGER does:**
- Route a query to exactly one policy-compliant optimal agent
- Enforce HIPAA and GDPR policies as hard routing constraints
- Resolve conflicts when multiple agents are compliant

**PAGER does not:**
- Decompose queries across multiple agents (orchestration)
- Support dynamic agent registration at runtime
- Handle multi-turn conversations
- Adapt routing based on learned feedback (Phase 2, conditional)

---

## Quick Start

### Prerequisites

- Python 3.11+
- OPA (Open Policy Agent) binary

**Install OPA** (required for policy evaluation):
```bash
# macOS
brew install opa

# Linux
curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static
chmod +x opa && sudo mv opa /usr/local/bin/

# Verify
opa version
```

### Installation

```bash
# Clone the repository
git clone https://github.com/sivakumar-arch/PAGER.git
cd PAGER

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Verify setup
pytest --co -q  # list tests without running
```

### Environment Variables

```bash
# Copy template and fill in your keys (only needed for Phase 4 evaluation)
cp .env.example .env
```

`.env` format:
```
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

### Run Tests

```bash
# All tests with coverage
pytest

# Unit tests only (fast, no external dependencies)
pytest -m unit

# Specific component
pytest tests/test_conflict_resolver.py -v
```

### Run Linting

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Fix auto-fixable issues
ruff check --fix src/ tests/
```

---

## Project Structure

```
PAGER/
├── configs/
│   ├── agents/
│   │   ├── healthcare_agents.yaml   # 5 HIPAA-compliant agents (FHIR capabilities)
│   │   └── gdpr_agents.yaml         # 3 GDPR agents (data residency, consent)
│   └── pager_config.yaml            # Global PAGER configuration
│
├── policies/
│   ├── hipaa/
│   │   ├── pii_access.rego          # Hard: PII requires HIPAA-compliant agent
│   │   ├── authorization.rego       # Hard: Role-based access control
│   │   ├── sensitivity.rego         # Hard: Data sensitivity level enforcement
│   │   ├── cost_optimization.rego   # Soft: Cost threshold preference
│   │   └── sla_requirements.rego    # Soft: Latency SLA preference
│   └── gdpr/
│       ├── data_residency.rego      # Hard: EU data must stay in EU
│       └── consent.rego             # Hard: Marketing requires consent
│
├── src/
│   ├── pager/
│   │   ├── core.py                  # PAGER main class — orchestrates all components
│   │   ├── query_analyzer.py        # Component 1: intent, entities, PII, sensitivity
│   │   ├── policy_engine.py         # Component 2: OPA integration
│   │   ├── agent_registry.py        # Component 3: YAML-based agent registry
│   │   ├── conflict_resolver.py     # Component 4: 5 resolution strategies
│   │   ├── execution_coordinator.py # Component 5: invocation, timeout, retry
│   │   └── feedback_collector.py    # Component 6: JSON audit logging
│   ├── models/
│   │   ├── agent.py                 # Agent dataclass
│   │   ├── query.py                 # AnalyzedQuery dataclass
│   │   ├── policy_result.py         # PolicyEvaluationResult dataclass
│   │   ├── resolution.py            # ResolutionResult dataclass
│   │   └── execution.py             # ExecutionResult dataclass
│   └── utils/
│       ├── logger.py                # Structured logging
│       └── config_loader.py         # YAML config loading
│
├── tests/
│   ├── test_query_analyzer.py
│   ├── test_policy_engine.py
│   ├── test_agent_registry.py
│   ├── test_conflict_resolver.py
│   ├── test_execution_coordinator.py
│   ├── test_feedback_collector.py
│   └── test_integration.py
│
├── experiments/
│   ├── scenarios/
│   │   ├── healthcare_scenario.py   # 75-question MedAgentBench evaluation
│   │   └── gdpr_scenario.py         # 2 hand-crafted GDPR scenarios
│   ├── baselines/
│   │   ├── random_router.py
│   │   ├── round_robin_router.py
│   │   ├── rule_based_router.py
│   │   └── embedding_router.py      # sentence-transformers cosine similarity
│   ├── metrics/
│   │   ├── policy_compliance.py
│   │   ├── routing_accuracy.py
│   │   └── performance.py
│   └── run_evaluation.py            # Entry point: runs all 3 experiments
│
├── data/
│   ├── medagentbench/
│   │   ├── test_data_v2.json        # 300 MedAgentBench questions
│   │   └── funcs_v1.json            # FHIR API definitions
│   ├── feedback/                    # Runtime routing logs (gitignored)
│   └── results/                     # Experiment outputs (gitignored)
│
├── docs/
│   ├── decisions.md                 # Architecture decisions and rationale
│   ├── architecture.md              # Detailed component documentation
│   └── evaluation_plan.md           # Experiment design and metrics
│
├── notebooks/
│   ├── exploratory_analysis.ipynb
│   └── results_visualization.ipynb
│
├── LICENSE
├── README.md
├── requirements.txt
├── pyproject.toml
└── .gitignore
```

---

## Evaluation

PAGER is evaluated on **MedAgentBench** (75 questions sampled from 300, balanced across 10 task types):

| Experiment | Description |
|-----------|-------------|
| **Exp 1** | PAGER vs 4 baselines (random, round-robin, rule-based, embedding) |
| **Exp 2** | Ablation: PAGER-NoPolicy vs PAGER-NoConflict vs PAGER-Full |
| **Exp 3** | Strategy comparison across 5 conflict resolution strategies + weight sensitivity |

**Success criteria:**
- Policy Compliance Rate: 100%
- Authorization Violation Rate: 0%
- Routing Accuracy: ≥ 90%
- Conflict Resolution Effectiveness: ≥ 95%

```bash
# Run full evaluation (Phase 4)
python experiments/run_evaluation.py
```

---

## Citation

```bibtex
@article{chintham2026pager,
  title={PAGER: Policy-Aware Routing and Conflict Resolution for Enterprise Multi-Agent Systems},
  author={Chintham, Siva Kumar},
  year={2026}
}
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.
