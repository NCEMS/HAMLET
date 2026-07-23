# Agentic-Only Workflow

## Overview

The **agentic-only mode** allows you to skip the computationally expensive search stages (organism_id, determine_taxids, search) and run only the fetch, metadata assessment, and metadata extraction stages. It:

1. Fetches raw data from PRIDE
2. Runs runAssessor to assess metadata
3. Determines acquisition parameters (DIA vs DDA)
4. **Creates minimal aggregated results** (no organism_id or search)
5. Runs metadata extraction and finalization

This is useful when:
- You want to quickly test metadata extraction logic without re-running expensive search
- You want to parallelize metadata extraction independently
- You want fresh PRIDE metadata for a set of PXDs but skip GPU-intensive organism identification
- You're iterating on LLM metadata extraction parameters

## Workflow Stages

### Executed Stages (In Order)
1. `fetch_pxd` - Downloads raw data from PRIDE
2. `run_assessor` - Assesses metadata from raw files
3. `determine_acquisition_params` - Detects DIA/DDA acquisition type
4. **`create_minimal_aggregated_results`** - **NEW** - Creates stub aggregated results with minimal but valid structure
5. `agentic_metadata_extraction` - LLM-based metadata extraction from publications
6. `llm_judge` - Multi-run consensus evaluation of extracted metadata
7. `finalize_sdrf` - Final SDRF generation with user overrides
8. `results_summary` - Pipeline summary CSV

### Skipped Stages (Bypassed)
- `organism_id` - De novo sequencing to predict organism
- `determine_taxids` - Determines taxid for search
- `search` - Spectral search (SAGE/DIA-NN)
- `aggregate_results` - Aggregates full search results

## Input Requirements

You need either:
- A single PXD: `--pxd PXD000070`
- A CSV file with multiple PXDs: `--pxd_csv GSlist0.csv`

The CSV should have a header row with "PXD" as the first column name.

## Usage

### Basic Command with Single PXD

```bash
nextflow run main.nf --agentic_only true --pxd PXD000070 -resume
```

### With Multiple PXDs from CSV

```bash
nextflow run main.nf --agentic_only true --pxd_csv GSlist0.csv -resume
```

### Limit Number of PXDs

```bash
nextflow run main.nf \
    --agentic_only true \
    --pxd_csv GSlist0.csv \
    --num_pxds 5 \
    -resume
```

### With Specific Number of Judge Runs

By default, the pipeline runs 3 judge passes for consensus. Adjust with:

```bash
nextflow run main.nf \
    --agentic_only true \
    --pxd_csv GSlist0.csv \
    --n_judge_runs 5 \
    -resume
```

### SLURM Job Submission

A pre-configured SLURM script is available:

```bash
sbatch assets/slurm/scripts/run_HAMLETAgenticOnly.slurm
```

Edit the script to change the PXD list:

```bash
# Edit this line in the script:
--pxd_csv assets/pxd_lists/GSlist_split/GSlist0.csv
```

## Output Structure

Results are written to `results/<PXD>/` with the structure:

```
results/
  PXD000070/
    agentic_metadata/
      metadata_extraction_output/
        integrated_output/
          TechnicalAgent/
          BiologicalAgent/
          ExperimentalDesignAgent/
        post_judge/        # Second-pass judge results (after user overrides)
      PXD000070.sdrf.tsv   # Final SDRF file
    detected_params.json   # Detected acquisition parameters
    PXD000070_aggregated_results.json  # Minimal aggregated results
  ...
ResultsSummary.csv         # Pipeline completion summary
```

## Minimal Aggregated Results Structure

The `create_minimal_aggregated_results` process generates a lightweight JSON with:

```json
{
  "pxd_id": "PXD000070",
  "pipeline_version": "agentic_only_1.0",
  "aggregation_timestamp": "2026-07-23T...",
  "input_paths": {...},
  "runAssessor": {...},           // Full runAssessor metadata
  "organism_identification": {
    "status": "skipped_agentic_only",
    "results": {}
  },
  "PTM-shepherd_open_search": {
    "status": "skipped_agentic_only",
    "results": {}
  },
  "PTM-shepherd_closed_search": {
    "status": "skipped_agentic_only",
    "results": {}
  },
  "Search_and_modification_results": {
    "status": "skipped_agentic_only",
    "files": {}
  },
  "modification_site_fractions": {...},
  "pride_metadata": {...},
  "processing_summary": {...},
  "llm_extracted_metadata": {},
  "consolidated_pipeline": {...}
}
```

This structure is valid for `agentic_metadata_extraction` and downstream processes, avoiding missing-key errors.

## Performance Notes

- **Agentic-only runs ~2-3 minutes per PXD** (vs ~30-60 minutes for full pipeline including search)
- Requires PRIDE network access to download raw data
- No GPU required (organism_id and search are skipped)
- Metadata extraction still requires LLM API calls (rate-limited by `--llm_workers`)

## Troubleshooting

### Error: Must specify either --pxd or --pxd_csv

**Solution**: Provide at least one of:
```bash
--pxd PXD000070              # Single PXD
--pxd_csv my_pxds.csv        # CSV with PXD list
```

### Error: Could not load study_metadata.json

**Solution**: This means `run_assessor` failed for a PXD. The error will be in `results/<PXD>/.nextflow.log`. Common causes:
- Network timeout downloading from PRIDE
- Corrupted mzML file
- mzML file has no spectra

### PXD skipped by stage_manifest

If a PXD is skipped, check the stage manifest:
```bash
cat results/pipeline_stage_manifest.json | grep -A 5 "<PXD>"
```

To force re-run:
```bash
nextflow run main.nf --agentic_only true --pxd PXD000070 -resume -N
# -N flag clears the cache
```

## Comparing Workflows

### Full Pipeline (Default)
```
fetch → run_assessor → determine_acq_params → organism_id → determine_taxids → 
search → aggregate_results → agentic_metadata_extraction → llm_judge → finalize_sdrf
```
- **Time**: ~30-60 min per PXD (including 1-2 GPU hours for organism_id + search)
- **Resources**: GPU required
- **Output**: Complete proteomics analysis with PTM/modification info

### Agentic-Only Pipeline
```
fetch → run_assessor → determine_acq_params → [create_minimal_aggregated_results] → 
agentic_metadata_extraction → llm_judge → finalize_sdrf
```
- **Time**: ~2-3 min per PXD
- **Resources**: No GPU required
- **Output**: Metadata extraction only (no search results)

Use agentic-only when you need **metadata/SDRF** without full proteomics analysis.
