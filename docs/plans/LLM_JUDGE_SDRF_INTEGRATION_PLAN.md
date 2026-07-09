# LLM Judge to SDRF Integration Plan

Date: 2026-07-01
Status: Draft
Scope: Integrate `llm_judge` outputs into final SDRF generation without breaking current HAMLET workflow structure.

## 1. Problem Statement

Current workflow ordering is:

1. `aggregate_results`
2. `agentic_metadata_extraction`
3. SDRF is written inside `run_agentic_metadata.py`
4. `llm_judge`
5. `results_summary`

This means `llm_judge` currently evaluates metadata and SDRF-related content only after the SDRF has already been written. As a result, judge findings can inform manual review, but cannot improve final SDRF output automatically.

## 2. Core Question

If we want `llm_judge` to affect final SDRF output, should we call the judge inside `agentic_metadata_extraction`, or should we keep `llm_judge` as a separate process?

## 3. Recommendation

Recommendation: keep `llm_judge` as a separate Nextflow process.

Do not embed final judge execution directly inside `agentic_metadata_extraction` as the primary design.

Instead:

1. Change `agentic_metadata_extraction` to stop at integrated metadata output.
2. Keep `llm_judge` as an independent downstream process.
3. Add a new downstream process that consumes:
   - integrated metadata output
   - judge output
   - aggregated results JSON
4. Write the final SDRF in that new process.

This preserves modularity, caching, optional execution, and observability.

## 4. Why Not Put `llm_judge` Inside `agentic_metadata_extraction`?

Embedding judge directly in `agentic_metadata_extraction` would work technically, but has several drawbacks:

### 4.1 Coupled responsibilities

`agentic_metadata_extraction` currently does two things already:
- run agentic extraction
- write SDRF

Adding judge execution would make it do three logically distinct jobs:
- extract metadata
- evaluate metadata
- finalize metadata output

That is too much responsibility for one process.

### 4.2 Worse cache granularity

If judge logic changes, or if the judge model changes, the whole extraction step would need to rerun.

Keeping the judge separate allows:
- extraction cache to remain valid
- judge reruns without re-extraction
- SDRF regeneration from existing artifacts

### 4.3 Harder failure handling

Judge is currently non-blocking and isolated. If placed inside extraction, failures become harder to reason about:
- did extraction fail?
- did judge fail?
- did SDRF finalization fail?

### 4.4 Harder optionality

`run_agentic_metadata` and `run_llm_judge` are already independent workflow toggles. Keeping that separation is valuable.

## 5. Target Architecture

Recommended future ordering:

1. `aggregate_results`
2. `agentic_metadata_extraction`
3. `llm_judge`
4. `sdrf_finalize`
5. `results_summary`

### 5.1 New responsibility split

#### `agentic_metadata_extraction`
Produces only:
- biological integrated JSON
- technical integrated JSON
- experimental design integrated JSON
- any raw annotation outputs

Does not write final SDRF.

#### `llm_judge`
Consumes integrated metadata and emits:
- annotation review CSV
- per-paper summary CSV
- coverage CSV
- machine-readable structured override JSON

#### `sdrf_finalize`
Consumes:
- integrated metadata output
- aggregated results JSON
- structured judge overrides

Writes:
- final SDRF TSV
- optional SDRF decision report

## 6. Minimal Viable Implementation

The lowest-risk first version should avoid letting the judge rewrite everything.

### Phase 1: structured judge overrides for a small safe field set

Only allow judge-informed overrides for fields that are:
- high value for SDRF correctness
- low ambiguity
- naturally scalar

Recommended initial fields:
- organism
- organism part
- instrument
- number of biological replicates
- number of technical replicates
- number of fractions

Do not auto-override yet for:
- factor values
- experimental design free text
- disease
- sex
- sample_source
- material_type

### Phase 1 behavior

For each candidate field:

1. If judge verdict is `high` and pipeline value is correct, keep original value.
2. If judge marks value hallucinated or incorrect and provides a safe corrected value, use override.
3. If judge says incorrect but corrected value is missing or ambiguous, keep original value and emit warning.

## 7. Required Code Changes

### 7.1 `src/python/run_agentic_metadata.py`

Current state:
- runs extraction
- immediately calls `agentic_to_sdrf(...)`

Planned change:
- add a flag such as `--skip_sdrf_write` or invert flow to extraction-only mode
- keep helper code reusable for downstream finalization

Alternative:
- move SDRF writing logic entirely out of this script and into a new script

Preferred option:
- keep extraction here
- move SDRF finalization to a new script

### 7.2 `main.nf`

Current state:
- `agentic_metadata_extraction` calls `run_agentic_metadata.py`
- `llm_judge` runs later

Planned changes:

1. Update `agentic_metadata_extraction` so it no longer validates presence of `*.sdrf.tsv`.
2. Keep `llm_judge` process.
3. Add new process, e.g. `finalize_sdrf`.
4. Wire `finalize_sdrf` after `llm_judge` when judge is enabled.
5. If judge is disabled, `finalize_sdrf` should still run using integrated metadata only.

### 7.3 `src/python/LLm_as_judge.py`

Current state:
- emits CSV summaries and JSON outputs
- does not emit a normalized override artifact designed for machine consumption

Planned change:
- add a compact machine-readable output such as:

```json
{
  "paper_id": "PXD073162",
  "field_overrides": {
    "instrument": {
      "pipeline_value": "Q Exactive HF-X",
      "judge_verdict": "low",
      "hallucination": true,
      "corrected_value": "Q Exactive HF",
      "apply_override": true,
      "rationale": "text supports HF, not HF-X"
    }
  }
}
```

Suggested filename:
- `judge_output/json_outputs/PXD073162_sdrf_overrides.json`

### 7.4 New script: `src/python/finalize_sdrf.py`

Responsibilities:

1. Load integrated metadata JSONs.
2. Load aggregated results JSON.
3. Optionally load structured judge override JSON.
4. Apply override policy.
5. Call `AgenticToSDRF` with either:
   - patched temporary JSONs, or
   - explicit override map passed into builder
6. Write final SDRF.
7. Emit optional decision report.

### 7.5 `src/python/sdrf_builder.py`

Planned change:
- add optional override hook support

Suggested API:

```python
builder = AgenticToSDRF(
    tech_json=tech_json,
    bio_json=bio_json,
    exp_json=exp_json,
    aggregated_json=aggregated_json,
    overrides=override_dict,
)
```

Or alternatively:

```python
builder.apply_overrides(override_dict)
builder.to_sdrf(output_path)
```

Recommended approach:
- support overrides at field resolution layer rather than patching TSV rows after write

## 8. Override Policy

The judge must not become a freeform rewrite engine.

Recommended policy:

### Allow override only when all are true

1. Field is in approved safe field list.
2. Judge verdict is `low` or hallucination flag is true.
3. Judge provides a single corrected value.
4. Corrected value type matches expected SDRF field type.
5. Corrected value is not multi-valued unless field supports it.

### Do not override when any are true

1. Corrected value is missing.
2. Corrected value is multi-valued for scalar field.
3. Judge verdict is only `medium` and correction is expansive/interpretive.
4. Field is free text or semantically broad.

## 9. Whether We Still Need the `llm_judge` Process

Short answer: yes, under the recommended architecture.

We still want the standalone `llm_judge` process because it provides:
- independent evaluation artifacts
- reusable QA outputs
- separate caching and reruns
- optional non-blocking execution
- a clean place to emit machine-readable overrides

If you instead move judge entirely inside `agentic_metadata_extraction`, then the standalone `llm_judge` process becomes redundant for pipeline execution, but you would lose modularity and likely still want a separate benchmark/evaluation mode for development. So even then, you would probably keep the Python script, but not necessarily the Nextflow process.

Therefore:

### Recommended answer

Keep:
- `LLm_as_judge.py`
- `llm_judge` Nextflow process

Add:
- `finalize_sdrf` Nextflow process

Reduce:
- SDRF writing inside `agentic_metadata_extraction`

## 10. Proposed Workflow Refactor

### Current

```text
aggregate_results
  -> agentic_metadata_extraction
      -> writes final SDRF
  -> llm_judge
  -> results_summary
```

### Proposed

```text
aggregate_results
  -> agentic_metadata_extraction
  -> llm_judge
  -> finalize_sdrf
  -> results_summary
```

### With judge disabled

```text
aggregate_results
  -> agentic_metadata_extraction
  -> finalize_sdrf
  -> results_summary
```

## 11. Validation Plan

### Functional checks

1. Judge disabled:
- final SDRF still builds successfully
- outputs match current behavior

2. Judge enabled with no overrides:
- final SDRF matches non-judge output
- judge artifacts still produced

3. Judge enabled with safe override:
- field is corrected in final SDRF
- decision report records override

### Regression dataset

Use PXD073162 as first integration test because it already exposes:
- organism conflict case
- previous cell line contamination case
- instrument mismatch case
- replicate ambiguity case

## 12. Deliverables

### Phase 1 deliverables

1. Structured override JSON emitted by judge.
2. New `finalize_sdrf.py` script.
3. `main.nf` wiring for downstream final SDRF creation.
4. `run_agentic_metadata.py` changed to extraction-only or optional SDRF mode.
5. Safe override policy for a minimal field set.

### Phase 2 deliverables

1. Expanded override coverage.
2. Better provenance reporting.
3. Dataset-level summary of judge-driven SDRF corrections.

## 13. Recommendation Summary

Do not solve this by simply calling `LLm_as_judge.py` inside `agentic_metadata_extraction` and deleting the `llm_judge` process.

Instead:

1. Keep `llm_judge` as a separate process.
2. Stop writing the final SDRF before judge runs.
3. Add a new downstream SDRF finalization process that consumes judge outputs.
4. Limit auto-corrections to a narrow safe field set first.

That gives the cleanest architecture and the lowest implementation risk.
