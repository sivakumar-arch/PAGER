"""QueryAnalyzer: Rule-based intent extraction and PII detection.

Parses raw natural language queries into structured AnalyzedQuery objects.
Uses deterministic pattern matching appropriate for MedAgentBench's
structured EHR queries.

Design rationale (Section 4.2):
    Rule-based analysis ensures deterministic intent extraction during
    evaluation, enabling clean attribution of routing decisions to
    PolicyEngine and ConflictResolver rather than query understanding
    variability. The modular architecture supports LLM-based analysis
    for production deployments with more diverse query patterns.
"""

import re
from dataclasses import dataclass, field

from src.models.query import AnalyzedQuery
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class _CapabilityPattern:
    """Maps keyword patterns to FHIR capabilities and sensitivity."""

    keywords: tuple[str, ...]
    capabilities: tuple[str, ...]
    sensitivity: str  # "low" | "medium" | "high"
    intent: str  # "lookup" | "retrieval" | "ordering" | "calculation"


# ---------------------------------------------------------------------------
# MedAgentBench task-to-FHIR capability mapping
# Covers all 10 task types per Section 6 of the handoff
# ---------------------------------------------------------------------------
_CAPABILITY_PATTERNS: list[_CapabilityPattern] = [
    # Task 1 & 2: Patient Demographics (GET /Patient)
    # Note: "mrn" removed — it appears in ALL task queries as patient identifier,
    # not as a signal for demographics intent. Use specific demographics terms only.
    _CapabilityPattern(
        keywords=("medical record number", "date of birth", "dob", "patient name",
                  "demographics", "patient id", "address", "phone", "contact",
                  "what is the mrn", "what's the mrn", "find the mrn",
                  "age of the patient", "patient age", "date of birth",
                  "who is patient"),
        capabilities=("GET /Patient", "patient_lookup", "demographics_retrieval"),
        sensitivity="medium",
        intent="lookup",
    ),
    # Task 3: Vital Signs (POST /Observation)
    # Sensitivity = medium: recording vitals is routine clinical data,
    # not restricted-level (level 3). Nurses record vitals routinely.
    _CapabilityPattern(
        keywords=("vital signs", "blood pressure", "heart rate", "temperature",
                  "respiratory rate", "oxygen saturation", "pulse rate",
                  "record vital", "patient weight", "patient height"),
        capabilities=("POST /Observation", "vital_signs", "blood_pressure"),
        sensitivity="medium",
        intent="ordering",
    ),
    # Task 5 & 9: Conditional lab-check + medication ordering
    # MUST be before labs pattern — "if low, order replacement" primary intent is ordering
    # Labs keywords (magnesium, potassium) appear in same query but ordering is the action
    _CapabilityPattern(
        keywords=("if low", "if high", "if abnormal", "order replacement",
                  "order potassium", "order magnesium", "replete",
                  "replacement potassium", "replacement magnesium",
                  "replacement electrolyte"),
        capabilities=("POST /MedicationRequest", "GET /MedicationRequest",
                      "medication_ordering", "prescription_management"),
        sensitivity="high",
        intent="ordering",
    ),
    # Task 4, 6, 7, 10: Lab Results (GET /Observation)
    _CapabilityPattern(
        keywords=("lab result", "lab value", "magnesium", "glucose", "hba1c",
                  "hemoglobin", "creatinine", "sodium", "potassium", "cholesterol",
                  "triglyceride", "albumin", "bilirubin", "platelet",
                  "white blood cell", "red blood cell",
                  "test result", "most recent", "cbg", "capillary blood glucose",
                  "average cbg", "serum", "level"),
        capabilities=("GET /Observation", "lab_results", "diagnostic_data"),
        sensitivity="high",
        intent="retrieval",
    ),
    # Task 5 & 9: Direct medication queries (no conditional)
    _CapabilityPattern(
        keywords=("medication", "drug", "prescription", "dose", "dosage",
                  "medicine", "pharmaceutical", "pill", "tablet", "injection",
                  "antibiotic", "statin", "insulin", "metformin"),
        capabilities=("POST /MedicationRequest", "GET /MedicationRequest",
                      "medication_ordering", "prescription_management"),
        sensitivity="high",
        intent="ordering",
    ),
    # Task 8: Procedures & Referrals (POST /ServiceRequest)
    _CapabilityPattern(
        keywords=("referral", "procedure", "surgery", "operation", "specialist",
                  "appointment", "consult", "consultation", "orthopedic",
                  "cardiology", "radiology", "imaging", "mri", "ct scan",
                  "x-ray", "ultrasound", "biopsy"),
        capabilities=("POST /ServiceRequest", "procedure_ordering",
                      "referral_management", "surgery_scheduling"),
        sensitivity="high",
        intent="ordering",
    ),
]

# PII indicators — triggers HIPAA hard constraints in PolicyEngine
_PII_PATTERNS: tuple[str, ...] = (
    r"\b[A-Z][a-z]+ [A-Z][a-z]+\b",   # Patient name pattern (e.g. "Peter Stafford")
    r"\bS\d{7}\b",                      # MRN pattern (e.g. "S3032536")
    r"\b\d{4}-\d{2}-\d{2}\b",          # Date of birth (ISO format)
    r"\bDOB\b",                         # Explicit DOB reference
    r"\bMRN\b",                         # Explicit MRN reference
    r"\bpatient\s+[A-Z][a-z]+\b",      # "patient [Name]"
)

# Role-to-sensitivity mapping for default context inference
_ROLE_DEFAULT_SENSITIVITY: dict[str, str] = {
    "admin": "medium",
    "receptionist": "medium",
    "nurse": "high",
    "doctor": "high",
    "lab_tech": "high",
    "pharmacist": "high",
    "data_processor": "medium",
    "data_controller": "medium",
    "marketing_manager": "low",
}


class QueryAnalyzer:
    """Rule-based query analyzer for structured EHR queries.

    Deterministically maps MedAgentBench queries to FHIR capabilities,
    PII flags, and sensitivity levels. All outputs are reproducible —
    identical input always produces identical AnalyzedQuery.

    Production extension:
        Replace _classify_intent_and_capabilities() with an LLM-based
        classifier for handling diverse query phrasings. The AnalyzedQuery
        interface is unchanged — only this component is swapped.
    """

    def __init__(self) -> None:
        self._pii_patterns = [re.compile(p) for p in _PII_PATTERNS]
        logger.info("QueryAnalyzer initialized", mode="rule-based")

    def analyze(
        self,
        raw_query: str,
        user_role: str,
        user_region: str | None = None,
        requires_consent: bool = False,
        task_type: int | None = None,
    ) -> AnalyzedQuery:
        """Parse a raw query string into a structured AnalyzedQuery.

        Args:
            raw_query: The raw natural language query string.
            user_role: Role of the requesting user (e.g. 'nurse', 'doctor').
            user_region: User's data region for GDPR checks (e.g. 'EU').
            requires_consent: True for marketing queries requiring GDPR consent.
            task_type: MedAgentBench task number (1-10), if known.

        Returns:
            AnalyzedQuery with classified intent, capabilities, and PII flags.
        """
        query_lower = raw_query.lower()

        contains_pii = self._detect_pii(raw_query)
        matched = self._classify(query_lower)
        capabilities = list(matched.capabilities) if matched else []
        intent = matched.intent if matched else "retrieval"
        sensitivity = self._resolve_sensitivity(
            matched, contains_pii, user_role
        )
        entities = self._extract_entities(raw_query, query_lower)

        analyzed = AnalyzedQuery(
            raw_query=raw_query,
            intent=intent,
            entities=entities,
            contains_pii=contains_pii,
            data_sensitivity=sensitivity,
            required_capabilities=capabilities,
            user_role=user_role,
            user_region=user_region,
            requires_consent=requires_consent,
            task_type=task_type,
        )

        logger.debug(
            "Query analyzed",
            intent=intent,
            pii=contains_pii,
            sensitivity=sensitivity,
            capabilities=capabilities,
        )
        return analyzed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_pii(self, raw_query: str) -> bool:
        """Return True if any PII pattern matches in the raw query."""
        return any(p.search(raw_query) for p in self._pii_patterns)

    def _classify(self, query_lower: str) -> _CapabilityPattern | None:
        """Return the first matching capability pattern, or None."""
        for pattern in _CAPABILITY_PATTERNS:
            if any(kw in query_lower for kw in pattern.keywords):
                return pattern
        return None

    def _resolve_sensitivity(
        self,
        matched: _CapabilityPattern | None,
        contains_pii: bool,
        user_role: str,
    ) -> str:
        """Determine data sensitivity level.

        PII always elevates to at least 'medium'.
        Capability pattern takes precedence over role default.
        """
        if matched:
            base = matched.sensitivity
        else:
            base = _ROLE_DEFAULT_SENSITIVITY.get(user_role, "medium")

        # PII elevates sensitivity
        if contains_pii and base == "low":
            return "medium"
        return base

    def _extract_entities(
        self, raw_query: str, query_lower: str
    ) -> dict[str, str]:
        """Extract key entities from query text.

        Extracts patient identifiers and clinical terms.
        Returns a flat dict of entity_type → value.
        """
        entities: dict[str, str] = {}

        # MRN (e.g. S3032536)
        mrn_match = re.search(r"\bS\d{7}\b", raw_query)
        if mrn_match:
            entities["mrn"] = mrn_match.group()

        # Date of birth (ISO format)
        dob_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", raw_query)
        if dob_match:
            entities["dob"] = dob_match.group()

        # Patient name (two capitalized words)
        name_match = re.search(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b", raw_query)
        if name_match:
            entities["patient_name"] = name_match.group()

        # Lab test type
        lab_terms = (
            "magnesium", "glucose", "hba1c", "hemoglobin", "creatinine",
            "sodium", "potassium", "cholesterol",
        )
        for term in lab_terms:
            if term in query_lower:
                entities["lab_test"] = term
                break

        # Procedure type
        proc_terms = (
            "orthopedic", "cardiology", "radiology", "mri", "ct scan",
            "x-ray", "ultrasound", "biopsy", "surgery", "referral",
        )
        for term in proc_terms:
            if term in query_lower:
                entities["procedure_type"] = term
                break

        return entities
