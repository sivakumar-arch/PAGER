"""Agent data model.

Represents a registered agent in the PAGER framework with its capabilities,
compliance attributes, and performance characteristics loaded from YAML config.
"""

from pydantic import BaseModel, Field, field_validator


class Agent(BaseModel):
    """A registered agent with its capabilities and compliance attributes.

    Agents are loaded from YAML configuration files (configs/agents/).
    All fields are immutable after construction — registry is static for POC.
    """

    model_config = {"frozen": True}

    # --- Identity ---
    id: str = Field(description="Unique agent identifier (snake_case)")
    name: str = Field(description="Human-readable agent name")

    # --- Capabilities ---
    capabilities: list[str] = Field(
        description="FHIR API operations this agent supports (e.g. 'GET /Patient')"
    )

    # --- Compliance ---
    hipaa_compliant: bool = Field(
        description="Whether agent meets HIPAA compliance requirements"
    )
    gdpr_compliant: bool = Field(
        description="Whether agent meets GDPR compliance requirements"
    )

    # --- Authorization ---
    authorized_roles: list[str] = Field(
        default_factory=list,
        description="User roles permitted to invoke this agent",
    )
    data_access_level: int = Field(
        ge=1,
        le=3,
        description="Data sensitivity tier: 1=public, 2=clinical, 3=restricted",
    )

    # --- Performance (used by ConflictResolver) ---
    cost_per_query: float = Field(
        gt=0, description="Cost in USD per query invocation"
    )
    avg_latency_ms: float = Field(
        gt=0, description="Average response latency in milliseconds"
    )
    quality_score: float = Field(
        ge=0.0, le=1.0, description="Historical quality score [0.0, 1.0]"
    )

    # --- Operational ---
    endpoint: str = Field(
        description="Agent endpoint URI (mock:// for POC, https:// for production)"
    )
    max_concurrent: int = Field(
        gt=0, description="Maximum concurrent requests this agent handles"
    )

    # --- GDPR-specific (optional — only present for GDPR agents) ---
    data_residency: str | None = Field(
        default=None,
        description="Data storage region: 'EU', 'US', 'multi-region', or None",
    )
    consent_aware: bool | None = Field(
        default=None,
        description="Whether agent enforces GDPR consent requirements",
    )

    @field_validator("id")
    @classmethod
    def id_must_be_snake_case(cls, v: str) -> str:
        if not v.replace("_", "").isalnum():
            raise ValueError(f"Agent id must be snake_case alphanumeric, got: {v!r}")
        return v

    @field_validator("capabilities")
    @classmethod
    def capabilities_must_not_be_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Agent must have at least one capability")
        return v

    def __repr__(self) -> str:
        return (
            f"Agent(id={self.id!r}, hipaa={self.hipaa_compliant}, "
            f"cost={self.cost_per_query}, latency={self.avg_latency_ms}ms)"
        )
