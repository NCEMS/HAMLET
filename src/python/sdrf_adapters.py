"""Adapters from HAMLET source documents to normalized SDRF evidence."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sdrf_evidence import FieldEvidence


_MISSING_VALUES = {"", "unknown", "none", "null", "n/a", "nan"}
_PRIDE_NO_PTMS_ACCESSION = "PRIDE:0000398"


@dataclass(frozen=True)
class ModificationEvidence:
    """One source-supplied modification record before SDRF rendering."""

    name: str
    accession: str | None
    targets: tuple[str, ...]
    modification_type: str | None
    source: str
    scope: str
    source_path: str
    source_value: str
    raw_stem: str | None = None
    fraction_modified: float | None = None


def _targets(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple, set)):
        values = (str(item).strip() for item in value)
    else:
        values = (item.strip() for item in str(value).replace(";", ",").split(","))
    return tuple(dict.fromkeys(item for item in values if item and item.lower() not in _MISSING_VALUES))


def _explicit_modification_type(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if text == "fixed":
        return "Fixed"
    if text == "variable":
        return "Variable"
    return None


def modification_evidence(
    pride_ptms: Iterable[Any],
    technical_document: dict[str, Any],
    search_records: Iterable[Any],
    *,
    raw_stem: str,
) -> tuple[ModificationEvidence, ...]:
    """Adapt PRIDE, TechnicalAgent, and per-file search PTMs losslessly.

    This function only parses the structures supplied by those sources. It does
    not infer ontology IDs, targets, terminal positions, or fixed/variable state.
    """
    records: list[ModificationEvidence] = []

    for index, item in enumerate(pride_ptms):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        accession = str(item.get("accession") or "").strip() or None
        if accession == _PRIDE_NO_PTMS_ACCESSION:
            continue
        if not name and not accession:
            continue
        records.append(ModificationEvidence(
            name=name or accession or "",
            accession=accession,
            targets=_targets(item.get("targets") or item.get("target") or item.get("residue") or item.get("position")),
            modification_type=_explicit_modification_type(item.get("modificationType") or item.get("mod_type")),
            source=str(item.get("source") or "pride"),
            scope=str(item.get("scope") or "study"),
            source_path=str(item.get("source_path") or f"pride_metadata.project.identifiedPTMStrings[{index}]"),
            source_value=str(item.get("source_value") or name or accession or ""),
        ))

    for field in ("ptm", "modification"):
        entry = technical_document.get(field)
        resolved = entry.get("resolved") if isinstance(entry, dict) else None
        if resolved is None:
            continue
        for index, value in enumerate(str(resolved).split(";")):
            name = value.strip()
            if not name or name.lower() in _MISSING_VALUES:
                continue
            records.append(ModificationEvidence(
                name=name,
                accession=None,
                targets=(),
                modification_type=None,
                source="technical_agent",
                scope="study",
                source_path=f"TechnicalAgent.{field}.resolved[{index}]",
                source_value=name,
            ))

    for index, item in enumerate(search_records):
        if not isinstance(item, dict):
            continue
        unimod_id = item.get("unimod_id")
        accession = str(item.get("accession") or "").strip() or (f"UNIMOD:{unimod_id}" if unimod_id not in (None, "") else None)
        name = str(item.get("name") or item.get("mod_name") or "").strip()
        if not name and not accession:
            continue
        fraction = item.get("fraction_modified")
        records.append(ModificationEvidence(
            name=name or accession or "",
            accession=accession,
            targets=_targets(item.get("targets")) or (_targets(item.get("allowed_residues")) + _targets(item.get("allowed_terms"))),
            modification_type=_explicit_modification_type(item.get("modification_type") or item.get("mod_type")),
            source=str(item.get("source") or "ptm_shepherd"),
            scope=str(item.get("scope") or "assay"),
            source_path=str(item.get("source_path") or f"modification_site_fractions.dda_closed_search.per_sample_files.{raw_stem}.data[{index}]"),
            source_value=str(item.get("source_value") or name or accession or ""),
            raw_stem=raw_stem,
            fraction_modified=float(fraction) if isinstance(fraction, (int, float)) else None,
        ))
    return tuple(records)


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