# Unified Stage Manifest Final Plan

## Objective
Enable per-PXD resume from the first incomplete stage, based on a simple manifest with only:
- Availability: user-controlled boolean for whether a stage should run for that PXD.
- Complete: pipeline-controlled boolean indicating stage success and checkpoint files present.
- Key outputs: required files used to validate completion.

This replaces single-checkpoint skipping (for example SDRF-only) with stage-aware skipping.

## Confirmed Current State (Latest Run)
For the latest run in .nextflow.log:
- aggregate_results completed for 131 unique PXDs.
- 131/131 of those PXDs have results/PXD*/PXD*_aggregated_results.json present.
- Missing among completed: 0.

## Final 9 Stages
Keeping the 9-stage model we agreed on:
1. fetch
2. determine_acquisition_params
3. organism_id
4. determine_taxids
5. search
6. aggregate_results
7. agentic_metadata_extraction
8. llm_judge
9. finalize_sdrf

## Key Outputs by Stage
Below are the required key outputs to track. Items marked with NEW are key outputs not in your original short list.

### 1) fetch
- Required checkpoint:
  - spectral_files/PXDxxxxxx/*.mzML (at least one valid mzML)
- Recommended additional evidence:
  - spectral_files/PXDxxxxxx/PXDxxxxxx_PRIDEmetadata.json (NEW)
  - spectral_files/PXDxxxxxx/runAssessor/study_metadata.json (NEW)
- Failure marker (optional):
  - spectral_files/PXDxxxxxx/PXDxxxxxx_NO_SPECTRAL_FILES_WARNING.log (NEW)

### 2) determine_acquisition_params
- Required checkpoint:
  - spectral_files/PXDxxxxxx/detected_params.json (NEW)
- If run_llm_extraction is enabled, also validate at least one LLM artifact exists:
  - spectral_files/PXDxxxxxx/llm_results/PubText.json (NEW)
  - or spectral_files/PXDxxxxxx/llm_results/<model>/<PXD>_Metadata.json (NEW)

### 3) organism_id
- Required checkpoint:
  - results/PXDxxxxxx/organism_results/CasanovoSequence/PXD*/Peptonizer2000_data/PXD*_filtered70pct_slim/peptonizer_result.csv

### 4) determine_taxids
- Required checkpoints:
  - results/PXDxxxxxx/taxid_mapping.json (NEW)
  - results/PXDxxxxxx/taxid_warnings.json (NEW)

### 5) search
- Required checkpoint (DDA):
  - results/PXDxxxxxx/search/dda_search/search_results.tsv
- Required checkpoint (DIA):
  - results/PXDxxxxxx/search/dia_search/search_results.tsv (NEW)

### 6) aggregate_results
- Required checkpoint:
  - results/PXDxxxxxx/PXDxxxxxx_aggregated_results.json
- Recommended additional evidence:
  - results/PXDxxxxxx/PXDxxxxxx_pipeline.json (NEW)
  - results/PXDxxxxxx/PXDxxxxxx_pipeline_summary.md (NEW)

### 7) agentic_metadata_extraction
- Required checkpoints:
  - results/PXDxxxxxx/agentic_metadata/integrated_output/TechnicalAgent/temp_0.0/PXDxxxxxx_PubText_enriched.json (NEW)
  - results/PXDxxxxxx/agentic_metadata/integrated_output/BiologicalAgent/temp_0.0/PXDxxxxxx_PubText_enriched.json (NEW)
  - results/PXDxxxxxx/agentic_metadata/integrated_output/ExperimentalDesignAgent/temp_0.0/PXDxxxxxx_PubText_enriched.json (NEW)

### 8) llm_judge
- Required checkpoints:
  - results/PXDxxxxxx/judge_output/llm_judge_annotation_review.csv (NEW)
  - results/PXDxxxxxx/judge_output/llm_judge_per_paper.csv (NEW)
  - results/PXDxxxxxx/judge_output/llm_judge_coverage.csv (NEW)
  - results/PXDxxxxxx/judge_output/json_outputs/PXDxxxxxx_sdrf_overrides.json (NEW)

### 9) finalize_sdrf
- Required checkpoint:
  - results/PXDxxxxxx/agentic_metadata/PXDxxxxxx.sdrf.tsv
- Recommended additional evidence:
  - results/PXDxxxxxx/agentic_metadata/PXDxxxxxx.sdrf_refinement_report.json (NEW)
  - results/PXDxxxxxx/agentic_metadata/PXDxxxxxx.sdrf_refinement_metrics.json (NEW)

## Manifest Structure (Simple)
Single editable file, for example:
- results/pipeline_stage_manifest.json

Per PXD, per stage, store only:
- availability: boolean
- complete: boolean
- key_outputs: string[]

Example skeleton:

{
  "version": 1,
  "pxds": {
    "PXD009375": {
      "stages": {
        "fetch": {"availability": true, "complete": true, "key_outputs": ["spectral_files/PXD009375/*.mzML"]},
        "determine_acquisition_params": {"availability": true, "complete": true, "key_outputs": ["spectral_files/PXD009375/detected_params.json"]},
        "organism_id": {"availability": true, "complete": true, "key_outputs": ["results/PXD009375/organism_results/CasanovoSequence/**/peptonizer_result.csv"]},
        "determine_taxids": {"availability": true, "complete": true, "key_outputs": ["results/PXD009375/taxid_mapping.json", "results/PXD009375/taxid_warnings.json"]},
        "search": {"availability": true, "complete": true, "key_outputs": ["results/PXD009375/search/dda_search/search_results.tsv", "results/PXD009375/search/dia_search/search_results.tsv"]},
        "aggregate_results": {"availability": true, "complete": true, "key_outputs": ["results/PXD009375/PXD009375_aggregated_results.json"]},
        "agentic_metadata_extraction": {"availability": true, "complete": false, "key_outputs": ["results/PXD009375/agentic_metadata/integrated_output/TechnicalAgent/temp_0.0/PXD009375_PubText_enriched.json", "results/PXD009375/agentic_metadata/integrated_output/BiologicalAgent/temp_0.0/PXD009375_PubText_enriched.json", "results/PXD009375/agentic_metadata/integrated_output/ExperimentalDesignAgent/temp_0.0/PXD009375_PubText_enriched.json"]},
        "llm_judge": {"availability": true, "complete": false, "key_outputs": ["results/PXD009375/judge_output/llm_judge_per_paper.csv"]},
        "finalize_sdrf": {"availability": true, "complete": false, "key_outputs": ["results/PXD009375/agentic_metadata/PXD009375.sdrf.tsv"]}
      }
    }
  }
}

## Stage Resume Semantics
For each PXD:
1. Validate complete against filesystem for each stage key_outputs.
2. If a stage has availability=true and complete=false, run starts there.
3. All earlier stages with complete=true and valid key outputs are skipped.
4. If user wants rerun from a stage, set that stage complete=false (and optionally later stages false).

## Flag Strategy (What We Likely Won't Need as Execution Toggles)
If manifest Availability controls per-PXD stage execution, these global run toggles become optional/default-only (not primary resume controls):
- run_organism_id
- run_search
- run_agentic_metadata
- run_llm_judge

Recommended approach:
- Keep existing flags for backward compatibility and initial bootstrap.
- Manifest is primary for per-PXD resume/skip.
- Flags become defaults when a PXD or stage is absent from manifest.

## Pipeline + User Co-Management
- User edits availability or complete to control reruns.
- Pipeline updates complete after successful stage completion and file validation.
- On startup, pipeline re-validates all key_outputs and auto-corrects stale complete=true entries if files are missing.

## Notes for Implementation Phase
- Keep updates atomic (write temp file then rename).
- Log per-PXD stage decisions at startup for transparency.
- Keep ResultsSummary independent so it still runs even when all PXDs are already complete.
