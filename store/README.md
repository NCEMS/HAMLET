# HAMLET Store

**HAMLET** (Hybrid Agentic Metadata Literature Extraction and Technical annotation tool) is a Nextflow pipeline for automated re-annotation of public proteomics datasets from the PRIDE Archive. For each dataset (PXD accession) HAMLET downloads raw spectral files, characterises the experiment, identifies the source organism via de novo sequencing, runs a database search, extracts metadata from the associated publication using an LLM, and produces structured SDRF-compatible outputs.

**Source code and documentation:** https://github.com/ianmsitarik/HAMLET *(private — contact authors for access)*

---

## Store layout

```
store/
├── README.md                         ← this file
├── aggregated_results_files/         ← one JSON per PXD (primary output)
├── hamlet_sdrfs/                     ← curated SDRF TSV files per PXD
├── agentic_results_files/            ← per-PXD agentic LLM extraction outputs
└── intermediate_files/               ← per-PXD intermediate pipeline artefacts
```

---

## Output files per PXD

### 1. `aggregated_results_files/PXD######_aggregated_results.json`

The primary output for each dataset. A single JSON document that consolidates all pipeline outputs into one record. Top-level keys:

| Key | Description |
|-----|-------------|
| `pxd_id` | PRIDE accession (e.g. `PXD000095`) |
| `pipeline_version` | HAMLET pipeline version string |
| `aggregation_timestamp` | ISO-8601 timestamp of aggregation |
| `input_paths` | Paths used during processing (mzML dir, organism dir, search dir, etc.) |
| `runAssessor` | Per-file instrument characterisation: acquisition type (DDA/DIA), fragmentation method, labeling reagent, precursor charge distribution, and any detected problems |
| `organism_identification` | Results and summary from de novo sequencing + Peptonizer2000 taxonomic inference; includes per-file taxid scores |
| `PTM-shepherd_open_search` | Open-search PTM profile from PTM-Shepherd (DDA only); null if insufficient PSMs or DIA data |
| `PTM-shepherd_closed_search` | Closed-search PTM profile from PTM-Shepherd (DDA only); null if skipped |
| `Search_and_modification_results` | SAGE search statistics (pass 1 open, pass 2 closed): PSM counts, unique peptides/proteins, per-file breakdown |
| `modification_site_fractions` | Fractional abundance of each variable modification site across the dataset |
| `pride_metadata` | Full PRIDE REST API metadata: title, description, instruments, organisms, sample attributes, references, file list |
| `processing_summary` | Boolean flags indicating which pipeline stages produced output (runAssessor, organism_results, search, PTM-Shepherd, LLM, PRIDE metadata) |
| `llm_extracted_metadata` | Structured metadata extracted from the associated publication by the LLM baseline agent; null if extraction was skipped or failed |
| `consolidated_pipeline` | Structured event log from the search orchestrator: lifecycle events, quality gate decisions, skip reasons, taxid warnings, key findings |

---

### 2. `hamlet_sdrfs/PXD######.sdrf.tsv`

A tab-separated Sample and Data Relationship Format (SDRF) file produced by the agentic metadata extraction stage. Each row corresponds to one sample/raw file. Columns follow the PRIDE SDRF specification:

| Column group | Example columns |
|---|---|
| Sample characteristics | `characteristics[organism]`, `characteristics[organism part]`, `characteristics[disease]`, `characteristics[cell type]`, `characteristics[cell line]`, `characteristics[biological replicate]` |
| Technology | `technology type`, `comment[instrument]`, `comment[label]`, `comment[fractionation method]` |
| File references | `comment[data file]`, `comment[fraction identifier]`, `comment[technical replicate]` |

These files are suitable for direct submission to PRIDE or downstream SDRF-aware tools.

---

### 3. `agentic_results_files/PXD######/`

Per-PXD outputs from the multi-agent LLM metadata extraction pipeline. Subdirectory structure:

```
agentic_results_files/PXD######/
├── Biological_annotations/
│   └── temp_0.0/
│       └── PXD######_PubText.json          ← raw publication text extracted for biological annotation
├── experimental_design_output/
│   └── temp_0.0/
│       └── PXD######_PubText.json          ← publication text used by experimental design agent
├── technical_metadata_output/
│   └── temp_0.0/
│       └── PXD######_PubText.json          ← publication text used by technical metadata agent
└── integrated_output/
    ├── BiologicalAgent/
    │   └── temp_0.0/
    │       └── PXD######_PubText_enriched.json    ← biological metadata enriched by LLM agent
    ├── ExperimentalDesignAgent/
    │   └── temp_0.0/
    │       └── PXD######_PubText_enriched.json    ← experimental design metadata enriched by LLM
    └── TechnicalAgent/
        └── temp_0.0/
            └── PXD######_PubText_enriched.json    ← technical metadata enriched by LLM agent
```

The `_enriched.json` files contain the structured LLM output (JSON-schema compliant) for each agent's domain. These feed into the final SDRF generation step.

---

### 4. `intermediate_files/PXD######/`

Per-PXD intermediate artefacts retained for reproducibility and debugging:

```
intermediate_files/PXD######/
├── detected_params.json                    ← runAssessor output: detected DDA/DIA, labeling, fragmentation
├── taxid_mapping.json                      ← per-file taxid assignments (source: organism_id / LLM / PRIDE)
├── taxid_warnings.json                     ← warnings when falling back to PRIDE project-level taxid
├── llm_results/                            ← raw LLM extraction outputs (PubText.json, GPT response JSON)
├── search/                                 ← SAGE search outputs (open + closed pass TSVs, results JSON)
├── organism_results/
│   └── CasanovoSequence/
│       └── PXD######_<file>/
│           ├── <file>.mztab                ← Casanovo/Cascadia de novo sequencing results (mzTab format)
│           ├── <file>.log                  ← de novo sequencing run log
│           ├── <file>_processed.tsv        ← filtered de novo sequences above confidence threshold
│           ├── <file>_filtered70pct.tsv    ← sequences filtered to ≥70% confidence
│           ├── <file>_filtered70pct_slim.tsv  ← slim version (peptide + score only) for Peptonizer
│           └── Peptonizer2000_data/
│               └── <file>_filtered70pct_slim/
│                   ├── peptide_taxa.json   ← Unipept taxonomy hits per peptide
│                   └── *_config.yaml       ← Peptonizer2000 run configuration
└── PXD######_aggregated_results.json       ← copy of aggregated results (same as aggregated_results_files/)
    PXD######_pipeline.json                 ← structured pipeline event log
    PXD######_pipeline_summary.md           ← human-readable pipeline run summary
```

---

## Coverage

As of the most recent tarball generation:

| Directory | PXD count |
|---|---|
| `aggregated_results_files/` | 2,317 |
| `hamlet_sdrfs/` | 299 |
| `agentic_results_files/` | 1,705 |
| `intermediate_files/` | 2,317 |

---

## Changelog

| Date | Version | Notes |
|------|---------|-------|
| 2026-06-04 | v1.0 | Initial store tarball. 2,317 PXDs processed from PRIDE Archive. Includes organism ID (Casanovo + Peptonizer2000), SAGE open/closed search, LLM baseline extraction, and agentic SDRF generation. |
