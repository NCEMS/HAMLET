# HAMLET

**H**ybrid **A**gentic **M**etadata **L**iterature **E**xtraction and **T**echnical annotator

HAMLET is a local Nextflow DSL2 pipeline that processes PRIDE proteomics datasets end-to-end — from raw file download through database search — and produces a structured JSON report per experiment enriched with organism identity, instrument parameters, post-translational modifications, and optionally LLM- and agentic-extracted publication metadata.

## What HAMLET does

1. **Fetches** RAW files from PRIDE and converts them to mzML (via ThermoRawFileParser / ProteoWizard)
2. **Assesses** each run with runAssessor — detects acquisition type (DDA/DIA), labeling, instrument model, fragmentation
3. **Identifies organisms** via de novo peptide sequencing (Casanovo) + Peptonizer2000 taxonomy scoring
4. **Routes searches** automatically — DDA via SAGE, DIA via DIA-NN (controlled by `--acquisition_type`)
5. **Extracts publication metadata** optionally via direct LLM prompting (`--run_llm_extraction`) or a multi-agent agentic pipeline (`--run_agentic_metadata`)
6. **Aggregates** all per-PXD outputs into a single `*_aggregated_results.json` report
7. **Generates SDRF** — the agentic pipeline can produce SDRF-Proteomics v1.1.0 TSV files via `src/python/run_agentic_metadata.py`

The pipeline is **100% container-free**, using conda environments for all tools.

---

## Quick Start

### 1. Prerequisites

| Requirement | Notes |
|------------|-------|
| Linux (x86-64) | Tested on Ubuntu 22.04+ |
| [Nextflow](https://www.nextflow.io/docs/latest/install.html) ≥ 25.04 | `curl -s https://get.nextflow.io \| bash` |
| curl or wget | For Miniconda and file downloads |
| NVIDIA GPU | Optional — speeds up organism identification (Casanovo) |
| ~50 GB free disk | Per PXD (RAW files are 1–3 GB each) |

### 2. Clone and bootstrap

```bash
git clone <repo-url> HAMLET
cd HAMLET
bash src/setup.sh
```

`src/setup.sh` will:
- Install Miniconda if not already present (then ask you to re-run after `source ~/.bashrc`)
- Create four conda environments from [src/conda_envs/](src/conda_envs/):
  - `meti_env` — core tools: FetchPXD, SAGE, runAssessor, aggregation scripts
  - `search_env` — database search dependencies
  - `cascadia_env` — DIA peptide identification (Cascadia)
  - `casanovo_env` — DDA de novo sequencing (Casanovo)
- Verify key executables (`ThermoRawFileParser`, `aria2c`, etc.)

### 3. Download the Cascadia model (required for DIA)

The Cascadia checkpoint (558 MB) is stored separately from the repo:

1. Download `cascadia.ckpt` from [Google Drive](https://drive.google.com/drive/folders/1UTrZIrCdUqYqscbqga_KdX8kc8ZjMMfr?usp=sharing)
2. Place it in the repo:
   ```bash
   mv ~/Downloads/cascadia.ckpt assets/
   ```

If you only process DDA datasets you can skip this step.

### 4. Set your API key (required for LLM/agentic features)

```bash
export OPENAI_API_KEY="sk-..."   # or any OpenAI-compatible key
```

Add this to `~/.bashrc` to make it persistent. The pipeline reads it from the environment — **never put API keys in source files**.

### 5. Verify setup

```bash
conda activate meti_env
which ThermoRawFileParser && which aria2c
python -c "import pandas, sage_runner; print('OK')"
conda deactivate
```

---

## Running the pipeline

### Single PXD (minimal)

```bash
nextflow run main.nf --pxd PXD000070
```

### Single PXD — limit files (for quick testing)

```bash
nextflow run main.nf \
  --pxd PXD000070 \
  --max_raw_files 3 \
  -resume
```

### Batch from CSV

The CSV must have a `PXD` column:
```csv
PXD
PXD000070
PXD000312
PXD000534
```

```bash
nextflow run main.nf \
  --pxd_csv master.csv \
  --num_pxds 10 \
  --max_raw_files 5 \
  -resume
```

### With database search enabled

HAMLET auto-routes each PXD to SAGE (DDA) or DIA-NN (DIA) based on runAssessor detection:

```bash
nextflow run main.nf \
  --pxd PXD000070 \
  --run_search true \
  -resume
```

Force a specific mode or supply a fallback taxid if organism detection may fail:

```bash
nextflow run main.nf \
  --pxd PXD000070 \
  --run_search true \
  --acquisition_type DDA \
  --taxid 9606 \
  -resume
```

### With LLM metadata extraction

```bash
export OPENAI_API_KEY="sk-..."

nextflow run main.nf \
  --pxd_csv master.csv \
  --run_llm_extraction true \
  -resume
```

### With full agentic metadata (LLM + multi-agent enrichment)

```bash
export OPENAI_API_KEY="sk-..."

nextflow run main.nf \
  --pxd_csv master.csv \
  --run_llm_extraction true \
  --run_agentic_metadata true \
  -resume
```

---

## Generating SDRF files

After the pipeline produces `*_aggregated_results.json` outputs, you can generate SDRF-Proteomics v1.1.0 TSV files independently using the agentic metadata script.

**Run the agentic extraction + SDRF conversion for one PXD:**

```bash
python src/python/run_agentic_metadata.py \
  --input results/PXDxxxxxx/PXDxxxxxx_aggregated_results.json \
  --outdir store/agentic_results_files/PXDxxxxxx/ \
  --pride_cache pride_survey/pride_cache \
  --pmc_cache pride_survey/pmc_cache
```

Output: `store/agentic_results_files/PXDxxxxxx/sdrf.tsv`

**Batch run with parallelism (requires GNU parallel):**

```bash
parallel -j 10 < run_agentic_metadata.cmds
```

---

## Parameters

### Input

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--pxd` | — | Single PRIDE accession (mutually exclusive with `--pxd_csv`) |
| `--pxd_csv` | — | CSV file with a `PXD` column |
| `--num_pxds` | all | Limit how many PXDs to read from `--pxd_csv` |

### Download & conversion

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--max_raw_files` | `30` | Max RAW files per PXD (`null` = all) |
| `--use_aria2c` | `true` | Parallel downloads via aria2c |
| `--aria2c_threads` | `4` | aria2c concurrency per download |
| `--download_timeout` | `4h` | Timeout for download + mzML conversion |
| `--max_parallel_pxds` | `10` | Max PXDs fetched at the same time |

### Output

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--outdir` | `results` | Published results directory |
| `--central_mzml_dir` | `spectral_files` | Central store for converted mzML files |

### Acquisition routing

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--acquisition_type` | `AUTO` | `AUTO`, `DDA`, or `DIA` |
| `--auto_detect` | `true` | Use runAssessor to detect acquisition type and labeling |

### Search

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--run_search` | `false` | Enable database search |
| `--taxid` | unset | Fallback taxid if organism detection fails |
| `--sage_config` | `assets/default_sage.config` | SAGE search configuration |
| `--search_min_ptm_psms` | `50` | Min PSMs for a PTM to be included |
| `--search_max_variable_mods` | `3` | Max variable-mod residue types per search |
| `--high_confidence_q_threshold` | `0.01` | spectrum_q threshold for high-confidence PSMs |
| `--min_high_confidence_peptides` | `10` | Min high-confidence PSMs before running PTM-Shepherd |

### Organism identification

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--denovo_threshold` | `70` | Min Casanovo peptide confidence |
| `--min_peptides_for_peptonizer` | `5` | Min peptides required to run Peptonizer2000 |
| `--contaminants_fasta` | `assets/UniversalContaminats.fasta` | Contaminant sequences |
| `--taxid_list_file` | `assets/taxid_lists/CommonPRIDEtaxids.txt` | Allowed taxid list |

### Metadata extraction

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--run_llm_extraction` | `false` | LLM-based metadata extraction from publications |
| `--run_agentic_metadata` | `false` | Multi-agent enrichment after aggregation |
| `--pride_database_path` | `/THISPATHDOESNOTEXIST` | Path to local PRIDE publication text database |
| `--llm_prompt_file` | `src/BaselinePrompt.txt` | Prompt template for LLM extraction |
| `--llm_workers` | `1` | Parallel LLM API calls per PXD |

### Tool paths

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--conda_base` | `~/miniconda3` | Conda installation prefix |
| `--cascadia_model_path` | `assets/cascadia.ckpt` | Cascadia DIA model checkpoint |
| `--peptonizer2000_host_path` | `src/Peptonizer2000` | Peptonizer2000 source directory |

---

## Output layout

Each processed PXD produces a subdirectory under `--outdir`:

```
results/
└── PXDxxxxxx/
    ├── mzML/                                # Converted mzML files
    ├── organism_results/                    # Casanovo + Peptonizer2000 outputs
    ├── search/                              # SAGE or DIA-NN search results
    ├── llm_results/                         # LLM-extracted metadata (if enabled)
    ├── agentic_metadata/                    # Agentic enrichment outputs (if enabled)
    ├── taxid_mapping.json
    ├── taxid_warnings.json
    └── PXDxxxxxx_aggregated_results.json    # ← main output
```

The `*_aggregated_results.json` is the primary deliverable: a single document with runAssessor data, organism identification, search results, PTM fractions, PRIDE metadata, and optionally LLM/agentic enrichments.

---

## Caching and resume

`resume = true` is set globally in [nextflow.config](nextflow.config). Nextflow caches completed tasks in `work/` — keep this directory to avoid re-running expensive steps. You can also pass `-resume` explicitly on the command line.

---

## Repository structure

```
main.nf                      # Pipeline entrypoint
nextflow.config              # All parameters and process resources
src/
  setup.sh                   # Environment bootstrap
  conda_envs/                # Environment YAML definitions
  python/
    run_agentic_metadata.py  # Standalone agentic extraction + SDRF script
    sdrf_builder.py          # AgenticToSDRF class (SDRF-Proteomics v1.1.0)
  agentic-metadata/          # Multi-agent metadata extraction system
  bash/                      # Helper bash scripts
assets/
  cascadia.ckpt              # Cascadia model (download separately)
  default_sage.config        # Default SAGE search parameters
  UniversalContaminats.fasta # Contaminant sequences
  taxid_lists/               # Allowed organism taxid lists
aggregated_results/          # Pre-computed results for reference PXDs
store/                       # Agentic extraction outputs and SDRF files
docs/                        # Implementation notes and architecture docs
```

---

## Troubleshooting

**`command not found: conda`** — Run `source ~/.bashrc` (or `source ~/miniconda3/etc/profile.d/conda.sh`) then retry.

**`ThermoRawFileParser not found`** — The `meti_env` conda environment is not activated. Run `conda activate meti_env`.

**Exit code 42 on `fetch_pxd`** — The PXD contains no usable RAW files (e.g. DIA-NN output only). This is expected and the PXD is skipped automatically.

**Out of memory during search** — Reduce `memory` for the `search` process in [nextflow.config](nextflow.config):
```groovy
withName: search {
    memory = '50 GB'
}
```

**Organism identification times out** — The `organism_id` process has `errorStrategy = 'ignore'`; the pipeline continues without it and falls back to PRIDE metadata for taxid assignment.

**`parallel: command not found`** — Install GNU parallel: `sudo apt install parallel` or `conda install -c conda-forge parallel`.

---

## License

MIT License — see [LICENSE](LICENSE).
