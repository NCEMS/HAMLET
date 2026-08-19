"""Adapters from HAMLET source documents to normalized SDRF evidence."""

from collections.abc import Iterable
from typing import Any

from sdrf_evidence import FieldEvidence


_MISSING_VALUES = {"", "unknown", "none", "null", "n/a"}


def agentic_evidence(
    document: dict[str, Any],
    *,
    source: str,
    scope: str,
    field_aliases: dict[str, str] | None = None,
) -> tuple[FieldEvidence, ...]:
    """Extract resolved agent values without assigning SDRF headers."""
    aliases = field_aliases or {}
    records: list[FieldEvidence] = []
    for source_field, entry in document.items():
        if not isinstance(entry, dict):
            continue
        raw_value = entry.get("resolved")
        value = str(raw_value).strip() if raw_value is not None else ""
        if value.lower() in _MISSING_VALUES:
            continue
        sources = entry.get("sources") if isinstance(entry.get("sources"), dict) else {}
        llm_source = sources.get("llm") if isinstance(sources.get("llm"), dict) else {}
        meti_source = sources.get("meti") if isinstance(sources.get("meti"), dict) else {}
        confidence = entry.get("confidence")
        records.append(
            FieldEvidence(
                field=aliases.get(source_field, source_field),
                value=value,
                source=source,
                scope=scope,  # type: ignore[arg-type]
                evidence=str(llm_source.get("evidence") or ""),
                agent_status=str(entry.get("status") or "") or None,
                agent_confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
                cv_accession=str(meti_source.get("accession") or "") or None,
                cv_name=str(meti_source.get("value") or "") or None,
                metadata={"source_field": source_field},
            )
        )
    return tuple(records)


def judge_evidence(document: dict[str, Any]) -> tuple[FieldEvidence, ...]:
    """Adapt judge assessment rows to evidence records keyed by builder field."""
    records: list[FieldEvidence] = []
    field_overrides = document.get("field_overrides", {})
    if not isinstance(field_overrides, dict):
        return ()
    for judge_field, info in field_overrides.items():
        if not isinstance(info, dict):
            continue
        field = str(info.get("builder_field") or "").strip()
        selected_value = str(info.get("selected_value") or "").strip()
        if not field or selected_value.lower() in _MISSING_VALUES:
            continue
        rows: Iterable[Any] = info.get("judge_rows", [])
        for row in rows:
            if not isinstance(row, dict):
                continue
            records.append(
                FieldEvidence(
                    field=field,
                    value=selected_value,
                    source="judge",
                    scope="study",
                    judge_verdict=str(row.get("verdict") or "") or None,
                    judge_corrected_value=str(row.get("corrected_value") or "") or None,
                    judge_hallucination=row.get("hallucination") if isinstance(row.get("hallucination"), bool) else None,
                    judge_type_mismatch=row.get("type_mismatch") if isinstance(row.get("type_mismatch"), bool) else None,
                    metadata={
                        "judge_field": judge_field,
                        "apply_override": bool(info.get("apply_override")),
                        "selection_source": str(info.get("selection_source") or ""),
                    },
                )
            )
    return tuple(records)