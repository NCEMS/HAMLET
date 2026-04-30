# Pooling Strategy Quick Reference

## What is a Pooling Strategy?

A pooling strategy controls whether SAGE open and closed searches run on **all files together** (pooled) or **each file individually** (per-file).

- **Pooled searches**: Faster, files share database hits and modifications
- **Per-file searches**: Slower, each file analyzed independently, better quantification per sample

## Strategy Selection Guide

### `--sage_pooling_strategy both` (DEFAULT)
```
Open Search:   Pooled (all files together)
Closed Search: Pooled (all files together)
```
- ✅ **Fastest** - single run for each search type
- ✅ **Recommended** for initial analysis or when speed matters
- ⚠️ Sample identity may be lost during pooling
- **Use case**: Large studies, batch processing, discovery

**Command**:
```bash
nextflow run main.nf --input_csv PXDs.csv
# or explicitly:
nextflow run main.nf --input_csv PXDs.csv --sage_pooling_strategy both
```

---

### `--sage_pooling_strategy open_only` (Per-File Closed Search)
```
Open Search:   Pooled (all files together)
Closed Search: Per-file (each file individually)
```
- ✅ **Preserves per-sample quantification** - each file gets own closed search
- ✅ **Moderate speed** - open search fast, closed search slower
- ✅ **PTM knowledge shared** - modifications identified in pooled open search
- ⚠️ **Now fully implemented** - broken in previous versions
- **Use case**: When sample-level quantification matters more than speed

**Command**:
```bash
nextflow run main.nf --input_csv PXDs.csv --sage_pooling_strategy open_only
```

**What this does**:
1. All files searched together in open search → find modifications
2. Each file searched individually in closed search → count peptides per sample
3. Results aggregated with per-file tracking

**Output**: `per_file_search.log` shows progress; `metadata.json` shows per-file success rates

---

### `--sage_pooling_strategy closed_only` (Per-File Open Search)
```
Open Search:   Per-file (each file individually)
Closed Search: Pooled (all files together)
```
- 🔧 **Not yet implemented** - do not use
- Would allow per-sample PTM discovery
- Performance tbd

**Status**: Planning phase, use `open_only` instead

---

### `--sage_pooling_strategy none` (Complete Per-File)
```
Open Search:   Per-file (each file individually)
Closed Search: Per-file (each file individually)
```
- 🔧 **Not yet implemented** - do not use
- Would provide maximum sample isolation
- Slowest option

**Status**: Planning phase, use `open_only` for per-sample quantification

---

## Decision Tree

Choose your pooling strategy:

```
Is speed most important?
├─ YES → Use '--sage_pooling_strategy both' (default)
│
├─ NO → Do you need per-sample quantification?
│        ├─ YES → Use '--sage_pooling_strategy open_only'
│        │
│        └─ NO (need per-sample PTMs?)
│             └ Use '--sage_pooling_strategy both'
```

## Common Scenarios

### Scenario 1: Large Batch Analysis (100s of PXDs)
```bash
nextflow run main.nf --input_csv AllPXDs.csv --sage_pooling_strategy both
```
- Fastest approach
- Good for discovery and PTM validation
- Results are batch-wide, not per-sample

### Scenario 2: Per-Sample Quantification Study (20-50 PXDs)
```bash
nextflow run main.nf --input_csv PXDs.csv --sage_pooling_strategy open_only
```
- Moderate performance
- Each sample analyzed individually in closed search
- Quantification values reflect each sample independently
- Uses pooled PTMs from open search

### Scenario 3: Method Comparison (small subset)
```bash
# Compare both strategies:
nextflow run main.nf --input_csv TestPXDs.csv --sage_pooling_strategy both
nextflow run main.nf --input_csv TestPXDs.csv --sage_pooling_strategy open_only -resume
```
- Run both strategies on same data
- Use `-resume` to skip re-processing reads
- Compare open/closed search strategies

## Performance Metrics (Estimated)

For a typical PXD with 500 .mzML files:

| Strategy | Open Search | Closed Search | Total |
|----------|-------------|---------------|-------|
| `both` | 30 min | 2-4 hours | 2.5-4.5 hours |
| `open_only` | 30 min | 30-60 min × 500 files* | ~250-500 hours |
| Both (parallel) | 30 min | 30-60 min (parallel) | ~1.5-1.75 hours* |

*Per-file closed search can be parallelized by Nextflow - actual time depends on available CPU cores.

**Tip**: For large `open_only` runs, increase `-with-dag` parallelization:
```bash
nextflow run main.nf --input_csv PXDs.csv \
  --sage_pooling_strategy open_only \
  -qs 10  # 10 concurrent processes
```

## Monitoring Per-File Searches

When using `open_only`, check progress:

```bash
# Monitor the per-file search log
watch -n 5 'tail -20 results/PXD001234/Pass_2/per_file_search.log'

# Check success rate
tail results/PXD001234/Pass_2/per_file_search.log | grep -E "Successful:|Failed:"

# View per-file metadata
jq . results/PXD001234/Pass_2/metadata.json
```

## Troubleshooting

### Problem: `--sage_pooling_strategy open_only` taking too long
**Solution**:
- Enable Nextflow parallelization: `-qs 20` or higher
- Check individual file size in logs
- Very large .mzML files take proportionally longer per file

### Problem: Results don't match between `both` and `open_only`
**Expected**: Different results are normal!
- **Pooled** (both): All files contribute to modification database in closed search
- **Per-file** (open_only): Each file searches only its own spectra against modifications from open search
- Largest files more likely to find peptides in `open_only` per-file mode

### Problem: Some files failed in `open_only`
**Check**:
- View `results/PXD123456/Pass_2/metadata.json` for per-file status
- Look at specific file log: `results/PXD123456/Pass_2/filename/sage.log`
- Likely causes: corrupted mzML, permission denied, or memory issues

## Advanced: Custom Strategy Combinations

Planning future work:

```bash
# Future: Per-file open with pooled closed
--sage_pooling_strategy closed_only

# Future: Complete per-file isolation
--sage_pooling_strategy none
```

These will be implemented based on research needs.

---

## Quick Command Reference

```bash
# Fastest (default) - pooled both open and closed
nextflow run main.nf --input_csv PXDs.csv

# Per-sample quantification - pooled open, per-file closed
nextflow run main.nf --input_csv PXDs.csv --sage_pooling_strategy open_only

# Resumable run (skip already-done steps)
nextflow run main.nf --input_csv PXDs.csv --sage_pooling_strategy open_only -resume

# Run with more parallelization (10 concurrent processes)
nextflow run main.nf --input_csv PXDs.csv --sage_pooling_strategy open_only -qs 10

# Run on small test subset first
nextflow run main.nf --input_csv TestPXDs.csv --sage_pooling_strategy open_only
```

---

**Last Updated**: 2025-01-26
**Implemented Strategies**: `both` (default), `open_only` (per-file closed search)
**Status**: Core per-file functionality now fully operational
