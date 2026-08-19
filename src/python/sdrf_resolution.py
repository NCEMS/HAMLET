"""Deterministic resolution of normalized SDRF evidence candidates."""

from collections.abc import Iterable

from sdrf_evidence import FieldEvidence, ResolvedField


DEFAULT_SOURCE_PRECEDENCE = (
    "technical_agent",
    "biological_agent",
    "experimental_design_agent",
    "runassessor",
    "aggregate",
    "pride",
    "llm_metadata",
)


def resolve_field(
    field: str,
    evidence: Iterable[FieldEvidence],
    *,
    fallback: str = "not available",
    source_precedence: tuple[str, ...] = DEFAULT_SOURCE_PRECEDENCE,
) -> ResolvedField:
    """Select one value without losing the candidates that informed it.

    Judge corrections have priority. A judge-validated candidate is next,
    followed by the configured source order and finally the fallback value.
    """
    candidates = tuple(item for item in evidence if item.field == field and item.value.strip())
    if not candidates:
        return ResolvedField(
            field=field,
            value=fallback,
            scope="study",
            selected=None,
            resolution_rule="fallback",
            assessment_state="not_assessed",
            candidates=(),
        )

    for candidate in candidates:
        if candidate.judge_corrected_value:
            return ResolvedField(
                field=field,
                value=candidate.judge_corrected_value,
                scope=candidate.scope,
                selected=candidate,
                resolution_rule="judge_corrected_value",
                assessment_state="assessed",
                candidates=candidates,
            )

    validated = next(
        (
            candidate
            for candidate in candidates
            if candidate.judge_verdict in {"high", "medium"}
            and not candidate.judge_hallucination
            and not candidate.judge_type_mismatch
        ),
        None,
    )
    if validated:
        return ResolvedField(
            field=field,
            value=validated.value,
            scope=validated.scope,
            selected=validated,
            resolution_rule="judge_validated_value",
            assessment_state="assessed",
            candidates=candidates,
        )

    source_rank = {source: index for index, source in enumerate(source_precedence)}
    selected = min(
        enumerate(candidates),
        key=lambda item: (source_rank.get(item[1].source, len(source_rank)), item[0]),
    )[1]
    return ResolvedField(
        field=field,
        value=selected.value,
        scope=selected.scope,
        selected=selected,
        resolution_rule=f"source_precedence:{selected.source}",
        assessment_state="derived",
        candidates=candidates,
    )