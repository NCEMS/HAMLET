# SDRF Conversion Plan: `AgenticToSDRF`

> **Status**: Draft — for review before implementation  
> **SDRF spec version**: v1.1.0  
> **Reference**: https://sdrf.quantms.org/specification.html

---

## 1. Overview

`AgenticToSDRF` is a Python class that reads all available metadata for a single PXD
experiment and produces a valid SDRF-Proteomics v1.1.0 TSV file. It integrates four
distinct data sources and maps them onto SDRF columns. One SDRF row is written per
`.raw` data file.

---

## 2. File Organisation

A separate module is cleanest given the complexity:

```
src/python/
  run_agentic_metadata.py    # entrypoint — imports and calls AgenticToSDRF
  sdrf_builder.py            # new file — contains AgenticToSDRF class
```

`run_agentic_metadata.py` calls:
```python
from sdrf_builder import AgenticToSDRF

builder = AgenticToSDRF(
    tech_json=...,
    bio_json=...,
    exp_json=...,
    aggregated_json=...,
)
builder.to_sdrf(sdrf_output)
```

---

## 3. Input Data Sources

| # | Source | Scope | Access |
|---|--------|-------|--------|
| 1 | **TechnicalAgent enriched JSON** | Experiment-level | `integrated_output/TechnicalAgent/temp_0.0/{pxd}_PubText_enriched.json` |
| 2 | **BiologicalAgent enriched JSON** | Experiment-level | `integrated_output/BiologicalAgent/temp_0.0/{pxd}_PubText_enriched.json` |
| 3 | **ExperimentalDesignAgent enriched JSON** | Experiment-level | `integrated_output/ExperimentalDesignAgent/temp_0.0/{pxd}_PubText_enriched.json` |
| 4 | **`{pxd}_aggregated_results.json`** | Experiment + per-file | Passed as `--input` argument |

### 4a. Aggregated Results JSON — relevant sub-sections

| Section | Key fields used |
|---------|----------------|
| `runAssessor.files` | Per-`.mzML` file: `instrument_model`, `spectra_stats.acquisition_type`, `spectra_stats.fragmentation_tag`, `summary.labeling.call` |
| `runAssessor.search_criteria` | Overall `acquisition_type`, `fragmentation_type`, `labeling` (fallback if per-file missing) |
| `runAssessor.knowledge.instrument_model` | Overall instrument model (fallback) |
| `organism_identification.results` | Per-`.mzML` file: ranked list of organisms with Peptonizer scores; top score = primary organism |
| `modification_site_fractions.dda_closed_search.per_sample_files` | Per-sample: mods with `unimod_id`, `mod_name`, `mass_shift` → used for `comment[modification parameters]` |
| `sage_results.pass2_closed_search.quantification.method` | Overall quantification method (e.g. `"LFQ"`) |
| `pride_metadata.project` | `organisms`, `sampleAttributes` (organism part), `instruments`, `sampleProcessingProtocol` (for cleavage agent text), `dataProcessingProtocol`, `quantificationMethods`, `identifiedPTMStrings` |
| `llm_extracted_metadata` | Per-`.raw` file (keys are `"{stem}.raw"`): `Raw Data File`, `Characteristics[CellLine]`, `Characteristics[OrganismTaxid]`, `FactorValue[Experimental]` |

### Raw file name resolution

The SDRF requires `.raw` filenames. They are obtained from (in priority order):
1. `llm_extracted_metadata` keys — already keyed as `"{stem}.raw"` in the aggregated JSON
2. Match stem of `.mzML` keys in `runAssessor.files` → replace extension with `.raw`
3. Fallback: keep `.mzML` basename

The stem links `runAssessor.files` (`.mzML`) → `llm_extracted_metadata` (`.raw`) → `modification_site_fractions` (no extension in keys, just stem).

---

## 4. Data Source Priority

For each SDRF field, data is resolved in this order — first non-null value wins:

```
Agentic JSON (resolved field)
  → aggregated_results.json (runAssessor / organism_identification / modification_site_fractions)
    → pride_metadata.project (PRIDE-annotated metadata)
      → llm_extracted_metadata (legacy LLM per-file extraction)
        → "not available"  (SDRF reserved word)
```

Agentic fields are trusted highest because they are drawn from the published paper text. PRIDE metadata is submitted by authors and may be incomplete. The legacy `llm_extracted_metadata` is a last resort.

---

## 5. SDRF Column Mapping

### 5.1 Sample metadata columns (`characteristics[...]`)

| SDRF column | Requirement | Data source (priority order) | Notes |
|-------------|-------------|------------------------------|-------|
| `source name` | REQUIRED | Constructed as `{pxd}-Sample-{i}` where `i` increments per `.raw` file | Each file = one row, one sample |
| `characteristics[organism]` | REQUIRED | BiologicalAgent `organism.resolved` or `species.resolved` → `organism_identification` top-score taxon → `pride_metadata.project.organisms[0].name` | Lowercase (e.g. `homo sapiens`) |
| `characteristics[organism part]` | REQUIRED | BiologicalAgent `tissue.resolved` → `pride_metadata.project.sampleAttributes` where key=`organism part` | e.g. `colon`, `cell culture` |
| `characteristics[disease]` | REQUIRED (human) | BiologicalAgent `disease_state.resolved` → `pride_metadata.project.diseases` | `normal` for healthy |
| `characteristics[cell type]` | RECOMMENDED | BiologicalAgent `cell_type.resolved` | e.g. `cancer cell` |
| `characteristics[cell line]` | REQUIRED in cell-lines template | BiologicalAgent `cell_line.resolved` → `llm_extracted_metadata[file]["Characteristics[CellLine]"]` (parse for cell line name) | e.g. `HCT116`; only emit if resolved |
| `characteristics[biological replicate]` | REQUIRED | ExperimentalDesignAgent `replicates.resolved` → default `"1"` | Integer |
| `characteristics[sex]` | REQUIRED (human) | BiologicalAgent `sex.resolved` | `male` / `female` / `not available` |
| `characteristics[age]` | REQUIRED (human) | BiologicalAgent `age.resolved` | Format: `45Y`, `not available` if unknown |
| `characteristics[individual]` | RECOMMENDED (human) | Derived from `.raw` stem (e.g. `LINC00955`) | Per-file sample identifier |
| `characteristics[material type]` | OPTIONAL | `pride_metadata.project.sampleAttributes` for material type | e.g. `tissue`, `cell line` |
| `characteristics[treatment]` | OPTIONAL | `llm_extracted_metadata[file]["FactorValue[Experimental]"]` → ExperimentalDesignAgent `treatment_groups.resolved` | e.g. `LPS stimulation`, `untreated`; only emit if resolved |
| `characteristics[enrichment process]` | OPTIONAL | `llm_extracted_metadata[file]["Comment[EnrichmentMethod]"]` → parse `sampleProcessingProtocol` | e.g. `enrichment of phosphorylated protein`; only emit if found |
| `characteristics[depletion]` | OPTIONAL | Parse `sampleProcessingProtocol` for high-abundance depletion keywords | `"no depletion"` or `"depletion"`; only emit if detectable |
| `characteristics[strain or breed]` | RECOMMENDED (vertebrates) | BiologicalAgent `strain.resolved` → `pride_metadata.project.organisms` | e.g. `C57BL/6`; only emit for non-human organisms |
| `characteristics[developmental stage]` | REQUIRED (vertebrates) | BiologicalAgent `developmental_stage.resolved` → `"not available"` | REQUIRED if non-human vertebrate; default `"not available"` if unresolved |
| `characteristics[sampling site]` | OPTIONAL | BiologicalAgent `sample_source.resolved` → `pride_metadata.project.sampleAttributes["sampling site"]` | e.g. `tumor`; only emit if resolved |
| `characteristics[culture medium]` | RECOMMENDED (cell-lines) | Parse `sampleProcessingProtocol` for DMEM/RPMI/MEM/Ham's F-12 keywords | e.g. `DMEM`; only emit for cell-line experiments |
| `characteristics[cellosaurus accession]` | REQUIRED (cell-lines) | `"not available"` — automated Cellosaurus lookup not implemented | Emitted as `"not available"` when cell-lines template detected |
| `characteristics[compound]` | OPTIONAL | ExperimentalDesignAgent `compound_treatment.resolved` → parse `sampleProcessingProtocol` | e.g. `doxorubicin`; only emit if resolved |
| `characteristics[dose]` | OPTIONAL | ExperimentalDesignAgent `dose.resolved` | e.g. `50 uM`; only emit if resolved |

### 5.2 Data file metadata columns (`comment[...]`)

| SDRF column | Requirement | Data source (priority order) | Notes |
|-------------|-------------|------------------------------|-------|
| `assay name` | REQUIRED | Constructed as `run {i}` (1-indexed, globally unique per file) | |
| `technology type` | REQUIRED | Fixed: `"proteomic profiling by mass spectrometry"` | |
| `comment[proteomics data acquisition method]` | REQUIRED | Per-file: `runAssessor.files[f].spectra_stats.acquisition_type` → overall `runAssessor.search_criteria.acquisition_type` | Mapped: `DDA` → `data-dependent acquisition`, `DIA` → `data-independent acquisition` |
| `comment[label]` | REQUIRED | Per-file: `runAssessor.files[f].summary.labeling.call` → `sage_results.pass2_closed_search.quantification.method` → ExperimentalDesignAgent `quantification_method.resolved` | Mapped: `none`/`LFQ` → `label free sample`; `TMT`→ `TMT126` etc. (see §6) |
| `comment[instrument]` | REQUIRED | TechnicalAgent `instrument.resolved` → per-file `runAssessor.files[f].instrument_model.name` → `runAssessor.knowledge.instrument_model` | e.g. `Q Exactive HF-X` |
| `comment[cleavage agent details]` | REQUIRED | Parse `pride_metadata.project.sampleProcessingProtocol` for enzyme keywords (Trypsin, Lys-C, etc.) → `"not available"` | Mapped to CV terms (see §6) |
| `comment[fraction identifier]` | REQUIRED | Default `"1"` (no fractionation detected) | |
| `comment[technical replicate]` | REQUIRED | Default `"1"` | |
| `comment[data file]` | REQUIRED | `llm_extracted_metadata` key basename → `.mzML` stem + `.raw` → basename of mzML | |
| `comment[dissociation method]` | RECOMMENDED | TechnicalAgent `fragmentation.resolved` → per-file `runAssessor.files[f].spectra_stats.fragmentation_tag` | Mapped to CV terms (see §6) |
| `comment[modification parameters]` | RECOMMENDED | Per-sample `modification_site_fractions.dda_closed_search.per_sample_files[stem]` unimod IDs → `pride_metadata.project.identifiedPTMStrings` | One column per modification; format `NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M` |
| `comment[precursor mass tolerance]` | RECOMMENDED | Parse `pride_metadata.project.dataProcessingProtocol` (e.g. `"10 ppm"`) | |
| `comment[fragment mass tolerance]` | RECOMMENDED | Parse `pride_metadata.project.dataProcessingProtocol` (e.g. `"0.02 Da"`) | |
| `comment[sdrf version]` | RECOMMENDED | Fixed: `"v1.1.0"` | |
| `comment[sdrf annotation tool]` | OPTIONAL | Fixed: `"HAMLET-agentic v0.1.0"` | |
| `comment[fractionation method]` | OPTIONAL | TechnicalAgent `fractionation.resolved` → parse `sampleProcessingProtocol` for SCX/hpHRP/SEC/SAX | e.g. `High-pH reversed-phase chromatography (hpHRP)`; only emit if detected |
| `comment[collision energy]` | OPTIONAL | Parse `sampleProcessingProtocol` for NCE/eV patterns (e.g. "NCE of 27%", "27 NCE") | e.g. `27 NCE`; only emit if parseable |
| `comment[reduction reagent]` | OPTIONAL | Parse `sampleProcessingProtocol` for DTT/TCEP/BME/dithiothreitol keywords | e.g. `dithiothreitol`; only emit if parseable |
| `comment[alkylation reagent]` | OPTIONAL | Parse `sampleProcessingProtocol` for IAA/iodoacetamide/CAA/chloroacetamide keywords | e.g. `iodoacetamide`; only emit if parseable |
| `comment[ms2 mass analyzer]` | OPTIONAL | Infer from instrument model: Q Exactive/Exploris/Fusion → `orbitrap`; timsTOF/QTOF → `TOF`; Velos/LTQ → `ion trap` | e.g. `orbitrap`; only emit if inferable |
| `comment[ms1 scan range]` | OPTIONAL | Parse `sampleProcessingProtocol` for m/z scan range (e.g. "350–1600 m/z", "350-1600") | e.g. `350m/z-1600m/z`; only emit if parseable |
| `comment[ms min rt]` | OPTIONAL | Parse `sampleProcessingProtocol` for gradient start time | Numeric minutes (usually `0`); only emit if gradient time parseable |
| `comment[ms max rt]` | OPTIONAL | Parse `sampleProcessingProtocol` for gradient duration (e.g. "60 min gradient", "120 min run") | e.g. `60`; only emit if parseable |
| `comment[elution conditions]` | OPTIONAL | Extract gradient description from `sampleProcessingProtocol` | Free-text; only emit if parseable |
| `comment[acquisition date]` | OPTIONAL | `pride_metadata.project.publicationDate` (approximate — actual acquisition date not in PRIDE) | ISO 8601 date; annotated as approximate |

### 5.3 Factor value columns (`factor value[...]`)

| SDRF column | Requirement | Data source | Notes |
|-------------|-------------|-------------|-------|
| `factor value[disease]` | When disease varies | Mirror `characteristics[disease]` | Per spec: factor values highlight study variables |
| `factor value[organism part]` | When tissue varies | Mirror `characteristics[organism part]` | |
| `factor value[treatment]` | When treatment present | Mirror `characteristics[treatment]` | Only emit column when `characteristics[treatment]` is present |
| `factor value[cell line]` | When cell line varies | Mirror `characteristics[cell line]` | Only emit when comparing multiple cell lines |

> **Rule**: If all rows have the same value for a factor column, it is still valid to include it. We include `factor value[disease]` unconditionally as the primary study variable.

---

## 6. Controlled Vocabulary (CV) Mappings

### Acquisition method
| Raw value | SDRF value |
|-----------|-----------|
| `DDA` | `data-dependent acquisition` |
| `DIA` | `data-independent acquisition` |
| `PRM` | `parallel reaction monitoring` |
| `SRM` | `selected reaction monitoring` |
| unknown | `not available` |

### Dissociation method (fragmentation)
| Raw value | SDRF value |
|-----------|-----------|
| `HR HCD`, `HCD`, `HR_HCD` | `NT=beam-type collision-induced dissociation;AC=MS:1000422` |
| `CID`, `LR_IT_CID`, `HR_IT_CID` | `NT=collision-induced dissociation;AC=MS:1000133` |
| `ETD`, `HR_IT_ETD` | `NT=electron transfer dissociation;AC=MS:1001356` |
| `EThcD`, `HR_EThcD` | `NT=electron transfer higher energy collision dissociation;AC=MS:1002631` |
| `ETciD`, `HR_ETciD` | `NT=electron transfer collision induced dissociation;AC=MS:1003182` |
| `QTOF`, `HR_QTOF` | `not available` (no standard accession for generic QTOF fragmentation) |
| `??` or unknown | `not available` |

### Cleavage agent (parsed from protocol text)
| Text match (case-insensitive) | SDRF value |
|-------------------------------|-----------|
| `trypsin` | `NT=Trypsin;AC=MS:1001251` |
| `lys-c` / `lysc` | `NT=Lys-C;AC=MS:1001309` |
| `asp-n` / `aspn` | `NT=Asp-N;AC=MS:1001303` |
| `glu-c` / `gluc` | `NT=Glu-C;AC=MS:1001917` |
| `chymotrypsin` | `NT=Chymotrypsin;AC=MS:1001306` |
| none found | `not available` |

### Label / quantification
| Raw value | SDRF value |
|-----------|-----------|
| `none` / `LFQ` / empty | `label free sample` |
| `TMT` | `TMT126` (default channel; no per-channel info available) |
| `TMT10` | `TMT126` |
| `TMTpro` | `TMTpro126C` |
| `iTRAQ` / `iTRAQ4` | `iTRAQ4plex-114` |
| `iTRAQ8` | `iTRAQ8plex-113` |
| `SILAC` | Requires per-channel info — emit `not available` |

### Modification parameters (from `modification_site_fractions`)
Each mod with a `unimod_id` is formatted as:
```
NT={mod_name};AC=UNIMOD:{unimod_id};MT=Variable;TA={allowed_residues}
```
Known fixed modifications inferred from protocol text parsing:
- `Carbamidomethyl [C]` → `NT=Carbamidomethyl;AC=UNIMOD:4;MT=Fixed;TA=C`

### Reduction reagent (parsed from `sampleProcessingProtocol`)
| Text match (case-insensitive) | SDRF value |
|-------------------------------|-----------|
| `dithiothreitol`, `DTT` | `dithiothreitol` |
| `TCEP`, `tris(2-carboxyethyl)phosphine` | `tris(2-carboxyethyl)phosphine` |
| `beta-mercaptoethanol`, `BME`, `2-ME` | `beta-mercaptoethanol` |
| none found | *(column omitted)* |

### Alkylation reagent (parsed from `sampleProcessingProtocol`)
| Text match (case-insensitive) | SDRF value |
|-------------------------------|-----------|
| `iodoacetamide`, `IAA` | `iodoacetamide` |
| `chloroacetamide`, `CAA`, `2-chloroacetamide` | `chloroacetamide` |
| `N-ethylmaleimide`, `NEM` | `N-ethylmaleimide` |
| none found | *(column omitted)* |

### Fractionation method (parsed from `sampleProcessingProtocol` or TechnicalAgent)
| Text match or TechnicalAgent value | SDRF value |
|------------------------------------|-----------|
| `hpHRP`, `high-pH reversed-phase`, `high pH RP` | `High-pH reversed-phase chromatography (hpHRP)` |
| `SCX`, `strong cation exchange` | `Strong cation-exchange chromatography (SCX)` |
| `SAX`, `strong anion exchange` | `Strong anion-exchange chromatography (SAX)` |
| `SEC`, `size exclusion` | `Size-exclusion chromatography (SEC)` |
| `OFFGEL`, `offgel` | `OFFGEL electrophoresis` |
| no fractionation detected | *(column omitted)* |

### MS2 mass analyzer (inferred from instrument model string)
| Instrument model substring | SDRF value |
|---------------------------|-----------|
| `Q Exactive`, `Exploris`, `Orbitrap`, `Fusion`, `Eclipse`, `Astral`, `Tribrid` | `orbitrap` |
| `timsTOF`, `QTOF`, `TripleTOF`, `SYNAPT`, `Xevo`, `Impact` | `TOF` |
| `Velos`, `Elite`, `LTQ` (without Orbitrap), `ion trap` | `ion trap` |
| `TSQ`, `triple quadrupole`, `QQTOF` | `quadrupole` |
| none matched | *(column omitted)* |

### Culture medium (parsed from `sampleProcessingProtocol`, cell-line experiments only)
| Text match (case-insensitive) | SDRF value |
|-------------------------------|-----------|
| `DMEM`, `Dulbecco` | `DMEM` |
| `RPMI`, `RPMI 1640` | `RPMI 1640` |
| `MEM`, `Minimum Essential` | `MEM` |
| `Ham's F-12`, `F-12` | `Ham's F-12` |
| `IMDM` | `IMDM` |
| none found | *(column omitted)* |

---

## 7. Class Structure: `AgenticToSDRF`

```python
class AgenticToSDRF:

    def __init__(
        self,
        tech_json: Path,
        bio_json: Path,
        exp_json: Path,
        aggregated_json: Path,
    ):
        ...

    # --- Internal loaders ---
    def _load_agentic_jsons(self) -> None: ...
    def _load_aggregated(self) -> None: ...

    # --- Field extractors ---
    def _get_agentic_field(self, agent: str, field: str) -> str | None:
        """Returns agent_data[field]['resolved'] if confidence > threshold and not None."""
        ...

    def _get_raw_files(self) -> list[str]:
        """Returns list of .raw basenames in run order from llm_extracted_metadata keys,
        falling back to mzML stem + '.raw'."""
        ...

    def _get_organism(self) -> str: ...
    def _get_organism_part(self) -> str: ...
    def _get_disease(self) -> str: ...
    def _get_cell_type(self) -> str | None: ...
    def _get_cell_line(self) -> str | None: ...
    def _get_sex(self) -> str: ...
    def _get_age(self) -> str: ...
    def _get_instrument(self, raw_stem: str) -> str: ...
    def _get_acquisition_method(self, raw_stem: str) -> str: ...
    def _get_label(self, raw_stem: str) -> str: ...
    def _get_dissociation_method(self, raw_stem: str) -> str: ...
    def _get_cleavage_agent(self) -> str: ...
    def _get_modification_params(self, raw_stem: str) -> list[str]: ...
    def _get_mass_tolerances(self) -> tuple[str, str]: ...
    def _get_treatment(self, raw_stem: str) -> str | None: ...
    def _get_enrichment_process(self, raw_stem: str) -> str | None: ...
    def _get_depletion(self) -> str | None: ...
    def _get_strain(self) -> str | None: ...
    def _get_developmental_stage(self) -> str | None: ...
    def _get_sampling_site(self) -> str | None: ...
    def _get_culture_medium(self) -> str | None: ...
    def _get_compound(self) -> str | None: ...
    def _get_fractionation_method(self) -> str | None: ...
    def _get_collision_energy(self) -> str | None: ...
    def _get_reduction_reagent(self) -> str | None: ...
    def _get_alkylation_reagent(self) -> str | None: ...
    def _get_ms2_analyzer(self, instrument: str) -> str | None: ...
    def _get_scan_range(self) -> str | None: ...
    def _get_rt_range(self) -> tuple[str | None, str | None]: ...
    def _get_elution_conditions(self) -> str | None: ...
    def _get_acquisition_date(self) -> str | None: ...

    # --- CV mappers (static) ---
    @staticmethod
    def _map_acquisition(raw: str) -> str: ...
    @staticmethod
    def _map_dissociation(raw: str) -> str: ...
    @staticmethod
    def _map_label(labeling_call: str) -> str: ...
    @staticmethod
    def _parse_cleavage_agent(protocol_text: str) -> str: ...
    @staticmethod
    def _format_modification(mod: dict) -> str: ...
    @staticmethod
    def _infer_ms2_analyzer(instrument_model: str) -> str | None: ...
    @staticmethod
    def _parse_protocol_for_reagent(protocol_text: str, reagent_type: str) -> str | None: ...
    @staticmethod
    def _parse_scan_range(protocol_text: str) -> str | None: ...
    @staticmethod
    def _parse_gradient_time(protocol_text: str) -> tuple[str | None, str | None]: ...

    # --- Row builder ---
    def build_rows(self) -> list[dict]:
        """Assembles one dict per .raw file with all SDRF column values."""
        ...

    # --- Output ---
    def to_sdrf(self, output_path: Path) -> None:
        """Writes tab-delimited SDRF TSV to output_path."""
        ...
```

---

## 8. Per-File vs Experiment-Level Data

Some fields vary per `.raw` file; others are constant across the whole dataset:

| Scope | Fields |
|-------|--------|
| **Per-file** (from `runAssessor.files` / `llm_extracted_metadata`) | `comment[instrument]`, `comment[proteomics data acquisition method]`, `comment[dissociation method]`, `comment[label]`, `comment[data file]`, `comment[modification parameters]`, `comment[ms2 mass analyzer]`, `characteristics[treatment]`, `characteristics[enrichment process]` |
| **Experiment-level** (from agentic / pride_metadata / protocol text) | `characteristics[organism]`, `characteristics[organism part]`, `characteristics[disease]`, `characteristics[cell type]`, `characteristics[cell line]`, `characteristics[sex]`, `characteristics[age]`, `characteristics[strain or breed]`, `characteristics[sampling site]`, `characteristics[culture medium]`, `characteristics[depletion]`, `comment[cleavage agent details]`, `comment[reduction reagent]`, `comment[alkylation reagent]`, `comment[fractionation method]`, `comment[collision energy]`, `comment[ms1 scan range]`, `comment[ms min rt]`, `comment[ms max rt]`, `comment[elution conditions]`, `comment[precursor mass tolerance]`, `comment[fragment mass tolerance]`, `comment[acquisition date]`, `factor value[...]` |

---

## 9. SDRF Column Order

Per spec, sections must appear in order: sample metadata → data file metadata → factor values.

```
source name
characteristics[organism]
characteristics[organism part]
characteristics[tissue supergroup]    ← only if resolved (rare)
characteristics[disease]
characteristics[cell type]            ← only if resolved
characteristics[cell line]            ← only if resolved
characteristics[cellosaurus accession] ← when cell_line resolved (value: "not available")
characteristics[biological replicate]
characteristics[material type]        ← only if resolved
characteristics[sex]
characteristics[age]
characteristics[individual]
characteristics[strain or breed]      ← only for non-human organisms
characteristics[developmental stage]  ← required for vertebrates; only if applicable
characteristics[sampling site]        ← only if resolved
characteristics[culture medium]       ← only for cell-line experiments
characteristics[treatment]            ← only if resolved
characteristics[enrichment process]   ← only if resolved
characteristics[depletion]            ← only if detectable
characteristics[compound]             ← only if resolved
characteristics[dose]                 ← only if resolved
assay name
technology type
comment[proteomics data acquisition method]
comment[label]
comment[instrument]
comment[cleavage agent details]
comment[fraction identifier]
comment[technical replicate]
comment[dissociation method]
comment[fractionation method]         ← only if detected
comment[modification parameters]      ← repeated for each distinct mod
comment[reduction reagent]            ← only if parseable
comment[alkylation reagent]           ← only if parseable
comment[ms2 mass analyzer]            ← only if inferable from instrument
comment[precursor mass tolerance]     ← only if parseable
comment[fragment mass tolerance]      ← only if parseable
comment[collision energy]             ← only if parseable
comment[ms1 scan range]               ← only if parseable
comment[ms min rt]                    ← only if parseable
comment[ms max rt]                    ← only if parseable
comment[elution conditions]           ← only if parseable
comment[acquisition date]             ← only if available (approximate)
comment[data file]
comment[sdrf version]
comment[sdrf template]                ← always; lists detected templates
comment[sdrf annotation tool]
factor value[disease]
factor value[organism part]           ← only if >1 distinct tissue value
factor value[treatment]               ← when treatment column present
factor value[cell line]               ← only if >1 distinct cell line
```

Optional columns (`cell type`, `cell line`, `precursor mass tolerance`, etc.) are only included in the output when at least one row has a non-`"not available"` value.

---

## 10. SDRF Terms Reference — Complete Mapping

Sourced directly from the YAML template definitions at https://github.com/bigbio/sdrf-templates (v1.1.0).

**Status legend:**
- ✅ **MAPPED** — implemented in Section 5, output when data available
- 🔶 **PARTIAL** — data source exists but requires protocol text parsing; emits `not available` if unparseable
- ❌ **NO DATA** — no data source in our inputs; column not emitted
- ➖ **N/A** — not applicable to standard ms-proteomics (e.g. MS3 columns, non-proteomics templates)

> Summary: ~30 ✅ fully mapped · ~20 🔶 best-effort · ~38 ❌ no data source

### 10.1 base template (inherited by all)
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `source name` | REQUIRED | ✅ | Constructed: `{pxd}-Sample-{i}` |
| `assay name` | REQUIRED | ✅ | Constructed: `run {i}` |
| `technology type` | REQUIRED | ✅ | Fixed: `proteomic profiling by mass spectrometry` |
| `comment[technical replicate]` | REQUIRED | ✅ | Default `1` |
| `comment[data file]` | REQUIRED | ✅ | Basename of `.raw` file |
| `comment[sdrf version]` | RECOMMENDED | ✅ | Fixed: `v1.1.0` |
| `comment[sdrf template]` | OPTIONAL | ✅ | Lists detected templates (e.g. `NT=ms-proteomics;VV=v1.1.0`) |
| `comment[sdrf annotation tool]` | OPTIONAL | ✅ | Fixed: `HAMLET-agentic v0.1.0` |
| `comment[sdrf validation hash]` | OPTIONAL | ❌ | Not computed |

### 10.2 sample-metadata template (inherited by all)
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `characteristics[organism]` | REQUIRED | ✅ | BiologicalAgent `organism.resolved` → `organism_identification` top score → `pride_metadata.project.organisms` |
| `characteristics[organism part]` | REQUIRED | ✅ | BiologicalAgent `tissue.resolved` → `pride_metadata.project.sampleAttributes["organism part"]` |
| `characteristics[tissue supergroup]` | OPTIONAL | ❌ | No data source; would require tissue→supergroup lookup table |
| `characteristics[cell type]` | RECOMMENDED | ✅ | BiologicalAgent `cell_type.resolved` |
| `characteristics[biological replicate]` | REQUIRED | ✅ | ExperimentalDesignAgent `replicates.resolved` → default `1` |
| `characteristics[pooled sample]` | OPTIONAL | ❌ | No data source |
| `characteristics[sample type]` | OPTIONAL | ❌ | No data source |
| `characteristics[disease]` | RECOMMENDED | ✅ | BiologicalAgent `disease_state.resolved` → `pride_metadata.project.diseases` |
| `characteristics[material type]` | OPTIONAL | ✅ | `pride_metadata.project.sampleAttributes["material type"]` → inferred from cell_line/tissue |
| `characteristics[tissue mass]` | OPTIONAL | ❌ | No data source |
| `characteristics[biosample accession number]` | OPTIONAL | ❌ | No data source |
| `characteristics[sampling time]` | OPTIONAL | ❌ | No data source |
| `characteristics[treatment]` | OPTIONAL | ✅ | `llm_extracted_metadata[file]["FactorValue[Experimental]"]` → ExperimentalDesignAgent |
| `characteristics[synthetic peptide]` | OPTIONAL | ❌ | No data source |
| `characteristics[spiked compound]` | OPTIONAL | ❌ | No data source |
| `characteristics[enrichment process]` | OPTIONAL | ✅ | `llm_extracted_metadata[file]["Comment[EnrichmentMethod]"]` → parse `sampleProcessingProtocol` |

### 10.3 ms-proteomics template
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `comment[proteomics data acquisition method]` | REQUIRED | ✅ | `runAssessor.files[f].spectra_stats.acquisition_type` → `runAssessor.search_criteria.acquisition_type` |
| `comment[instrument]` | REQUIRED | ✅ | TechnicalAgent `instrument.resolved` → `runAssessor.files[f].instrument_model.name` |
| `comment[cleavage agent details]` | REQUIRED | ✅ | Parse `sampleProcessingProtocol` for enzyme keywords; `not applicable` if no digestion |
| `comment[label]` | REQUIRED | ✅ | `runAssessor.files[f].summary.labeling.call` → `sage_results...quantification.method` |
| `comment[fraction identifier]` | REQUIRED | ✅ | Default `1` |
| `comment[dissociation method]` | RECOMMENDED | ✅ | TechnicalAgent `fragmentation.resolved` → `runAssessor.files[f].spectra_stats.fragmentation_tag` |
| `comment[fractionation method]` | OPTIONAL | 🔶 | TechnicalAgent `fractionation.resolved` → parse `sampleProcessingProtocol` for SCX/hpHRP/SEC |
| `comment[collision energy]` | OPTIONAL | 🔶 | Parse `sampleProcessingProtocol` for NCE/eV patterns |
| `comment[precursor mass tolerance]` | RECOMMENDED | ✅ | Parse `dataProcessingProtocol` |
| `comment[fragment mass tolerance]` | RECOMMENDED | ✅ | Parse `dataProcessingProtocol` |
| `comment[reduction reagent]` | OPTIONAL | 🔶 | Parse `sampleProcessingProtocol` for DTT/TCEP/BME |
| `comment[alkylation reagent]` | OPTIONAL | 🔶 | Parse `sampleProcessingProtocol` for IAA/chloroacetamide |
| `characteristics[depletion]` | OPTIONAL | 🔶 | Parse `sampleProcessingProtocol` for depletion keywords |
| `comment[modification parameters]` | RECOMMENDED | ✅ | `modification_site_fractions.dda_closed_search.per_sample_files` unimod IDs |
| `comment[ms2 mass analyzer]` | OPTIONAL | 🔶 | Infer from instrument model string (see §6) |
| `comment[sample preparation batch]` | OPTIONAL | ❌ | No data source |
| `comment[lc batch]` | OPTIONAL | ❌ | No data source |
| `comment[acquisition date]` | OPTIONAL | 🔶 | `pride_metadata.project.publicationDate` (approximate) |
| `comment[ms min mz]` | OPTIONAL | ➖ | Use `comment[ms1 scan range]` interval format instead |
| `comment[ms max mz]` | OPTIONAL | ➖ | Use `comment[ms1 scan range]` interval format instead |
| `comment[ms min charge]` | OPTIONAL | ❌ | No data source |
| `comment[ms max charge]` | OPTIONAL | ❌ | No data source |
| `comment[ms min rt]` | OPTIONAL | 🔶 | Parse `sampleProcessingProtocol` for gradient start (usually `0`) |
| `comment[ms max rt]` | OPTIONAL | 🔶 | Parse `sampleProcessingProtocol` for gradient duration |
| `comment[ms min im]` | OPTIONAL | ❌ | Only timsTOF experiments; no data source |
| `comment[ms max im]` | OPTIONAL | ❌ | Only timsTOF experiments; no data source |
| `comment[ms2 min mz]` | OPTIONAL | ❌ | No data source |
| `comment[ms2 max mz]` | OPTIONAL | ❌ | No data source |
| `comment[ms3 min mz]` | OPTIONAL | ➖ | Only MS3 experiments |
| `comment[ms3 max mz]` | OPTIONAL | ➖ | Only MS3 experiments |
| `comment[ms1 scan range]` | OPTIONAL | 🔶 | Parse `sampleProcessingProtocol` for m/z range (e.g. "350-1600 m/z") |
| `comment[ms2 scan range]` | OPTIONAL | ❌ | No data source |
| `comment[ms3 scan range]` | OPTIONAL | ➖ | Only MS3 experiments |
| `comment[elution conditions]` | OPTIONAL | 🔶 | Extract gradient description from `sampleProcessingProtocol` |

### 10.4 human template (Homo sapiens experiments)
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `characteristics[disease]` | REQUIRED (overrides) | ✅ | Same as §10.2 |
| `characteristics[ancestry category]` | RECOMMENDED | ❌ | No data source |
| `characteristics[age]` | REQUIRED | ✅ | BiologicalAgent `age.resolved` → `"not available"` |
| `characteristics[sex]` | REQUIRED | ✅ | BiologicalAgent `sex.resolved` → `"not available"` |
| `characteristics[developmental stage]` | OPTIONAL | ❌ | No data source for human experiments |
| `characteristics[individual]` | RECOMMENDED | ✅ | Derived from `.raw` file basename stem |

### 10.5 vertebrates template (non-human vertebrates)
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `characteristics[disease]` | REQUIRED (overrides) | ✅ | Same as §10.2 |
| `characteristics[developmental stage]` | REQUIRED | 🔶 | BiologicalAgent `developmental_stage.resolved` → `"not available"` (must emit even if unknown) |
| `characteristics[strain or breed]` | RECOMMENDED | ✅ | BiologicalAgent `strain.resolved` → `pride_metadata.project.organisms` |
| `characteristics[sex]` | RECOMMENDED | ✅ | BiologicalAgent `sex.resolved` |

### 10.6 cell-lines template (cultured cell line experiments)
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `characteristics[cell line]` | REQUIRED | ✅ | BiologicalAgent `cell_line.resolved` → `llm_extracted_metadata[file]["Characteristics[CellLine]"]` |
| `characteristics[disease]` | REQUIRED (overrides) | ✅ | Same as §10.2 |
| `characteristics[cellosaurus accession]` | REQUIRED | ✅ | Always `"not available"` — automated lookup not implemented |
| `characteristics[cellosaurus name]` | RECOMMENDED | ❌ | No data source without Cellosaurus lookup |
| `characteristics[sampling site]` | OPTIONAL | 🔶 | BiologicalAgent `sample_source.resolved` → `pride_metadata.project.sampleAttributes["sampling site"]` |
| `characteristics[passage number]` | RECOMMENDED | ❌ | No data source |
| `characteristics[biorepository]` | OPTIONAL | ❌ | No data source |
| `characteristics[cell line authentication]` | OPTIONAL | ❌ | No data source |
| `characteristics[culture medium]` | RECOMMENDED | 🔶 | Parse `sampleProcessingProtocol` for DMEM/RPMI/MEM keywords |
| `characteristics[developmental stage]` | OPTIONAL | ❌ | No data source |
| `characteristics[ancestry category]` | OPTIONAL | ❌ | No data source |
| `characteristics[sample storage temperature]` | RECOMMENDED | ❌ | No data source |

### 10.7 clinical-metadata template (treatment studies)
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `characteristics[disease]` | REQUIRED (overrides) | ✅ | Same as §10.2 |
| `characteristics[compound]` | OPTIONAL | 🔶 | ExperimentalDesignAgent `compound_treatment.resolved` if field exists |
| `characteristics[dose]` | OPTIONAL | 🔶 | ExperimentalDesignAgent `dose.resolved` if field exists |
| `characteristics[exposure duration]` | OPTIONAL | ❌ | No data source |
| `characteristics[treatment status]` | OPTIONAL | ❌ | No data source |
| `characteristics[treatment response]` | OPTIONAL | ❌ | No data source |
| `characteristics[pre-existing condition]` | OPTIONAL | ❌ | No data source |
| `characteristics[body mass index]` | OPTIONAL | ❌ | No data source |
| `characteristics[smoking status]` | OPTIONAL | ❌ | No data source |
| `characteristics[menopausal status]` | OPTIONAL | ❌ | No data source |
| `characteristics[genetic modification]` | OPTIONAL | 🔶 | BiologicalAgent `genetic_modification.resolved` if field exists |
| `characteristics[phenotype]` | OPTIONAL | ❌ | No data source |
| `characteristics[weight]` | OPTIONAL | ❌ | No data source |
| `characteristics[height]` | OPTIONAL | ❌ | No data source |
| `characteristics[sampling site]` | OPTIONAL | 🔶 | Same as §10.6 |
| `characteristics[genotype]` | OPTIONAL | 🔶 | BiologicalAgent `strain.resolved` for non-human; `genetic_modification.resolved` otherwise |

### 10.8 oncology-metadata template (cancer studies)
| Column | Requirement | Status | Data Source / Notes |
|--------|-------------|--------|---------------------|
| `characteristics[disease staging]` | OPTIONAL | 🔶 | BiologicalAgent `disease_staging.resolved` if field exists |
| `characteristics[tumor grading]` | OPTIONAL | ❌ | No data source |
| `characteristics[tumor stage]` | OPTIONAL | ❌ | No data source |
| `characteristics[tumor size]` | OPTIONAL | ❌ | No data source |
| `characteristics[tumor mass]` | OPTIONAL | ❌ | No data source |
| `characteristics[histologic subtype]` | OPTIONAL | 🔶 | BiologicalAgent `histological_subtype.resolved` if field exists |
| `characteristics[metastasis site]` | OPTIONAL | 🔶 | BiologicalAgent `metastasis_site.resolved` if field exists |
| `characteristics[biopsy site]` | OPTIONAL | ❌ | No data source |
| `characteristics[clinical data]` | OPTIONAL | ❌ | No data source |
| `characteristics[clinical history]` | OPTIONAL | ❌ | No data source |
| `characteristics[survival time]` | OPTIONAL | ❌ | No data source |
| `characteristics[last follow up]` | OPTIONAL | ❌ | No data source |
| `characteristics[mitotic rate]` | OPTIONAL | ❌ | No data source |
| `characteristics[dukes stage]` | OPTIONAL | 🔶 | BiologicalAgent `dukes_stage.resolved` if field exists (colorectal cancer) |
| `characteristics[ann arbor stage]` | OPTIONAL | ❌ | No data source |
| `characteristics[gleason score]` | OPTIONAL | ❌ | No data source |
| `characteristics[weiss grade]` | OPTIONAL | ❌ | No data source |

### 10.9 factor value columns
| Column | Condition | Status | Notes |
|--------|-----------|--------|-------|
| `factor value[disease]` | Always include | ✅ | Mirrors `characteristics[disease]` |
| `factor value[organism part]` | When tissue varies across files | ✅ | Mirrors `characteristics[organism part]` |
| `factor value[treatment]` | When treatment column present | 🔶 | Mirrors `characteristics[treatment]` |
| `factor value[cell line]` | When multiple cell lines compared | 🔶 | Mirrors `characteristics[cell line]` |
| `factor value[{any characteristic}]` | Study-design dependent | 🔶 | Any characteristic can become a factor value |

---

## 11. Reserved Words

Per spec, use lowercase exclusively:
- `not available` — value exists but unknown
- `not applicable` — concept does not apply
- `anonymized` — value redacted for privacy
- `pooled` — pooled sample

---

## 12. Decisions / Assumptions

| Topic | Decision |
|-------|----------|
| `source name` granularity | One per `.raw` file: `{pxd}-Sample-{i}` |
| Cell line column | Include `characteristics[cell line]` when BiologicalAgent resolves it (valid in cell-lines template) |
| Cleavage agent | Parse from `sampleProcessingProtocol` text; `"not available"` if no match |
| `comment[data file]` | Basename of `.raw` file only (no path, no URI) |
| Module organisation | Separate `src/python/sdrf_builder.py`; imported by `run_agentic_metadata.py` |
| Column presence | Optional columns omitted entirely when all values would be `"not available"` |
| Confidence threshold for agentic fields | Use `resolved` value if `confidence > 0` and `status != UNKNOWN`; `UNKNOWN` → skip to next source |
| Organism template | Determine dynamically: `homo sapiens` → human template columns; others → vertebrates/invertebrates |
| `comment[modification parameters]` | Only include mods present in `modification_site_fractions`; one column per distinct mod across the dataset |
| Confidence threshold for agentic fields | Use `resolved` value for all fields regardless of `confidence`; confidence-based filtering deferred to future work |
| `biological replicate` assignment | Default `1` for all files; no attempt to infer from ExperimentalDesignAgent |
| `factor value[organism part]` | Only emitted when organism part varies across rows (>1 distinct value) |
| Cellosaurus accession | Emit `"not available"` — automated lookup not implemented; do not attempt external API calls |
| External lookups generally | Skip all fields requiring significant external API calls (Cellosaurus, BioSamples, etc.) |

---

## 13. Example Output (PXD041514)

| Column | Row 1 (LINC00955.raw) | Row 2 (NC.raw) |
|--------|----------------------|----------------|
| `source name` | PXD041514-Sample-1 | PXD041514-Sample-2 |
| `characteristics[organism]` | homo sapiens | homo sapiens |
| `characteristics[organism part]` | colon | colon |
| `characteristics[disease]` | colorectal cancer | colorectal cancer |
| `characteristics[cell type]` | cancer cell | cancer cell |
| `characteristics[cell line]` | HCT116 | HCT116 |
| `characteristics[biological replicate]` | 1 | 2 |
| `characteristics[sex]` | female | female |
| `characteristics[age]` | not available | not available |
| `characteristics[individual]` | LINC00955 | NC |
| `assay name` | run 1 | run 2 |
| `technology type` | proteomic profiling by mass spectrometry | proteomic profiling by mass spectrometry |
| `comment[proteomics data acquisition method]` | data-dependent acquisition | data-dependent acquisition |
| `comment[label]` | label free sample | label free sample |
| `comment[instrument]` | Q Exactive HF-X | Q Exactive HF-X |
| `comment[cleavage agent details]` | NT=Trypsin;AC=MS:1001251 | NT=Trypsin;AC=MS:1001251 |
| `comment[fraction identifier]` | 1 | 1 |
| `comment[technical replicate]` | 1 | 1 |
| `comment[dissociation method]` | NT=beam-type collision-induced dissociation;AC=MS:1000422 | not available |
| `comment[modification parameters]` (Oxidation) | NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M | NT=Oxidation;AC=UNIMOD:35;MT=Variable;TA=M |
| `comment[modification parameters]` (Carbamidomethyl) | NT=Carbamidomethyl;AC=UNIMOD:4;MT=Fixed;TA=C | NT=Carbamidomethyl;AC=UNIMOD:4;MT=Fixed;TA=C |
| `comment[precursor mass tolerance]` | 10 ppm | 10 ppm |
| `comment[fragment mass tolerance]` | 0.02 Da | 0.02 Da |
| `comment[data file]` | LINC00955.raw | NC.raw |
| `comment[sdrf version]` | v1.1.0 | v1.1.0 |
| `comment[sdrf annotation tool]` | HAMLET-agentic v0.1.0 | HAMLET-agentic v0.1.0 |
| `factor value[disease]` | colorectal cancer | colorectal cancer |

> Note: `fragmentation_tag` for NC.raw is `"??"` in runAssessor, so dissociation method falls back to `not available` for that file.

---

## 14. Open Questions ~~for Review~~ — Resolved

All questions answered. No blockers remain.

| # | Question | Answer |
|---|----------|--------|
| 1 | `biological replicate` assignment | Default `1` for all files. |
| 2 | `factor value[organism part]` | Only include when organism part varies across files. |
| 3 | Confidence threshold | Use all `resolved` fields regardless of confidence (threshold deferred). |
| 4 | Cell line template compliance — Cellosaurus lookup | Skip. Emit `"not available"` for accession; no external API calls. |
