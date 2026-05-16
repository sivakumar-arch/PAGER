# MedAgentBench Dataset

Dataset files are **not tracked in git**. Download and place them in this directory before running experiments.

## Required Files

| File | Description |
|------|-------------|
| `test_data_v2.json` | 300 MedAgentBench evaluation questions across 10 FHIR task types |
| `funcs_v1.json` | FHIR API function definitions used by MedAgentBench agents |

## Source

**MedAgentBench**: [https://github.com/gersteinlab/MedAgentBench](https://github.com/gersteinlab/MedAgentBench)

Gersteinlab, Yale University.

## PAGER Evaluation Sample

PAGER uses a stratified sample of **75 questions** from the 300 available, balanced across all 10 task types (7-8 questions per task type).

| Task | Description | FHIR Operation | Agent |
|------|-------------|---------------|-------|
| 1 | Patient MRN lookup | GET /Patient | patient_demographics_agent |
| 2 | Patient demographics | GET /Patient | patient_demographics_agent |
| 3 | Vital signs recording | POST /Observation | vitals_agent |
| 4 | Lab results retrieval | GET /Observation | labs_agent |
| 5 | Medication ordering | POST /MedicationRequest | medication_agent |
| 6 | Lab value retrieval | GET /Observation | labs_agent |
| 7 | Lab trend analysis | GET /Observation | labs_agent |
| 8 | Procedure ordering | POST /ServiceRequest | procedure_agent |
| 9 | Medication management | GET /MedicationRequest | medication_agent |
| 10 | Lab result calculation | GET /Observation | labs_agent |

## Verify Setup

```bash
ls data/medagentbench/
# Expected output:
# README.md  funcs_v1.json  test_data_v2.json
```
