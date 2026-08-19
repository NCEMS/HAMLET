#!/usr/bin/env python3
"""
sdrf_builder.py — Convert agentic metadata JSONs + aggregated_results.json to
SDRF-Proteomics v1.1.0 TSV.

Usage (via run_agentic_metadata.py):
    builder = AgenticToSDRF(tech_json, bio_json, exp_json, aggregated_json)
    builder.to_sdrf(output_path)
"""

import csv
import json
import re
from pathlib import Path

from sdrf_adapters import agentic_evidence, judge_evidence
from sdrf_evidence import FieldEvidence
from sdrf_resolution import resolve_field
from sdrf_schema import flatten_internal_header, render_columns, rule_for_header, source_precedence_for
from sdrf_protocol import parse_alkylation_reagent, parse_cleavage_agent, parse_collision_energy, parse_mass_tolerances, parse_reduction_reagent, parse_scan_range
from sdrf_modifications import parse_protocol_modifications


class AgenticToSDRF:
    """
    Convert 3 agentic enriched JSONs + aggregated_results.json into an
    SDRF-Proteomics v1.1.0 TSV file.  One row is written per .raw data file.

    Priority order for every field:
        Agentic JSON (resolved field)
        → runAssessor / modification_site_fractions / organism_identification
            → pride_metadata.project
                → llm_extracted_metadata
                    → "not available"
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
        "hr hcd": "NT=beam-type collision-induced dissociation;AC=MS:1000422",
        "hr_hcd": "NT=beam-type collision-induced dissociation;AC=MS:1000422",
        "cid": "NT=collision-induced dissociation;AC=MS:1000133",
        "lr_it_cid": "NT=collision-induced dissociation;AC=MS:1000133",
        "hr_it_cid": "NT=collision-induced dissociation;AC=MS:1000133",
        "etd": "NT=electron transfer dissociation;AC=MS:1001356",
        "hr_it_etd": "NT=electron transfer dissociation;AC=MS:1001356",
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

    # Ordered: more specific patterns first
    _CLEAVAGE_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"chymotrypsin", re.I), "NT=Chymotrypsin;AC=MS:1001306"),
        (re.compile(r"lys[\s\-]?c\b", re.I), "NT=Lys-C;AC=MS:1001309"),
        (re.compile(r"asp[\s\-]?n\b", re.I), "NT=Asp-N;AC=MS:1001303"),
        (re.compile(r"glu[\s\-]?c\b", re.I), "NT=Glu-C;AC=MS:1001917"),
        (re.compile(r"trypsin", re.I), "NT=Trypsin;AC=MS:1001251"),
    ]

    # Canonical names and residues for known UNIMOD IDs
    _UNIMOD_NAME: dict[int, str] = {
        1: "Acetyl",
        4: "Carbamidomethyl",
        5: "Carbamyl",
        7: "Deamidation",
        21: "Phospho",
        35: "Oxidation",
        36: "Dimethyl",
        730: "TMT6plex",
        737: "TMTpro",
    }
    _UNIMOD_RESIDUES: dict[int, str] = {
        1: "K",
        4: "C",
        5: "K",
        7: "NQ",
        21: "STY",
        35: "M",
        36: "KR",
        730: "K",
        737: "K",
    }

    # Instrument model → MS2 analyzer
    _ANALYZER_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"q\s*exactive|exploris|orbitrap|fusion|eclipse|astral|tribrid", re.I), "orbitrap"),
        (re.compile(r"timstof|qtof|tripletoF|synapt|xevo|impact|maXis", re.I), "TOF"),
        (re.compile(r"\bvelos\b|\belite\b|\bltq\b|ion\s*trap", re.I), "ion trap"),
        (re.compile(r"tsq|triple\s*quadrupole", re.I), "quadrupole"),
    ]

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #

    def __init__(
        self,
        tech_json: Path,
        bio_json: Path,
        exp_json: Path,
        aggregated_json: Path,
        overrides: dict | None = None,
        judge_document: dict | None = None,
    ) -> None:
        self.tech_json = Path(tech_json)
        self.bio_json = Path(bio_json)
        self.exp_json = Path(exp_json)
        self.aggregated_json = Path(aggregated_json)
        self._overrides = overrides or {}
        self._judge_document = judge_document or {}
        self._load_agentic_jsons()
        self._load_aggregated()
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

    def _load_aggregated(self) -> None:
        with open(self.aggregated_json) as f:
            agg: dict = json.load(f)

        self.pxd_id: str = agg.get("pxd_id", "")

        ra = agg.get("runAssessor") or {}
        self._ra_files: dict = ra.get("files", {})          # mzml_path → file data
        self._ra_search: dict = ra.get("search_criteria", {})
        self._ra_knowledge: dict = ra.get("knowledge", {})

        oi = agg.get("organism_identification") or {}
        self._oi_results: list = oi.get("results", [])

        msf = agg.get("modification_site_fractions") or {}
        dda_msf = msf.get("dda_closed_search") or {}
        self._mods_per_stem: dict = dda_msf.get("per_sample_files", {})   # stem → {data:[...]}

        # sage quantification method
        sage = agg.get("sage_results") or {}
        p2 = sage.get("pass2_closed_search") or {} if isinstance(sage, dict) else {}
        self._quant_method: str = (
            p2.get("quantification", {}).get("method", "")
            if isinstance(p2, dict) else ""
        )

        pride_metadata = agg.get("pride_metadata") or {}
        pride_proj = pride_metadata.get("project") or {}
        self._sample_proc: str = pride_proj.get("sampleProcessingProtocol", "")
        self._data_proc: str = pride_proj.get("dataProcessingProtocol", "")
        self._pride_organisms: list = pride_proj.get("organisms", [])
        self._pride_sample_attrs: list = pride_proj.get("sampleAttributes", [])
        self._pride_diseases: list = pride_proj.get("diseases", [])
        self._pub_date: str = pride_proj.get("publicationDate", "")
        self._pride_raw_files: list[str] = [
            file_name
            for file_record in pride_metadata.get("files", [])
            if isinstance(file_record, dict)
            for file_name in [str(file_record.get("fileName") or "").strip()]
            if file_name.lower().endswith(".raw")
        ]

        self._llm_meta: dict = agg.get("llm_extracted_metadata") or {}   # raw_file → metadata

        # stem → mzML path index
        self._stem_to_mzml: dict[str, str] = {
            Path(p).stem: p for p in self._ra_files
        }

    def _build_sample_evidence(self) -> tuple[FieldEvidence, ...]:
        """Normalize biological-agent and PRIDE sample facts for resolution."""
        records = list(agentic_evidence(
            self._bio,
            source="biological_agent",
            scope="sample",
            field_aliases={
                "species": "organism",
                "tissue": "organism_part",
                "organ": "organism_part",
                "disease_state": "disease",
            },
        ))
        for organism in self._pride_organisms:
            name = str(organism.get("name") or "").strip()
            if name:
                records.append(FieldEvidence("organism", name, "pride", "sample"))
        for disease in self._pride_diseases:
            name = str(disease.get("name") or "").strip()
            if name:
                records.append(FieldEvidence("disease", name, "pride", "sample"))
        for attribute in self._pride_sample_attrs:
            key_name = str(attribute.get("key", {}).get("name") or "").lower()
            if "organism part" not in key_name:
                continue
            for value in attribute.get("value", []):
                name = str(value.get("name") or "").strip()
                if name:
                    records.append(FieldEvidence("organism_part", name, "pride", "sample"))
        return tuple(records)

    def _resolve_sample_field(self, field: str, fallback: str | None = None) -> str | None:
        resolved = resolve_field(field, self._sample_evidence, fallback=fallback or "not available")
        return None if resolved.value == "not available" and fallback is None else resolved.value

    def _build_experiment_evidence(self) -> tuple[FieldEvidence, ...]:
        """Normalize experimental-design values before renderer-specific checks."""
        structured_fields = {
            "number_of_biological_replicates",
            "number_of_technical_replicates",
            "number_of_fractions",
            "factor_value",
        }
        return agentic_evidence(
            {key: value for key, value in self._exp.items() if key in structured_fields},
            source="experimental_design_agent",
            scope="study",
            field_aliases={
                "number_of_biological_replicates": "biological_replicate",
                "number_of_technical_replicates": "technical_replicate",
                "number_of_fractions": "fraction_identifier",
            },
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

    def _get_raw_files(self) -> list[str]:
        """Return ordered, de-duplicated .raw basenames from all inventories."""
        candidates = [
            *self._llm_meta.keys(),
            *(Path(path).stem + ".raw" for path in self._ra_files),
            *self._pride_raw_files,
        ]
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
        if override and override.lower() in ("male", "female", "intersex"):
            return override.lower()
        val = self._resolve_sample_field("sex")
        if val and val.lower() in ("male", "female", "intersex"):
            return val.lower()
        return "not available"

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
        override = self._override_field("biological_replicate")
        if override and override.isdigit():
            return override
        val = self._resolve_experiment_field("biological_replicate")
        if val and val.isdigit():
            return val
        return "1"

    def _get_technical_replicate(self) -> str:
        override = self._override_field("technical_replicate")
        if override and override.isdigit():
            return override
        val = self._resolve_experiment_field("technical_replicate")
        if val and val.isdigit():
            return val
        return "1"

    def _get_fraction_identifier(self) -> str:
        override = self._override_field("fraction_identifier")
        if override and override.isdigit():
            return override
        val = self._resolve_experiment_field("fraction_identifier")
        if val and val.isdigit():
            return val
        return "1"

    def _get_factor_value(self) -> str | None:
        return self._override_field("factor_value") or self._resolve_experiment_field("factor_value")

    # ------------------------------------------------------------------ #
    # Per-file data extractors
    # ------------------------------------------------------------------ #

    def _ra_file_data(self, raw_stem: str) -> dict:
        """Return the runAssessor file dict for the given stem, or {}."""
        mzml = self._stem_to_mzml.get(raw_stem)
        return self._ra_files.get(mzml, {}) if mzml else {}

    @staticmethod
    def _clean_fragmentation(value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if text.lower() in {"", "?", "??", "unknown", "not available", "n/a", "none", "null"}:
            return ""
        return text

    def _technical_evidence_for_file(self, raw_stem: str) -> tuple[FieldEvidence, ...]:
        """Normalize the existing per-file technical source precedence inputs."""
        file_data = self._ra_file_data(raw_stem)
        spectra_stats = file_data.get("spectra_stats", {})
        records: list[FieldEvidence] = []

        instrument = str(file_data.get("instrument_model", {}).get("name") or "").strip()
        if instrument:
            records.append(FieldEvidence("instrument", instrument, "runassessor", "assay"))
        agent_instrument = self._agentic_field(self._tech, "instrument")
        if agent_instrument:
            records.append(FieldEvidence("instrument", agent_instrument, "technical_agent", "assay"))
        knowledge_instrument = str(self._ra_knowledge.get("instrument_model") or "").strip()
        if knowledge_instrument:
            records.append(FieldEvidence("instrument", knowledge_instrument, "aggregate", "study"))

        acquisition = str(spectra_stats.get("acquisition_type") or "").strip()
        if acquisition:
            records.append(FieldEvidence("acquisition", acquisition, "runassessor", "assay"))
        search_acquisition = str(self._ra_search.get("acquisition_type") or "").strip()
        if search_acquisition:
            records.append(FieldEvidence("acquisition", search_acquisition, "aggregate", "study"))

        label = str(file_data.get("summary", {}).get("labeling", {}).get("call") or "").strip()
        if label:
            records.append(FieldEvidence("label", label, "runassessor", "assay"))
        agent_label = self._agentic_field(self._tech, "labeling")
        if agent_label:
            records.append(FieldEvidence("label", agent_label, "technical_agent", "study"))
        search_label = str(self._ra_search.get("labeling") or "").strip()
        if search_label:
            records.append(FieldEvidence("label", search_label, "aggregate", "study"))
        if self._quant_method:
            records.append(FieldEvidence("label", self._quant_method, "aggregate", "study"))

        for value, source, scope in (
            (spectra_stats.get("fragmentation_tag"), "runassessor", "assay"),
            (spectra_stats.get("fragmentation_type"), "runassessor", "assay"),
            (self._agentic_field(self._tech, "fragmentation"), "technical_agent", "assay"),
            (self._ra_search.get("fragmentation_type"), "aggregate", "study"),
        ):
            cleaned = self._clean_fragmentation(value)
            if cleaned:
                records.append(FieldEvidence("dissociation", cleaned, source, scope))
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
        name = self._get_instrument_name(raw_stem)
        if name == "not available":
            return name
        # the enrichment step already resolved an MS accession for this model,
        # so pair it with the name instead of writing the bare string.
        meti_value, accession = self._meti_accession("instrument")
        if accession and meti_value.strip().lower() == name.strip().lower():
            return f"NT={name};AC={accession}"
        return name

    def _get_acquisition_method(self, raw_stem: str) -> str:
        raw = self._resolve_technical_field("acquisition", self._technical_evidence_for_file(raw_stem)) or ""
        return self._map_acquisition(raw)

    def _raw_label(self, raw_stem: str) -> str:
        return self._resolve_technical_field("label", self._technical_evidence_for_file(raw_stem)) or ""

    @staticmethod
    def _label_scheme_key(raw_label: str) -> str:
        """Normalize recognized channel scheme names without changing label values."""
        normalized = raw_label.lower().strip().replace("-", "").replace(" ", "")
        # A mixed study-level description such as "SILAC, label-free" still
        # establishes SILAC assay channels. The paired channels come from the
        # explicit SDRF mapping, not from inferred label chemistry.
        if "silac" in normalized:
            return "silac"
        # TechnicalAgent can spell out the labeling chemistry rather than use
        # the compact TMT10plex scheme name emitted by RunAssessor.
        if "tmt" in normalized and "10plex" in normalized:
            return "tmt10plex"
        return normalized

    def _get_label(self, raw_stem: str) -> str:
        raw_label = self._raw_label(raw_stem)
        scheme = self._label_scheme_key(raw_label)
        return self._map_label("silac" if scheme == "silac" else raw_label)

    def _has_silac_modification(self, raw_stem: str) -> bool:
        """Require observed per-file SILAC evidence before expanding channels."""
        for modification in self._mods_per_stem.get(raw_stem, {}).get("data", []):
            unimod_id = modification.get("unimod_id")
            modification_name = str(modification.get("mod_name") or "")
            if unimod_id in {259, 267} or "silac" in modification_name.lower():
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
        value = parse_cleavage_agent(override or "", self._sample_proc + " " + self._data_proc, self._tech_text("cleavage_agent"))
        return value or "not available"

    def _get_reduction_reagent(self) -> str | None:
        return parse_reduction_reagent(self._sample_proc, self._tech_text("reduction_reagent"))

    def _get_alkylation_reagent(self) -> str | None:
        return parse_alkylation_reagent(self._sample_proc, self._tech_text("alkylation_reagent"))

    def _get_mass_tolerances(self) -> tuple[str | None, str | None]:
        return parse_mass_tolerances(self._ra_search, self._data_proc + " " + self._sample_proc)

    def _get_scan_range(self) -> str | None:
        return parse_scan_range(self._sample_proc)

    def _get_collision_energy(self) -> str | None:
        return parse_collision_energy(self._sample_proc)

    def _get_ms2_analyzer(self, instrument: str) -> str | None:
        for pattern, analyzer in self._ANALYZER_PATTERNS:
            if pattern.search(instrument):
                return analyzer
        return None

    # ------------------------------------------------------------------ #
    # Modification parameters
    # ------------------------------------------------------------------ #

    def _parse_protocol_mods(self) -> list[dict]:
        text = " ".join([
            self._data_proc,
            self._sample_proc,
            self._tech_text("alkylation_reagent"),
            self._tech_text("ptm"),
            self._tech_text("modification"),
        ])
        return parse_protocol_modifications(text, self._get_alkylation_reagent())

    def _get_modification_params(self, raw_stem: str) -> list[str]:
        """
        Return list of SDRF-formatted modification parameter strings for the
        given file stem.  Protocol mods are primary; additional detected mods
        (fraction >= 0.05) supplement them.
        """
        proto_mods = self._parse_protocol_mods()
        proto_uids = {m["uid"] for m in proto_mods}

        result = []
        for m in proto_mods:
            result.append(
                f"NT={m['name']};AC=UNIMOD:{m['uid']};MT={m['mod_type']};TA={m['residues']}"
            )

        # supplement with fractions-based mods not in protocol
        alk = self._get_alkylation_reagent()
        for mod in self._mods_per_stem.get(raw_stem, {}).get("data", []):
            uid = mod.get("unimod_id")
            if uid is None or uid in proto_uids:
                continue
            frac = mod.get("fraction_modified") or 0.0
            if frac < 0.05:
                continue
            name = self._UNIMOD_NAME.get(uid, mod.get("mod_name", f"UNIMOD:{uid}"))
            # canonical residues if known, else first char of allowed_residues
            residues = mod.get("allowed_residues", "X")
            ta = self._UNIMOD_RESIDUES.get(uid, residues[:1] if residues else "X")
            # determine Fixed vs Variable
            mod_type = "Variable"
            if uid == 4 and alk:
                mod_type = "Fixed"
                ta = "C"
            result.append(f"NT={name};AC=UNIMOD:{uid};MT={mod_type};TA={ta}")
            proto_uids.add(uid)

        return result

    # ------------------------------------------------------------------ #
    # LLM-extracted per-file fields
    # ------------------------------------------------------------------ #

    def _get_treatment(self, raw_file: str) -> str | None:
        vals = self._llm_meta.get(raw_file, {}).get("FactorValue[Experimental]", [])
        if vals and isinstance(vals, list):
            v = vals[0].strip()
            if 0 < len(v) <= 200:
                return v
        return None

    def _get_enrichment_process(self, raw_file: str) -> str | None:
        vals = self._llm_meta.get(raw_file, {}).get("Comment[EnrichmentMethod]", [])
        if vals and isinstance(vals, list):
            v = vals[0].strip()
            # only use if short enough to be a CV-style term
            if 0 < len(v) <= 100:
                return v
        return None

    # ------------------------------------------------------------------ #
    # CV mappers
    # ------------------------------------------------------------------ #

    @classmethod
    def _map_acquisition(cls, raw: str) -> str:
        return cls._ACQUISITION_MAP.get(raw.lower().strip(), "not available")

    @classmethod
    def _map_dissociation(cls, raw: str) -> str:
        return cls._DISSOCIATION_MAP.get(raw.lower().strip(), "not available")

    @classmethod
    def _map_label(cls, raw: str) -> str:
        return cls._LABEL_MAP.get(raw.lower().strip(), "not available")

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
        prec_tol, frag_tol = self._get_mass_tolerances()
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
                "ms2_analyzer": self._get_ms2_analyzer(self._get_instrument_name(stem)),
                "mods": self._get_modification_params(stem),
                "treatment": self._get_treatment(raw_file),
                "enrichment": self._get_enrichment_process(raw_file),
            })

        # --- optional column flags ---
        max_mods = max((len(pf["mods"]) for pf in per_file), default=0)
        max_labels = max((len(ch) for pf in per_file for ch in pf["channels"]), default=1)
        has_cell_type = bool(cell_type)
        has_cell_line = bool(cell_line)
        has_prec_tol = bool(prec_tol)
        has_frag_tol = bool(frag_tol)
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
                row["comment[precursor mass tolerance]"] = prec_tol or "not available"
            if has_frag_tol:
                row["comment[fragment mass tolerance]"] = frag_tol or "not available"
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
            row["comment[sdrf annotation tool]"] = "HAMLET-agentic v0.1.0"
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

    def _provenance_for(self, field: str, raw_stem: str) -> tuple[FieldEvidence | None, str, str]:
        """Return selected evidence and state for fields already on the new path."""
        if field in {"organism", "organism_part", "disease", "cell_type", "cell_line", "sex", "age"}:
            resolved = resolve_field(field, self._sample_evidence)
            return resolved.selected, resolved.resolution_rule, resolved.assessment_state
        if field in {"biological_replicate", "technical_replicate", "fraction_identifier", "factor_value"}:
            resolved = resolve_field(field, self._experiment_evidence)
            return resolved.selected, resolved.resolution_rule, resolved.assessment_state
        if field in {"instrument", "acquisition", "dissociation", "label"}:
            evidence = self._technical_evidence_for_file(raw_stem)
            precedence = source_precedence_for(field)
            resolved = resolve_field(field, evidence, **({"source_precedence": precedence} if precedence else {}))
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
            "assessment state",
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
                    selected, resolution_rule, assessment_state = self._provenance_for(rule.field, raw_stem)
                    judge = judge_by_field.get(rule.field)
                    writer.writerow({
                        "sdrf row": row_index,
                        "source name": row.get("source name", ""),
                        "logical field": rule.field,
                        "sdrf header": header,
                        "selected value": value,
                        "selected source": selected.source if selected else "derived",
                        "evidence": selected.evidence if selected else "",
                        "agent status": selected.agent_status if selected and selected.agent_status else "",
                        "agent confidence": selected.agent_confidence if selected and selected.agent_confidence is not None else "",
                        "judge verdict": judge.judge_verdict if judge and judge.judge_verdict else "",
                        "judge hallucination": judge.judge_hallucination if judge and judge.judge_hallucination is not None else "",
                        "judge type mismatch": judge.judge_type_mismatch if judge and judge.judge_type_mismatch is not None else "",
                        "judge corrected value": judge.judge_corrected_value if judge and judge.judge_corrected_value else "",
                        "resolution rule": resolution_rule,
                        "assessment state": assessment_state,
                    })

        print(f"SDRF confidence sidecar written: {output_path}")
