# HAMLET Store

**HAMLET** (Hybrid Agentic Metadata Literature Extraction and Technical annotation tool) is a Nextflow pipeline for automated re-annotation of public proteomics datasets from the PRIDE Archive. For each dataset (PXD accession) HAMLET downloads raw spectral files, characterises the experiment, identifies the source organism via de novo sequencing, runs a database search, extracts metadata from the associated publication using an LLM, and produces structured SDRF-compatible outputs.

**Source code and documentation:** https://github.com/ianmsitarik/HAMLET *(private — contact authors for access)*

---

## Store layout

```
store/
├── README.md                         ← this file
├── aggregated_results_files/         ← one JSON per PXD (primary output)
├── hamlet_sdrfs/                     ← active curated SDRFs plus immutable release snapshots
├── agentic_results_files/            ← active agentic outputs plus immutable release snapshots
├── releases/                         ← immutable per-release manifests and active-version index
└── intermediate_files/               ← per-PXD intermediate pipeline artefacts
```

---

## Output files per PXD

### 1. `aggregated_results_files/PXD######_aggregated_results.json`

The primary output for each dataset. A single JSON document that consolidates all pipeline outputs into one record. Top-level keys:

| Key | Description |
|-----|-------------|
| `pxd_id` | PRIDE accession (e.g. `PXD000095`) |
| `pipeline_version` | Canonical HAMLET release version |
| `run_mode` | Processing scope: `full` or `agentic_only` |
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

## Release Structure

The active SDRF and agentic directories are a mixed-version materialization: each PXD is associated with one release in `releases/active.json`. Flat paths remain the backwards-compatible active copies, while versioned child directories preserve the actual immutable artifacts for each release:

```text
hamlet_sdrfs/
├── PXD######.sdrf.tsv                ← active compatibility copy
├── v2.1.0/PXD######.sdrf.tsv         ← immutable historical snapshot from Git revision 18d4e458
└── v2.1.1/PXD######.sdrf.tsv         ← immutable promoted v2.1.1 artifact

agentic_results_files/
├── PXD######/                        ← active compatibility copy
├── v2.1.0/PXD######/                 ← immutable historical agentic artifacts
└── v2.1.1/PXD######/                 ← immutable promoted agentic artifacts

releases/
├── active.json                       ← PXD -> active HAMLET release version
├── v2.1.0/manifest.json              ← Git-HEAD baseline hashes and judge metrics
└── v2.1.1/manifest.json              ← promoted v2.1.1 source and active SDRF hashes
```

`v2.1.1` promotes the 299 PXDs in `assets/pxd_lists/HamletPXDs.csv`. It does not relabel or overwrite unpromoted active records. Every promoted active SDRF has `comment[sdrf annotation tool] = HAMLET-agentic v2.1.1`; the remaining active SDRFs retain their own annotated release values. The `v2.1.0` snapshot preserves its Git-source bytes exactly, including its historical `HAMLET-agentic v0.1.0` row annotation; its directory name and release manifest identify the reviewed v2.1.0 baseline snapshot.

Use the release-aware promotion utility rather than copying result directories directly:

```bash
conda run -n meti_env python src/job_scripts/updatestore.py \
    results_hamletpxds_agentic_v2_1_1 store \
    --release-version v2.1.1
```

The utility validates every PXD bundle before modifying the store, writes immutable versioned artifacts before refreshing active copies, and refuses to overwrite an existing release manifest or versioned artifact directory. Use `materialize_store_versions.py` only to backfill a release from an explicit Git revision or from already promoted active records; it also refuses to replace existing snapshots.

Static QC comparisons are now version-to-version summaries built from these immutable store snapshots, rather than a fresh post-store judge rerun. Generate a comparison and publish it into the Store Explorer bundle with:

```bash
python src/python/run_sdrf_qc.py \
    --baseline-version v2.1.0 \
    --candidate-version v2.1.1 \
    --output-dir /tmp/hamlet-static-qc

python3 src/job_scripts/build_store_explorer.py \
    --pxd-file assets/pxd_lists/Hamlet_GS_pride_sdrf_union.csv \
    --qc-summary /tmp/hamlet-static-qc/qc-summary.json
```

The published `docs/store-explorer/data/qc-summary.json` is a static release-comparison artifact. The site reads it directly and lets reviewers switch between any version pairs present in that summary.

## STATUS — historical snapshot as of 2026-08-18

### 1. `aggregated_results_files/` — 2,756 PXDs

**Run-mode breakdown:**

| `run_mode` | Count | Description |
|---|---|---|
| `full` | **2,647** | Full HAMLET pipeline run (fetch → assessor → organism ID → search → aggregation) |
| `agentic_only` | **109** | Agentic-metadata-only pass; wet-lab pipeline stages skipped |

**Stage coverage across the 2,647 full-pipeline records:**

| Stage | PXDs with output | Coverage |
|---|---|---|
| runAssessor | 2,647 | 100% |
| PRIDE metadata | 2,647 | 100% |
| SAGE search results | 2,622 | 99% |
| Organism identification | 2,261 | 85% |
| PTM-Shepherd open search | 1,425 | 54% |
| Modification site fractions | 1,369 | 52% |
| LLM extracted metadata | 1,393 | 53% |
| PTM-Shepherd closed search | 0 | 0% — not yet run pipeline-wide |

Total spectral files indexed across all full-pipeline PXDs: **8,744**

**`agentic_only` breakdown (109 PXDs):**

| Category | Count |
|---|---|
| Never processed by full pipeline (single commit, always agentic-only) | 109 |
| Previously had full data, downgraded by a later commit (now restored) | 9 *(restored 2026-08-18)* |

The 9 previously-downgraded PXDs (PXD002080, PXD003209, PXD004143, PXD005463, PXD009602, PXD012307, PXD012986, PXD014528, PXD021874) have been restored to their richest git history version. They are now counted under `full` above.

---

### 2. `hamlet_sdrfs/` — 306 PXDs

306 curated SDRF TSV files produced by the agentic metadata extraction stage. These are a strict subset of the PXDs that completed the full agentic pipeline. Every SDRF has been validated against the PRIDE SDRF column specification.

---

### 3. `agentic_results_files/` — 1,820 PXDs

Raw per-agent LLM extraction outputs (BiologicalAgent, ExperimentalDesignAgent, TechnicalAgent) for 1,820 PXDs. This is a superset of `hamlet_sdrfs/` — not all agentic runs produced a passing SDRF. The gap between 1,820 (agentic runs) and 306 (final SDRFs) reflects LLM quality filtering, judge-stage failures, and datasets excluded from SDRF scope.

---

## Version and run-mode reference

HAMLET uses release-aware SDRF promotion. The current generator release is **`v2.1.1`**, while the active store legitimately contains v0.1.0, v2.1.0, and v2.1.1 records. Per-PXD release identity is determined by the final SDRF's `comment[sdrf annotation tool]` and indexed by `releases/active.json`; historical aggregate `pipeline_version` fields can predate the current release convention.

`run_mode` is separate from the release version and describes how the individual PXD was processed.

| `run_mode` | Stages present | When assigned |
|---|---|---|
| `full` | runAssessor, organism_id, SAGE search, PTM-Shepherd, LLM extraction, PRIDE metadata, consolidated pipeline event log | Full HAMLET pipeline run |
| `agentic_only` | runAssessor state block; unrun stages set to `"status": "skipped_agentic_only"` | Agentic-only run or runAssessor-only aggregation |

Key structural differences by run mode:

| Field | `full` | `agentic_only` |
|---|---|---|
| `runAssessor.files` | Full per-file spectral characterisation (ROI peaks, charge dist., labeling) | Empty `{}` |
| `organism_identification` | Casanovo de novo + Peptonizer2000 scores + final taxid | `{"status": "skipped_agentic_only", "results": {}}` |
| `PTM-shepherd_open_search` | PTM mass-shift profile from open search | `{"status": "skipped_agentic_only", "results": {}}` |
| `Search_and_modification_results` | SAGE PSM/peptide/protein counts, per-file breakdown | `{"status": "skipped_agentic_only", "files": {}}` |
| `modification_site_fractions` | Per-residue mod abundance fractions | `{"status": "skipped_agentic_only", "data": {}}` |
| `consolidated_pipeline` | Full lifecycle event log with taxid decisions, quality gates, key findings | `{"status": "minimal_agentic_only", "data": {}}` |
| `processing_summary` | Boolean flags per stage + `total_data_files` count | `{"status": "minimal_agentic_only", "total_files": 0}` |

---

## Coverage

As of 2026-08-18:

| Directory | PXD count | Disk |
|---|---|---|
| `aggregated_results_files/` | 2,756 | 507 MB |
| `agentic_results_files/` | 1,820 | 191 MB |
| `hamlet_sdrfs/` | 306 | 1.3 MB |

---

## Changelog

| Date | Version | Notes |
|------|---------|-------|
| 2026-08-18 | — | Restored 9 PXDs (PXD002080, PXD003209, PXD004143, PXD005463, PXD009602, PXD012307, PXD012986, PXD014528, PXD021874) from git history after later agentic-only records overwrote their full outputs. Added the STATUS section and version/run-mode reference. |
| 2026-06-04 | — | Initial store tarball. 2,317 PXDs processed from PRIDE Archive. Includes organism ID (Casanovo + Peptonizer2000), SAGE open/closed search, LLM baseline extraction, and agentic SDRF generation. |
