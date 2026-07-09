# Running the Full HAMLET Pipeline on a Single Test PXD

This guide explains how to run the complete HAMLET Nextflow pipeline on a single PXD for testing and validation.

## Quick Start

```bash
# Run full pipeline on a single PXD
./run_single_pxd_test.sh PXD000070

# Quick test (limit to 3 RAW files)
./run_single_pxd_test.sh PXD000070 --max_raw_files 3

# Resume a previous run
./run_single_pxd_test.sh PXD000070 -resume

# Using SLURM executor
./run_single_pxd_test.sh PXD000070 --profile slurm
```

## What the Pipeline Does

The full HAMLET pipeline performs these stages in order:

1. **Fetch** — Download RAW files from PRIDE and convert to mzML
2. **Run Assessor** — Detect DDA/DIA, instrument, labeling, fragmentation
3. **Determine Acquisition Params** — Set search parameters based on acquisition type
4. **Search** — DDA via SAGE, DIA via DIA-NN
5. **Aggregation** — Combine all results into a single JSON report
6. **Agentic Metadata Extraction** — Extract publication metadata via LLMs (optional)

## Prerequisites

### 1. HAMLET Setup

Ensure the basic HAMLET setup is complete:

```bash
cd /mnt/storage_1/HAMLET
bash src/setup.sh
```

This creates the required conda environments and downloads the NCBI taxonomy database.

### 2. Nextflow Installation

```bash
# Check if installed
nextflow --version

# If not installed
curl -s https://get.nextflow.io | bash
sudo mv nextflow /usr/local/bin/
```

### 3. API Keys (Optional, for LLM/Agentic Features)

For publication text extraction via LLMs:

```bash
export OPENAI_API_KEY="sk-..."
```

### 4. Disk Space

Ensure sufficient free disk space (per PXD):
- Minimal (3 RAW files): ~10 GB
- Full PXD: 50–150 GB (depending on dataset size)

## Usage

### Basic Run: Full Pipeline

```bash
./run_single_pxd_test.sh PXD000070
```

This will:
1. Download all RAW files from PRIDE
2. Run the complete analysis pipeline
3. Generate `results/PXD000070/PXD000070_aggregated_results.json`
4. Produce agentic metadata and SDRF files (if LLM API key is set)

**Estimated time:** 1–4 hours (depending on dataset size)

### Quick Test: Limit RAW Files

For fast validation, process only the first few RAW files:

```bash
./run_single_pxd_test.sh PXD000070 --max_raw_files 3
```

**Estimated time:** 15–30 minutes

### Resume Previous Run

If a run was interrupted, resume from the last checkpoint:

```bash
./run_single_pxd_test.sh PXD000070 -resume
```

Nextflow will skip completed stages and continue from where it left off.

### Force Acquisition Type

If automatic detection fails, force DDA or DIA:

```bash
./run_single_pxd_test.sh PXD000070 --acquisition_type DDA
./run_single_pxd_test.sh PXD000070 --acquisition_type DIA
```

### Provide Fallback Taxid

If organism identification fails, provide a known taxid:

```bash
./run_single_pxd_test.sh PXD000070 --taxid 9606  # Human
```

### Using SLURM Executor

Run on an HPC cluster with SLURM:

```bash
./run_single_pxd_test.sh PXD000070 --profile slurm
```

This requires SLURM configuration in `nextflow.config`.

### Debug Mode (Verbose Output)

```bash
./run_single_pxd_test.sh PXD000070 --debug_mode true
```

## Output Structure

After the pipeline completes, results will be in `results/PXD000070/`:

```
results/PXD000070/
├── PXD000070_aggregated_results.json          # Main output (all results)
├── agentic_metadata/
│   ├── PXD000070.sdrf.tsv                     # SDRF-Proteomics v1.1.0
│   └── metadata_extraction_output/
│       ├── TechnicalAgent/
│       ├── BiologicalAgent/
│       └── ExperimentalDesignAgent/
├── raw_files/                                 # Downloaded mzML files
├── search_results/
│   ├── SAGE_results/ (for DDA)
│   ├── DIA_NN_results/ (for DIA)
│   └── ...
├── per_run_files/                             # Per-RAW-file metadata
└── logs/                                      # Pipeline logs
```

### Key Output: Aggregated Results JSON

```bash
# Inspect the main output
head -20 results/PXD000070/PXD000070_aggregated_results.json | python -m json.tool

# Count identified peptides
python -c "import json; d=json.load(open('results/PXD000070/PXD000070_aggregated_results.json')); print(f\"Peptides: {len(d['peptides'])}\")"
```

### Key Output: SDRF File

If LLM extraction succeeded, an SDRF file is available:

```bash
# View columns
head -1 results/PXD000070/agentic_metadata/PXD000070.sdrf.tsv

# Count samples
wc -l results/PXD000070/agentic_metadata/PXD000070.sdrf.tsv
```

## Monitoring Progress

### View Nextflow Log

```bash
# Real-time monitoring (requires separate terminal)
tail -f .nextflow.log
```

### List Running/Completed Tasks

```bash
# After pipeline completes
ls -lh results/PXD000070/
```

## Troubleshooting

### Error: "Invalid PXD format"

**Solution:** Use format `PXDxxxxxx` (6 digits after PXD):
```bash
./run_single_pxd_test.sh PXD000070  # ✓ Correct
./run_single_pxd_test.sh PXD00070   # ✗ Wrong (5 digits)
```

### Error: "Nextflow not found"

**Solution:** Install Nextflow:
```bash
curl -s https://get.nextflow.io | bash
sudo mv nextflow /usr/local/bin/
```

### Error: "main.nf not found"

**Solution:** Run from the HAMLET repository root:
```bash
cd /mnt/storage_1/HAMLET
./run_single_pxd_test.sh PXD000070
```

### Error: "Conda environment not found"

**Solution:** Run setup:
```bash
bash src/setup.sh
```

### Error: "Cannot download RAW files"

**Solution:** Check internet connection and PRIDE server status. Or provide pre-downloaded files.

### Error: "Out of disk space"

**Solution:** Increase available disk space or use `--max_raw_files` to limit processing:
```bash
./run_single_pxd_test.sh PXD000070 --max_raw_files 2
```

### Error: "LLM API key not set" (for agentic stages)

**Solution:** Set the API key:
```bash
export OPENAI_API_KEY="sk-..."
./run_single_pxd_test.sh PXD000070
```

## Performance Tips

| Scenario | Command | Time |
|----------|---------|------|
| Quick validation | `--max_raw_files 2` | 10–20 min |
| Standard test | `--max_raw_files 5` | 30–60 min |
| Full pipeline | (no limit) | 1–4 hours |
| SLURM cluster | `--profile slurm -resume` | Varies |

## Advanced Usage

### Custom Nextflow Config

```bash
./run_single_pxd_test.sh PXD000070 -c custom.config
```

### Skip Certain Stages

Modify `nextflow.config` or use stage manifest (see README.md for details).

### Batch Processing Multiple PXDs

```bash
for pxd in PXD000070 PXD000312 PXD000534; do
    echo "Processing $pxd..."
    ./run_single_pxd_test.sh "$pxd" --max_raw_files 3 || echo "Failed: $pxd"
done
```

## Testing with Pre-configured Datasets

HAMLET provides curated test PXD lists for validation:

```bash
# Quick 2-PXD smoke test
nextflow run main.nf \
    --pxd_csv assets/pxd_test_files/PXDsTest.csv \
    --max_raw_files 3 \
    -resume

# Comprehensive 20-PXD test
nextflow run main.nf \
    --pxd_csv assets/pxd_test_files/ConsolidatedTestPXDs.csv \
    --num_pxds 20 \
    --max_raw_files 5 \
    -resume
```

See `assets/pxd_test_files/README.md` for details on test datasets.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (none) | OpenAI API key for LLM extraction |
| `LLM_API_KEY` | (none) | Alternative API key variable |
| `NEXTFLOW_HOME` | `~/.nextflow` | Nextflow config directory |

## Related Documentation

- **Main README:** [README.md](../README.md) — Full pipeline documentation
- **Test Files:** [assets/pxd_test_files/README.md](../assets/pxd_test_files/README.md) — Test dataset information
- **Architecture:** [docs/ARCHITECTURE.md](ARCHITECTURE.md) — Pipeline design
- **Script:** [./run_single_pxd_test.sh](../run_single_pxd_test.sh)

## FAQ

### Q: How long does a full run take?

**A:** Typically 1–4 hours per PXD, depending on dataset size and computational resources. Use `--max_raw_files` to limit processing for faster testing.

### Q: Can I run multiple PXDs in parallel?

**A:** Yes, use Nextflow's built-in parallelism or run multiple scripts in the background. See "Batch Processing" above.

### Q: What if a stage fails?

**A:** The pipeline continues (most stages have `errorStrategy 'ignore'`). Check `.nextflow.log` or `results/PXD000070/logs/` for error details. Resume with `-resume` to skip completed stages.

### Q: Can I use this on Windows?

**A:** The script is bash-based. Use WSL2 (Windows Subsystem for Linux) or Git Bash.

### Q: How do I view detailed logs?

**A:** Check:
- `.nextflow.log` — Nextflow execution log
- `results/PXD000070/logs/` — Per-stage logs
- `work/` — Intermediate task files

---

**Last Updated:** 2026  
**Script Location:** `./run_single_pxd_test.sh`  
**Documentation:** `docs/RUNNING_SINGLE_PXD_AGENTIC.md`
