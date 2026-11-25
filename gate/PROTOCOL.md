# PAGER Paper 2: Gate Protocol (frozen before any run)

Status: FROZEN at the commit that adds this file (tag `gate-freeze-v1`).
Any later change goes in `gate/AMENDMENTS.md` with date, reason, and whether results already existed. Results are reported under both the original and the amended rule.
No harness code is written before this commit is on GitHub.

Author: Siva Kumar Chintham, 25 Nov 2026. Review amendments are incorporated (section 11.2).

---

## 1. Hypotheses

- **H1.** With realistic, off-the-shelf detectors, the best policy that uses source labels still pays a measurable price (missed violations, false denials, or over-restriction) where labels must be inferred, including after declassification inside a multi-hop plan.
- **H2a.** Under complete mediation with labelled sources, planner (decomposition) errors cost utility but do not cause policy violations. A violation caused by a decomposition error falsifies H2a.
- **H2b.** Planner errors can cause over-access (record reads the request did not need), which every label-based gate allows. How often this happens is an open empirical question.

## 2. Scenario set (`gate/scenarios/scenarios_v1.json`)

Built by `gate/scenarios/build_scenarios.py` from pinned inputs (SHA-256 recorded inside the output). 76 scenarios:

| Stratum | n | What it is | Where labels come from |
|---|---|---|---|
| A record-sourced | 12 | MedAgentBench originals, one per task (two each for Tasks 5 and 9). Single-action tasks get an appended summarise step. Tasks 5, 9 and 10 keep their native conditional plans. Purpose: treatment. | Declared (record access) |
| B held-out | 20 | The frozen Paper 1 paraphrases of Tasks 5 and 9, run in a session with an open patient record. 18 of 20 have no identifier in the text. Purpose: treatment. | Declared (session record) |
| C free text | 12 | Pasted text, no record access. 6 PHI (1 hard), 6 non-PHI (4 traps). | Inferred (only option) |
| D declassification | 12 | Read a record document, de-identify, then summarise (6) or translate (6). 6 hard, 6 standard. Purposes: research, operations, education. | Declared, then inferred after de-identification |
| E no patient context | 20 (26%) | General clinical questions; 6 add a translation step. 6 traps. | Inferred |

- Non-PHI scenarios (C negatives + E): 26 (34%); 16 without traps.
- Scenarios with any PHI flow: 50; 43 without hard items.
- Oracle-infeasible (a correct system must deny): C02, C05, C06.
- D01, D03, D05, D07, D09, D11 end in translation, so they are feasible only if de-identification succeeds (decided at run time, section 3.4).
- Plan lengths: 23 one-step, 35 two-step, 18 three-step; 31 conditional steps.
- **Trap** (`trap: true`, negatives only): items that target generic NER weaknesses (eponyms, author or provider names, policy dates, "a patient" with a lab value).
- **Hard** (`hard: true`, positives only): C04 and D01 to D06, whose identifiers are hard for NER (no name or number, lower-case name, nickname, relative, employer, ZIP, age over 89). D07 to D12 use only conventional identifiers in conventional formats, so stratum D is not stacked with hard cases.
- **Standard subset**: all scenarios minus traps and hard items. Section 8 says where it is used.
- Authorship: the author of strata C, D and E and of the gold plans had read the rule-based analyzer's patterns before writing them (the Paper 1 held-out paraphrases were written without consulting them).
- H2 set (37): A08 to A12, all of B, all of D.

## 3. Annotation rules (the oracle)

The oracle never calls a detector, the QueryAnalyzer, or OPA. It reads the labels the builder assigned from these rules.

**3.1 PHI.** Text is PHI if it carries health information about an individual together with any HIPAA Safe Harbor identifier of that individual or of their relatives, employers or household members (names, geographic units smaller than a state, all date elements except year that relate to the individual, ages over 89, phone, email, SSN, MRN and other record numbers, and the rest of the 18). Not PHI: general medical knowledge; a clinical value attached to "a patient" with no identifier; aggregate counts; author or provider names not linked to a patient; policy dates.

**3.2 Provenance (taint).** Any step that reads from or writes to a patient record carries PHI, as does any request issued in a session with an open patient record. Data derived from a PHI-labelled step stays PHI until it passes an explicit de-identification step, *even if no identifier remains in the text*. This is an organisational taint policy, deliberately stricter than the Safe Harbor minimum: a bare lab value returned from a record is still the patient's data. Consequence to state in the paper: per-hop re-detection and query-text propagation fail in strata A and B partly by this definition. The empirical evidence about detectors comes from strata C, D and E.

**3.3 Implicit flow.** A conditional step that runs because of a PHI value (Tasks 5, 9, 10) carries PHI. Its input also contains the patient reference, because an order cannot be placed without naming its subject.

**3.4 Declassification.** The output of `text.deidentify` is PHI if any listed identifier survives, else NONPHI. The survival check is frozen as code in `gate/oracle_residual.py` (whole-token match after normalisation, plus a digit-string match for identifiers with four or more digits). Surnames, nicknames and relatives' names are listed as separate identifiers in `spec_v1.json`, so a surviving "Mr. Stafford" is caught. Reformatted dates written in words (for example "Nov 10") are not caught; this is a known limitation of the oracle.

**3.5 What detectors see.** At hop 1, the request text only (`text`), not the MedAgentBench `context` field and not the session record. At hop k > 1, the step's `input_text`.

**3.6 Mock outputs.** EHR steps return MedAgentBench's bare-answer format (for example `1.9`), as listed in `spec_v1.json`. All conditional branches fire. The de-identification step is real (section 5.4); every other agent is a mock that returns its frozen output.

## 4. Agent pool and resolver (`gate/agents/gate_agents.yaml`)

- Every EHR capability has a HIPAA agent and a cheaper non-HIPAA clone.
- `text.translate` and `knowledge.answer` have only non-HIPAA agents, so a false PHI label there causes a real denial.
- `text.summarize` has both, so a false PHI label there causes over-restriction (served by the costlier agent).
- The gate tests P1 only: PHI must go to a HIPAA-compliant agent. P2 (role) and P3 (sensitivity) are out of scope for the gate.
- Resolver: cheapest agent allowed by the policy's labels, ties broken by id. Deny if none is allowed. There is no full-pool fallback.
- The gate harness enforces P1 in plain Python. OPA parity is implementation-phase work.

## 5. Detectors

Each detector returns a score s in [0, 1] that the input is PHI.

1. **Rule-based** (author-written): the Paper 1 `QueryAnalyzer._detect_pii`, unchanged; s is 1 if any pattern matches, else 0.
2. **Presidio** (not author-written): `presidio-analyzer` with default recognizers only, no custom recognizers, spaCy `en_core_web_lg`. Entities counted: PERSON, LOCATION, DATE_TIME, PHONE_NUMBER, EMAIL_ADDRESS, US_SSN, US_DRIVER_LICENSE, MEDICAL_LICENSE, IP_ADDRESS, URL. s is the maximum score over these entities (0 if none).
3. **LLM classifier** (not author-written): a mid-sized open-weight instruct model, 24B to 35B parameters (for example Qwen2.5-32B-Instruct, Gemma 3 27B or Mistral Small 24B), run locally at 4-bit quantisation or better, so that the best independent detector is not artificially weak and no PHI leaves the machine. Not from the model family used in writing strata C, D and E and the gold plans (stated in the paper's AI-use disclosure), so that the detector cannot benefit from recognising that family's phrasing. Prompt `gate/prompts/phi_classifier.txt`, temperature 0, JSON output, s = the returned `p_phi`. Exact model, quantisation and weights hash pinned on Day 2 (section 9).

Thresholds (frozen): label PHI if s >= 0.5 (tau). Fail-closed labels PHI if s >= 0.2 (tau_low). For the rule-based detector, s is binary, so fail-closed equals the plain policy. A sweep of tau is reported as description only; decisions use the frozen values.

**5.4 De-identification agent.** `presidio-anonymizer` with default operators (replace by `<ENTITY_TYPE>`), run on the output of the same analyzer configuration as in item 2. This creates a known correlation: Presidio checking Presidio's output. The correlation is part of what stratum D measures and is reported explicitly.

## 6. Policies

| Id | Root label | Later hops | After de-identification |
|---|---|---|---|
| PROP | detector on request text | root label propagated (no source labels) | detector on de-ID output |
| REDETECT | detector on request text | detector on each hop's input, independently | detector on de-ID output |
| SRC | declared where a source exists (record access, session record), else detector | join (PHI if any upstream is PHI) | detector on de-ID output |
| SRC-FC | as SRC, with tau_low for inferred labels | as SRC | detector on de-ID output, tau_low |
| ORACLE | true labels | true labels | residual check (3.4) |

SRC-FC is the policy Paper 2 would propose. Each non-oracle policy is run with each of the three detectors: 4 × 3 + 1 = 13 configurations over 76 scenarios.

## 7. Metrics

Primary unit: the scenario. Report counts, rates and Wilson 95% intervals, for the full set and the standard subset.

- **FA (false allow)**: scenarios in which at least one hop sent PHI (true label; section 3.4 at run time) to a non-HIPAA agent, divided by the 50 scenarios with any PHI flow (43 in the standard subset).
- **FD_neg (false denial on non-PHI)**: denied scenarios divided by the 26 non-PHI scenarios (16 without traps).
- **FD_all**: denied scenarios that the oracle marks feasible, divided by all feasible scenarios (resolved at run time for D).
- **OR (over-restriction)**: completed feasible scenarios in which at least one hop used a costlier agent than the oracle's, divided by completed feasible scenarios.
- **Violation hop** and **error location**: each FA, FD and OR event is assigned to the hop where it first occurs.
- **Downstream errors**: FA, FD and OR events at D's post-declassification hop (hop 3), over the 12 D scenarios.
- **Source-label gap** (descriptive only): FA(PROP) minus FA(SRC-FC), each with its best non-author detector, overall and per stratum. On A and B the gap follows from rule 3.2; on C and E, SRC and PROP differ only through tau_low because no declared source exists; D is the only stratum where the gap is not definitional. Reported, never used as a decision condition.
- **Inferred-label dependence** (descriptive only): share of hop decisions whose label came from a detector and whose outcome would change if the label were flipped, per stratum. It measures the scenario mix as much as the method.
- **Correct denials**: C02, C05, C06 are reported separately and never count as false denials.
- **H2 metrics**: section 8.

## 8. Decision rules

D* = the better of the two non-author detectors (Presidio, LLM) for SRC-FC, chosen by lowest FA count, then lowest FD_neg, then lowest OR. The rule-based detector is reported but cannot be D*.

**H1: evaluate in this order; the first rule that matches decides.**

1. **FAIL** (inference is easy enough that there is nothing to bound): SRC-FC with D* has FA = 0 of 50, FD_neg <= 5% (at most 1 of 26, and 0 of 16 without traps), and OR <= 5%.
2. **NARROW** (entry-labelling paper; the multi-hop claim is judged on stratum D alone, because C and E place inference at hop 1 by design): at D's post-declassification hop, SRC-FC with D* has FA = 0 of 12 and FD + OR at most 1 of 12.
3. **PASS**: SRC-FC with D* pays a price on at least one axis, with the count meeting its threshold in both the full set and the standard subset:
   - FA >= 2 of 50 and >= 2 of 43; or
   - FD_neg >= 3 of 26 and >= 2 of 16; or
   - OR >= 10% in both views.
4. **GRAY**: anything else. Default outcome is NARROW, unless the review-day memo gives a written reason to proceed, recorded in AMENDMENTS.md before the decision.

**H2: planner test on the 37 H2 scenarios.** Each planner plan is executed under SRC with oracle labels at every inferred point, so that only decomposition varies.

- Error taxonomy: align the planner's capability sequence with the gold plan by Damerau-Levenshtein distance (unit costs). Substitution = wrong capability; deletion = missing step; insertion = extra step; adjacent transposition = wrong order; a conditional flag mismatch on an aligned step = condition error.
- Consequence of each erroneous plan: violation (oracle FA), denial, or utility only (completed, but the result differs from the gold plan).
- **Over-access**: a plan contains a record-read step (`ehr.patient_lookup`, `ehr.read_observation`, `ehr.read_document`) that the alignment marks as inserted or substituted. Extra record writes (`ehr.write_observation`, `ehr.order_*`) are reported separately as unrequested actions. Over-access passes every label-based gate by design, so it is not true or false by construction. It is measured at capability granularity, so it is a lower bound (an over-broad read inside one capability, such as all labs instead of magnesium, is not visible); planner instruction texts are kept for qualitative review. Reported by purpose: HIPAA's minimum-necessary standard does not apply to requests by a provider for treatment (45 CFR 164.502(b)(2)(i)), so for A and B over-access is a least-privilege measure, and for D (research, operations, education) it is a minimum-necessary concern.
- **H2a PASS**: at least 5 erroneous plans, zero violations, and at least 80% utility only. **H2a FAIL**: any violation that traces to a decomposition error under complete mediation; report it as a mediation gap and analyse it before any other step. **H2a INCONCLUSIVE**: fewer than 5 erroneous plans; then apply the frozen perturbation set (for each of the 37 H2 scenarios, one perturbation of each type: drop a step, duplicate a step, swap two adjacent steps, replace a capability with another from the closed set, flip a conditional flag; random choices with seed 20261126) and judge with the PASS and FAIL rules.
- **H2b outcome** (real planner plans only; perturbations never count): over-access in 4 or more of 37 plans (about 10% or more) makes plan-level read minimisation a stated requirement and an evaluated component of the March design; 1 to 3 plans make it a reported limitation with examples; 0 is reported as such.
- Stated before running: under complete mediation H2a is expected to hold by construction. The paper presents it as a proposition with its assumption; the experiment supplies the utility cost, checks for mediation gaps, and measures H2b.

## 9. Day 2 pinning (allowed before any run, no rule changes)

A separate commit before the first run may only fill in: Presidio and spaCy versions; the LLM classifier's model id, quantisation and weights hash; the planner's model id and version date; the runtime; and the prompt files if they changed only in formatting. Prompts may be smoke-tested on up to 5 dev sentences that are not in the scenario set; never on scenarios. Prompt templates contain literal JSON braces, so the harness substitutes `{text}` and `{session_state}` by string replacement, not `str.format`.

Constraints: the LLM classifier follows section 5 item 3. The planner follows the same exclusion; a model from the excluded family may be run only as a secondary planner and reported as such. If the local machine cannot run a 24B to 35B model, record this in AMENDMENTS.md before any run, name the model used instead, and state in the memo that the independent detector may be understated.

Local setup (evening of Day 1): `pip install presidio-analyzer presidio-anonymizer`, then `python -m spacy download en_core_web_lg`, then a local runtime for the classifier (for example Ollama or llama.cpp) with the chosen model pulled. A 30B-class model at 4-bit needs roughly 20 GB of GPU memory, or 32 GB or more of unified memory on Apple silicon.

## 10. Known limitations (to state in the memo)

- Scenarios are constructed, not sampled from a workload, so prevalence of inferred-label decisions cannot be estimated from this gate.
- Single annotator (rules applied mechanically by the builder); no inter-annotator agreement at the gate stage.
- Mock outputs decide what per-hop re-detection sees; the bare-answer format follows MedAgentBench and is frozen.
- Small n: 1 scenario is 2.0 points of FA, 3.8 points of FD_neg, and 8.3 points of the D downstream rate. Thresholds are stated as counts for this reason.
- Over-access is measured at capability granularity only (lower bound).

## 11. Changes from the 25 Nov handoff, with reasons

### 11.1 Changes in the first draft

1. Added strata C (free text) and D (declassification). Without them, source labelling makes every record-sourced decision trivially correct and the gate would return NARROW regardless of the method.
2. Split the proposed policy into SRC and SRC-FC, so the effect of source labels and the effect of fail-closed are separable.
3. Replaced "every policy pays 10% with at least one non-author detector": the worst detector could make any policy pass, and the true-label policy can never pay.
4. Dropped "or the trade-off changes with plan structure" as a pass route: as written it could not fail. Plan-structure effects are reported descriptively.
5. Replaced "inferred-label fraction is tiny" as a narrowing rule, because the fraction measures the scenario mix.
6. Added over-restriction as a third axis: when a HIPAA agent exists, fail-closed pays in cost, not in denials.
7. Added a GRAY outcome with a conservative default.
8. H2: "violating ones trace to the fallback" no longer applies (no fallback in Paper 2); a decomposition-caused violation now falsifies H2a, which is declared a proposition under complete mediation.

### 11.2 Review amendments (25 Nov), as applied

- **(A)** Stratum D enlarged from 6 to 12, and NARROW is now judged on D's post-declassification hop alone. The six new items use conventional identifiers only, so the added half of D is not stacked with hard cases.
- **(B)** The PROP versus SRC-FC 10-point condition is removed from PASS and reported descriptively (section 7, source-label gap). Restricting it to C, D and E was not used: on C and E, SRC and PROP are identical except for tau_low, so the comparison would measure the fail-closed threshold, not source labels.
- **(C)** All traps are negatives, so "FA without traps" would equal FA. The intent (the price must not rest on engineered items) is applied through a `hard` flag on positives (C04, D01 to D06): the FA route to PASS must hold on the 43-scenario standard subset as well as the full set.
- **(D)** Over-access added as H2b with a pre-registered consequence. Minimum-necessary framing is limited to D's non-treatment purposes, because the standard does not apply to treatment requests by providers; for A and B it is reported as least privilege.
- LLM classifier: a mid-sized local open-weight model (section 5 item 3).
