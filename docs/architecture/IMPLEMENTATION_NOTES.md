# Implementation Summary: Native Nextflow Parallel PXD Processing

## Overview

Successfully implemented native Nextflow-based parallel PXD processing, eliminating the need for external Python wrapper scripts. The solution leverages Nextflow's built-in channel operations and parallelism controls.

## Key Changes

### 1. Main Pipeline ([main.nf](main.nf))

**Workflow Changes:**
- Added support for both single PXD (`--pxd`) and CSV-based batch processing (`--pxd_csv`)
- Implemented channel-based parallelism where each PXD flows independently through the pipeline
- Used `.join()` operations to properly combine results from different processes
- Each process now outputs tuples with PXD ID to enable proper result matching

**Process Updates:**
- **fetch_pxd**: Now outputs `tuple(pxd, fetched_dir)` for channel joining
- **parse_runAssessor**: Outputs `tuple(pxd, fetched_dir, detected_params)`
- **organism_id**: Updated to accept and output PXD-tagged tuples
- **sage_search**: Updated to accept and output PXD-tagged tuples
- **aggregate_results**: Updated to accept combined tuple with all results
- All processes now use PXD-specific publishDir paths: `${params.outdir}/${pxd}`

### 2. Configuration ([nextflow.config](nextflow.config))

**New Parameters:**
- `params.pxd_csv`: Path to CSV file containing PXDs (column name: "PXD")
- `params.num_pxds`: Optional limit on number of PXDs to process from CSV
- Changed `params.pxd` default from 'PXD023343' to `null` (must be explicitly specified)
- Updated `download_dir` default to `work/downloads` for better organization
- Set reasonable defaults: `use_aria2c = true`, `max_raw_files = 30`, `casanovo_thresholds = '80'`

**Resource Configuration:**
Already optimized with `maxForks` settings:
- `fetch_pxd`: maxForks = 20 (network-bound)
- `organism_id`: maxForks = 2 (GPU-limited, adjust per your hardware)
- `sage_search`: maxForks = 6 (CPU-intensive)
- `aggregate_results`: maxForks = 10 (I/O-bound)

### 3. New Files

**[PXDs.csv](PXDs.csv)**
- Example CSV file with 4 test PXDs
- Format: Simple CSV with "PXD" column header

**[run_parallel_pxds.sh](run_parallel_pxds.sh)**
- Convenience wrapper script
- Provides easy-to-use interface with sensible defaults
- Usage: `./run_parallel_pxds.sh [num_pxds] [max_files] [csv_file]`

**[PARALLEL_EXECUTION.md](PARALLEL_EXECUTION.md)**
- Comprehensive documentation
- Quick start guide
- Performance tips and troubleshooting
- Comparison with serial processing approach

## How It Works

### Architecture

```
CSV File → Channel Creation → Parallel Processing → Result Aggregation
             ↓                        ↓
        [PXD1, PXD2, ...]    Each PXD flows through:
                             1. fetch_pxd
                             2. parse_runAssessor  
                             3. organism_id (GPU)
                             4. sage_search (CPU)
                             5. aggregate_results
```

### Channel Flow

```nextflow
pxd_ch [PXD1, PXD2, PXD3, ...]
  ↓
fetch_pxd: [(PXD1, dir1), (PXD2, dir2), ...]
  ↓
parse_runAssessor: [(PXD1, dir1, params1), (PXD2, dir2, params2), ...]
  ↓
organism_id: [(PXD1, org_results1), (PXD2, org_results2), ...]
  ↓
.join() operations combine all results
  ↓
aggregate_results: [(PXD1, dir1, org1, sage1), (PXD2, dir2, org2, sage2), ...]
```

### Parallelism Levels

1. **PXD-level**: Multiple PXDs processed simultaneously (limited by process maxForks)
2. **Process-level**: Each process can handle multiple PXDs in parallel
3. **Within-process**: GPU selection, download parallelism, etc.

## Usage Examples

### Basic Usage

```bash
# Single PXD (original behavior)
nextflow run main.nf --pxd PXD000070 -resume

# Multiple PXDs from CSV
nextflow run main.nf --pxd_csv PXDs.csv -resume

# First 5 PXDs only
nextflow run main.nf --pxd_csv PXDs.csv --num_pxds 5 -resume

# Testing with limited files
nextflow run main.nf --pxd_csv PXDs.csv --num_pxds 2 --max_raw_files 3 -resume
```

### Using the Wrapper Script

```bash
# Test with 2 PXDs, 3 files each
./run_parallel_pxds.sh 2 3

# Production: all PXDs, 30 files each
./run_parallel_pxds.sh all 30

# Custom CSV
./run_parallel_pxds.sh 10 30 my_pxds.csv
```

## Advantages Over Sandbox Approach

| Feature | Sandbox (Python + GNU Parallel) | This Implementation |
|---------|----------------------------------|---------------------|
| **Complexity** | Python wrapper + isolated NF instances | Pure Nextflow |
| **Parallelism** | GNU parallel manages separate NF jobs | Native NF parallelism |
| **Resource Management** | Manual via -j parameter | Automatic via maxForks |
| **Resume Capability** | Per-PXD basis | Global with shared cache |
| **Monitoring** | Separate logs per PXD | Unified NF dashboard |
| **GPU Scheduling** | Manual per-job | Automatic load balancing |
| **Maintainability** | Two systems to maintain | Single system |
| **Scalability** | Limited by shell parallelism | Scales to cluster/cloud |

## Performance Characteristics

### With 2 GPUs, 128 CPU cores:

- **Downloads (fetch_pxd)**: Up to 20 PXDs downloading simultaneously
- **GPU Processing (organism_id)**: 2 PXDs simultaneously (1 per GPU)
- **CPU Processing (sage_search)**: Up to 6 PXDs simultaneously
- **Aggregation**: Up to 10 PXDs simultaneously

### Expected Throughput:

The pipeline will maintain a steady state where:
- Multiple PXDs are downloading
- 2 PXDs are in GPU processing
- Multiple PXDs are in CPU-intensive SAGE search
- Multiple PXDs are aggregating results

This maximizes resource utilization without overwhelming any single resource.

## Testing Recommendations

1. **Quick Test** (verify pipeline works):
   ```bash
   ./run_parallel_pxds.sh 2 3
   ```

2. **Resource Test** (verify no overload):
   ```bash
   ./run_parallel_pxds.sh 5 10
   # Monitor with: htop, nvidia-smi
   ```

3. **Production Test** (verify at scale):
   ```bash
   ./run_parallel_pxds.sh 10 30
   ```

## Migration from Sandbox

If you were using `sandbox/run_pxds.py`:

**Old:**
```bash
cd sandbox
python src/python/run_pxds.py -n 5 --max-raw-files 30
```

**New:**
```bash
nextflow run main.nf --pxd_csv PXDs.csv --num_pxds 5 --max_raw_files 30 -resume
# or use the wrapper:
./run_parallel_pxds.sh 5 30
```

## Next Steps

1. Test with existing PXDs to verify functionality
2. Adjust `maxForks` settings based on your specific hardware
3. Consider adding custom profiles for different execution environments
4. Monitor resource usage and tune accordingly

## Technical Notes

### Why Nextflow Native is Better

1. **Single Work Directory**: All PXDs share the same work directory, enabling better caching
2. **Unified Resume**: One `-resume` works across all PXDs
3. **Resource Awareness**: Nextflow knows about all processes and can schedule optimally
4. **No Isolation Overhead**: No need for per-PXD Nextflow instances
5. **Better Error Handling**: Failed PXDs don't affect others, all can resume independently
6. **Future-Proof**: Can easily migrate to HPC/cloud with executor changes

### Potential Enhancements

Future improvements could include:
- Add support for multiple CSV files
- Implement custom resource profiles (test, production, cluster)
- Add real-time progress monitoring endpoint
- Integrate with workflow management systems
- Add metadata tracking database
