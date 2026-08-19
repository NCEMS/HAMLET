"""Typed internal contracts for SDRF evidence resolution and provenance."""

from dataclasses import dataclass, field
from typing import Any, Literal


EvidenceScope = Literal["study", "sample", "assay", "file"]
AssessmentState = Literal["assessed", "derived", "not_assessed"]


@dataclass(frozen=True)
class FieldEvidence:
    """A candidate value before source precedence or SDRF mapping is applied."""

    field: str
    value: str
    source: str
    scope: EvidenceScope
    evidence: str = ""
    agent_status: str | None = None
    agent_confidence: float | None = None
    cv_accession: str | None = None
    cv_name: str | None = None
    judge_verdict: str | None = None
    judge_corrected_value: str | None = None
    judge_hallucination: bool | None = None
    judge_type_mismatch: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedField:
    """A selected field value with its complete audit trail."""

    field: str
    value: str
    scope: EvidenceScope
    selected: FieldEvidence | None
    resolution_rule: str
    assessment_state: AssessmentState
    candidates: tuple[FieldEvidence, ...] = ()
