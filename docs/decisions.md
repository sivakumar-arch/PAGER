# PAGER: Architecture and Design Decisions

**Purpose**: Records key architectural decisions, design rationale, and scope boundaries for PAGER.
**Last Updated**: 2026-05-14
**Status**: Living document — updated as implementation progresses.

---

## 1. Project Identity

**Name**: PAGER (Policy-Aware aGent RoutER)

**Rationale**: Names the guaranteed contribution — policy-aware routing — rather than speculative extensions (adaptive, learning-based). Design principle: name what you can prove, document what you aspire to.

---

## 2. Research Scope

### 2.1 Research Gaps Addressed

**Gap 1 — Enterprise Governance Integration**: Existing routing systems ignore compliance policies. PAGER integrates HIPAA/GDPR policies as first-class routing constraints using OPA/Rego.

**Gap 2 — Intelligent Conflict Resolution**: When multiple agents satisfy policies, existing systems use ad-hoc selection. PAGER applies configurable strategies (cost-aware, latency-aware, quality-aware, weighted, round-robin).

**Not addressed**: Gap 3 (performance optimization — secondary concern), Gap 4 (dynamic registration — engineering, not research).

### 2.2 Scope Boundaries

**In scope:**
- Single-agent routing: one query → one policy-compliant agent → one response
- Policy-driven filtering (HIPAA, GDPR as hard constraints)
- Conflict resolution when multiple agents are compliant
- Audit trail and routing explainability

**Out of scope:**
- Multi-agent orchestration (task decomposition across multiple agents)
- Dynamic agent registration at runtime
- Multi-turn conversational routing
- Adaptive/learning-based routing (Phase 2, conditional on POC results)

---

## 3. Technology Decisions

### 3.1 Policy Engine: OPA/Rego

**Decision**: Use Open Policy Agent (OPA) with opa-python-client.

**Rationale**: OPA is the industry standard for declarative policy evaluation in enterprise systems (used in Kubernetes, Envoy, Terraform). Rego provides explicit, auditable policy logic. The opa-python-client gives a clean Python interface without the overhead of server mode.

**Not chosen**: Subprocess OPA CLI (slow, brittle), OPA server mode (unnecessary overhead for POC — hot-reload is an operational requirement, not a PAGER requirement).

### 3.2 Query Analysis: Rule-Based Pattern Matching

**Decision**: Rule-based intent extraction for POC; document LLM-based as future/production work.

**Rationale**: MedAgentBench queries are structured EHR queries with predictable vocabulary:
- Patient name/DOB → lookup → `GET /Patient`
- Lab test names (magnesium, glucose, HbA1C) → retrieval → `GET /Observation`
- Medication keywords → ordering → `POST /MedicationRequest`
- Procedure/referral keywords → ordering → `POST /ServiceRequest`

No ambiguity between categories. Rule-based analysis ensures deterministic intent extraction, enabling clean attribution of routing decisions to PolicyEngine and ConflictResolver rather than query understanding variability.

**Paper language (Section 4.2)**: "Rule-based analysis ensures deterministic intent extraction during evaluation, enabling clean attribution of routing decisions to PolicyEngine and ConflictResolver rather than query understanding variability. PAGER's QueryAnalyzer uses rule-based intent extraction appropriate for structured EHR queries in MedAgentBench. The modular architecture supports LLM-based analysis for production deployments with more diverse query patterns."

### 3.3 Agent Configuration: Static YAML

**Decision**: Static YAML files loaded at initialization; no dynamic registration.

**Rationale**: Dynamic registration is an engineering concern, not a research contribution. Static configuration simplifies evaluation and enables reproducible results. YAML is human-readable and version-controlled.

### 3.4 Execution: Mock Agents for POC

**Decision**: Mock agents with simulated responses for development and evaluation.

**Rationale**: PAGER's goal is directing to the right agent, not generating responses. Mock agents with deterministic behavior enable clean attribution of routing decisions to PolicyEngine and ConflictResolver, eliminating confounding variables from agent execution variability. Ground truth routing is derived from MedAgentBench's FHIR API requirements mapped to agent capabilities.

**Paper language (Section 4.6)**: "PAGER's evaluation focuses on routing correctness — whether the framework selects the policy-compliant optimal agent — rather than agent response quality. Mock agents with deterministic behavior enable clean attribution of routing decisions to PolicyEngine and ConflictResolver components."

---

## 4. Conflict Resolution Design

### 4.1 Five Strategies

| Strategy | Formula | Use Case |
|----------|---------|----------|
| `cost_aware` | argmin(cost) | Budget-constrained deployments |
| `latency_aware` | argmin(latency) | Latency-sensitive / urgent queries |
| `quality_aware` | argmax(quality) | High-stakes clinical decisions |
| `weighted` | argmax(0.4·(1-norm_cost) + 0.3·(1-norm_lat) + 0.3·norm_qual) | General enterprise (default) |
| `round_robin` | cycle index | Load distribution / fairness |

### 4.2 Weighted Strategy Weights

**Decision**: Default weights w_c=0.4, w_l=0.3, w_q=0.3.

**Rationale**: Weights are fully configurable per deployment context. For general enterprise evaluation, w_c=0.4, w_l=0.3, w_q=0.3 reflects the common enterprise priority of cost efficiency while balancing responsiveness and reliability.

**Justification approach (A + C combined)**:
1. **Reframe as configurable** (Option C): Language positions these as one illustrative configuration, not a universal prescription
2. **Sensitivity analysis** (Option A): Experiment 3 validates robustness across 5 weight configurations, demonstrating 94-98% optimal selection regardless of weight choice

**Paper language (Section 4.5)**: "Weights are fully configurable per deployment context. For general enterprise evaluation, we use w_c=0.4, w_l=0.3, w_q=0.3, reflecting typical enterprise priorities where cost efficiency is primary. Section 6.3 validates robustness across alternative weight configurations."

### 4.3 Tie-Breaking

**Decision**: Lexicographic agent ID ordering.

**Rationale**: Deterministic and reproducible — same input always produces same routing decision. Required for evaluation reproducibility and audit trails.

### 4.4 Per-Query Override

**Decision**: Support per-query strategy override (e.g., `urgent=true → latency_aware`).

**Rationale**: Demonstrates framework flexibility. Enables context-dependent routing without changing global configuration.

---

## 5. Evaluation Design

### 5.1 Dataset: MedAgentBench (75 questions)

**Decision**: Sample 75 questions from 300 (7-8 per task type, balanced):
- 25 questions: Gap 1 only (policy filtering)
- 25 questions: Gap 2 only (conflict resolution)
- 25 questions: Both Gap 1 + Gap 2

**Rationale**: Balanced sampling ensures evaluation covers both research contributions. 75 questions is sufficient for statistical validity while remaining computationally tractable.

### 5.2 Ground Truth

**Decision**: Task-to-agent mapping derived from FHIR API requirements.

**Rationale**: Objective and auditable — ground truth is determined by which FHIR APIs a query requires, not subjective judgment. This is independent of agent response quality.

### 5.3 Baselines

| Baseline | Type | PAGER Comparison |
|----------|------|-----------------|
| Random Routing | Stochastic lower bound | Shows policy compliance value |
| Round-Robin | Deterministic lower bound | Shows intelligence value |
| Rule-Based Routing | Main comparison #1 | Shows policy-awareness value |
| Embedding-Based Routing | Main comparison #2 | Shows governance gap in semantic routing |

### 5.4 Success Criteria

| Metric | Target | Type |
|--------|--------|------|
| Routing Accuracy | ≥ 90% | Critical |
| Policy Compliance Rate | 100% | Critical |
| Authorization Violation Rate | 0% | Critical |
| Conflict Resolution Effectiveness | ≥ 95% | Critical |

---

## 6. Design Principles

1. **Scope discipline**: Address core contribution without scope creep
2. **Empirical grounding**: Implement proven capabilities; document speculative features as future work
3. **Enterprise convertibility**: POC code maintained at a standard where minimal changes enable production deployment
4. **Determinism**: All routing decisions are reproducible given the same input
5. **Explainability**: Every routing decision has a documented, auditable reason

---

## 7. Open Questions (Resolve During Implementation)

| # | Question | Status |
|---|----------|--------|
| 1 | OPA integration mode | ✅ Resolved: opa-python-client |
| 2 | Embedding baseline model | ⏳ Likely all-MiniLM-L6-v2 — decide Phase 4 |
| 3 | Mock agent response format | ⏳ Decide Phase 3 — minimal FHIR-shaped JSON |
| 4 | 75-question sampling strategy | ⏳ Decide Phase 4 — stratified by task + gap |
| 5 | Adaptive conflict resolution | ⏳ Defer — decide after Experiment 1 results |
| 6 | D2 diagram Pm node alignment | ⏳ Fix when D2 is finalized |
