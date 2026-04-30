# Per-File Closed Search Architecture

**Component Summary**: Visual documentation of the per-file closed search implementation

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          NEXTFLOW WORKFLOW (main.nf)                        │
│  Lines 40-43: Pooling strategy documentation (updated)                     │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │  Input: --sage_pooling_strategy open_only                           │  │
│  └──┬─────────────────────────────────────────────────────────────────┬─┘  │
│     │                                                                   │    │
│     ▼                                                                   │    │
│  ┌──────────────────────────────────────────────────────────────────┐  │    │
│  │  Step 1: PASS 1 - POOLED OPEN SEARCH                            │  │    │
│  │  (All mzML files searched together)                             │  │    │
│  │  → Identifies modifications for later closed search             │  │    │
│  └──┬───────────────────────────────────────────────────────────────┘  │    │
│     │                                                                   │    │
│     ▼                                                                   │    │
│  ┌──────────────────────────────────────────────────────────────────┐  │    │
│  │  Step 2: PER-FILE CLOSED SEARCH (NEW IMPLEMENTATION)            │  │    │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │    │
│  │  │  sage_run_per_file_closed_search.sh                        │ │  │    │
│  │  │  (Lines 1-101: Enhanced with logging/error handling)       │ │  │    │
│  │  │                                                             │ │  │    │
│  │  │  ┌────────────────────────────────────────────────────┐   │ │  │    │
│  │  │  │  FOR each mzML file:                             │   │ │  │    │
│  │  │  │  ┌──────────────────────────────────────────────┐ │   │ │  │    │
│  │  │  │  │  SAGE.py (Lines 415, 471-490)               │ │   │ │  │    │
│  │  │  │  │                                              │ │   │ │  │    │
│  │  │  │  │  ┌─ Argument: --mzml_file <filename> ──┐   │ │   │ │  │    │
│  │  │  │  │  │ (NEW: Line 415)                      │   │ │   │ │  │    │
│  │  │  │  │  │                                      │   │ │   │ │  │    │
│  │  │  │  │  │ Conditional mzML Detection:         │   │ │   │ │  │    │
│  │  │  │  │  │  if --mzml_file:                    │   │ │   │ │  │    │
│  │  │  │  │  │    → Per-file mode (Lines 472-480) │   │ │   │ │  │    │
│  │  │  │  │  │    → Process ONLY that file        │   │ │   │ │  │    │
│  │  │  │  │  │  else:                             │   │ │   │ │  │    │
│  │  │  │  │  │    → Aggregate mode (Lines 481-490)│   │ │   │ │  │    │
│  │  │  │  │  │    → Process ALL files             │   │ │   │ │  │    │
│  │  │  │  │  └────────────────────────────────────┘   │ │   │ │  │    │
│  │  │  │  │                                            │ │   │ │  │    │
│  │  │  │  │  Output: file_subdir/results.sage.tsv    │ │   │ │  │    │
│  │  │  │  │  (One TSV per mzML file)                 │ │   │ │  │    │
│  │  │  │  │                                            │ │   │ │  │    │
│  │  │  │  │  On Error: file_subdir/error.txt         │ │   │ │  │    │
│  │  │  │  │  (Marker for aggregation to detect)      │ │   │ │  │    │
│  │  │  │  └──────────────────────────────────────────┘ │   │ │  │    │
│  │  │  └────────────────────────────────────────────────┘   │ │  │    │
│  │  │                                                        │ │  │    │
│  │  │  Logging Output: per_file_search.log                 │ │  │    │
│  │  │  ├─ Timestamp & stage                                │ │  │    │
│  │  │  ├─ Progress: [N/M] files                            │ │  │    │
│  │  │  ├─ Per-file success/failure                         │ │  │    │
│  │  │  └─ Summary: X successful, Y failed                 │ │  │    │
│  │  └────────────────────────────────────────────────────────┘  │    │
│  └──┬───────────────────────────────────────────────────────────┘    │    │
│     │                                                                  │    │
│     ▼                                                                  │    │
│  ┌──────────────────────────────────────────────────────────────────┐  │    │
│  │  Step 3: AGGREGATE PER-FILE RESULTS (aggregate_sage_results.py) │  │    │
│  │  (Lines 30, 52-56, 104-138: Enhanced error handling)            │  │    │
│  │                                                                   │  │    │
│  │  Input: Directory with file subdirectories                       │  │    │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │    │
│  │  │  FOR each file subdirectory:                              │ │  │    │
│  │  │    ├─ Check for error.txt (NEW: Lines 52-56)            │ │  │    │
│  │  │    │  └─ If failed: skip, add to failed_files list     │ │  │    │
│  │  │    ├─ Read results.sage.tsv if exists                   │ │  │    │
│  │  │    └─ Concatenate PSMs (skip header duplicates)         │ │  │    │
│  │  └────────────────────────────────────────────────────────────┘ │  │    │
│  │                                                                   │  │    │
│  │  Output 1: results.sage.tsv (aggregated)                         │  │    │
│  │  ├─ Single header row                                           │  │    │
│  │  └─ All PSMs from all files (concatenated)                      │  │    │
│  │                                                                   │  │    │
│  │  Output 2: metadata.json (NEW TRACKING)                          │  │    │
│  │  ├─ total_files_attempted                                       │  │    │
│  │  ├─ total_files_successful                                      │  │    │
│  │  ├─ total_files_failed                                          │  │    │
│  │  ├─ total_psms                                                  │  │    │
│  │  └─ files: {                                                    │  │    │
│  │      "file1": {"status": "success", "psm_count": 7500},        │  │    │
│  │      "file2": {"status": "success", "psm_count": 8200},        │  │    │
│  │      "failed_file": {"status": "failed"}                       │  │    │
│  │    }                                                             │  │    │
│  └──┬───────────────────────────────────────────────────────────────┘  │    │
│     │                                                                   │    │
│     └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘

LEGEND:
  NEW        = Newly added/modified for per-file closed search
  Lines X-Y  = Specific code locations in the implementation
  ════════   = Main data flow
  ┌──────┐   = Components/modules
  ↓      = Process flow direction
```

## Data Flow: Per-File Closed Search

### Input
```
results/PXD012345/Pass_1/
├─ mzML/
│  ├─ sample_1.mzML (200 MB)
│  ├─ sample_2.mzML (180 MB)
│  ├─ sample_3.mzML (220 MB)
│  └─ ... (more files)
├─ mzml_list_filtered.txt (list of paths)
└─ detected_params.json (open search params for closed search)
```

### Processing: sage_run_per_file_closed_search.sh
```
FOR EACH file IN mzml_list_filtered.txt:
  1. Create: sample_1/
  2. Call: SAGE.py 
           --mzml_dir results/PXD012345/Pass_1/mzML/
           --mzml_file sample_1.mzML          ← NEW parameter
           -o sample_1/
           --ClosedSearch
           (+ other params)
  3. Wait for completion
  4. Check: sample_1/results.sage.tsv exists?
     YES → Log success, increament success counter
     NO  → Write error.txt, log failure, increment failed counter

LOG OUTPUT: per_file_search.log
[1/100] Processing: sample_1.mzML
  ✓ Success: 7500 PSMs
[2/100] Processing: sample_2.mzML
  ✓ Success: 8200 PSMs
[3/100] Processing: sample_3.mzML
  ✗ Failed with exit code 1
...
[100/100] Processing: sample_100.mzML
  ✓ Success: 6800 PSMs

Per-file closed searches complete
  Successful: 99/100
  Failed: 1/100
```

### Output: Directory Structure
```
results/PXD012345/Pass_2/
├─ sample_1/
│  ├─ results.sage.tsv (7500 PSMs)
│  ├─ sage.log
│  └─ (other SAGE outputs)
├─ sample_2/
│  ├─ results.sage.tsv (8200 PSMs)
│  ├─ sage.log
│  └─ (other SAGE outputs)
├─ sample_3/
│  ├─ error.txt ← NEW: Error marker
│  ├─ sage.log (contains error details)
│  └─ (incomplete outputs)
├─ ... (more files)
├─ results.sage.tsv (AGGREGATED)
│  ├─ Header row (once)
│  └─ 150000+ PSMs (concatenated from all files)
├─ metadata.json (NEW TRACKING)
│  ├─ "total_files_attempted": 100
│  ├─ "total_files_successful": 99
│  ├─ "total_files_failed": 1
│  ├─ "total_psms": 150000
│  └─ "files": {...per-file stats...}
└─ per_file_search.log (NEW LOGGING)
```

## Code Interaction Map

### Component 1: SAGE.py
```
Function: sage_run_closed_search_per_file()

INPUT PARAMETERS:
├─ --mzml_dir (required)
├─ --mzml_file (optional) ← NEW: Triggers per-file mode
├─ --ClosedSearch (closed search modifications)
└─ ... (other standard parameters)

CONDITIONAL ROUTING (Lines 471-490):
├─ if --mzml_file:
│  └─ mzml_files = [specific_file] → Only 1 file processed
│
└─ else:
   └─ mzml_files = glob.glob("*.mzML") → All files processed

OUTPUT:
├─ results.sage.tsv (per-file result if --mzml_file)
├─ results.sage.tsv (aggregated if no --mzml_file)
└─ sage.log (standard logging)
```

### Component 2: sage_run_per_file_closed_search.sh
```
Function: Iterate through mzML list and run SAGE per-file

INPUT:
├─ $1: mzml_list_filtered.txt (line-delimited file paths)
├─ $2: OUTPUT_DIR (where to put results)
├─ $3-$6: SAGE parameters (taxid, labeling, config, mods)
└─ LOG_FILE: per_file_search.log ← NEW

MAIN LOOP (Lines 35-80):
├─ FOR each line in mzml_list_filtered.txt:
│  ├─ Extract: file_dir/, file_name
│  ├─ CREATE: file_dir/ subdirectory
│  ├─ CALL: SAGE.py --mzml_file file_name ← FIXED PARAMETER
│  │         (previously used --mzml_files)
│  ├─ WAIT: for completion
│  ├─ CHECK: results.sage.tsv exists?
│  │  ├─ YES: Log success, count PSMs
│  │  └─ NO:  Write error.txt, log failure
│  └─ LOG: All to per_file_search.log ← NEW

SUMMARY OUTPUT (Lines 82-89):
├─ "Per-file closed searches complete"
├─ "  Successful: X/$total_files"
├─ "  Failed: Y/$total_files"
└─ Write to log + console
```

### Component 3: aggregate_sage_results.py
```
Function: aggregate_sage_results(per_file_dir, output_file, output_metadata)

INPUT:
├─ per_file_dir: Directory with file subdirectories
└─ output_file: Aggregated results.sage.tsv location

ERROR DETECTION (Lines 52-56): ← NEW EXPLICIT
├─ FOR each file_subdir:
│  ├─ Check: error.txt exists?
│  │  ├─ YES: Read error message, add to failed_files
│  │  └─ NO:  Try to read results.sage.tsv
│  └─ SKIP failed files in aggregation

AGGREGATION LOGIC (Lines 60-98):
├─ Initialize: header = None, all_psms = []
├─ FOR each successful file_subdir:
│  ├─ Read: results.sage.tsv
│  ├─ Extract: header (first line, once)
│  ├─ Concatenate: all PSM lines (skip header in each file)
│  └─ Track: per_file_metadata[filename] = {"status": "success", "psm_count": N}
└─ FOR each failed file_subdir:
   └─ Track: per_file_metadata[filename] = {"status": "failed"}

OUTPUT 1: results.sage.tsv (Lines 105-110)
├─ Single header row ← Deduplicated
└─ All PSMs concatenated [file1 PSMs] + [file2 PSMs] + ...

OUTPUT 2: metadata.json (Lines 119-125) ← NEW COMPREHENSIVE TRACKING
├─ "aggregation_strategy": "per_file"
├─ "total_files_attempted": len(per_file_subdirs)
├─ "total_files_successful": count(successful files)
├─ "total_files_failed": len(failed_files)
├─ "total_psms": len(all_psms)
└─ "files": {per_file_metadata}

RETURN VALUE (Lines 127-131):
├─ True: Aggregation successful
└─ False: Zero PSMs OR all files failed
```

## Control Flow: Single File Processing

```
SAGE.py --mzml_file sample_1.mzML processes as:

┌──────────────────────────────────────────┐
│ Parse arguments                          │
│ mzml_file = "sample_1.mzML"              │
└──────┬───────────────────────────────────┘
       ▼
┌──────────────────────────────────────────┐
│ Check: args.mzml_file? (Line 471)        │
│ YES: Enter per-file mode                 │
└──────┬───────────────────────────────────┘
       ▼
┌──────────────────────────────────────────┐
│ Construct path (Line 474)                │
│ mzml_path = mzml_dir + "sample_1.mzML"   │
└──────┬───────────────────────────────────┘
       ▼
┌──────────────────────────────────────────┐
│ Verify file exists (Line 475-477)        │
│ if not → quit with error                 │
└──────┬───────────────────────────────────┘
       ▼
┌──────────────────────────────────────────┐
│ Set mzML list (Line 478)                 │
│ mzml_files = [full_path_to_sample_1]     │
└──────┬───────────────────────────────────┘
       ▼
┌──────────────────────────────────────────┐
│ Continue normal SAGE processing          │
│ └─ Load FASTA                            │
│ └─ Run SAGE binary with single file      │
│ └─ Generate results.sage.tsv             │
└──────────────────────────────────────────┘
```

## Error Handling Flow

```
SAGE.py error → error.txt marker
                    ↓
sage_run_per_file_closed_search.sh detects
                    ↓
Writes "Failed" to file_subdir/error.txt
                    ↓
Logs failure in per_file_search.log
                    ↓
Continues with next file
                    ↓
aggregate_sage_results.py reads error.txt
                    ↓
Skips this file in aggregation
                    ↓
Adds to failed_files list
                    ↓
Includes in metadata.json
└─ "status": "failed"
└─ "files": {"failed_file": {"status": "failed"}}

RESULT:
├─ Pipeline continues (non-fatal)
├─ User sees warning in logs
├─ Metadata clearly marks failed files
└─ Can retry just failed files with -resume
```

## Performance Model

```
Time Complexity:

Pooled Search (strategy: both):
  Time = O(1) for open + O(1) for closed = O(1)
  (Single run regardless of file count)

Per-File Search (strategy: open_only):
  Time = O(1) for open + O(N) for closed
  where N = number of mzML files
  = single open run + (N × per_file_search_time)

Example: 100 files
├─ Open: 30 minutes (all files together)
├─ Closed: 100 × 5 min = 500 minutes (~8 hours)
└─ Total: ~8.5 hours (vs 2-4 hours for pooled)

Parallelization Option:
├─ With -qs 10 (10 concurrent):
├─ Per-file can reduce to: ~8.5 hours / 10 = ~51 minutes per iteration
├─ Total: ~1.5 hours (for per-file with parallelization)
└─ Trade-off: More compute resources, faster turnaround
```

---

## Summary: From Broken to Working

| Aspect | Before | After |
|--------|--------|-------|
| **Parameter** | `--mzml_files` (doesn't exist) | `--mzml_file` (defined, working) |
| **SAGE.py Logic** | No per-file support | Conditional per-file vs aggregate |
| **Error Handling** | Silent failures (errorStrategy 'ignore') | Explicit error markers (error.txt) |
| **Logging** | No per-file log | per_file_search.log with progress |
| **Metadata** | None | Comprehensive metadata.json with stats |
| **Documentation** | Misleading (said pooled when per-file) | Accurate (documents what it does) |
| **Result** | Pass 2: 0/20 PXDs successful | Pass 2: Expected 20/20 successful |

---

**Last Updated**: January 26, 2025  
**Architecture**: Simplified per-file closed search pipeline with comprehensive error handling  
**Status**: Complete and ready for testing
