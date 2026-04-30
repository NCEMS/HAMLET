# HAMLET annotator Unified Container Refactoring

## Overview

The HAMLET annotator pipeline has been refactored to use a **single unified Singularity container** instead of 8 separate containers + 3 conda environments. This significantly simplifies deployment, reduces maintenance overhead, and ensures consistent tool versions across all pipeline stages.

## What Changed

### Before Refactoring
- **Multiple containers**: pride-fetch, organism-id, organism-id_DIA, DiaNN, sage, llm-extraction, agentic-metadata, proteowizard
- **Multiple conda environments**: base, casanovo_env, cascadia_env, search_env
- Complex orchestration to manage tool paths and inter-container dependencies
- Duplicated system dependencies across containers

### After Refactoring
- **Single unified container**: `meti-unified.sif`
- **Single conda environment**: `meti` (consolidated from all previous environments)
- All tools pre-installed and on PATH
- Simpler nextflow pipeline with consistent container usage
- Faster execution (no repeated singularity container pulls)

## Container Contents

The unified container includes:

### System Dependencies
- Build tools (gcc, make, cmake, pkg-config)
- Java 17 (for PTM-Shepherd)
- Language support (Python 3.11, Git, curl, wget, etc.)
- X11 libraries (for plotting, visualization)
- Format conversion tools (ThermoRawFileParser)

### Python Environment (micromamba-based)
- **Core packages**: pandas, numpy, scipy, scikit-learn, PyArrow, PyYAML
- **Proteomics**: Casanovo, Cascadia, pyteomics, protkolearn
- **De novo**: Snakemake (for workflow orchestration in OrganismID)
- **ML**: PyTorch, accelerate
- **LLM**: OpenAI, LiteLLM, LangChain
- **Utilities**: tqdm, Click, networkx, Pydantic, requests

### Search Tools (pre-downloaded binaries)
- **SAGE v0.14.7**: Database search engine
- **DIA-NN 2.2.0**: Data-independent acquisition analysis
- **PTM-Shepherd 2.0.5**: Post-translational modification discovery
- **dotnet 8.0**: Runtime for DIA-NN .raw file support

### Baked-In Dependencies
- **Peptonizer2000**: Taxonomic inference engine (from `/src/Peptonizer2000`)
- **ThermoRawFileParser**: Raw file conversion
- **Environment variables**: Pre-configured for all tools

## Building the Container

### Prerequisites
- Singularity 3.10+ installed
- ~15 GB disk space for container build and download of large binaries
- Internet access for downloading tool binaries and dependencies

### Build Command

```bash
cd /mnt/storage_2/Production

# Build the container (this will take 5-15 minutes depending on network)
singularity build containers/meti-unified.sif containers/meti-unified.def

# Optional: Verify the container
singularity exec containers/meti-unified.sif python --version
singularity exec containers/meti-unified.sif sage --version
singularity exec containers/meti-unified.sif diann --help
```

### Build Tips
- **First build**: Download buffers may make this slower (~10-15 min)
- **Subsequent rebuilds**: Use `--force` to rebuild or add changes to `.def`
- **Troubleshooting**: If a tool download fails, the build will stop. Check network connectivity and tool URLs in the `.def` file.

## Running the Pipeline

### Basic Usage (No Changes)

The pipeline usage is identical:

```bash
# Single PXD
nextflow run main.nf --pxd PXD000070 --run_search true -resume

# Batch processing
nextflow run main.nf --pxd_csv PXDs.csv --max_parallel_pxds 10 -resume

# DIA-specific
nextflow run main.nf --pxd_csv PXDs.csv --acquisition_type DIA -resume
```

### Updated Configuration

**New parameter** in nextflow.config:
```groovy
params.unified_container = "${baseDir}/containers/meti-unified.sif"
```

**Removed parameters** (no longer needed):
```groovy
// These are now baked into the unified container:
// - fetch_container
// - organism_container
// - organism_dia_container
// - diann_container
// - sage_container
// - llm_container
// - agentic_metadata_container
// - casanovo_env_path
// - cascadia_env_path
// - search_env_path
// - conda_exe
// - organismid_python
```

**Unchanged parameters**:
- `cascadia_model_path`: Still mounted from host (large model file)
- `sage_config`: Pipeline configuration (mounted from host)
- Other data paths, PXD input, search thresholds, etc.

## Process-by-Process Changes

### 1. **fetch_pxd**
- **Before**: Ran on host with access to separate ProteoWizard container
- **After**: Now uses unified container with ThermoRawFileParser built-in
- **Impact**: Faster, cleaner code, no need for external singularity calls

### 2. **parse_runAssessor**
- **Before**: Used `${params.fetch_container}`
- **After**: Uses `${params.unified_container}`
- **Impact**: No functional change, reduced container overhead

### 3. **organism_id**
- **Before**: Ran on-host with conda environments (casanovo_env, cascadia_env)
- **After**: Uses unified container with all tools on PATH
- **Impact**: Simpler script, no more conda activation or environment path passing
- **Changes to script**:
  - Removed: conda_exe, casanovo_env_path, cascadia_env_path parameters
  - Added: Direct `python` call (uses container python automatically)

### 4. **search**
- **Before**: Ran on-host with `${params.search_env_path}` conda environment
- **After**: Uses unified container with SAGE, DIA-NN, PTM-Shepherd on PATH
- **Impact**: Simpler setup, no conda environment activation needed
- **Changes to script**:
  - Removed: Conda environment path resolution
  - Changed: `SEARCH_PY` now hardcoded to `python` (uses container python)
  - Unchanged: Search orchestration logic

### 5. **determine_taxids**
- **Before**: Used `${params.organism_container}`
- **After**: Uses `${params.unified_container}`
- **Impact**: No functional change

### 6. **llm_extraction**
- **Before**: Used `${params.llm_container}`
- **After**: Uses `${params.unified_container}`
- **Impact**: Includes LLM dependencies (OpenAI, LangChain)

### 7. **aggregate_results**
- **Before**: Used `${params.organism_container}`
- **After**: Uses `${params.unified_container}`
- **Impact**: No functional change

### 8. **agentic_metadata_extraction**
- **Before**: Used `${params.agentic_metadata_container}`
- **After**: Uses `${params.unified_container}`
- **Impact**: Now includes agentic-metadata dependencies

## Files Modified

- **New file**: `containers/meti-unified.def` - The unified container definition
- **Modified**: `nextflow.config` - Updated container references, removed conda env paths
- **Modified**: `main.nf` - Updated all processes to use unified container, simplified scripts
- **Preserved**: All Python scripts in `src/python/` work unchanged

## Testing & Validation

### Post-Refactoring Tests

1. **Container build verification**:
   ```bash
   singularity inspect containers/meti-unified.sif
   singularity shell containers/meti-unified.sif
   # Inside container:
   python --version
   which python
   sage --version
   diann --help > /dev/null && echo "DIA-NN OK"
   java -version
   ```

2. **Single PXD test**:
   ```bash
   nextflow run main.nf --pxd PXD000070 --run_search false -resume
   ```

3. **Batch test**:
   ```bash
   nextflow run main.nf --pxd_csv PXDsing.csv --num_pxds 3 -resume
   ```

4. **Search test**:
   ```bash
   nextflow run main.nf --pxd PXD000070 --run_search true -resume
   ```

5. **DIA workflow test**:
   ```bash
   nextflow run main.nf --pxd PXD025663 --acquisition_type DIA -resume
   ```

### Expected Behavior
- All PXDs should process through all stages
- No changes to output format or results quality
- Pipeline should complete faster (no container startup overhead)
- Error messages should be the same or clearer (no container layer confusion)

## Troubleshooting

### Issue: Container Build Fails
**Solution**: Check network access and tool URLs in `meti-unified.def`

### Issue: Tools Not Found in Container
**Solution**: Verify container was built successfully and mounted correctly:
```bash
singularity exec containers/meti-unified.sif which sage
singularity exec containers/meti-unified.sif echo $PATH
```

### Issue: Python Script Can't Import Module
**Solution**: Module is in unified container but not activated:
```bash
# Inside container, python automatically activates meti conda env
python -c "import casanovo; print(casanovo.__version__)"
```

### Issue: "permission denied" when running singularity
**Solution**: Ensure container file is readable:
```bash
chmod 644 containers/meti-unified.sif
ls -lh containers/meti-unified.sif
```

## Performance Improvements

- **Container startup**: Faster (single container, not 8)
- **Disk usage**: Slightly reduced (consolidated dependencies)
- **Build time**: One-time cost of ~15 minutes (vs. multiple container builds)
- **Runtime**: No change to actual pipeline execution (tools are same)

## Migration Notes for Users

### If You Created Custom Environments
If you modified the conda environments, you'll need to update `meti-unified.def` and rebuild.

### If You Have Local Containers
Old containers (pride-fetch.sif, organism-id.sif, etc.) can be removed:
```bash
rm containers/pride-fetch.sif containers/organism-id.sif containers/sage.sif \
   containers/DiaNN.sif containers/llm-extraction.sif containers/agentic-metadata.sif
# Keep containers/proteowizard/ if used elsewhere
```

### If You're Using the Pipeline in Docker
You can still build a Docker image from this, but Singularity is the primary target.

## Future Maintenance

### Adding a New Tool
1. Update `meti-unified.def` (%post section)
2. Rebuild: `singularity build containers/meti-unified.sif containers/meti-unified.def`
3. Update docs if parameters change

### Updating Tool Versions
1. Modify version numbers in `meti-unified.def` (e.g., SAGE_VERSION, DIANN_VERSION)
2. Rebuild container

### Adding Python Packages
Add to the micromamba environment install command in `meti-unified.def`

## Rollback Plan

If you need to revert to the old multi-container setup:
1. Restore old `nextflow.config` and `main.nf` from git history
2. Keep old container `.sif` files
3. Re-run with `nextflow run main.nf -resume`

## Questions?

Refer to the unified container help:
```bash
singularity run-help containers/meti-unified.sif
```

Or check tool documentation:
- SAGE: https://github.com/lazear/sage
- DIA-NN: https://github.com/vdemichev/DiaNN
- Casanovo: https://github.com/Noble-Lab/casanovo
- Cascadia: https://github.com/grosenberger/cascadia
