#!/usr/bin/env python3
"""Render enriched agent metadata as an SDRF-Proteomics v1.1.0 TSV."""

import csv
import json
import re
from pathlib import Path

from sdrf_adapters import ModificationEvidence, agentic_evidence, judge_evidence, modification_evidence
from sdrf_evidence import FieldEvidence
from sdrf_resolution import resolve_field
from sdrf_schema import flatten_internal_header, render_columns, rule_for_header, source_precedence_for
from sdrf_protocol import parse_alkylation_reagent, parse_reduction_reagent
from hamlet_version import HAMLET_VERSION


class AgenticToSDRF:
    """
    Convert three enriched agent JSONs and an explicit RAW manifest into an
    SDRF-Proteomics v1.1.0 TSV file. One row is written per .raw data file.

    The renderer never reads aggregated pipeline data. It renders values and
    source records that the upstream integration step has already resolved.
    """

    # ------------------------------------------------------------------ #
    # Class-level CV maps
    # ------------------------------------------------------------------ #

    # accessions are PRIDE CV children of PRIDE:0000659 "Proteomics data acquisition method" that is the value source the SDRF spec names for
    # this column (assets/sdrf-terms.csv)and the equivalent ms terms are the xrefs MS:1003221 (DDA) and MS:1003215 (DIA).
    _ACQUISITION_MAP: dict[str, str] = {
        "dda": "NT=data-dependent acquisition;AC=PRIDE:0000627",
        "dia": "NT=data-independent acquisition;AC=PRIDE:0000450",
        "prm": "NT=parallel reaction monitoring;AC=PRIDE:0000629",
        "srm": "NT=selected reaction monitoring;AC=PRIDE:0000630",
        "targeted": "NT=parallel reaction monitoring;AC=PRIDE:0000629",
    }

    _DISSOCIATION_MAP: dict[str, str] = {
        "hcd": "NT=beam-type collision-induced dissociation;AC=MS:1000422",
        "hr_hcd": "NT=beam-type collision-induced dissociation;AC=MS:1000422",
        "lr_hcd": "NT=beam-type collision-induced dissociation;AC=MS:1000422",
        "cid": "NT=collision-induced dissociation;AC=MS:1000133",
        "lr_it_cid": "NT=collision-induced dissociation;AC=MS:1000133",
        "hr_it_cid": "NT=collision-induced dissociation;AC=MS:1000133",
        "etd": "NT=electron transfer dissociation;AC=MS:1001356",
        "hr_it_etd": "NT=electron transfer dissociation;AC=MS:1001356",
        "lr_it_etd": "NT=electron transfer dissociation;AC=MS:1001356",
        "ethcd": "NT=electron transfer higher energy collision dissociation;AC=MS:1002631",
        "hr_ethcd": "NT=electron transfer higher energy collision dissociation;AC=MS:1002631",
        "etcid": "NT=electron transfer collision induced dissociation;AC=MS:1003182",
        "hr_etcid": "NT=electron transfer collision induced dissociation;AC=MS:1003182",
        "ecd": "NT=electron capture dissociation;AC=MS:1000250",
    }

    _LABEL_MAP: dict[str, str] = {
        "none": "label free sample",
        "lfq": "label free sample",
        "label free": "label free sample",
        "label-free": "label free sample",
        "tmt": "TMT126",
        "tmt6": "TMT126",
        "tmt10": "TMT126",
        "tmtpro": "TMTpro126C",
        "itraq": "iTRAQ4plex-114",
        "itraq4": "iTRAQ4plex-114",
        "itraq8": "iTRAQ8plex-113",
        "silac": "not available",
    }

    # label channels per multiplex scheme. names and SILAC accessions
    # follow the curated SDRF files in assets/gold_standard_sdrfs/.
    _TMT6_CHANNELS: list[str] = [
        "TMT126", "TMT127", "TMT128", "TMT129", "TMT130", "TMT131",
    ]
    _TMT10_CHANNELS: list[str] = [
        "TMT126", "TMT127N", "TMT127C", "TMT128N", "TMT128C",
        "TMT129N", "TMT129C", "TMT130N", "TMT130C", "TMT131",
    ]
    _TMT11_CHANNELS: list[str] = _TMT10_CHANNELS + ["TMT131C"]
    _TMT16_CHANNELS: list[str] = [
        "TMT126", "TMT127N", "TMT127C", "TMT128N", "TMT128C",
        "TMT129N", "TMT129C", "TMT130N", "TMT130C", "TMT131N",
        "TMT131C", "TMT132N", "TMT132C", "TMT133N", "TMT133C", "TMT134N",
    ]
    _ITRAQ4_CHANNELS: list[str] = ["iTRAQ114", "iTRAQ115", "iTRAQ116", "iTRAQ117"]
    _ITRAQ8_CHANNELS: list[str] = [
        "iTRAQ113", "iTRAQ114", "iTRAQ115", "iTRAQ116",
        "iTRAQ117", "iTRAQ118", "iTRAQ119", "iTRAQ121",
    ]
    # SILAC carries one label term per labelled residue so a channel is a list.
    _SILAC_RK_CHANNELS: list[list[str]] = [
        ["AC=PRIDE:0000615;NT=SILAC heavy R:13C(6)15N(4)",
         "AC=PRIDE:0000617;NT=SILAC heavy K:13C(6)15N(2)"],
        ["AC=PRIDE:0000611;NT=SILAC light R:12C(6)14N(4)",
         "AC=PRIDE:0000613;NT=SILAC light K:12C(6)14N(2)"],
    ]

    _LABEL_CHANNELS: dict[str, list[list[str]]] = {
        "tmt": [[c] for c in _TMT6_CHANNELS],
        "tmt2": [[c] for c in _TMT6_CHANNELS[:2]],
        "tmt6": [[c] for c in _TMT6_CHANNELS],
        "tmt6plex": [[c] for c in _TMT6_CHANNELS],
        "tmt10": [[c] for c in _TMT10_CHANNELS],
        "tmt10plex": [[c] for c in _TMT10_CHANNELS],
        "tmt11": [[c] for c in _TMT11_CHANNELS],
        "tmt11plex": [[c] for c in _TMT11_CHANNELS],
        "tmt16": [[c] for c in _TMT16_CHANNELS],
        "tmt16plex": [[c] for c in _TMT16_CHANNELS],
        "tmtpro": [[c] for c in _TMT16_CHANNELS],
        "itraq": [[c] for c in _ITRAQ4_CHANNELS],
        "itraq4": [[c] for c in _ITRAQ4_CHANNELS],
        "itraq4plex": [[c] for c in _ITRAQ4_CHANNELS],
        "itraq8": [[c] for c in _ITRAQ8_CHANNELS],
        "itraq8plex": [[c] for c in _ITRAQ8_CHANNELS],
        "silac": [list(c) for c in _SILAC_RK_CHANNELS],
        "silac2": [list(c) for c in _SILAC_RK_CHANNELS],
    }

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        tech_json: Path,
        bio_json: Path,
        exp_json: Path,
        raw_files: list[str],
        pxd_id: str,
        overrides: dict | None = None,
        judge_document: dict | None = None,
    ) -> None:
        self.tech_json = Path(tech_json)
        self.bio_json = Path(bio_json)
        self.exp_json = Path(exp_json)
        self.pxd_id = str(pxd_id).strip()
        self._raw_files = self._normalize_raw_files(raw_files)
        self._overrides = overrides or {}
        self._judge_document = judge_document or {}
        self._load_agentic_jsons()
        self._sample_evidence = self._build_sample_evidence()
        self._experiment_evidence = self._build_experiment_evidence()
        self._judge_evidence = judge_evidence(self._judge_document)

    def _load_agentic_jsons(self) -> None:
        with open(self.tech_json) as f:
            self._tech: dict = json.load(f)
        with open(self.bio_json) as f:
            self._bio: dict = json.load(f)
        with open(self.exp_json) as f:
            self._exp: dict = json.load(f)

    def _build_sample_evidence(self) -> tuple[FieldEvidence, ...]:
        """Normalize upstream-integrated biological values for rendering."""
        return agentic_evidence(
            self._bio,
            source="biological_agent",
            scope="sample",
            field_aliases={
                "species": "organism",
                "tissue": "organism_part",
                "organ": "organism_part",
                "disease_state": "disease",
            },
        )

    def _resolve_sample_field(self, field: str, fallback: str | None = None) -> str | None:
        resolved = resolve_field(field, self._sample_evidence, fallback=fallback or "not available")
        return None if resolved.value == "not available" and fallback is None else resolved.value

    def _build_experiment_evidence(self) -> tuple[FieldEvidence, ...]:
        """Normalize experimental-design values before renderer-specific checks."""
        structured_fields = {
            "factor_value",
        }
        return agentic_evidence(
            {key: value for key, value in self._exp.items() if key in structured_fields},
            source="experimental_design_agent",
            scope="study",
        )

    def _resolve_experiment_field(self, field: str) -> str | None:
        resolved = resolve_field(field, self._experiment_evidence)
        return None if resolved.value == "not available" else resolved.value

    # ------------------------------------------------------------------ #
    # Generic helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _agentic_field(data: dict, field: str) -> str | None:
        """Return data[field]['resolved'] if non-null/unknown, else None."""
        entry = data.get(field)
        if not isinstance(entry, dict):
            return None
        val = entry.get("resolved")
        if val is None:
            return None
        val_s = str(val).strip()
        if val_s.upper() in ("", "UNKNOWN", "NONE", "NULL", "N/A"):
            return None
        return val_s

    def _override_field(self, field: str) -> str | None:
        val = self._overrides.get(field)
        if val is None:
            return None
        val_s = str(val).strip()
        if val_s.upper() in ("", "UNKNOWN", "NONE", "NULL", "N/A"):
            return None
        return val_s

    @staticmethod
    def _normalize_raw_files(candidates: list[str]) -> list[str]:
        """Return ordered, de-duplicated RAW filenames from the supplied manifest."""
        raw_files: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            raw_file = str(candidate).strip()
            if not raw_file or not raw_file.lower().endswith(".raw"):
                continue
            key = raw_file.casefold()
            if key not in seen:
                seen.add(key)
                raw_files.append(raw_file)
        return raw_files

    def _get_raw_files(self) -> list[str]:
        return self._raw_files

    # ------------------------------------------------------------------ #
    # Sample characteristics extractors
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_organism(name: str) -> str:
        """species names are written Genus species so the first letter is a
        capital and the rest of the source casing is kept as it is. any common
        name in brackets is dropped, for example Homo sapiens (human)."""
        name = re.sub(r"\s*\([^)]+\)", "", str(name)).strip()
        if not name:
            return ""
        return name[0].upper() + name[1:]

    def _get_organism(self) -> str:
        override = self._override_field("organism")
        if override:
            return self._format_organism(override)
        return self._format_organism(self._resolve_sample_field("organism", "not available") or "not available")

    def _get_organism_part(self) -> str:
        override = self._override_field("organism_part")
        if override:
            return override.lower()
        return (self._resolve_sample_field("organism_part", "not available") or "not available").lower()

    def _get_disease(self) -> str:
        override = self._override_field("disease")
        if override:
            return override.lower()
        return (self._resolve_sample_field("disease", "not available") or "not available").lower()

    def _get_cell_type(self) -> str | None:
        return self._override_field("cell_type") or self._resolve_sample_field("cell_type")

    def _get_cell_line(self) -> str | None:
        return self._override_field("cell_line") or self._resolve_sample_field("cell_line")

    def _get_sex(self) -> str:
        override = self._override_field("sex")
        if override:
            return override
        val = self._resolve_sample_field("sex")
        return val or "not available"

    def _get_age(self) -> str:
        override = self._override_field("age")
        if override:
            return override
        val = self._resolve_sample_field("age")
        return val if val else "not available"

    # ------------------------------------------------------------------ #
    # Experimental design extractors (from ExperimentalDesignAgent)
    # ------------------------------------------------------------------ #

    def _get_biological_replicate(self) -> str:
        return "not available"

    def _get_technical_replicate(self) -> str:
        return "not available"

    def _get_fraction_identifier(self) -> str:
        return "not available"

    def _get_factor_value(self) -> str | None:
        return self._override_field("factor_value") or self._resolve_experiment_field("factor_value")

    # ------------------------------------------------------------------ #
    # Per-file data extractors
    # ------------------------------------------------------------------ #

    def _per_raw_data(self, raw_stem: str) -> dict:
        records = self._tech.get("per_raw_file")
        if not isinstance(records, dict):
            return {}
        return records.get(raw_stem, {}) if isinstance(records.get(raw_stem), dict) else {}

    @staticmethod
    def _clean_fragmentation(value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text.lower() in {"", "?", "??", "unknown", "not available", "n/a", "none", "null"}:
            return ""
        return text

    def _technical_evidence_for_file(self, raw_stem: str) -> tuple[FieldEvidence, ...]:
        """Normalize source records supplied by upstream per-RAW integration."""
        per_raw = self._per_raw_data(raw_stem)
        records: list[FieldEvidence] = []

        for field in ("instrument", "acquisition", "label", "dissociation", "ms2_analyzer"):
            source_field = per_raw.get(field)
            if not isinstance(source_field, dict):
                continue
            candidates = source_field.get("candidates")
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if not isinstance(candidate, dict) or not candidate.get("valid"):
                    continue
                value = self._clean_fragmentation(candidate.get("value"))
                if not value:
                    continue
                records.append(FieldEvidence(
                    field,
                    value,
                    str(candidate.get("source") or "runassessor"),
                    str(candidate.get("scope") or "assay"),
                    cv_accession=str(candidate.get("cv_accession") or "") or None,
                    cv_name=str(candidate.get("cv_name") or "") or None,
                    metadata={"source_path": str(candidate.get("source_path") or "")},
                ))

        for field, agent_fields in (
            ("instrument", ("instrument",)),
            ("label", ("labeling",)),
            ("dissociation", ("fragmentation_method",)),
            ("ms2_analyzer", ("mass_analyzer", "ms2_analyzer")),
        ):
            value = next((
                value for agent_field in agent_fields
                if (value := self._agentic_field(self._tech, agent_field))
            ), None)
            if value:
                records.append(FieldEvidence(field, value, "technical_agent", "study"))
        return tuple(records)

    @staticmethod
    def _resolve_technical_field(field: str, evidence: tuple[FieldEvidence, ...]) -> str | None:
        source_precedence = source_precedence_for(field)
        kwargs = {"source_precedence": source_precedence} if source_precedence else {}
        resolved = resolve_field(field, evidence, **kwargs)
        return None if resolved.value == "not available" else resolved.value

    def _meti_accession(self, field: str) -> tuple[str, str]:
        """the METI value and its accession for a TechnicalAgent field."""
        entry = self._tech.get(field)
        if not isinstance(entry, dict):
            return "", ""
        sources = entry.get("sources")
        if not isinstance(sources, dict):
            return "", ""
        meti = sources.get("meti")
        if not isinstance(meti, dict):
            return "", ""
        return str(meti.get("value") or ""), str(meti.get("accession") or "")

    def _get_instrument_name(self, raw_stem: str) -> str:
        override = self._override_field("instrument")
        if override:
            return override
        return self._resolve_technical_field("instrument", self._technical_evidence_for_file(raw_stem)) or "not available"

    def _get_instrument(self, raw_stem: str) -> str:
        override = self._override_field("instrument")
        if override:
            return override
        evidence = self._technical_evidence_for_file(raw_stem)
        precedence = source_precedence_for("instrument")
        resolved = resolve_field("instrument", evidence, **({"source_precedence": precedence} if precedence else {}))
        if resolved.value == "not available":
            return resolved.value
        if resolved.selected and resolved.selected.cv_accession:
            return f"NT={resolved.value};AC={resolved.selected.cv_accession}"
        return resolved.value

    def _get_acquisition_method(self, raw_stem: str) -> str:
        raw = self._resolve_technical_field("acquisition", self._technical_evidence_for_file(raw_stem)) or ""
        return self._map_acquisition(raw)

    def _raw_label(self, raw_stem: str) -> str:
        return self._resolve_technical_field("label", self._technical_evidence_for_file(raw_stem)) or ""

    @staticmethod
    def _label_scheme_key(raw_label: str) -> str:
        """Normalize recognized channel scheme names without changing label values."""
        normalized = raw_label.lower().strip().replace("-", "").replace(" ", "")
        aliases = {
            "10plextandemmasstag(tmt)": "tmt10plex",
        }
        return aliases.get(normalized, normalized)

    def _get_label(self, raw_stem: str) -> str:
        raw_label = self._raw_label(raw_stem)
        scheme = self._label_scheme_key(raw_label)
        return self._map_label("silac" if scheme == "silac" else raw_label)

    def _has_silac_modification(self, raw_stem: str) -> bool:
        """Require observed per-file SILAC evidence before expanding channels."""
        for modification in self._per_raw_data(raw_stem).get("modifications", []):
            accession = str(modification.get("accession") or "")
            modification_name = str(modification.get("name") or "")
            if accession in {"UNIMOD:259", "UNIMOD:267"} or "silac" in modification_name.lower():
                return True
        return False

    def _get_channels(self, raw_stem: str) -> list[list[str]]:
        """label channels for this file. one entry per SDRF row to emit."""
        key = self._label_scheme_key(self._raw_label(raw_stem))
        channels = self._LABEL_CHANNELS.get(key)
        if channels and (key != "silac" or self._has_silac_modification(raw_stem)):
            return [list(c) for c in channels]
        return [[self._get_label(raw_stem)]]

    def _get_dissociation_method(self, raw_stem: str) -> str:
        raw = self._resolve_technical_field("dissociation", self._technical_evidence_for_file(raw_stem)) or ""
        return self._map_dissociation(raw)

    # ------------------------------------------------------------------ #
    # Experiment-level extractors (parsed from protocol text)
    # ------------------------------------------------------------------ #

    def _tech_evidence(self, field: str) -> str:
        """return the LLM evidence quote for a TechnicalAgent field or ""."""
        entry = self._tech.get(field)
        if not isinstance(entry, dict):
            return ""
        sources = entry.get("sources")
        if not isinstance(sources, dict):
            return ""
        llm = sources.get("llm")
        if not isinstance(llm, dict):
            return ""
        return str(llm.get("evidence") or "")

    def _tech_text(self, field: str) -> str:
        """agentic resolved value plus its evidence quote for regex matching."""
        return " ".join([
            self._agentic_field(self._tech, field) or "",
            self._tech_evidence(field),
        ])

    def _get_cleavage_agent(self) -> str:
        override = self._override_field("cleavage_agent")
        value = override or self._agentic_field(self._tech, "cleavage_agent")
        return self._map_cleavage_agent(value or "")

    def _get_reduction_reagent(self) -> str | None:
        return parse_reduction_reagent("", self._tech_text("reduction_reagent"))

    def _get_alkylation_reagent(self) -> str | None:
        return parse_alkylation_reagent("", self._tech_text("alkylation_reagent"))

    def _get_mass_tolerances(self, raw_stem: str) -> tuple[str | None, str | None]:
        return (
            self._override_field("precursor_tolerance") or self._agentic_field(self._tech, "precursor_tolerance"),
            self._override_field("fragment_tolerance") or self._agentic_field(self._tech, "fragment_tolerance"),
        )

    def _get_scan_range(self) -> str | None:
        return None

    def _get_collision_energy(self) -> str | None:
        return self._agentic_field(self._tech, "collision_energy")

    def _get_ms2_analyzer(self, raw_stem: str) -> str | None:
        return self._resolve_technical_field("ms2_analyzer", self._technical_evidence_for_file(raw_stem))

    # ------------------------------------------------------------------ #
    # Modification parameters
    # ------------------------------------------------------------------ #

    def _modification_records(self, raw_stem: str) -> tuple[ModificationEvidence, ...]:
        meti_data = self._tech.get("_meti_data")
        ptm_data = meti_data.get("ptms") if isinstance(meti_data, dict) else {}
        pride_records = ptm_data.get("records", []) if isinstance(ptm_data, dict) else []
        search_data = self._per_raw_data(raw_stem).get("modifications", [])
        return modification_evidence(
            pride_records if isinstance(pride_records, list) else [],
            self._tech,
            search_data if isinstance(search_data, list) else [],
            raw_stem=raw_stem,
        )

    @staticmethod
    def _same_modification(record: ModificationEvidence, candidate: ModificationEvidence) -> bool:
        """Compare source-provided identities without ontology-name inference."""
        if record.name.casefold() == candidate.name.casefold():
            return True
        return bool(record.accession and candidate.accession and record.accession.casefold() == candidate.accession.casefold())

    def _resolved_modifications(self, raw_stem: str) -> list[tuple[str, tuple[ModificationEvidence, ...]]]:
        grouped: list[list[ModificationEvidence]] = []
        for record in self._modification_records(raw_stem):
            matching_group = next(
                (records for records in grouped if any(self._same_modification(record, candidate) for candidate in records)),
                None,
            )
            if matching_group is None:
                grouped.append([record])
            else:
                matching_group.append(record)

        rendered: list[tuple[str, tuple[ModificationEvidence, ...]]] = []
        for records in grouped:
            first = records[0]
            accession = next((record.accession for record in records if record.accession), None)
            targets = tuple(dict.fromkeys(target for record in records for target in record.targets))
            statuses = {record.modification_type for record in records if record.modification_type}
            modification_type = next(iter(statuses)) if len(statuses) == 1 else "!" if statuses else "?"
            parts = [f"NT={first.name}"]
            if accession:
                parts.append(f"AC={accession}")
            parts.append(f"MT={modification_type}")
            if targets:
                parts.append(f"TA={','.join(targets)}")
            rendered.append((";".join(parts), tuple(records)))
        return rendered

    def _get_modification_params(self, raw_stem: str) -> list[str]:
        return [value for value, _ in self._resolved_modifications(raw_stem)]

    def _modification_provenance(self, raw_stem: str, value: str) -> tuple[ModificationEvidence, ...]:
        for rendered, records in self._resolved_modifications(raw_stem):
            if rendered == value:
                return records
        return ()

    # ------------------------------------------------------------------ #
    # LLM-extracted per-file fields
    # ------------------------------------------------------------------ #

    def _get_treatment(self, raw_file: str) -> str | None:
        return None

    def _get_enrichment_process(self, raw_file: str) -> str | None:
        return None

    # ------------------------------------------------------------------ #
    # CV mappers
    # ------------------------------------------------------------------ #

    @classmethod
    def _map_acquisition(cls, raw: str) -> str:
        return cls._ACQUISITION_MAP.get(raw.lower().strip(), "not available")

    @staticmethod
    def _canonical_fragmentation(raw: str) -> str:
        return re.sub(r"[\s_-]+", "_", raw.strip().lower()).strip("_")

    @classmethod
    def _map_dissociation(cls, raw: str) -> str:
        return cls._DISSOCIATION_MAP.get(cls._canonical_fragmentation(raw), "not available")

    @classmethod
    def _map_label(cls, raw: str) -> str:
        return cls._LABEL_MAP.get(raw.lower().strip(), "not available")

    @staticmethod
    def _map_cleavage_agent(raw: str) -> str:
        values = {
            "chymotrypsin": "NT=Chymotrypsin;AC=MS:1001306",
            "lys-c": "NT=Lys-C;AC=MS:1001309",
            "asp-n": "NT=Asp-N;AC=MS:1001303",
            "glu-c": "NT=Glu-C;AC=MS:1001917",
            "trypsin": "NT=Trypsin;AC=MS:1001251",
            "trypsin/p": "NT=Trypsin/P;AC=MS:1001313",
        }
        return values.get(raw.strip().lower(), "not available")

    # ------------------------------------------------------------------ #
    # Column order builder
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_column_order(
        *,
        has_cell_type: bool,
        has_cell_line: bool,
        max_mods: int,
        has_prec_tol: bool,
        has_frag_tol: bool,
        has_reduction: bool,
        has_alkylation: bool,
        has_ms2_analyzer: bool,
        has_scan_range: bool,
        has_collision_energy: bool,
        has_treatment: bool,
        has_enrichment: bool,
        has_fv_organism_part: bool,
        has_factor_value: bool,
        max_labels: int = 1,
    ) -> list[str]:
        included_fields = {
            "source_name", "organism", "organism_part", "disease", "biological_replicate",
            "sex", "age", "assay_name", "technology_type", "acquisition", "label", "instrument",
            "cleavage_agent", "fraction_identifier", "technical_replicate", "dissociation", "modification",
            "data_file", "sdrf_version", "annotation_tool", "factor_disease",
        }
        if has_cell_type:
            included_fields.add("cell_type")
        if has_cell_line:
            included_fields.update({"cell_line", "cellosaurus_accession"})
        if has_treatment:
            included_fields.add("treatment")
        if has_enrichment:
            included_fields.add("enrichment")
        if has_factor_value:
            included_fields.add("factor_value")
        if has_prec_tol:
            included_fields.add("precursor_tolerance")
        if has_frag_tol:
            included_fields.add("fragment_tolerance")
        if has_reduction:
            included_fields.add("reduction_reagent")
        if has_alkylation:
            included_fields.add("alkylation_reagent")
        if has_ms2_analyzer:
            included_fields.add("ms2_analyzer")
        if has_scan_range:
            included_fields.add("ms1_scan_range")
        if has_collision_energy:
            included_fields.add("collision_energy")
        if has_fv_organism_part:
            included_fields.add("factor_organism_part")
        return render_columns(included_fields, {"label": max_labels, "modification": max_mods})

    # ------------------------------------------------------------------ #
    # Row building
    # ------------------------------------------------------------------ #

    def build_rows(self) -> tuple[list[str], list[dict]]:
        """
        Return (columns, rows).

        columns: ordered list of internal column keys (mod params use #N suffix).
        rows: list of dicts {column_key: value_string}.
        """
        raw_files = self._get_raw_files()

        # --- experiment-level ---
        organism = self._get_organism()
        organism_part = self._get_organism_part()
        disease = self._get_disease()
        cell_type = self._get_cell_type()
        cell_line = self._get_cell_line()
        sex = self._get_sex()
        age = self._get_age()
        biological_replicate = self._get_biological_replicate()
        technical_replicate = self._get_technical_replicate()
        fraction_identifier = self._get_fraction_identifier()
        factor_value = self._get_factor_value()
        cleavage_agent = self._get_cleavage_agent()
        reduction_reagent = self._get_reduction_reagent()
        alkylation_reagent = self._get_alkylation_reagent()
        scan_range = self._get_scan_range()
        collision_energy = self._get_collision_energy()

        # --- per-file precompute ---
        per_file: list[dict] = []
        for raw_file in raw_files:
            stem = Path(raw_file).stem
            instrument = self._get_instrument(stem)
            per_file.append({
                "raw_file": raw_file,
                "stem": stem,
                "instrument": instrument,
                "acq": self._get_acquisition_method(stem),
                "label": self._get_label(stem),
                "channels": self._get_channels(stem),
                "dissociation": self._get_dissociation_method(stem),
                "ms2_analyzer": self._get_ms2_analyzer(stem),
                "mods": self._get_modification_params(stem),
                "precursor_tolerance": self._get_mass_tolerances(stem)[0],
                "fragment_tolerance": self._get_mass_tolerances(stem)[1],
                "treatment": self._get_treatment(raw_file),
                "enrichment": self._get_enrichment_process(raw_file),
            })

        # --- optional column flags ---
        max_mods = max((len(pf["mods"]) for pf in per_file), default=0)
        max_labels = max((len(ch) for pf in per_file for ch in pf["channels"]), default=1)
        has_cell_type = bool(cell_type)
        has_cell_line = bool(cell_line)
        has_prec_tol = any(pf["precursor_tolerance"] for pf in per_file)
        has_frag_tol = any(pf["fragment_tolerance"] for pf in per_file)
        has_reduction = bool(reduction_reagent)
        has_alkylation = bool(alkylation_reagent)
        has_ms2_analyzer = any(pf["ms2_analyzer"] for pf in per_file)
        has_scan_range = bool(scan_range)
        has_collision_energy = bool(collision_energy)
        has_treatment = any(pf["treatment"] for pf in per_file)
        has_enrichment = any(pf["enrichment"] for pf in per_file)
        organism_parts = [organism_part] * len(raw_files)
        has_fv_organism_part = len(set(organism_parts)) > 1
        has_factor_value = bool(factor_value)

        columns = self._build_column_order(
            has_cell_type=has_cell_type,
            has_cell_line=has_cell_line,
            max_mods=max_mods,
            has_prec_tol=has_prec_tol,
            has_frag_tol=has_frag_tol,
            has_reduction=has_reduction,
            has_alkylation=has_alkylation,
            has_ms2_analyzer=has_ms2_analyzer,
            has_scan_range=has_scan_range,
            has_collision_energy=has_collision_energy,
            has_treatment=has_treatment,
            has_enrichment=has_enrichment,
            has_fv_organism_part=has_fv_organism_part,
            has_factor_value=has_factor_value,
            max_labels=max_labels,
        )

        rows: list[dict] = []
        sample_index = 0
        channel_rows = [(i, pf, ch) for i, pf in enumerate(per_file) for ch in pf["channels"]]
        for i, pf, channel in channel_rows:
            sample_index += 1
            row: dict[str, str] = {}
            row["source name"] = f"{self.pxd_id}-Sample-{sample_index}"
            row["characteristics[organism]"] = organism
            row["characteristics[organism part]"] = organism_part
            row["characteristics[disease]"] = disease
            if has_cell_type:
                row["characteristics[cell type]"] = cell_type or "not available"
            if has_cell_line:
                row["characteristics[cell line]"] = cell_line or "not available"
                row["characteristics[cellosaurus accession]"] = "not available"
            row["characteristics[biological replicate]"] = biological_replicate
            row["characteristics[sex]"] = sex
            row["characteristics[age]"] = age
            if has_treatment:
                row["characteristics[treatment]"] = pf["treatment"] or "not available"
            if has_enrichment:
                row["characteristics[enrichment process]"] = pf["enrichment"] or "not available"
            row["assay name"] = f"run {i + 1}"
            row["technology type"] = "proteomic profiling by mass spectrometry"
            row["comment[proteomics data acquisition method]"] = pf["acq"]
            for j in range(max(1, max_labels)):
                row[f"comment[label]#{j}"] = channel[j] if j < len(channel) else "not applicable"
            row["comment[instrument]"] = pf["instrument"]
            row["comment[cleavage agent details]"] = cleavage_agent
            row["comment[fraction identifier]"] = fraction_identifier
            row["comment[technical replicate]"] = technical_replicate
            row["comment[dissociation method]"] = pf["dissociation"]
            for j, mod_str in enumerate(pf["mods"]):
                row[f"comment[modification parameters]#{j}"] = mod_str
            # fill any unused mod slots with "not applicable"
            for j in range(len(pf["mods"]), max_mods):
                row[f"comment[modification parameters]#{j}"] = "not applicable"
            if has_prec_tol:
                row["comment[precursor mass tolerance]"] = pf["precursor_tolerance"] or "not available"
            if has_frag_tol:
                row["comment[fragment mass tolerance]"] = pf["fragment_tolerance"] or "not available"
            if has_reduction:
                row["comment[reduction reagent]"] = reduction_reagent or "not available"
            if has_alkylation:
                row["comment[alkylation reagent]"] = alkylation_reagent or "not available"
            if has_ms2_analyzer:
                row["comment[ms2 mass analyzer]"] = pf["ms2_analyzer"] or "not available"
            if has_scan_range:
                row["comment[ms1 scan range]"] = scan_range or "not available"
            if has_collision_energy:
                row["comment[collision energy]"] = collision_energy or "not available"
            row["comment[data file]"] = pf["raw_file"]
            row["comment[sdrf version]"] = "v1.1.0"
            row["comment[sdrf annotation tool]"] = f"HAMLET-agentic {HAMLET_VERSION}"
            row["factor value[disease]"] = disease
            if has_fv_organism_part:
                row["factor value[organism part]"] = organism_part
            if has_factor_value:
                row["factor value[experimental design]"] = factor_value or "not available"
            rows.append(row)

        return columns, rows

    # ------------------------------------------------------------------ #
    # Output
    # ------------------------------------------------------------------ #

    def to_sdrf(self, output_path: Path) -> None:
        """Write SDRF-Proteomics v1.1.0 TSV to output_path."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        columns, rows = self.build_rows()

        headers = [flatten_internal_header(column) for column in columns]

        with open(output_path, "w", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(headers)
            for row in rows:
                writer.writerow([row.get(col, "not available") for col in columns])

        print(f"SDRF written: {output_path}  ({len(rows)} sample rows × {len(headers)} columns)")

    def _resolution_for(self, field: str, raw_stem: str):
        """Return the normalized resolution object for a rendered field."""
        if field in {"organism", "organism_part", "disease", "cell_type", "cell_line", "sex", "age"}:
            return resolve_field(field, self._sample_evidence)
        if field in {"biological_replicate", "technical_replicate", "fraction_identifier", "factor_value"}:
            return resolve_field(field, self._experiment_evidence)
        if field in {"instrument", "acquisition", "dissociation", "label", "ms2_analyzer"}:
            evidence = self._technical_evidence_for_file(raw_stem)
            precedence = source_precedence_for(field)
            return resolve_field(field, evidence, **({"source_precedence": precedence} if precedence else {}))
        return None

    def _provenance_for(self, field: str, raw_stem: str) -> tuple[FieldEvidence | None, str, str]:
        """Return selected evidence and state for fields already on the new path."""
        resolved = self._resolution_for(field, raw_stem)
        if resolved:
            return resolved.selected, resolved.resolution_rule, resolved.assessment_state
        return None, "legacy_derivation", "derived"

    def to_confidence_sidecar(self, output_path: Path) -> None:
        """Write provenance without adding non-standard columns to the SDRF."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        columns, rows = self.build_rows()
        headers = [flatten_internal_header(column) for column in columns]
        judge_by_field = {record.field: record for record in self._judge_evidence}
        sidecar_headers = [
            "sdrf row", "source name", "logical field", "sdrf header", "selected value",
            "selected source", "evidence", "agent status", "agent confidence", "judge verdict",
            "judge hallucination", "judge type mismatch", "judge corrected value", "resolution rule",
            "assessment state", "source records",
        ]

        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=sidecar_headers, delimiter="\t")
            writer.writeheader()
            for row_index, row in enumerate(rows, start=1):
                raw_stem = Path(row.get("comment[data file]", "")).stem
                for column, header in zip(columns, headers):
                    rule = rule_for_header(header)
                    value = row.get(column, "")
                    if not rule or value in {"", "not available", "not applicable"}:
                        continue
                    modification_records: tuple[ModificationEvidence, ...] = ()
                    if rule.field == "modification":
                        modification_records = self._modification_provenance(raw_stem, value)
                        selected = None
                        resolution_rule = "normalized_source_union"
                        assessment_state = "derived"
                        source_records = [
                            {
                                "source": record.source,
                                "scope": record.scope,
                                "source_path": record.source_path,
                                "source_value": record.source_value,
                                "raw_stem": record.raw_stem,
                                "fraction_modified": record.fraction_modified,
                            }
                            for record in modification_records
                        ]
                    else:
                        selected, resolution_rule, assessment_state = self._provenance_for(rule.field, raw_stem)
                        resolved = self._resolution_for(rule.field, raw_stem)
                        source_records = [
                            {
                                "source": record.source,
                                "scope": record.scope,
                                "value": record.value,
                                "cv_accession": record.cv_accession,
                                "cv_name": record.cv_name,
                                "metadata": record.metadata,
                            }
                            for record in resolved.candidates
                        ] if resolved else []
                    judge = judge_by_field.get(rule.field)
                    writer.writerow({
                        "sdrf row": row_index,
                        "source name": row.get("source name", ""),
                        "logical field": rule.field,
                        "sdrf header": header,
                        "selected value": value,
                        "selected source": ";".join(dict.fromkeys(record.source for record in modification_records)) if modification_records else selected.source if selected else "derived",
                        "evidence": " | ".join(record.source_value for record in modification_records) if modification_records else selected.evidence if selected else "",
                        "agent status": selected.agent_status if selected and selected.agent_status else "",
                        "agent confidence": selected.agent_confidence if selected and selected.agent_confidence is not None else "",
                        "judge verdict": judge.judge_verdict if judge and judge.judge_verdict else "",
                        "judge hallucination": judge.judge_hallucination if judge and judge.judge_hallucination is not None else "",
                        "judge type mismatch": judge.judge_type_mismatch if judge and judge.judge_type_mismatch is not None else "",
                        "judge corrected value": judge.judge_corrected_value if judge and judge.judge_corrected_value else "",
                        "resolution rule": resolution_rule,
                        "assessment state": assessment_state,
                        "source records": json.dumps(source_records, sort_keys=True),
                    })

        print(f"SDRF confidence sidecar written: {output_path}")
