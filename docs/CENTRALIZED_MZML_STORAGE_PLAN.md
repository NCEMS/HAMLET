# Centralized mzML Storage Architecture Plan

**Date:** March 24, 2026  
**Status:** Ready for Implementation (pending bug fix)  
**Priority:** High (reduces disk usage from ~50GB per PXD to single repository)

---

## Executive Summary

This document outlines the implementation plan for centralizing all mzML files (predownloaded + freshly downloaded) in a single repository at `${baseDir}/spectral_files/` using symlinks throughout the pipeline. This eliminates duplicate mzML files and provides a single source of truth.

**Key Decisions Confirmed:**
1. ✅ Central location: `${baseDir}/spectral_files/` (not `${params.download_dir}`)
2. ✅ No copies anywhere: ALL mzML files symlinked to central repository
3. ✅ Unified parameter: `${params.central_mzml_dir}` (replaces separate predownloaded + download logic)

---

## Current Problem

**Before Implementation:**
```
results/
├── PXD034195/
│   ├── PXD034195/    (actual mzML files, ~50GB)
│   └── search/
├── PXD022741/
│   ├── PXD022741/    (actual mzML files, ~50GB)
│   └── search/
└── PXD026287/
    ├── PXD026287/    (actual mzML files, ~50GB)
    └── search/

work/downloads/
├── PXD034195/        (duplicate, ~50GB)
├── PXD022741/        (duplicate, ~50GB)
└── PXD026287/        (duplicate, ~50GB)
```
**Total Disk: 300GB for 3 PXDs × 50GB = 150GB actual data + 150GB duplication**

---

## Proposed Solution

**After Implementation:**
```
${baseDir}/spectral_files/           ← CENTRAL REPOSITORY (ONE COPY PER PXD)
├── PXD034195/
│   ├── DS_Goe_c.mzML (50GB)
│   └── DS_Hem_c.mzML (actual files)
├── PXD022741/
│   └── *.mzML (actual files)
└── PXD026287/
    └── *.mzML (actual files)

results/
├── PXD034195/
│   ├── PXD034195/    (SYMLINKS → ../../../spectral_files/PXD034195/)
│   └── search/
├── PXD022741/
│   ├── PXD022741/    (SYMLINKS → ../../../spectral_files/PXD022741/)
│   └── search/
└── PXD026287/
    ├── PXD026287/    (SYMLINKS → ../../../spectral_files/PXD026287/)
    └── search/

work/downloads/
├── PXD034195/        (SYMLINKS → ../../spectral_files/PXD034195/)
├── PXD022741/        (SYMLINKS → ../../spectral_files/PXD022741/)
└── PXD026287/        (SYMLINKS → ../../spectral_files/PXD026287/)
```
**Total Disk: 150GB for 3 PXDs (ONE copy each, rest are symlinks)**  
**Savings: 50% reduction for 100+ PXD datasets**

---

## Architecture Design

### 1. New Parameter

**File:** `nextflow.config`  
**Location:** Add to `params` section

```groovy
// Centralized mzML storage: all raw files stored here, with symlinks in work/results
central_mzml_dir = "${baseDir}/spectral_files"
```

**Behavior:**
- All mzML files downloaded/provided go to this directory
- Directory structure: `${central_mzml_dir}/${PXD}/*.mzML`
- work/downloads/${PXD}/ and results/${PXD}/${PXD}/ will symlink to this location

### 2. FetchPXD.py Modifications

**Goal:** Modify fetch behavior to place files in central repository and symlink to work/downloads

**Key Changes:**

**a) New validation function (add at module level)**
```python
def validate_mzml(filepath, min_size_mb=1):
    """
    Validate mzML file integrity.
    
    Args:
        filepath: Path to mzML file
        min_size_mb: Minimum file size in MB (default 1)
    
    Returns:
        (is_valid: bool, reason: str or None)
    """
    try:
        if not filepath.exists():
            return False, f"File does not exist: {filepath}"
        
        # Check file size (mzML files should be > 1MB)
        size_mb = filepath.stat().st_size / (1024 * 1024)
        if size_mb < min_size_mb:
            return False, f"File too small ({size_mb:.1f}MB < {min_size_mb}MB)"
        
        # Check for mzML markers in file
        with open(filepath, 'rb') as f:
            # Read first 1KB for header check
            header = f.read(1024)
            if b'<mzML' not in header and b'<?xml' not in header:
                return False, "File does not contain mzML markers"
            
            # Quick check: file should contain 'spectrum' or 'scan' tags
            f.seek(0)
            content_sample = f.read(50000).decode('utf-8', errors='ignore')
            if 'spectrum' not in content_sample and 'scan' not in content_sample:
                return False, "File does not contain spectrum data"
        
        return True, None
    
    except Exception as e:
        return False, f"Validation error: {str(e)}"
```

**b) Modify download logic to save to central repository**  
**Current behavior (lines ~200-230):**
```python
# Current: saves to standalone temp directory
raw_dir = work_dir / "raw_files"
raw_dir.mkdir(parents=True, exist_ok=True)

# NEW: save to central repository instead
# This will be passed as parameter from nextflow
```

**Changes needed:**
- Accept `central_mzml_dir` as parameter from nextflow
- Save downloaded files to `${central_mzml_dir}/${PXD}/` instead of `${work_dir}/`
- After download/conversion, symlink `${work_dir}/PXD/` → central location
- Validate each mzML before moving to central repository

**c) New function for symlink creation**
```python
def create_symlink_tree(source_dir, target_dir):
    """
    Create symlink for entire directory tree.
    
    Args:
        source_dir: Central repository directory (e.g., spectral_files/PXD034195/)
        target_dir: Work directory location (e.g., work/downloads/PXD034195/)
    
    Returns:
        (success: bool, message: str)
    """
    try:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        
        # If target exists and is symlink, remove it
        if target_dir.is_symlink():
            target_dir.unlink()
        elif target_dir.exists():
            # Path exists but is not symlink - error condition
            return False, f"Target path exists as real directory: {target_dir}"
        
        # Create symlink: target_dir -> source_dir (absolute path)
        target_dir.symlink_to(source_dir.resolve())
        return True, f"Symlink created: {target_dir} -> {source_dir}"
    
    except Exception as e:
        return False, f"Symlink creation failed: {str(e)}"
```

**d) Integration into fetch process**

Pseudocode for fetch_pxd process:
```python
1. Create central directory: ${central_mzml_dir}/${PXD}/
2. Download/convert mzML files → central repository
3. Validate each file using validate_mzml()
4. If validation fails:
   - Log error
   - Try to download again (retry logic)
   - If all retries fail, delete corrupted file and raise error
5. After successful download:
   - Create symlink: ${work_dir}/PXD/ → central repository
   - Output symlink path (not actual path)
```

### 3. Predownloaded mzML Support

**When user provides `--predownloaded_dir`:**

1. Check structure: `${predownloaded_dir}/${PXD}/*.mzML`
2. Validate each file with `validate_mzml()`
3. **Copy** valid files to central repository: `${central_mzml_dir}/${PXD}/`
4. Create symlink: `${work_dir}/PXD/` → central repository
5. Skip fetch_pxd process for this PXD
6. Mark PXD as "predownloaded" in metadata

**Logic flow:**
```
if predownloaded_dir && file exists in ${predownloaded_dir}/${PXD}/:
    validate_predownloaded_files()
    copy_to_central_repository()
    create_symlink_to_work()
    skip_fetch_pxd
else:
    fetch_pxd_normal_flow()
    save_to_central_repository()
    create_symlink_to_work()
```

---

## Implementation Steps

### Phase 1: Setup (Non-Breaking)
- [ ] Add `central_mzml_dir` parameter to `nextflow.config`
- [ ] Create `validate_mzml()` function in FetchPXD.py
- [ ] Create `create_symlink_tree()` function in FetchPXD.py
- [ ] Test validation function with known-good and corrupted mzML files

### Phase 2: FetchPXD Integration
- [ ] Modify fetch_pxd to accept `central_mzml_dir` parameter
- [ ] Update download logic to save to central repository
- [ ] Add symlink creation after successful download
- [ ] Add validation checks before moving files to central repo
- [ ] Update error handling for corrupted files

### Phase 3: Predownloaded Integration
- [ ] Add `--predownloaded_dir` parameter to main.nf
- [ ] Create validation wrapper for predownloaded files
- [ ] Implement copy-to-central logic with conflict detection
- [ ] Update workflow to conditionally skip fetch_pxd

### Phase 4: Results Directory Symlinks
- [ ] Modify workflow to create symlinks in `results/${PXD}/${PXD}/`
- [ ] Symlink structure: `results/PXD/${PXD}/*.mzML` → `spectral_files/PXD/*.mzML`
- [ ] Ensures users can access files from results/ without duplication

### Phase 5: Testing & Validation
- [ ] Single PXD test (fetch_pxd flow)
- [ ] Multi-PXD test with CSV input
- [ ] Mixed mode test (predownloaded + fresh fetch)
- [ ] Verify symlinks resolve correctly
- [ ] Verify disk usage reduction

### Phase 6: Cleanup (Optional)
- [ ] Remove old `work/downloads/` copy logic
- [ ] Update documentation with new structure
- [ ] Add disk usage metrics to logs

---

## Code Changes Required

### File 1: nextflow.config

**Add to params section (after line ~12):**
```groovy
// Centralized mzML storage: all files stored here, symlinks elsewhere
central_mzml_dir = "${baseDir}/spectral_files"

// Optional: allow pre-downloaded files (will be copied to central repository)
predownloaded_dir = null
```

### File 2: FetchPXD.py

**Add functions (after imports):**
- `validate_mzml(filepath, min_size_mb=1)` - validate file integrity
- `create_symlink_tree(source_dir, target_dir)` - create directory symlink

**Modify download process:**
- Accept `central_mzml_dir` parameter
- Save files to `${central_mzml_dir}/${PXD}/` instead of local temp
- Create symlinks in `${work_dir}/`
- Validate files before moving to central repo

### File 3: main.nf

**Modify fetch_pxd process:**
- Add `central_mzml_dir` to process environment
- Pass to FetchPXD.py script
- Update output channel to use symlink path

**Add conditional workflow for predownloaded:**
```groovy
if (params.predownloaded_dir) {
    // Route through predownloaded validation
    // Copy to central repository
    // Skip fetch_pxd for those PXDs
} else {
    // Normal fetch_pxd flow
}
```

---

## Expected Directory Structure After Implementation

```
${baseDir}/
├── spectral_files/                          ← CENTRAL (one copy per PXD)
│   ├── PXD034195/
│   │   ├── DS_Goe_c.mzML
│   │   └── DS_Hem_c.mzML
│   ├── PXD022741/
│   │   └── *.mzML
│   └── ...
│
├── results/
│   ├── PXD034195/
│   │   ├── PXD034195 → ../../spectral_files/PXD034195/ (SYMLINK)
│   │   ├── search/
│   │   ├── PXD034195_detected_params.json
│   │   └── ...
│   └── ...
│
├── work/downloads/
│   ├── PXD034195/ → ../../spectral_files/PXD034195/ (SYMLINK)
│   ├── PXD022741/ → ../../spectral_files/PXD022741/ (SYMLINK)
│   └── ...
```

---

## Backwards Compatibility

**Breaking Changes:**
- Old workflows with files in `results/PXD/` will need symlink update
- Old `work/downloads/` directories will be bypassed

**Migration Path:**
1. Create symlinks for existing PXDs in `spectral_files/`
2. Update any scripts referencing `work/downloads/` paths
3. No need to re-download if files are already present

**Rollback:**
- If issues arise, can manually copy files from symlink targets back to original locations
- Symlinks can be safely removed without data loss

---

## Validation Checklist

After implementation, verify:
- [ ] Central repository contains one copy of each mzML file
- [ ] Symlinks in work/downloads/ point to central repository
- [ ] Symlinks in results/ point to central repository
- [ ] DIA-NN search reads files correctly through symlinks
- [ ] File path logging shows symlink resolution
- [ ] Disk usage reduced by ~50% for multi-PXD runs
- [ ] Predownloaded files copied to central repository on first run
- [ ] Mixed mode (predownloaded + fresh fetch) works correctly
- [ ] Validation catches corrupted mzML files

---

## Command Examples

**Usage after implementation:**

```bash
# Normal flow (fetch from PRIDE, save to central repo)
nextflow run main.nf --pxd PXD034195 --run_search true

# With predownloaded files (copy to central, then process)
nextflow run main.nf --pxd_csv PXDs.csv --predownloaded_dir /path/to/downloads --run_search true

# Multi-PXD (all stored in central repository)
nextflow run main.nf --pxd_csv PXDs.csv --run_search true
# All files in: ${baseDir}/spectral_files/PXD*/
```

---

## Performance & Resource Impact

**Disk Space:**
- Before: 150GB for 3 PXDs (3×50GB actual + 3×50GB duplicates)
- After: 150GB for same 3 PXDs (no duplicates)
- For 100 PXDs: 5TB → 2.5TB savings

**Symlink Resolution:**
- No performance penalty (kernel-level symlink resolution)
- Slightly faster I/O (single source of truth, no duplicate copies)

**Memory:** No change

**Network:** No change (same PRIDE download logic)

---

## Known Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| User deletes central repo by mistake | Keep backups; symlinks provide fallback error detection |
| Symlink breaks during pipeline | Validation checks at each stage; will retry fetch if needed |
| Mixed predownloaded + fresh fetch conflicts | Validation before copy; skip if file already exists in central |
| Old references to work/downloads/ fail | Update documentation; provide migration script if needed |

---

## Timeline Estimate

- **Analysis & Planning:** ✅ Complete
- **FetchPXD.py modifications:** 2-3 hours
- **main.nf workflow integration:** 2-3 hours
- **Testing (single + multi PXD):** 2-4 hours
- **Predownloaded integration:** 1-2 hours
- **Final validation:** 1-2 hours
- **Total:** ~8-14 hours of development time

**Ready to proceed?** Please confirm bugs are fixed, then we can begin Phase 1 (setup).

