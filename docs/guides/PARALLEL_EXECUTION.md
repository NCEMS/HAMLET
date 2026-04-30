# Parallel PXD Processing

This pipeline now supports processing multiple PXDs in parallel, fully leveraging your available compute resources. All parallelization is handled natively by Nextflow without requiring external wrapper scripts.

## Quick Start

### Process Multiple PXDs from CSV

```bash
# Process all PXDs in PXDs.csv
nextflow run main.nf --pxd_csv PXDs.csv -resume

# Process first 5 PXDs (for testing)
nextflow run main.nf --pxd_csv PXDs.csv --num_pxds 5 -resume

# Process with limited files per PXD (for quick testing)
nextflow run main.nf --pxd_csv PXDs.csv --num_pxds 2 --max_raw_files 3 -resume
```

### Process Single PXD (Original Mode)

```bash
# Process a single PXD
nextflow run main.nf --pxd PXD000070 -resume
```

## CSV File Format

Your CSV file should have a header row with a column named `PXD`:

```csv
PXD
PXD000070
PXD002619
PXD005207
PXD022741
```

## How Parallelization Works

### Automatic Parallel Execution

Nextflow automatically parallelizes the pipeline at multiple levels:

1. **Multiple PXDs in Parallel**: Multiple PXDs are processed simultaneously based on resource availability
2. **Process-Level Parallelism**: Each PXD goes through the pipeline stages independently
3. **Resource Management**: Nextflow respects the `maxForks` settings in `nextflow.config` to prevent resource overload

### Resource Allocation

The `nextflow.config` defines maximum parallelism per process:

- **fetch_pxd**: `maxForks = 20` - Download operations are network-bound
- **organism_id**: `maxForks = 2` - Limited by GPU count (adjust based on your GPUs)
- **sage_search**: `maxForks = 6` - CPU-intensive, adjust based on available cores
- **aggregate_results**: `maxForks = 10` - Light I/O operations

### GPU Management

The pipeline includes automatic GPU selection:
- Each GPU-requiring process automatically selects the GPU with the most free memory
- Set `maxForks` in the organism_id process to match your GPU count
- With 2 GPUs: `maxForks = 2` means up to 2 PXDs using GPUs simultaneously

## Example Workflows

### Test Run (Quick Validation)

```bash
# Test with 2 PXDs, 3 files each
./run_parallel_pxds.sh 2 3
```

### Production Run (All PXDs, Limited Files)

```bash
# Process all PXDs with max 30 files each
./run_parallel_pxds.sh all 30
```

### Full Processing

```bash
# Process all PXDs with all their files
nextflow run main.nf --pxd_csv PXDs.csv --max_raw_files null -resume
```

## Monitoring Progress

### View Pipeline Status

```bash
# Nextflow provides real-time progress updates
# You'll see output like:
# executor >  local (15)
# [8f/123abc] process > fetch_pxd (PXD000070)      [100%] 4 of 4 ✔
# [a2/456def] process > organism_id (PXD000070)    [ 50%] 2 of 4
```

### Check Completed Results

```bash
# List all completed PXDs
ls results/*/PXD*_aggregated_results.json

# Count completed PXDs
find results -name "*_aggregated_results.json" | wc -l
```

### View Logs

```bash
# Nextflow logs are in .nextflow.log
tail -f .nextflow.log

# Process-specific logs are in work directories
# Find the work directory for a specific process from the output or .nextflow.log
```

## Output Structure

```
results/
├── PXD000070/
│   ├── PXD000070_aggregated_results.json
│   ├── organism_results/
│   └── detected_params.json
├── PXD002619/
│   ├── PXD002619_aggregated_results.json
│   ├── organism_results/
│   └── detected_params.json
└── ...

work/
├── downloads/
│   ├── PXD000070/  (storeDir - permanent cache)
│   ├── PXD002619/  (storeDir - permanent cache)
│   └── ...
└── [hash]/  (work directories for each process execution)
```

## Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--pxd_csv` | null | CSV file containing PXDs to process |
| `--pxd` | null | Single PXD to process |
| `--num_pxds` | null | Limit number of PXDs from CSV (null = all) |
| `--max_raw_files` | 30 | Maximum raw files to download per PXD |
| `--use_aria2c` | true | Use aria2c for faster parallel downloads |
| `--aria2c_threads` | 8 | Number of download threads for aria2c |
| `--casanovo_thresholds` | 80 | Confidence threshold for Casanovo |
| `--min_peptides_for_peptonizer` | 5 | Minimum peptides for organism ID |
| `--run_sage` | false | Enable SAGE/DIA-NN quantification |
| `--auto_detect` | true | Auto-detect acquisition type (DIA/DDA) |

## Performance Tips

### Optimize for Your Hardware

1. **Adjust GPU parallelism**: Edit `nextflow.config` → `organism_id.maxForks` to match your GPU count
2. **Adjust CPU parallelism**: Edit `nextflow.config` → `sage_search.maxForks` based on available cores
3. **Monitor resource usage**: Use `htop` and `nvidia-smi` to ensure you're not over-allocating

### Resume Failed Runs

Nextflow's `-resume` flag caches completed work:

```bash
# If a run fails or is interrupted, simply resume:
nextflow run main.nf --pxd_csv PXDs.csv -resume
```

Only failed or incomplete processes will be re-executed.

### Clean Up

```bash
# Remove work directory (but keep downloads cache)
rm -rf work/[0-9a-f][0-9a-f]

# Clean everything (including cached downloads)
nextflow clean -f -k
rm -rf work
```

## Comparison to Serial Processing

| Aspect | Serial (sandbox/run_pxds.py) | Parallel (Native Nextflow) |
|--------|------------------------------|----------------------------|
| Parallelism | One PXD at a time | Multiple PXDs simultaneously |
| Resource Usage | Underutilized | Full resource utilization |
| Fault Tolerance | Prompt to continue | Automatic retry with -resume |
| Monitoring | Python logs | Nextflow dashboard + logs |
| Complexity | Python wrapper + Nextflow | Pure Nextflow (simpler) |
| Scalability | Limited by serial execution | Scales with available resources |

## Troubleshooting

### Pipeline Hangs or Runs Out of Memory

Reduce parallelism in `nextflow.config`:
```groovy
withName: organism_id {
    maxForks = 1  // Reduce GPU parallelism
}
```

### Downloads Fail

Try reducing download threads:
```bash
nextflow run main.nf --pxd_csv PXDs.csv --aria2c_threads 4 -resume
```

### GPU Out of Memory

Reduce number of files processed or GPU parallelism:
```bash
nextflow run main.nf --pxd_csv PXDs.csv --max_raw_files 10 -resume
```

## Advanced: Custom Resource Profiles

You can create custom configuration profiles for different execution environments:

```groovy
// nextflow.config
profiles {
    test {
        params.max_raw_files = 3
        params.num_pxds = 2
    }
    
    production {
        params.max_raw_files = null  // All files
        process.withName: organism_id {
            maxForks = 4  // If you have 4 GPUs
        }
    }
}
```

Then run with:
```bash
nextflow run main.nf --pxd_csv PXDs.csv -profile production -resume
```
