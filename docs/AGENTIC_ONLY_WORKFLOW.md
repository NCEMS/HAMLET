# Agentic-Only Workflow

## Overview

The **agentic-only mode** reuses existing aggregated results and runs only the agentic metadata and SDRF stages. It:

1. Loads each `<PXD>_aggregated_results.json` from `--aggregated_results_dir`
2. Runs agentic metadata extraction from publication text and the stored aggregate
3. Runs multi-pass LLM judge consensus
4. Finalizes the SDRF using judge-approved overrides

This is useful when:
- You want to quickly test metadata extraction logic without re-running expensive search
- You want to parallelize metadata extraction independently
- You want fresh PRIDE metadata for a set of PXDs but skip GPU-intensive organism identification
- You're iterating on LLM metadata extraction parameters

## Workflow Stages

### Executed Stages (In Order)
1. `agentic_metadata_extraction` - LLM-based metadata extraction from publications and the stored aggregate
2. `llm_judge` - Multi-run consensus evaluation of extracted metadata
3. `finalize_sdrf` - Final SDRF generation with user overrides
4. `results_summary` - Pipeline summary CSV

### Skipped Stages (Bypassed)
- `fetch_pxd` - RAW file download and conversion
- `run_assessor` - Instrument/run characterization
- `determine_acquisition_params` - DIA/DDA detection
- `organism_id` - De novo sequencing to predict organism
- `determine_taxids` - Determines taxid for search
- `search` - Spectral search (SAGE/DIA-NN)
- `aggregate_results` - Full pipeline aggregation

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
    --aggregated_results_dir store/aggregated_results_files \
    --stage_manifest results/agentic_only_stage_manifest.json \
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
  ...
ResultsSummary.csv         # Pipeline completion summary
```

The stored `*_aggregated_results.json` file remains in `--aggregated_results_dir`; agentic-only mode does not download RAW files, run runAssessor, or create a replacement aggregate. Use a dedicated `--stage_manifest` path as shown above so the temporary upstream-stage skips do not affect a future full-pipeline run for the same PXD.

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
