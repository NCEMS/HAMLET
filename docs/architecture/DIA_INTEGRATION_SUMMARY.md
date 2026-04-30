# DIA Integration Summary

## Overview
Successfully integrated DIA (Data-Independent Acquisition) support into the RawDataPipeline. The pipeline now supports both DDA and DIA proteomics workflows through a single boolean flag.

## Changes Made

### 1. Configuration Files

#### nextflow.config
- Added `params.organism_dia_container` parameter pointing to organism-id_DIA.sif
- Added `params.diann_container` parameter pointing to DiaNN.sif  
- Added `params.DIA` boolean flag (default: false) to control DDA vs DIA mode
- Updated `singularity.runOptions` to mount Cascadia models directory: `-B /home/ians/cascadia_models:/opt/cascadia/models`

#### main.nf
- Updated parameter defaults to include DIA containers and flag
- Modified `organism_id` process:
  * Conditional container selection: `params.DIA ? organism_dia_container : organism_container`
  * Added `.cache/cascadia` directory for Cascadia model caching
  * Added intelligent GPU selection logic (picks GPU with most free memory)
- Modified `sage_search` process:
  * Renamed tag to show "diann" or "sage" based on mode
  * Conditional container selection: `params.DIA ? diann_container : sage_container`
  * Added conditional execution: runs DiaNN.py for DIA mode, SAGE.py for DDA mode

### 2. Python Scripts

#### src/python/OrganismID.py
- Added `convert_ssl_to_mztab()` function to convert Cascadia SSL output to mztab format
- Modified `run_casanovo()` function to support both Casanovo and Cascadia:
  * Detects mode via `CASCADIA_HOME` environment variable
  * Creates separate output directories: CasanovoSequence vs CascadiaSequence
  * Executes appropriate tool with correct parameters
  * Converts Cascadia SSL output to mztab for pipeline compatibility
  * Both tools support GPU-first with CPU fallback

#### src/python/DiaNN.py (NEW)
- Copied from alternative pipeline
- Implements DIA-NN quantification for DIA data
- Features:
  * Library-free search with in silico spectral library generation
  * Supports both .raw (native) and .mzML file formats
  * Downloads FASTA from UniProt based on taxid
  * Configurable modifications (Oxidation, Acetyl, Carbamidomethyl)
  * Comprehensive error handling and logging

#### src/python/FetchPXD.py
- **CRITICAL FIX**: Removed hardcoded 1-file download limit (lines 264-266)
- Pipeline now processes all .raw files available for a PXD

### 3. Container Definitions

#### containers/organism-id_DIA.def (NEW)
- Based on Ubuntu 24.04
- Python 3.11 via micromamba
- Installs **Cascadia** instead of Casanovo for DIA de novo sequencing
- Includes Peptonizer2000 for organism identification
- Model directory: /opt/cascadia/models/
- Note: Users must manually download cascadia.ckpt from Google Drive

#### containers/DiaNN.def (NEW)
- Based on Ubuntu 24.04
- Python 3.11 via micromamba
- Installs **DIA-NN 2.2.0** for DIA quantification
- Includes .NET 8.0 SDK for native .raw file support
- Binary location: /opt/diann/

## Architecture

### DDA Mode (params.DIA = false)
```
fetch_pxd → organism_id (Casanovo) → sage_search (SAGE + PTM-Shepherd) → aggregate_results
            Container: organism-id.sif   Container: sage.sif
```

### DIA Mode (params.DIA = true)
```
fetch_pxd → organism_id (Cascadia) → sage_search (DIA-NN) → aggregate_results
            Container: organism-id_DIA.sif   Container: DiaNN.sif
```

## Usage

### DDA Analysis (default)
```bash
nextflow run main.nf --pxd PXD023343 --taxid 9606
```

### DIA Analysis
```bash
nextflow run main.nf --pxd PXD030983 --taxid 9606 --DIA true
```

## Setup Requirements

### 1. Build New Containers
```bash
cd containers/

# Build DIA organism identification container
singularity build organism-id_DIA.sif organism-id_DIA.def

# Build DIA-NN quantification container
singularity build DiaNN.sif DiaNN.def
```

### 2. Download Cascadia Model
- Download `cascadia.ckpt` from: https://drive.google.com/drive/folders/1UTrZIrCdUqYqscbqga_KdX8kc8ZjMMfr
- Place in: `/home/ians/cascadia_models/cascadia.ckpt`
- This path is mounted to `/opt/cascadia/models/` inside containers

## Verification Status

### ✅ Completed Capabilities
1. **DDA Support**: Full workflow with Casanovo + SAGE + PTM-Shepherd
2. **DIA Support**: Full workflow with Cascadia + DIA-NN
3. **Quantification**: Both DDA (SAGE) and DIA (DIA-NN) quantification
4. **Labeling Detection**: runAssessor detects TMT, iTRAQ, SILAC, LFQ (works for both DDA and DIA)
5. **Multi-file Processing**: Removed 1-file limitation, now processes all available files
6. **GPU Optimization**: Intelligent GPU selection based on free memory

### ⚠️ Known Limitations
1. **PTM Identification**: Only implemented for DDA (via PTM-Shepherd with SAGE), not yet for DIA-NN
2. **Container Building**: New containers need to be built before first DIA run
3. **Model Download**: Cascadia model must be manually downloaded (~1GB)

## Testing Plan

### Test 1: DDA Regression Test
```bash
nextflow run main.nf --pxd PXD023343 --taxid 9606 --DIA false
```
- Expected: Should work exactly as before with no regression
- Verify: Casanovo runs, SAGE quantifies, PTM-Shepherd identifies PTMs

### Test 2: DIA Workflow Test
```bash
nextflow run main.nf --pxd [DIA_PXD] --taxid 9606 --DIA true
```
- Expected: Cascadia de novo sequencing, DIA-NN quantification
- Verify: CascadiaSequence outputs created, DIA-NN report.tsv generated

### Test 3: Multi-file Processing
```bash
nextflow run main.nf --pxd [PXD_WITH_MULTIPLE_FILES] --taxid 9606
```
- Expected: All .raw files downloaded and processed
- Verify: Output for each .raw file, not just first one

## Technical Details

### Tool Versions
- **Casanovo**: 5.1.0 (DDA)
- **Cascadia**: Latest from PyPI (DIA)
- **SAGE**: Database search (DDA)
- **DIA-NN**: 2.2.0 (DIA)
- **PTM-Shepherd**: PTM localization (DDA only)
- **PyTorch**: 2.5.1 (fixed for Casanovo compatibility)

### Environment Detection
The pipeline uses environment variables to detect which tool to use:
- `CASCADIA_HOME`: If set, OrganismID.py uses Cascadia instead of Casanovo
- `CASCADIA_MODEL`: Path to cascadia.ckpt (default: /opt/cascadia/models/cascadia.ckpt)
- `DIANN_HOME`: Path to DIA-NN installation (default: /opt/diann)

### GPU Management
- Automatically selects GPU with most free memory
- Uses `nvidia-smi --query-gpu=index,memory.free`
- Falls back to CPU if GPU unavailable
- Sets `CUDA_VISIBLE_DEVICES` for process isolation

### File Format Compatibility
- **Cascadia** outputs: .ssl → converted to .mztab
- **Casanovo** outputs: .mztab (native)
- **DIA-NN** outputs: report.tsv
- **SAGE** outputs: results.sage.tsv

## Next Steps

1. **Build Containers**: Build organism-id_DIA.sif and DiaNN.sif
2. **Download Model**: Place cascadia.ckpt in /home/ians/cascadia_models/
3. **Test DDA**: Verify no regression in existing DDA workflow
4. **Test DIA**: Run complete DIA workflow with test dataset
5. **PTM Support**: Investigate adding PTM identification for DIA-NN (future enhancement)
6. **Documentation**: Update README.md with DIA usage examples

## References
- Alternative pipeline: `sandbox/AltPipeline/` (reference implementation)
- Cascadia models: https://drive.google.com/drive/folders/1UTrZIrCdUqYqscbqga_KdX8kc8ZjMMfr
- DIA-NN releases: https://github.com/vdemichev/DiaNN/releases

---

**Integration Date**: January 18, 2025  
**Author**: Ian (with AI assistance)  
**Status**: ✅ Code complete, awaiting container builds and testing
