"""AnalyzedQuery data model.

Represents the structured output of QueryAnalyzer — the result of parsing
a raw natural language query into intent, entities, and routing metadata.
"""

from typing import Literal

from pydantic import BaseModel, Field


class AnalyzedQuery(BaseModel):
    """Structured representation of a parsed query.

    Produced by QueryAnalyzer from a raw query string + user context.
    Consumed by PolicyEngine and ConflictResolver.
    """

    model_config = {"frozen": True}

    # --- Raw input (preserved for audit trail) ---
    raw_query: str = Field(description="Original unmodified query string")

    # --- Intent classification ---
    intent: Literal["lookup", "retrieval", "ordering", "calculation"] = Field(
        description=(
            "Classified query intent: "
            "lookup (find record), "
            "retrieval (get value/list), "
            "ordering (create order/request), "
            "calculation (compute aggregate)"
        )
    )

    # --- Extracted entities ---
    entities: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Key-value pairs of extracted entities. "
            "Examples: {'patient_name': 'Peter Stafford', 'mrn': 'S3032536', "
            "'dob': '1932-12-29', 'lab_test': 'magnesium'}"
        ),
    )

    # --- PII and sensitivity flags (used by PolicyEngine) ---
    contains_pii: bool = Field(
        description="True if query contains patient names, MRNs, or other PII"
    )
    data_sensitivity: Literal["low", "medium", "high"] = Field(
        description=(
            "Sensitivity tier of data involved: "
            "low (general info), "
            "medium (demographics), "
            "high (clinical/lab/medication/procedure)"
        )
    )

    # --- Required FHIR capabilities ---
    required_capabilities: list[str] = Field(
        description=(
            "FHIR API operations needed to answer this query. "
            "Used by AgentRegistry to filter capable agents. "
            "Examples: ['GET /Patient'], ['GET /Observation'], ['POST /MedicationRequest']"
        )
    )

    # --- User context (routing and authorization metadata) ---
    user_role: str = Field(description="Role of the requesting user (e.g. 'nurse')")
    user_region: str | None = Field(
        default=None,
        description="User's data region for GDPR residency checks (e.g. 'EU')",
    )
    requires_consent: bool = Field(
        default=False,
        description="True for marketing queries that require GDPR consent verification",
    )

    # --- MedAgentBench metadata (evaluation only) ---
    task_type: int | None = Field(
        default=None,
        description="MedAgentBench task number (1-10) — set during evaluation",
    )

    def __repr__(self) -> str:
        return (
            f"AnalyzedQuery(intent={self.intent!r}, "
            f"pii={self.contains_pii}, "
            f"sensitivity={self.data_sensitivity!r}, "
            f"capabilities={self.required_capabilities})"
        )
