# Potential New Features Report: PXD-Scoped Metadata Extraction

Date: 2026-07-01

## Summary

This report proposes follow-on features to improve metadata extraction quality for SDRF generation, with focus on avoiding context leakage from non-sample experiments and improving provenance, validation, and maintainability.

## Current Gap Pattern

The key failure mode observed is context bleed-through: metadata terms mentioned in the paper (for example recombinant-expression cell lines) can be extracted even when they are not part of the submitted PXD proteomics samples.

## Proposed Features

### 1) Sample-Linked Context Classifier (Pre-Filter)

Add a lightweight classifier over text chunks/sentences to label context as:
- `sample_linked_proteomics`
- `auxiliary_non_proteomics`
- `ambiguous`

Only `sample_linked_proteomics` evidence should be eligible for extraction by default.

Expected impact:
- Reduce false positives for `cell_line`, `species`, `disease_state`, and `sample_source`.

### 2) Field-Specific Guardrails in Integration

Add deterministic post-extraction guardrails in integration for sensitive biological fields:
- If `cell_line` is LLM-only and evidence is not sample-linked, force `unknown`.
- If PRIDE sample metadata and paper sample metadata agree, prefer that over tool/LLM outliers.

Expected impact:
- Better behavior even when prompt behavior drifts.

### 3) Provenance Context Tags

Extend integrated outputs with per-field provenance tags:
- `source_type` (pride, llm, meti)
- `source_context` (sample_linked, auxiliary, unknown)
- `decision_rule` (majority_vote, pride_priority, guardrail_override)

Expected impact:
- Easier debugging and auditability.

### 4) PRIDE-First Structured Signals

Increase usage of structured PRIDE fields for biological attributes before free-text inference:
- `project.organisms`
- `sampleProcessingProtocol`
- sample attributes where available

Expected impact:
- More stable extraction on noisy/manuscript-heavy projects.

### 5) Conflict Detector and Warning Layer

Add conflict flags when sources disagree on key fields:
- species/tool conflict
- tissue/cell-line incompatibility
- disease inconsistency

Include warnings in output JSON and optional report summary.

Expected impact:
- Prevent silent incorrect defaults.

### 6) Regression Test Corpus for Known Failure Modes

Create test fixtures for:
- recombinant-expression mentions not part of MS samples
- mixed-species data
- non-model organism projects
- IP/affinity workflows with dominant background species

Expected impact:
- Catch regressions quickly after prompt or rule changes.

### 7) Optional Strict Mode for SDRF-Critical Fields

Add a strict mode where SDRF-critical biological fields require:
- PRIDE support, or
- explicit sample-linked evidence with high confidence

Otherwise set to `unknown` and emit warning.

Expected impact:
- Conservative and safer SDRF output when confidence is low.

### 8) Scoring Improvements

Update confidence scoring with penalties for:
- evidence from auxiliary context
- value/evidence mismatch quality
- unsupported inference chains

Expected impact:
- Confidence better reflects real reliability.

## Suggested Implementation Order

1. Add integration guardrails for `cell_line` and other sensitive biological fields.
2. Add provenance context tags to integrated output.
3. Add regression fixtures for known failure modes.
4. Add lightweight context classifier.
5. Add strict mode and enhanced conflict reporting.

## Success Criteria

- PXD-style cases with auxiliary HEK293T mentions no longer populate `characteristics[cell line]` unless sample-linked.
- Species/tissue fields remain aligned with PRIDE sample-level metadata when available.
- Integrated output explains *why* each value was chosen with explicit context/provenance.
