# HAMLET Version History

This log summarizes changes to the agentic metadata and SDRF workflow described
in the [project README](../README.md). Each entry names the implementation
surface so a researcher can connect a Version QC distribution to the pipeline
step that produced it. Versions before v2.2.1 use the historical
pre-finalization `llm_judge`; v2.2.1 and later use `sdrf_judge` on the rendered
SDRF, so their judge distributions must not be compared directly.

## v2.2.5 - Analyzer Provenance and Safe Cell-Line Overrides

Status: immutable 423-PXD release finalized on 2026-09-21. Every stored SDRF
has a completed final-SDRF judge snapshot.

- `src/python/sdrf_judge.py` recognizes METI-derived `mass_analyzer` values when RunAssessor supplies the same analyzer. Manuscript-absent analyzers such as `Orbitrap` are recorded as `runassessor_only`, contributing to `judge_accuracy_adjusted` rather than being called hallucinations.
- `src/python/finalize_sdrf.py` rejects a refinement override for `cell_line` when it is only a comma-separated superset of the integrated MS-sample value, such as replacing `HAP1` with `HAP1, HeLa`.
- The change preserves legitimate replacements and targets nine residual v2.2.4 cell-line errors caused by additive refinement overrides.

## v2.2.4 - RunAssessor Acquisition Provenance

Status: evaluated on the fixed 20-PXD cohort on 2026-09-20.

- `src/python/sdrf_judge.py` treats `runAssessor.search_criteria.acquisition_type` as deposited evidence for the final SDRF acquisition-method field.
- RunAssessor `DDA` and `DIA` values are matched to the SDRF controlled terms `data-dependent acquisition` and `data-independent acquisition`.
- Fifteen v2.2.3 acquisition-method flags (14 DDA and one DIA) are credited as `runassessor_only` when absent from the manuscript; strict manuscript accuracy remains unchanged.

## v2.2.3 - Biological MS-Sample Context

Status: evaluated on the fixed 20-PXD cohort; outputs are stored in `results_hamletpxds_agentic_v2_2_3`.

- `src/agentic-metadata/core/prompts.py` requires BiologicalAgent fields to describe the material analyzed in the submitted PXD proteomics workflow, not validation assays, expression hosts, pathology, or other background biology.
- The prompt narrows species, tissue, cell type, disease, sample source, age, cell line, sex, and strain extraction to PXD-MS-linked evidence; common HAP1/HeLa and HEK293T/mouse failure patterns are explicit exclusions.
- Final `sdrf_judge` review improved adjusted per-PXD accuracy from a 73.88% mean in v2.2.2 to 82.25% and reduced residual BiologicalAgent errors from 53 to 17. Strict and adjusted totals are not a controlled same-SDRF ablation because the rendered SDRFs changed.

## v2.2.2 - Repository-Backed Final Judge Provenance

Status: evaluated on the fixed 20-PXD cohort on 2026-09-20.

- `src/python/sdrf_judge.py` separates manuscript-absent values backed by RunAssessor, PRIDE project metadata, or PTM-Shepherd from unsupported hallucinations.
- `src/python/finalize_sdrf.py` passes TechnicalAgent enriched metadata to the final judge so deposited PTM and per-RAW search evidence can be assessed.
- `judge_accuracy` remains manuscript-text-only; `judge_accuracy_adjusted` credits the three repository-backed categories. The cohort produced 73.46% adjusted accuracy across 358 final values.

## v2.2.1 - Final SDRF Judge Restoration

Status: evaluated through final SDRF judging; this establishes the later `sdrf_judge` metric family.

- `src/python/finalize_sdrf.py` renders the SDRF and then invokes `src/python/sdrf_judge.py` on that exact file; final reports are published under `<PXD>/sdrf_judge/`.
- `main.nf` and `src/python/stage_manifest.py` require the final judge artifact for the `finalize_sdrf` stage in both full-pipeline and agentic-only execution.
- `src/job_scripts/updatestore.py` requires `sdrf_judge/llm_judge_per_paper.csv` before promoting an in-progress or finalized release, preventing unevaluated SDRFs from entering the versioned store.

## v2.1.11 - Experimental Manifest Isolation

Status: experimental 20-PXD snapshot; compare only with the stated v2.1.7 baseline.

- `src/python/run_agentic_metadata.py` and `src/agentic-metadata/core/prompts.py` provide the structured PRIDE RAW manifest only to ExperimentalDesignAgent.
- BiologicalAgent and TechnicalAgent return to the publication-plus-filename context used before v2.1.8, preventing manifest counts from changing biological or technical fields.
- ExperimentalDesignAgent may use the manifest for count and replicate interpretation, but must not let RAW-file counts determine `experimental_design` or `factor_value`.

## v2.1.10 - Archived Experimental Snapshot

Status: immutable 20-PXD archive.

- `results_hamletpxds_agentic_v2_1_10` was promoted by `src/job_scripts/updatestore.py` with its SDRF, agentic, and aggregate artifacts preserved under `store/*/v2.1.10/`.
- No distinct prompt or integrator change was recorded separately from the adjacent v2.1.9 and v2.1.11 experiments; treat this as an archived experimental result, not a standalone implementation claim.

## v2.1.9 - Cache-Corrected Structured Experimental Count Evidence

Status: experimental 20-PXD snapshot; rerun after v2.1.8 staging was found stale.

- `src/python/run_agentic_metadata.py` always rebuilds `/tmp/{PXD}_PubText.txt` from the current publication text and PRIDE manifest instead of reusing an existing descriptor.
- The correction ensures the v2.1.8 structured count prompt actually receives its intended context; a regression test verifies stale descriptors are overwritten.

## v2.1.8 - Structured Experimental Count Evidence

Status: superseded. Do not interpret `results_hamletpxds_agentic_v2_1_8` as a valid evaluation of this prompt change because the run used stale descriptors.

- `src/python/run_agentic_metadata.py` appends a labelled PRIDE RAW manifest to the publication descriptor and identifies RAW counts as acquisition counts rather than biological sample, replicate, or fraction counts.
- `src/agentic-metadata/core/prompts.py` limits `number_of_samples` and replicate fields to explicit or fully enumerated PXD-MS evidence; unclear evidence yields `unknown` rather than an inferred count.
- The prompt excludes counts from fractions, injections, technical repeats, blanks, or non-MS cohorts and retains the v2.1.6 replicate type-safety rules.

## v2.1.7 - Material-Type Contract Refinement

Status: evaluated against v2.1.6 on the fixed 20-PXD cohort.

- `src/agentic-metadata/core/prompts.py` restricts BiologicalAgent `sample_source`, rendered as SDRF `material_type`, to broad SDRF classes such as tissue, cell line, primary cells, biofluid, serum, whole organism, or organoid.
- The prompt rejects free-text origins, named cell lines, suppliers, anatomy, donor descriptions, and institutions as material-type values while retaining evidence for normalized classifications.
- Mean historical judge accuracy increased from 0.5794 to 0.6371; material-type type mismatches fell from 23 to 9, while hallucination flags increased from 33 to 43.

## v2.1.6 - Restored Baseline With Replicate Type Safety

Status: evaluated against v2.1.5 on the fixed 20-PXD cohort.

- `src/agentic-metadata/core/prompts.py` restores the v2.1.2 prompt baseline and retains only a narrow rule that biological and technical replicates must be numeric PXD-MS counts.
- The prompt permits normalized explicit terms such as duplicate or triplicate, but excludes cell lines, conditions, clones, fractions, and non-MS assay counts from replicate fields.
- Mean historical judge accuracy increased from 0.4361 to 0.5794; this restored broad coverage but reopened some field-contract errors that v2.1.7 addressed for material type.

## v2.1.5 - Evidence-Supported Coverage Recovery

Status: evaluated against v2.1.4 on the fixed 20-PXD cohort.

- `src/agentic-metadata/core/prompts.py` adds a PXD-MS evidence ledger and restores values only when each biological value, count, fraction, label, or design term is explicitly supported by the submitted experiment.
- The prompt allows explicit totals and complete PXD-MS inventories, rejects absence-based label-free and fraction defaults, and keeps replicate fields numeric.
- The release removed replicate type mismatches but reduced coverage and mean historical judge accuracy from 0.4611 to 0.4361, motivating restoration of the stronger v2.1.2 baseline in v2.1.6.

## v2.1.4 - Field-Contract Refinement

Status: evaluated against v2.1.3 and v2.1.1 on the fixed 20-PXD cohort.

- `src/agentic-metadata/core/prompts.py` adds field-specific PXD-MS evidence contracts for biological, technical, and experimental metadata, including exact instrument linkage and explicit count roles.
- `src/conda_envs/meti_env.yml` and `src/setup.sh` add LiteLLM needed by the agentic-metadata DocETL path.
- The stricter rules reduced type mismatches, incorrect values, incomplete values, and hallucinations relative to v2.1.1, but over-suppressed some explicitly supported single values and reduced mean historical judge accuracy to 0.4611.

## v2.1.3 - Count and Instrument Eligibility Refinement

Status: evaluated against v2.1.2 on the fixed 20-PXD cohort.

- `src/agentic-metadata/core/prompts.py` requires exact model and PXD-run linkage for instruments and requires a counted unit, count role, and PXD-MS linkage for sample or replicate counts.
- The same prompt requires compact experimental-design labels and disallows `single-group profiling` when an eligible multi-level factor exists.
- Replicate errors and experimental-design type mismatches improved, while instrument errors did not and `number_of_samples` errors increased; mean historical judge accuracy changed from 0.4949 to 0.4874.

## v2.1.2 - Scope and SDRF-Type Refinement

Status: evaluated against v2.1.1 on the fixed 20-PXD cohort.

- `src/agentic-metadata/core/prompts.py` adds PXD-MS eligibility gates to all three agents, restricts material type to broad SDRF classes, requires exact instrument evidence, and separates enrichment from fractionation.
- Experimental prompts add count-role checks, compact design guidance, and cautious defaults for fields with incomplete evidence.
- Mean historical judge accuracy increased from 0.4068 to 0.4949; type mismatches fell from 68 to 25 and incorrect values from 123 to 76, with fewer annotations emitted overall.

## v2.1.1 - Baseline Release and Audit

Status: initial reviewed agentic release and baseline for the low-accuracy cohort.

- `src/python/run_agentic_metadata.py`, `src/python/LLm_as_judge.py`, and the agentic-metadata integration produced the historical pre-finalization metadata and `llm_judge` metrics used by v2.1.x QC.
- The wider 299-PXD review is documented in `docs/HAMLET_V2.1.1_sdrf_judge_report.md`; the integrator follow-up is in `docs/HAMLET_V2.1.1_LOW_ACCURACY_INTEGRATOR_AUDIT.md`.
- Later v2.1.x experiments should be read against this baseline, while v2.2.1+ final-SDRF judge metrics are a different evaluation stage.

## v2.1.0 - Unified Run Versioning

Status: immutable legacy release.

- `src/python/hamlet_version.py` establishes the shared HAMLET version identifier used to stamp pipeline outputs.
- `src/python/aggregate_results.py` and `src/python/create_minimal_aggregated_results.py` record that version in normal and agentic-only aggregate outputs.
- `README.md` and `store/README.md` document the unified versioning and store layout so archived results can be interpreted with their pipeline revision.

## v2.0.0 - Legacy Agentic-Metadata Compatibility

Status: immutable legacy-store snapshot.

- `src/python/run_agentic_metadata.py` was updated for agentic-metadata v2.0.0 compatibility by passing `--meti-dir` rather than the removed `--runassessor-dir` option.
- The agentic-metadata submodule was subsequently advanced to v2.5.0; Version QC treats v2.0.0 as a historical `llm_judge` release.
- The versioned store preserves the legacy snapshot: 490 SDRFs, 1,822 agentic bundles, and 2,756 aggregate JSONs.