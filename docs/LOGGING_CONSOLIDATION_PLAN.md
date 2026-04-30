# Logging Consolidation Architecture - Detailed Implementation Plan

**Status**: Planning phase  
**Date**: March 22, 2026  
**Objective**: Fix systemic logging collection bug to create unified event trails across all pipeline processes

---

## Executive Summary

The logging infrastructure has a **fundamental architecture gap**: events are written to subprocess directories but consolidation expects them at the PXD root. This plan creates a complete collection and merge strategy to unify timestamps, organize by process, and enable full audit trails.

---

## Part 1: Diagnosis

### Current State
- **Only search process** logs events → `search/events.jsonl`
- **No collection mechanism** to merge subprocess events
- **consolidate_pxd_logs.py** looks for `${pxd_root}/events.jsonl` (doesn't exist)
- **Result**: Empty events array in pipeline JSON files

### Root Causes
1. **Path mismatch**: subprocess events not merged to root
2. **Missing imports**: Other processes (fetch, organism, agentic) not integrated with PipelineLogger
3. **No merge step**: aggregate_results.py has no logic to collect from subprocess directories

### Pipeline Processes (Priority for logging)

| Process | Current Status | Priority | Output Dir | Should Log |
|---------|---|---|---|---|
| `fetch_pxd` | ❌ No logging | P1 | `${pxd_id}/` | Yes (data retrieval events) |
| `organism_id` | ❌ No logging | P1 | `${pxd_id}/organism/` | Yes (organism detection, config selection) |
| `search` | ✅ Logging done | P0 | `${pxd_id}/search/` | Yes (comprehensive search events) |
| `aggregate_results` | ⚠️ Partial | P1 | `${pxd_id}/` | Yes (consolidation status) |
| `agentic_metadata_extraction` | ❌ No logging | P2 | `${pxd_id}/agentic/` | Optional (LLM metadata) |
| `results_summary` | ❌ No logging | P3 | `${pxd_id}/` | Optional (final summary) |

---

## Part 2: Solution Architecture

### Design Decisions

#### 2.1 Event Collection Strategy: "Pull + Merge"
- **Approach**: Each subprocess writes events to its own directory
- **Collection**: aggregate_results.py will **pull all events from subprocesses** and merge them to root
- **Why**: 
  - Minimal changes to existing processes
  - Preserves subprocess isolation (events stay in process directories)
  - Clean separation of concerns
  - Allows process-specific analysis if needed

#### 2.2 Event Storage Locations

```
${pxd_id}/
├── events.jsonl                    ← UNIFIED root (all events merged here)
├── fetch/
│   └── events.jsonl               ← fetch_pxd subprocess events
├── organism/
│   └── events.jsonl               ← organism_id subprocess events
├── search/
│   └── events.jsonl               ← search subprocess events
└── agentic/
    └── events.jsonl               ← agentic_metadata_extraction events
```

#### 2.3 Merging Logic

```python
def collect_and_merge_events(pxd_root_dir):
    """
    Collect events from all subprocess directories and merge to root.
    Maintains chronological order across all processes.
    Returns: list of events sorted by timestamp
    """
    all_events = []
    
    # Subdirectories that may contain events
    subdirs = ["fetch", "organism", "search", "agentic", "llm"]
    
    for subdir in subdirs:
        events_file = Path(pxd_root_dir) / subdir / "events.jsonl"
        if events_file.exists():
            events = read_jsonl_file(events_file)
            all_events.extend(events)
    
    # Sort by timestamp globally
    all_events.sort(key=lambda x: x.get("timestamp", ""))
    
    return all_events
```

---

## Part 3: Implementation Roadmap

### Phase 1: Fix Search Process (Already Done)
**Status**: ✅ Complete
- ✅ PipelineLogger.py created
- ✅ search_orchestrator.py integrated with logger
- ✅ Events written to `search/events.jsonl`

### Phase 2: Implement Event Merging (IMMEDIATE - Priority P0)
**Files to modify**: consolidate_pxd_logs.py

**Changes**:
1. Update consolidate_logs() to merge events from all subprocess directories
2. Create collect_and_merge_events() function
3. Sort merged events by timestamp
4. Update consolidation.py to use merged events

**Pseudocode**:
```python
def consolidate_logs(output_dir: str, pxd_id: str) -> dict:
    output_dir = Path(output_dir)
    
    # NEW: Collect and merge events from all subprocesses
    all_events = collect_and_merge_events(output_dir)
    
    # Rest of consolidation logic uses all_events
    error_count = sum(1 for e in all_events if e.get("level") == "ERROR")
    ...
```

**Testing**: Run on PXD026287 (search events should consolidate correctly)

---

### Phase 3: Integrate Logging into Other Processes (Priority P1)

#### 3.1 fetch_pxd
**File**: main.nf lines 491-533

**Changes needed in Nextflow**:
```bash
# Add to fetch_pxd process output
output:
tuple val(pxd), path("${pxd}"), path("fetch")  # Add fetch dir

# Add logging call in script section
--log_file fetch/events.jsonl
```

**Changes needed in Python** (if separate script exists):
- Import PipelineLogger
- Log: Start, data download, file count, completion
- Write to `fetch/events.jsonl`

**Events to capture**:
- `lifecycle:started` - When fetch begins
- `info:raw_files_found` - Number of raw files in PRIDE
- `info:downloaded` - Files downloaded count
- `info:conversion_needed` - mzML conversion requirement
- `lifecycle:completed` - When fetch ends
- `error:*` - Any download/conversion failures

#### 3.2 organism_id
**File**: main.nf lines 535-628

**Changes needed in Nextflow**:
```bash
# Add organism dir to output
output:
tuple val(pxd), path("detected_params.json"), path("organism")

# Add logging call
--log_file organism/events.jsonl
```

**Events to capture**:
- `lifecycle:started`
- `info:organism_detected` - Which organism(s) detected
- `info:pipeline_config_selected` - DDA vs DIA, enzyme, etc.
- `info:proteome_size` - Proteome size (affects search config)
- `lifecycle:completed`
- `warning:*` - If organism ambiguous
- `error:*` - If organism detection fails

#### 3.3 agentic_metadata_extraction (Lower priority)
**File**: main.nf lines 745-809

**Similar approach**: Add logging subdirectory and event logging

**Events to capture**:
- LLM API calls
- Metadata extraction results
- Any validation warnings

### Phase 4: Update aggregate_results.py (Priority P1)

**File**: src/python/aggregate_results.py lines 744-772

**Changes**:
1. ✅ Already calls consolidate_logs() - no change needed here
2. Consolidate_logs.py will be updated to merge events (Phase 2)
3. Add messaging about event collection process

**Verify**:
- [ ] Events from search/ are found and merged
- [ ] Final JSON includes all_events sorted by timestamp
- [ ] Markdown summary shows all processes and their event counts

### Phase 5: Test and Validate (Priority P1)

**Test cases**:
1. Run PXD026287 again → search events should consolidate properly
2. Run a fresh PXD → verify search events are collected (need no other logging yet)
3. After Phase 3: Run fresh PXD → verify all process events merge correctly
4. Validate JSON schema for consolidated log

**Validation checklist**:
- [ ] events.jsonl created in PXD root
- [ ] Events sorted chronologically
- [ ] Event count > 0 (previously was 0 due to path bug)
- [ ] All process types represented (if available)
- [ ] Timestamps make sense (no clock skew)

---

## Part 4: Code Changes Summary

### Files to Modify

| File | Phase | Change Type | Scope |
|------|-------|-------------|-------|
| consolidate_pxd_logs.py | 2 | Merge logic | New collect_and_merge_events() function |
| aggregate_results.py | 2 | Status message | Log what consolidate_logs() returns |
| main.nf | 3 | fetch_pxd | Add --log_file parameter and output dir |
| main.nf | 3 | organism_id | Add --log_file parameter and output dir |
| search_orchestrator.py | (already done) | - | - |
| fetch script* | 3 | Logging integration | Import PipelineLogger, add events |
| organism script* | 3 | Logging integration | Import PipelineLogger, add events |

*If separate Python scripts exist for fetch/organism

### Files NOT to Modify
- PipelineLogger.py (complete)
- format_pxd_summary.py (complete)
- search_orchestrator.py (logging integrated)

---

## Part 5: Implementation Sequence

### Week 1 (Immediate)

**Task 2.1**: Update consolidate_pxd_logs.py
- Create collect_and_merge_events() function
- Update consolidate_logs() to use merged events
- **Effort**: 30 minutes
- **Validation**: Test on PXD026287

**Task 2.2**: Verify search events consolidate correctly
- Run test PXD
- Check events.jsonl in root directory
- Verify timestamps are correct
- **Effort**: 15 minutes

### Week 2

**Task 3.1**: Integrate fetch_pxd logging
- Add PipelineLogger import to fetch script
- Add --log_file to main.nf
- Log relevant fetch events
- **Effort**: 1 hour

**Task 3.2**: Integrate organism_id logging
- Add PipelineLogger import to organism script
- Add --log_file to main.nf
- Log organism detection and config selection
- **Effort**: 1 hour

**Task 3.3**: Full pipeline test
- Run test PXD with logging
- Verify all four processes (fetch, organism, search, aggregate) create events
- Check final consolidated JSON
- **Effort**: 30 minutes

### Week 3

**Task 4.1**: Integrate agentic_metadata_extraction (if needed)
- Similar to fetch/organism integration
- **Effort**: 1 hour

**Task 4.2**: Documentation and QA
- Update README with logging architecture
- Create troubleshooting guide for log inspection
- **Effort**: 1 hour

---

## Part 6: Risk Mitigation

### Risk 1: Subprocess directories don't exist
**Mitigation**: collect_and_merge_events() checks if each subdir exists before reading

### Risk 2: Events file malformed/corrupted
**Mitigation**: read_jsonl_file() already handles JSON decode errors gracefully

### Risk 3: Timestamp ordering issues across processes
**Mitigation**: Sort global_events by timestamp after merge

### Risk 4: Multiple pipeline runs create duplicate events
**Mitigation**: (Future enhancement) Add run_id to each event, or clear old events on re-run

### Risk 5: Other processes haven't been modified yet
**Mitigation**: collect_and_merge_events() gracefully skips missing directories

---

## Part 7: Success Criteria

- ✅ PXD026287 re-run produces PXD026287_pipeline.json with >1 event (not empty array)
- ✅ Events are sorted chronologically
- ✅ Events include all process types that have logged (search at minimum)
- ✅ Markdown summary shows event counts and process breakdown
- ✅ No silent failures (consolidation doesn't fail secretly)
- ✅ Path compatibility: works for all PXD runs regardless of directory structure

---

## Appendix: Event Schema Reference

```json
{
  "timestamp": "2026-03-22T10:32:20.124567Z",
  "pxd": "PXD026287",
  "process": "search",
  "level": "INFO",
  "category": "lifecycle|debug|validation|quality",
  "message": "Starting search",
  "details": {
    "key": "value"
  }
}
```

Events should be consistent across all processes using this schema.
