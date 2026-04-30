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

    _ACQUISITION_MAP: dict[str, str] = {
        "dda": "data-dependent acquisition",
        "dia": "data-independent acquisition",
        "prm": "parallel reaction monitoring",
        "srm": "selected reaction monitoring",
        "targeted": "parallel reaction monitoring",
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
    ) -> None:
        self.tech_json = Path(tech_json)
        self.bio_json = Path(bio_json)
        self.exp_json = Path(exp_json)
        self.aggregated_json = Path(aggregated_json)
        self._load_agentic_jsons()
        self._load_aggregated()

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

        ra = agg.get("runAssessor", {})
        self._ra_files: dict = ra.get("files", {})          # mzml_path → file data
        self._ra_search: dict = ra.get("search_criteria", {})
        self._ra_knowledge: dict = ra.get("knowledge", {})

        oi = agg.get("organism_identification", {})
        self._oi_results: list = oi.get("results", [])

        msf = agg.get("modification_site_fractions", {})
        dda_msf = msf.get("dda_closed_search", {})
        self._mods_per_stem: dict = dda_msf.get("per_sample_files", {})   # stem → {data:[...]}

        # sage quantification method
        sage = agg.get("sage_results", {})
        p2 = sage.get("pass2_closed_search", {}) if isinstance(sage, dict) else {}
        self._quant_method: str = (
            p2.get("quantification", {}).get("method", "")
            if isinstance(p2, dict) else ""
        )

        pride_proj = agg.get("pride_metadata", {}).get("project", {})
        self._sample_proc: str = pride_proj.get("sampleProcessingProtocol", "")
        self._data_proc: str = pride_proj.get("dataProcessingProtocol", "")
        self._pride_organisms: list = pride_proj.get("organisms", [])
        self._pride_sample_attrs: list = pride_proj.get("sampleAttributes", [])
        self._pride_diseases: list = pride_proj.get("diseases", [])
        self._pub_date: str = pride_proj.get("publicationDate", "")

        self._llm_meta: dict = agg.get("llm_extracted_metadata", {})   # raw_file → metadata

        # stem → mzML path index
        self._stem_to_mzml: dict[str, str] = {
            Path(p).stem: p for p in self._ra_files
        }

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

    def _get_raw_files(self) -> list[str]:
        """Return ordered list of .raw basenames."""
        if self._llm_meta:
            return list(self._llm_meta.keys())
        # fallback from runAssessor mzML paths
        return [Path(p).stem + ".raw" for p in self._ra_files]

    # ------------------------------------------------------------------ #
    # Sample characteristics extractors
    # ------------------------------------------------------------------ #

    def _get_organism(self) -> str:
        for field in ("species", "organism"):
            val = self._agentic_field(self._bio, field)
            if val:
                return val.lower()
        if self._pride_organisms:
            name = self._pride_organisms[0].get("name", "")
            name = re.sub(r"\s*\([^)]+\)", "", name).strip()
            if name:
                return name.lower()
        return "not available"

    def _get_organism_part(self) -> str:
        for field in ("tissue", "organ"):
            val = self._agentic_field(self._bio, field)
            if val:
                return val.lower()
        for attr in self._pride_sample_attrs:
            key_name = attr.get("key", {}).get("name", "").lower()
            if "organism part" in key_name:
                vals = attr.get("value", [])
                if vals:
                    return vals[0].get("name", "").lower()
        return "not available"

    def _get_disease(self) -> str:
        for field in ("disease_state", "disease"):
            val = self._agentic_field(self._bio, field)
            if val:
                return val.lower()
        if self._pride_diseases:
            return self._pride_diseases[0].get("name", "not available").lower()
        return "not available"

    def _get_cell_type(self) -> str | None:
        return self._agentic_field(self._bio, "cell_type")

    def _get_cell_line(self) -> str | None:
        return self._agentic_field(self._bio, "cell_line")

    def _get_sex(self) -> str:
        val = self._agentic_field(self._bio, "sex")
        if val and val.lower() in ("male", "female", "intersex"):
            return val.lower()
        return "not available"

    def _get_age(self) -> str:
        val = self._agentic_field(self._bio, "age")
        return val if val else "not available"

    # ------------------------------------------------------------------ #
    # Per-file data extractors
    # ------------------------------------------------------------------ #

    def _ra_file_data(self, raw_stem: str) -> dict:
        """Return the runAssessor file dict for the given stem, or {}."""
        mzml = self._stem_to_mzml.get(raw_stem)
        return self._ra_files.get(mzml, {}) if mzml else {}

    def _get_instrument(self, raw_stem: str) -> str:
        fd = self._ra_file_data(raw_stem)
        name = fd.get("instrument_model", {}).get("name")
        if name:
            return name
        val = self._agentic_field(self._tech, "instrument")
        if val:
            return val
        km = self._ra_knowledge.get("instrument_model")
        return str(km) if km else "not available"

    def _get_acquisition_method(self, raw_stem: str) -> str:
        fd = self._ra_file_data(raw_stem)
        raw = fd.get("spectra_stats", {}).get("acquisition_type") or self._ra_search.get("acquisition_type", "")
        return self._map_acquisition(raw)

    def _get_label(self, raw_stem: str) -> str:
        fd = self._ra_file_data(raw_stem)
        raw = (
            fd.get("summary", {}).get("labeling", {}).get("call")
            or self._ra_search.get("labeling")
            or self._quant_method
            or ""
        )
        return self._map_label(raw)

    def _get_dissociation_method(self, raw_stem: str) -> str:
        fd = self._ra_file_data(raw_stem)
        raw = (
            fd.get("spectra_stats", {}).get("fragmentation_tag")
            or self._agentic_field(self._tech, "fragmentation")
            or self._ra_search.get("fragmentation_type")
            or ""
        )
        return self._map_dissociation(raw)

    # ------------------------------------------------------------------ #
    # Experiment-level extractors (parsed from protocol text)
    # ------------------------------------------------------------------ #

    def _get_cleavage_agent(self) -> str:
        text = self._sample_proc + " " + self._data_proc
        for pattern, sdrf_val in self._CLEAVAGE_PATTERNS:
            if pattern.search(text):
                return sdrf_val
        return "not available"

    def _get_reduction_reagent(self) -> str | None:
        t = self._sample_proc
        if re.search(r"dithiothreitol|\bDTT\b", t, re.I):
            return "dithiothreitol"
        if re.search(r"\bTCEP\b|tris\(2-carboxyethyl\)phosphine", t, re.I):
            return "tris(2-carboxyethyl)phosphine"
        if re.search(r"beta-mercaptoethanol|\b2-ME\b|\bBME\b", t, re.I):
            return "beta-mercaptoethanol"
        return None

    def _get_alkylation_reagent(self) -> str | None:
        t = self._sample_proc
        if re.search(r"iodoacetamide|\bIAA\b", t, re.I):
            return "iodoacetamide"
        if re.search(r"chloroacetamide|\bCAA\b|2-chloroacetamide", t, re.I):
            return "chloroacetamide"
        if re.search(r"N-ethylmaleimide|\bNEM\b", t, re.I):
            return "N-ethylmaleimide"
        return None

    def _get_mass_tolerances(self) -> tuple[str | None, str | None]:
        text = self._data_proc + " " + self._sample_proc
        prec = frag = None
        m = re.search(r"precursor[^.]{0,80}?(\d+(?:\.\d+)?)\s*(ppm|Da|mmu)", text, re.I)
        if m:
            prec = f"{m.group(1)} {m.group(2)}"
        m2 = re.search(r"fragment[^.]{0,80}?(\d+(?:\.\d+)?)\s*(ppm|Da|mmu)", text, re.I)
        if m2:
            frag = f"{m2.group(1)} {m2.group(2)}"
        return prec, frag

    def _get_scan_range(self) -> str | None:
        # Normalize soft hyphens (U+00AD) and en-dashes to ASCII hyphen
        t = self._sample_proc.replace("\xad", "-").replace("\u2013", "-")
        # with separator: "350-1600 m/z" or "350–1600"
        m = re.search(r"(\d{3,4})\s*[-to]+\s*(\d{3,4})\s*m/?z", t, re.I)
        if m:
            return f"{m.group(1)}m/z-{m.group(2)}m/z"
        m = re.search(r"m/?z\s*(?:range\s*of\s*)?(\d{3,4})\s*[-to]+\s*(\d{3,4})", t, re.I)
        if m:
            return f"{m.group(1)}m/z-{m.group(2)}m/z"
        # dash-less concatenation e.g. "3501600" after "m/z range of"
        m = re.search(r"m/?z\s*(?:range\s*of\s*)?(\d{7,8})\b", t, re.I)
        if m:
            s = m.group(1)
            if len(s) == 7:       # e.g. 3501600 → 350 + 1600
                return f"{s[:3]}m/z-{s[3:]}m/z"
            if len(s) == 8:       # e.g. 35016000 → 350 + 16000 (rare)
                return f"{s[:4]}m/z-{s[4:]}m/z"
        return None

    def _get_collision_energy(self) -> str | None:
        t = self._sample_proc
        m = re.search(r"\bNCE\)?[\s]*(?:of\s+)?(\d+(?:\.\d+)?)%?", t, re.I)
        if m:
            return f"{m.group(1)} NCE"
        m = re.search(r"normalized collision energy[^)]*?(\d+(?:\.\d+)?)%", t, re.I)
        if m:
            return f"{m.group(1)} NCE"
        m = re.search(r"collision energy[^)]*?(\d+(?:\.\d+)?)\s*eV", t, re.I)
        if m:
            return f"{m.group(1)} eV"
        return None

    def _get_ms2_analyzer(self, instrument: str) -> str | None:
        for pattern, analyzer in self._ANALYZER_PATTERNS:
            if pattern.search(instrument):
                return analyzer
        return None

    # ------------------------------------------------------------------ #
    # Modification parameters
    # ------------------------------------------------------------------ #

    def _parse_protocol_mods(self) -> list[dict]:
        """
        Parse dataProcessingProtocol for explicit modification mentions.
        Returns list of dicts: {uid, name, residues, mod_type}.
        """
        text = self._data_proc + " " + self._sample_proc
        result: list[dict] = []
        seen: set[int] = set()

        def _add(uid: int, name: str, residues: str, mod_type: str) -> None:
            if uid not in seen:
                seen.add(uid)
                result.append({"uid": uid, "name": name, "residues": residues, "mod_type": mod_type})

        if re.search(r"carbamidomethyl", text, re.I):
            _add(4, "Carbamidomethyl", "C", "Fixed")
        if re.search(r"\bTMT\b|\bTMTpro\b", text, re.I):
            _add(730, "TMT6plex", "K", "Fixed")
        if re.search(r"\biTRAQ\b", text, re.I):
            _add(214, "iTRAQ4plex", "K", "Fixed")
        if re.search(r"oxidation", text, re.I):
            _add(35, "Oxidation", "M", "Variable")
        if re.search(r"\bacetyl\b.*\bn.?term|n.?term.*\bacetyl\b", text, re.I):
            _add(1, "Acetyl", "K", "Variable")
        if re.search(r"phospho(?:rylation)?", text, re.I):
            _add(21, "Phospho", "STY", "Variable")
        if re.search(r"deamid", text, re.I):
            _add(7, "Deamidation", "NQ", "Variable")
        if re.search(r"methylat", text, re.I):
            _add(34, "Methyl", "KR", "Variable")

        return result

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
    ) -> list[str]:
        cols: list[str] = [
            "source name",
            "characteristics[organism]",
            "characteristics[organism part]",
            "characteristics[disease]",
        ]
        if has_cell_type:
            cols.append("characteristics[cell type]")
        if has_cell_line:
            cols.append("characteristics[cell line]")
            cols.append("characteristics[cellosaurus accession]")
        cols += [
            "characteristics[biological replicate]",
            "characteristics[sex]",
            "characteristics[age]",
            "characteristics[individual]",
        ]
        if has_treatment:
            cols.append("characteristics[treatment]")
        if has_enrichment:
            cols.append("characteristics[enrichment process]")
        cols += [
            "assay name",
            "technology type",
            "comment[proteomics data acquisition method]",
            "comment[label]",
            "comment[instrument]",
            "comment[cleavage agent details]",
            "comment[fraction identifier]",
            "comment[technical replicate]",
            "comment[dissociation method]",
        ]
        # multi-cardinality: indexed internally, flattened to same header on write
        for j in range(max_mods):
            cols.append(f"comment[modification parameters]#{j}")
        if has_prec_tol:
            cols.append("comment[precursor mass tolerance]")
        if has_frag_tol:
            cols.append("comment[fragment mass tolerance]")
        if has_reduction:
            cols.append("comment[reduction reagent]")
        if has_alkylation:
            cols.append("comment[alkylation reagent]")
        if has_ms2_analyzer:
            cols.append("comment[ms2 mass analyzer]")
        if has_scan_range:
            cols.append("comment[ms1 scan range]")
        if has_collision_energy:
            cols.append("comment[collision energy]")
        cols += [
            "comment[data file]",
            "comment[sdrf version]",
            "comment[sdrf annotation tool]",
            "factor value[disease]",
        ]
        if has_fv_organism_part:
            cols.append("factor value[organism part]")
        return cols

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
                "dissociation": self._get_dissociation_method(stem),
                "ms2_analyzer": self._get_ms2_analyzer(instrument),
                "mods": self._get_modification_params(stem),
                "treatment": self._get_treatment(raw_file),
                "enrichment": self._get_enrichment_process(raw_file),
            })

        # --- optional column flags ---
        max_mods = max((len(pf["mods"]) for pf in per_file), default=0)
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
        )

        rows: list[dict] = []
        for i, pf in enumerate(per_file):
            row: dict[str, str] = {}
            row["source name"] = f"{self.pxd_id}-Sample-{i + 1}"
            row["characteristics[organism]"] = organism
            row["characteristics[organism part]"] = organism_part
            row["characteristics[disease]"] = disease
            if has_cell_type:
                row["characteristics[cell type]"] = cell_type or "not available"
            if has_cell_line:
                row["characteristics[cell line]"] = cell_line or "not available"
                row["characteristics[cellosaurus accession]"] = "not available"
            row["characteristics[biological replicate]"] = "1"
            row["characteristics[sex]"] = sex
            row["characteristics[age]"] = age
            row["characteristics[individual]"] = pf["stem"]
            if has_treatment:
                row["characteristics[treatment]"] = pf["treatment"] or "not available"
            if has_enrichment:
                row["characteristics[enrichment process]"] = pf["enrichment"] or "not available"
            row["assay name"] = f"run {i + 1}"
            row["technology type"] = "proteomic profiling by mass spectrometry"
            row["comment[proteomics data acquisition method]"] = pf["acq"]
            row["comment[label]"] = pf["label"]
            row["comment[instrument]"] = pf["instrument"]
            row["comment[cleavage agent details]"] = cleavage_agent
            row["comment[fraction identifier]"] = "1"
            row["comment[technical replicate]"] = "1"
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

        # Map internal #N-indexed mod-param keys → canonical SDRF header name
        def _header(col: str) -> str:
            if col.startswith("comment[modification parameters]#"):
                return "comment[modification parameters]"
            return col

        headers = [_header(c) for c in columns]

        with open(output_path, "w", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t")
            writer.writerow(headers)
            for row in rows:
                writer.writerow([row.get(col, "not available") for col in columns])

        print(f"SDRF written: {output_path}  ({len(rows)} sample rows × {len(headers)} columns)")
