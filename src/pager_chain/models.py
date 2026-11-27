"""Data models for chain plans and per-hop gate decisions."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Label(str, Enum):
    """Data label carried along a plan. NONPHI < PHI."""

    NONPHI = "NONPHI"
    PHI = "PHI"

    def join(self, other: "Label") -> "Label":
        """Least upper bound: PHI if either side is PHI."""
        return Label.PHI if Label.PHI in (self, other) else Label.NONPHI


class LabelSource(str, Enum):
    """Where the label used at a hop came from (gate protocol section 6)."""

    DECLARED = "declared"                    # record access or open session record
    INFERRED = "inferred"                    # detector on text
    PROPAGATED = "propagated"                # carried from upstream
    INFERRED_DECLASS = "inferred-declass"    # detector on a declassifier's output


class Detection(BaseModel):
    """A detector's answer for one text. ok=False marks an unusable answer (scored as PHI upstream)."""

    model_config = {"frozen": True}

    score: float = Field(ge=0.0, le=1.0)
    ok: bool = True


class ChainStep(BaseModel):
    """One step of a plan: a capability, never an agent (the planner does not name agents)."""

    model_config = {"frozen": True}

    capability: str
    conditional: bool = False


class ChainPlan(BaseModel):
    """An ordered (sequential) plan for one request."""

    model_config = {"frozen": True}

    request_text: str
    steps: tuple[ChainStep, ...]
    session_record: str | None = Field(
        default=None, description="Open patient record in the session, if any (metadata, not text)"
    )

    @model_validator(mode="after")
    def _non_empty(self) -> "ChainPlan":
        if not self.steps:
            raise ValueError("A plan needs at least one step")
        return self


class HopDecision(BaseModel):
    """The gate's decision at one hop."""

    model_config = {"frozen": True}

    hop: int = Field(ge=1)
    capability: str
    label: Label
    label_source: LabelSource
    score: float | None = None
    detection_ok: bool = True
    agent_id: str | None = None          # None means the hop was denied
    reason: str = ""

    @property
    def denied(self) -> bool:
        return self.agent_id is None


class ChainResult(BaseModel):
    """All hop decisions for one plan. Execution stops at the first denied hop."""

    plan: ChainPlan
    hops: list[HopDecision]
    label_policy: str
    resolver_strategy: str

    @property
    def denied_at(self) -> int | None:
        return next((h.hop for h in self.hops if h.denied), None)

    @property
    def completed(self) -> bool:
        return self.denied_at is None
