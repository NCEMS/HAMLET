# Getting Started with HAMLET

This guide is for someone running HAMLET for the first time. It covers installation, the two supported execution modes, the files to inspect after a run, the important intermediate outputs, and practical recovery steps when a stage fails.

HAMLET is a local, container-free Nextflow pipeline for PRIDE proteomics datasets. A full run downloads and assesses the data, identifies organisms, performs a DDA or DIA search, creates an aggregated results JSON, extracts publication metadata, judges that metadata, and writes an SDRF. An agentic-only run starts from an existing aggregate and performs the metadata, judge, and SDRF portion only.

## Before You Start

### Host requirements

Use a Linux x86-64 system. The default configuration assumes substantial local disk and memory because RAW/mzML files and search outputs can be large.

Install these prerequisites before cloning HAMLET:

| Requirement | Purpose |
|---|---|
| Git | Clone HAMLET and its submodules |
| GitHub CLI (`gh`) | Authenticate to the private agentic-metadata submodule over HTTPS |
| curl or wget | Bootstrap Miniconda and downloads |
| Conda/Miniconda | HAMLET tool environments |
| NVIDIA GPU, optional | Accelerates organism identification |
| OpenRouter API key | Required for agentic metadata extraction and judging |

For a full PXD, plan for at least 50 GB free disk. The actual requirement depends on the number and size of the RAW files.

`src/setup.sh` installs Nextflow 25.04.4 and Java 17 in `meti_env`; use that environment to launch HAMLET. A separate system-wide Nextflow installation is not required.

### Clone and bootstrap

```bash
git clone <HAMLET-repository-url> HAMLET
cd HAMLET
gh auth login --hostname github.com --git-protocol https --web
bash src/setup.sh
```

Authorize the GitHub CLI as the collaborator account that can access `CompOmics/agentic-metadata`. `src/setup.sh` initializes both required submodules and fetches the latest `feature/hamlet-per-raw-integration` commit for agentic-metadata, so do not run a separate generic submodule update command. GitHub SSH keys are not required.

If the installer adds Miniconda to your shell configuration, open a new shell or run the command it prints before rerunning `src/setup.sh`.

Recent Conda installations can require acceptance of Anaconda's Terms of Service before the environment files can use their `defaults` channel. Review and accept the terms in your own Conda installation before running setup:

```bash
conda tos interactive --override-channels \
  --channel https://repo.anaconda.com/pkgs/main \
  --channel https://repo.anaconda.com/pkgs/r
```

Or, after reviewing the terms, accept them non-interactively:

```bash
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main
conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r
```

The setup script creates the conda environments under the active Conda installation's `envs/` directory. Use `--conda_base /path/to/miniconda` at pipeline run time only when its environments are located under a different Conda base.

### Required external assets

`src/setup.sh` provisions the two large, local assets below when they are absent. It stops if it cannot obtain the Cascadia checkpoint and warns if taxonomy download fails. You can rerun the individual taxonomy downloader after resolving a network failure:

| Asset | Required for | Location | Provisioning |
|---|---|---|---|
| Cascadia checkpoint (558 MB) | DIA organism identification | `assets/cascadia.ckpt` | Downloaded by `src/setup.sh`; override with `--cascadia_model_path` if needed. |
| NCBI taxonomy database (about 500 MB) | Species-level organism identification | `assets/taxonomy/nodes.dmp`, `assets/taxonomy/names.dmp` | Downloaded by `src/setup.sh`; retry with `bash src/bash/download_ncbi_taxonomy.sh`. |
| Casanovo checkpoint | DDA organism identification | `${XDG_CACHE_HOME:-$HOME/.cache}/casanovo/` | Downloaded automatically on the first DDA organism-identification task and reused from the persistent user cache. Keep network access available until it has been cached. |
| UniProt organism FASTA | DDA SAGE and DIA-NN search | Results FASTA cache or search output | Downloaded automatically for the selected taxid at search time. Keep network access available. |

The repository already includes the static inputs required at launch: `assets/UniversalContaminats.fasta`, `assets/taxid_lists/CommonPRIDEtaxids.txt`, and `assets/default_sage.config`. `assets/diann_libraries/` is an optional reusable DIA-NN library cache; HAMLET creates it when absent. Do not download organism FASTA files in advance unless you need an offline run; HAMLET selects them from the resolved taxid and caches them.

Verify the local assets before a full run:

```bash
test -s assets/cascadia.ckpt
test -s assets/taxonomy/nodes.dmp
test -s assets/taxonomy/names.dmp
test -s assets/UniversalContaminats.fasta
test -s assets/taxid_lists/CommonPRIDEtaxids.txt
test -s assets/default_sage.config
```

Export the OpenRouter API key before an agentic or full run:

   ```bash
export OPENROUTER_API_KEY="sk-or-..."
   ```

`OPENROUTER_API_KEY` is the only API credential HAMLET requires. Do not put it in a Nextflow config file or commit it to the repository.

### Quick environment check

```bash
source "${HOME}/miniconda3/etc/profile.d/conda.sh"
conda activate meti_env
nextflow -version
which ThermoRawFileParser
which aria2c
python -c "import pandas; print('HAMLET core environment OK')"
conda run -n search_env sh -c 'command -v sage && command -v diann'
conda run -n casanovo_env python -c "import casanovo; print('Casanovo environment OK')"
conda run -n cascadia_env python -c "import torch; print('Cascadia environment OK')"
```

Keep `meti_env` active for all `nextflow run` commands below. Run `conda deactivate` only after the pipeline exits.

## Choose a Run Mode

### Full pipeline

Use this mode when HAMLET needs to download and process the experimental files.

```bash
conda activate meti_env
nextflow run main.nf \
  --pxd PXD000070 \
  -resume
```

For a CSV batch, use a first column named `PXD`:

```csv
PXD
PXD000070
PXD000534
```

```bash
conda activate meti_env
nextflow run main.nf \
  --pxd_csv pxds.csv \
  --max_raw_files 5 \
  -resume
```

Start with a small `--max_raw_files` value for an unfamiliar PXD. Remove the limit only when the small run succeeds and the resource use is understood.

### Agentic-only pipeline

Use this mode when a valid aggregate JSON is already available in `store/aggregated_results_files/`. It skips RAW download, organism identification, and search; it runs metadata extraction, LLM judging, and SDRF finalization.

```bash
conda activate meti_env
nextflow run main.nf \
  --agentic_only true \
  --pxd PXD000070 \
  --aggregated_results_dir store/aggregated_results_files \
  --stage_manifest results/agentic_only_stage_manifest.json \
  --outdir results \
  -resume
```

For a batch:

```bash
conda activate meti_env
nextflow run main.nf \
  --agentic_only true \
  --pxd_csv assets/pxd_lists/Hamlet_GS_pride_sdrf_union.csv \
  --aggregated_results_dir store/aggregated_results_files \
  --stage_manifest results/agentic_only_stage_manifest.json \
  --outdir results \
  -resume
```

An agentic-only PXD must have `store/aggregated_results_files/PXD######_aggregated_results.json`. HAMLET stops early if an input aggregate is missing.

### runAssessor-only mode

Use this mode to download/convert input and capture runAssessor metadata without running the later stages.

```bash
conda activate meti_env
nextflow run main.nf \
  --pxd PXD000070 \
  --runAssessorOnly true \
  --max_raw_files 1 \
  -resume
```

### Important run controls

| Parameter | When to use it |
|---|---|
| `--acquisition_type AUTO` | Default. Route each PXD from detected acquisition metadata. |
| `--acquisition_type DDA` or `DIA` | Force one search path while debugging. |
| `--num_pxds N` | Take only the first `N` PXD rows from a CSV. |
| `--max_raw_files N` | Limit files per PXD during smoke tests. |
| `--organism_id_all true` | Run de novo/taxonomy on every file instead of using representative-file optimization. |
| `--taxid 9606` | Supply a fallback taxid if taxonomy cannot be inferred. |
| `--central_mzml_dir PATH` | Put fetched/converted spectral data outside the repository. |
| `--outdir PATH` | Put runtime results outside the repository. |
| `-resume` | Reuse successful Nextflow tasks. Use it for normal reruns. |

## Understand Stage Control

HAMLET records per-PXD state in a stage manifest, normally:

```text
results/pipeline_stage_manifest.json
```

The stages are:

```text
fetch
run_assessor
determine_acquisition_params
organism_id
determine_taxids
search
aggregate_results
agentic_metadata_extraction
llm_judge
finalize_sdrf
```

Each stage records `availability`, `complete`, key output paths, and optional forced-rerun state. Do not infer completion only from the Nextflow progress display; inspect the final files listed below and the manifest entry for the PXD.

## Full-Pipeline Stages and Key Outputs

The table uses `PXD######` as a placeholder. Paths are relative to the repository unless you override `--central_mzml_dir` or `--outdir`.

| Stage | What it does | Key intermediate output | What to inspect |
|---|---|---|---|
| `fetch` | Downloads PRIDE RAW files and converts to mzML. | `spectral_files/PXD######/*.mzML` | mzML count and FetchPXD log; ensure there are usable files. |
| `run_assessor` | Examines runs for instruments, labels, and acquisition metadata. | `spectral_files/PXD######/runAssessor/study_metadata.json` | `files` must not be an empty object when mzML inputs exist. |
| `determine_acquisition_params` | Consolidates acquisition type and technical parameters. | `spectral_files/PXD######/detected_params.json` | Confirm DDA/DIA classification before interpreting search output. |
| `organism_id` | Runs de novo peptide sequencing and Peptonizer taxonomy scoring. | `results/PXD######/organism_results/**/peptonizer_result.csv` | Candidate organisms and confidence. This stage can be absent if upstream data is unavailable. |
| `determine_taxids` | Reconciles taxids from PRIDE, LLM, and organism identification. | `results/PXD######/taxid_mapping.json`, `taxid_warnings.json` | Selected taxid and warnings before search. |
| `search` | Runs SAGE for DDA or DIA-NN for DIA and derives PTM/search evidence. | `results/PXD######/search/dda_search/search_results.tsv` or `results/PXD######/search/dia_search/search_results.tsv` | Correct routing, PSM/peptide counts, and search errors. |
| `aggregate_results` | Combines technical, taxonomy, and search outputs. | `results/PXD######/PXD######_aggregated_results.json` | The main structured summary for a full run. |
| `agentic_metadata_extraction` | Extracts biological, design, and technical metadata from publications. | `results/PXD######/agentic_metadata/metadata_extraction_output/integrated_output/*Agent/temp_0.0/PXD######_PubText_enriched.json` | All three Agent JSON files should exist. |
| `llm_judge` | Reviews extracted metadata and produces safe initial corrections. | `results/PXD######/llm_refinement_judge/json_outputs/PXD######_sdrf_overrides.json` | `field_overrides` and `apply_override` decisions. |
| `finalize_sdrf` | Builds the final SDRF, confidence sidecar, and final-SDRF judge report. | `results/PXD######/agentic_metadata/PXD######.sdrf.tsv` | Final SDRF, confidence sidecar, and `sdrf_judge/` report. |
| `results_summary` | Summarizes completed run results. | `results/ResultsSummary.csv` | Batch-level counts and judge metrics. |

## What a Successful PXD Produces

For a successful agentic finalization, start at:

```text
results/PXD######/agentic_metadata/
```

Expected files and directories are:

```text
PXD######.sdrf.tsv
PXD######.confidence.sdrf.tsv
metadata_extraction_output/
  integrated_output/
    BiologicalAgent/temp_0.0/PXD######_PubText_enriched.json
    ExperimentalDesignAgent/temp_0.0/PXD######_PubText_enriched.json
    TechnicalAgent/temp_0.0/PXD######_PubText_enriched.json
llm_refinement_judge/
  json_outputs/PXD######_sdrf_overrides.json
  llm_judge_per_paper.csv
sdrf_judge/
    llm_judge_per_paper.csv
    llm_judge_annotation_review.csv
```

Read the outputs in this order:

1. **`PXD######.sdrf.tsv`**: the final standards-oriented annotation file.
2. **`PXD######.confidence.sdrf.tsv`**: provenance, confidence, selected source, and judge rationale for SDRF fields.
3. **`sdrf_judge/llm_judge_per_paper.csv`** and its annotation review: authoritative evaluation of the final SDRF, not the pre-finalization `llm_refinement_judge` copy.
4. **`PXD######_aggregated_results.json`**: the structured full-pipeline result and run metadata.

## Update the Store After a Run

`store/` is the durable, reviewable layout. Do not copy individual directories by hand. Use the updater:

```bash
python3 src/job_scripts/updatestore.py results store
```

For each PXD, it copies the runtime aggregate JSON when present and **replaces** `store/agentic_results_files/PXD######/` with the current agentic schema. Replacement matters: merging old and new layouts can leave stale `integrated_output/` or old judge files beside current outputs.

Only run the updater on a results root containing finalized PXD directories. For a partially completed batch, construct a filtered results root or wait for finalization; otherwise a PXD with incomplete agentic output can replace a known-good store record.

The Explorer data bundle is rebuilt separately:

```bash
python3 src/job_scripts/build_store_explorer.py \
  --pxd-file assets/pxd_lists/Hamlet_GS_pride_sdrf_union.csv
```

This writes `docs/store-explorer/data/store-index.json` and the web-safe artifacts consumed by GitHub Pages.

## Common Failures and Recovery

### The pipeline exits before work starts

Check that exactly one input mode is set: `--pxd` or `--pxd_csv`. Agentic-only mode also requires every requested aggregate JSON to be present in `--aggregated_results_dir`.

```bash
ls store/aggregated_results_files/PXD000070_aggregated_results.json
nextflow run main.nf --help
```

### Conda environment or executable is missing

Verify `--conda_base`, then rerun setup or activate the environment and test the executable directly.

```bash
source /path/to/miniconda/etc/profile.d/conda.sh
conda activate meti_env
which ThermoRawFileParser
```

### `fetch` has no usable RAW files

`fetch_pxd` can intentionally exit with code 42 when PRIDE has no usable RAW files. Inspect the fetch task log and PRIDE project files. This is a dataset availability issue, not a search failure.

### `run_assessor` looks complete but has no files

An empty `study_metadata.json` can be a partial write after a killed task. HAMLET treats an empty `files` object as incomplete when mzML inputs exist. Delete the invalid output, inspect the task log, and rerun with `-resume`.

### DDA/DIA search is wrong or missing

Inspect `spectral_files/PXD######/detected_params.json`. For diagnosis, force a route with `--acquisition_type DDA` or `--acquisition_type DIA`. Also inspect `taxid_mapping.json`; a missing taxid can prevent a meaningful search.

### Organism identification fails or times out

This stage is allowed to fail without stopping all downstream work. Check GPU availability, the Casanovo/Cascadia environments, the taxonomy files, and the selected taxid. Use `--taxid` as a fallback for a targeted rerun.

### Agentic extraction or judge fails

Confirm `OPENROUTER_API_KEY` is exported in the shell that launches Nextflow. Inspect the task `.command.err` under `work/`, then check whether all three integrated Agent JSON files and `llm_refinement_judge/llm_judge_per_paper.csv` exist.

### SDRF is missing despite a judge output

`finalize_sdrf` is a separate stage. Confirm:

```bash
test -f results/PXD######/agentic_metadata/PXD######.sdrf.tsv
grep -n -A 20 '"PXD######"' results/pipeline_stage_manifest.json
```

The final judge files are created after the SDRF is written. Use `sdrf_judge/llm_judge_per_paper.csv` and `sdrf_judge/llm_judge_annotation_review.csv` to audit the final file. The pre-SDRF refinement judge only supplies bounded, unambiguous overrides during SDRF construction.

### A rerun keeps old outputs

Use `-resume` for normal recovery. If the manifest believes a stage is complete but the output is stale or invalid, inspect its `force_rerun_after` state and the stage's key outputs. Do not delete the whole `work/` directory casually: it is useful for logs and makes debugging harder.

To inspect a failed task:

```bash
find work -name .command.err -print
find work -name .command.err -exec sh -c 'echo "--- $1"; tail -n 80 "$1"' _ {} \;
```

## A Safe First Run Checklist

1. Run one PXD with `--max_raw_files 1` or `3`.
2. Confirm `study_metadata.json`, `detected_params.json`, and `taxid_mapping.json` exist.
3. Confirm one DDA or DIA search result exists under `results/PXD######/search/`.
4. Confirm `PXD######_aggregated_results.json` exists.
5. Confirm the final SDRF and confidence sidecar exist.
6. Read the final `sdrf_judge` report before treating the SDRF as reviewed.
7. Only then expand the batch size or remove `--max_raw_files`.

## Related Documentation

- [README](../../README.md): architecture, parameters, and component overview.
- [Agentic-only workflow](../AGENTIC_ONLY_WORKFLOW.md): focused agentic execution details.
- [Pipeline verification](PIPELINE_VERIFICATION.md): validation-oriented checks.
- [Store README](../../store/README.md): store schema, coverage, and archival conventions.