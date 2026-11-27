"""Label policies for chain hops (gate protocol, sections 5 and 6).

Each policy decides the label that the policy gate uses at a hop. The rules are written
to match the frozen gate harness (gate/harness/engine.py) exactly; package 4 checks this
hop by hop on the 76 frozen scenarios.

    PROP      detector on the request text at hop 1, then propagated (no source labels)
    REDETECT  detector on each hop's own input, independently
    SRC       declared PHI where a source exists (record access, open session record);
              detector at hop 1 otherwise; then join with upstream
    SRC-FC    as SRC with the lower fail-closed threshold for inferred labels
In every non-oracle policy, the hop after a declassifier is labelled by the detector on
the declassifier's output (declassification by verification).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.pager_chain.models import Detection, Label, LabelSource

TAU = 0.5        # frozen protocol section 5
TAU_LOW = 0.2    # fail-closed threshold


@dataclass(frozen=True)
class LabelPolicy:
    name: str
    tau: float
    declared_sources: bool     # use record access / session record as declared PHI
    propagate: bool            # carry the upstream label to later hops
    redetect: bool             # run the detector on every hop's input

    def threshold(self, d: Detection) -> Label:
        return Label.PHI if d.score >= self.tau else Label.NONPHI


POLICIES: dict[str, LabelPolicy] = {
    "PROP": LabelPolicy("PROP", TAU, declared_sources=False, propagate=True, redetect=False),
    "REDETECT": LabelPolicy("REDETECT", TAU, declared_sources=False, propagate=False, redetect=True),
    "SRC": LabelPolicy("SRC", TAU, declared_sources=True, propagate=True, redetect=False),
    "SRC-FC": LabelPolicy("SRC-FC", TAU_LOW, declared_sources=True, propagate=True, redetect=False),
}


def get_policy(name: str) -> LabelPolicy:
    try:
        return POLICIES[name]
    except KeyError:
        raise ValueError(f"Unknown label policy {name!r}; valid: {sorted(POLICIES)}") from None


@dataclass(frozen=True)
class HopContext:
    """Everything a label policy may look at for one hop."""

    hop: int                       # 1-based
    request_text: str
    hop_input: str                 # the text this hop receives
    record_access: bool            # the hop's capability reads or writes a patient record
    session_open: bool             # a patient record is open in the session
    after_declassifier: bool       # the previous hop was a declassifier
    upstream: Label | None         # label carried into this hop (None at hop 1)


def decide_label(policy: LabelPolicy, ctx: HopContext,
                 detect: Callable[[str], Detection]) -> tuple[Label, LabelSource, Detection | None]:
    """Return (label, source, detection or None) for one hop. Pure apart from detector calls."""
    if ctx.after_declassifier:
        d = detect(ctx.hop_input)
        return policy.threshold(d), LabelSource.INFERRED_DECLASS, d
    if policy.redetect:
        d = detect(ctx.request_text if ctx.hop == 1 else ctx.hop_input)
        return policy.threshold(d), LabelSource.INFERRED, d
    if policy.declared_sources and (ctx.record_access or (ctx.hop == 1 and ctx.session_open)):
        return Label.PHI, LabelSource.DECLARED, None
    if ctx.hop == 1:
        d = detect(ctx.request_text)
        return policy.threshold(d), LabelSource.INFERRED, d
    if policy.propagate:
        if ctx.upstream is None:
            raise ValueError("upstream label missing for a propagated hop")
        return ctx.upstream, LabelSource.PROPAGATED, None
    raise ValueError(f"policy {policy.name} cannot label hop {ctx.hop}")
