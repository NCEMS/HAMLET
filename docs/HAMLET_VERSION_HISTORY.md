# HAMLET Version History

This log records agentic metadata prompt changes and their evaluation status.
The v2.1.2 through v2.1.7 comparisons use the fixed 20-PXD cohort in
`assets/pxd_lists/HAMLET_v2.1.2_low_accuracy_20.csv` and three judge runs per
PXD. Results are indicators of quality, not deterministic ground truth.

## v2.2.5 - Analyzer Provenance and Safe Cell-Line Overrides

Status: changes ready for the fixed 20-PXD cohort rerun.

The final judge now maps TechnicalAgent `mass_analyzer` values sourced from METI
to RunAssessor provenance. Manuscript-absent analyzer values such as `Orbitrap`
remain manuscript-unsupported, but are classified as `runassessor_only` and
credited in `judge_accuracy_adjusted` rather than counted as hallucinations.

Finalization now blocks an LLM refinement override for `cell_line` when it is a
strict comma-separated superset of the integrated value. This preserves a
supported MS cell line such as `HAP1` when the refinement judge proposes
`HAP1, HeLa`, while allowing a genuine replacement such as `HeLa` to `HAP1`.
The guard targets nine v2.2.4 residual cell-line errors caused by additive
overrides; it does not suppress cell-line corrections or alter other fields.

## v2.2.4 - RunAssessor Acquisition Provenance

Status: evaluated on the fixed 20-PXD cohort on 2026-09-20.

Final `sdrf_judge` now recognises `runAssessor.search_criteria.acquisition_type`
as authoritative repository provenance. The RunAssessor `DDA` and `DIA` codes
are matched to final SDRF `data-dependent acquisition` and `data-independent
acquisition` values. A strict manuscript-absent acquisition value remains
manuscript-unsupported, but is now classified as `runassessor_only` and credited
by `judge_accuracy_adjusted` rather than counted as a hallucination.

This targets the 15 v2.2.3 final acquisition-method flags: 14 DDA and one DIA,
all rendered from RunAssessor per-RAW acquisition evidence.

## v2.2.3 - Biological MS-Sample Context

Status: changes ready for the fixed 20-PXD cohort rerun.

The BiologicalAgent prompt now identifies the material prepared for the PXD
proteomics workflow before extracting any biological field. Species, tissue,
cell type, disease, sample source, age, tumor site, BMI, cell line, sex, and
strain must describe that MS sample; values from validation assays, expression
hosts, animal models, pathology, histology, binding experiments, and unrelated
background biology are excluded. Biological inferences are now conditional on
the same MS-sample evidence, with targeted examples for the recurrent HAP1/HeLa,
HEK293T/mouse, and non-MS cell-assay failure modes.

This targets the 53 residual BiologicalAgent errors in the v2.2.2 final judge:
15 cell-line, 9 organ, 9 age, 7 cell-type, 6 disease, 5 species, and 2 sex
errors. It does not change final SDRF provenance scoring or the pre-finalization
refinement judge.

The completed cohort is in `results_hamletpxds_agentic_v2_2_3`. Across 315 final
SDRF values, strict manuscript-only accuracy was 46.03% (145/315) and weighted
provenance-adjusted accuracy was 82.22% (259/315). Per-PXD adjusted accuracy
increased from a 73.88% mean and 75.00% median in v2.2.2 to an 82.25% mean and
81.25% median in v2.2.3. Residual BiologicalAgent errors fell from 53 to 17.

## v2.2.2 - Repository-Backed Final Judge Provenance

Status: evaluated on the fixed 20-PXD cohort on 2026-09-20.

Final `sdrf_judge` review now distinguishes manuscript-absent SDRF values that
are backed by authoritative deposited metadata from actual hallucinations. The
annotation review reports `repository_origin` and classifies these as
`runassessor_only`, `pride_repository_only`, or `ptm_shepherd_only` rather than
`hallucinated`. Raw manuscript accuracy remains text-only; adjusted accuracy
credits repository-backed values, with separate count columns for each source.

The finalizer supplies the TechnicalAgent enriched metadata directory to the
final judge. This preserves the final SDRF content while allowing PRIDE PTM
declarations and per-RAW PTM-Shepherd search evidence to be audited as distinct
repository evidence.

The completed agentic-only cohort is in `results_hamletpxds_agentic_v2_2_2`.
Across 358 final SDRF values, strict manuscript-only accuracy was 40.22%
(144/358), compared with 40.11% (146/364) for v2.2.1. Provenance-adjusted
accuracy was 73.46%: 29 values were backed by RunAssessor, 22 by PRIDE project
metadata, and 68 by PTM-Shepherd. Strict manuscript hallucinations fell from
180 in v2.2.1 to 52 in v2.2.2; the lower final-value count and changing SDRFs
mean this is a fresh-cohort comparison rather than a fully controlled
same-SDRF ablation.

## v2.2.1 - Final SDRF Judge Restoration

Status: ready for the fixed 20-PXD cohort rerun.

`LLm_as_judge.py` remains the pre-finalization refinement stage. Its outputs
are published under `<PXD>/llm_refinement_judge/` and are used only to select
safe overrides while constructing the SDRF. After the final SDRF is rendered,
`finalize_sdrf.py` now always evaluates that exact file through
`sdrf_judge.py`; its canonical final metrics and review artifacts are published
under `<PXD>/sdrf_judge/`.

Finalization now requires a readable PMC cache and a non-empty final judge
result. The stage manifest and release-promotion utility require the final
`sdrf_judge/llm_judge_per_paper.csv`, preventing an SDRF without final
evaluation evidence from being reused or promoted. Historical v2.1.x judge
paths remain supported only as fallbacks when reading immutable releases.

## v2.1.11 - Experimental Manifest Isolation

Status: changes ready for the next controlled cohort rerun against v2.1.7.

This experiment retains v2.1.9 count and replicate safety rules while isolating
their context to the agent that owns those fields:

- `BiologicalAgent` and `TechnicalAgent` receive the exact pre-v2.1.8
  publication-plus-filename descriptor format.
- `ExperimentalDesignAgent` alone receives the structured PRIDE RAW manifest
  and its count/replicate interpretation guidance.
- The experimental prompt explicitly bars RAW filenames and manifest counts
  from shaping `experimental_design` or `factor_value`; those fields use only
  PXD-MS-linked publication evidence.

This addresses v2.1.9's broad regressions in biological metadata, experimental
design, and factor value while preserving its improved count/replicate safety.
Validation passed: five descriptor tests, 32 focused extractor/validator
tests, prompt compilation, and all prompt-template formatting checks.

## v2.1.9 - Cache-Corrected Structured Experimental Count Evidence

Status: changes ready for the next controlled cohort rerun against v2.1.7.

This rerun preserves the intended v2.1.8 scope and fixes descriptor staging in
`src/python/run_agentic_metadata.py`: the temporary
`/tmp/{PXD}_PubText.txt` file is now rebuilt for every extraction rather than
reused when present. A focused regression test verifies that an existing file
is overwritten with the current publication and PRIDE-manifest descriptor.

## v2.1.8 - Structured Experimental Count Evidence

Status: superseded; `results_hamletpxds_agentic_v2_1_8` must not be compared
as an evaluation of this change.

This experiment is limited to experimental-design count evidence:

- `src/python/run_agentic_metadata.py` now preserves the existing publication
  text and appends a separately labelled PRIDE RAW data-file manifest. The
  manifest explicitly states that a RAW-file count is an acquisition count,
  not a biological-sample, replicate, or fraction count.
- `ExperimentalDesignAgent` now defines `number_of_samples` as distinct
  biological specimens or materials processed in the submitted PXD MS
  experiment. It prioritizes PXD-MS-linked METHODS, RESULTS, and FIGURE
  CAPTIONS, excluding background, ancillary assays, and non-MS cohorts.
- Sample counts may be emitted only from an explicit count or complete,
  explicitly enumerated PXD-MS inventory. Counts cannot be derived from RAW
  files, fractions, injections, technical repeats, or blanks.
- Replicate fields retain the v2.1.6 type-safety rules and now explicitly
  reject RAW-manifest-only inference. The unsupported default of one
  biological replicate was removed; unclear PXD-MS replicate evidence yields
  `unknown`.

No biological, technical, material-type, SDRF-builder, or judge changes are
included. Validation passed: two descriptor tests, 32 focused
extractor/validator tests, prompt compilation, and all prompt-template
formatting checks.

The completed v2.1.8 pipeline run reused existing
`/tmp/{PXD}_PubText.txt` files because the staging code regenerated a
descriptor only when that path did not exist. Inspection found none of the new
descriptor markers in the resulting extraction artifacts. It therefore tested
the stricter experimental prompt against stale, unstructured inputs, not the
planned publication-plus-manifest context. The cache-corrected rerun is
tracked as v2.1.9 to preserve these artifacts for diagnosis.

## v2.1.7 - Material-Type Contract Refinement

Status: evaluated against v2.1.6 on the fixed 20-PXD cohort. Output is stored
in `results_hamletpxds_agentic_v2_1_7`.

This is a single-field experiment in `src/agentic-metadata/core/prompts.py`.
The `BiologicalAgent/sample_source` output, rendered downstream as SDRF
`material_type`, now returns only broad material classes: `tissue`, `cell
line`, `primary cells`, `biofluid`, `plasma`, `serum`, `whole organism`, or
`organoid`. It may normalize an explicit PXD-MS sample description, such as a
named established cell line to `cell line`, while retaining the source sentence
as evidence.

The change prevents free-text origins and non-material descriptions such as
`cell culture`, donor/patient descriptions, biopsies, named cell lines,
anatomy, specimen formats, models, suppliers, and institutions from being
emitted as material type. All other v2.1.6 prompt behavior, including the
replicate type-safety rules, is unchanged.

Rationale: `BiologicalAgent/material_type` was the largest controllable v2.1.6
error category, with 48 combined incorrect, incomplete, type-mismatch, and low
verdict flags. The recurrent failure emitted `cell culture` where the SDRF
contract requires `cell line` or `primary cells`.

Outcome compared with v2.1.6:

| Measure | v2.1.6 | v2.1.7 | Delta |
| --- | ---: | ---: | ---: |
| Mean judge accuracy | 0.5794 | 0.6371 | +0.0577 |
| Median judge accuracy | 0.5670 | 0.6181 | +0.0511 |
| Correct annotations | 180 | 209 | +29 |
| Extracted annotations | 313 | 328 | +15 |
| Type mismatches | 23 | 9 | -14 |
| Incorrect values | 42 | 22 | -20 |
| Incomplete values | 58 | 54 | -4 |
| Hallucinations | 33 | 43 | +10 |

v2.1.7 improved 13 PXDs, was unchanged for 2, and regressed for 5. The
largest gains were PXD028480 (+0.2000), PXD023906 (+0.1765), and PXD043087
(+0.1667). The material-type contract substantially reduced mismatches and
wrong values, while the rise in hallucination flags motivates the more
evidence-constrained v2.1.8 count experiment.

## v2.1.6 - v2.1.2 Baseline With Replicate Type Safety

Status: evaluated against v2.1.5 on the fixed 20-PXD cohort. Output is stored
in `results_hamletpxds_agentic_v2_1_6`.

`src/agentic-metadata/core/prompts.py` was restored to the exact v2.1.2 cohort
revision (`ea1e8d8b22ecdf946084253a51a2f8170bb4c8b2`), the highest-scoring
fixed-cohort prompt baseline. The only intentional deviation is a narrow
replicate type-safety rule:

- Biological and technical replicate outputs must be numeric counts linked to
  the submitted PXD MS experiment.
- Cell lines, conditions, treatments, probes, clones, fractions, sample
  descriptions, and non-MS assay counts cannot be emitted as replicates.
- Explicit replicate words such as single, duplicate, triplicate, and
  quadruplicate may normalize to `1`, `2`, `3`, and `4` respectively, with the
  source phrase retained as evidence.

No v2.1.3-v2.1.5 broad scope, field-contract, count-inventory, or label-free
changes remain in the v2.1.6 prompt. Validation passed: prompt compilation,
template formatting, and 31 focused extractor/validator tests.

Outcome compared with v2.1.5:

| Measure | v2.1.5 | v2.1.6 | Delta |
| --- | ---: | ---: | ---: |
| Mean judge accuracy | 0.436115 | 0.579380 | +0.143265 |
| Median judge accuracy | 0.422650 | 0.566950 | +0.144300 |
| Correct annotations | 86 | 180 | +94 |
| Extracted annotations | 191 | 313 | +122 |
| Type mismatches | 5 | 23 | +18 |
| Incorrect values | 49 | 75 | +26 |
| Incomplete values | 105 | 133 | +28 |
| Hallucinations | 33 | 33 | 0 |
| Low verdicts | 49 | 75 | +26 |

v2.1.6 improved 16 PXDs, was unchanged for 0, and regressed for 4. The
largest gains were PXD041051 (+0.5059), PXD016814 (+0.3175), PXD018749
(+0.3000), PXD024642 (+0.2917), and PXD070229 (+0.2549). The regressions were
PXD044788 (-0.1000), PXD006856 (-0.0598), PXD041561 (-0.0539), and PXD016311
(-0.0208). The restored baseline substantially improved overall accuracy and
coverage, while reopening field-contract errors that v2.1.7 isolates only for
material type.

## v2.1.5 - Evidence-Supported Coverage Recovery

Status: evaluated against v2.1.4 on the fixed 20-PXD cohort. Output is stored
in `results_hamletpxds_agentic_v2_1_5`.

Review basis: all v2.1.4 judge review and corrected-value records for the
fixed 20-PXD cohort, the local SDRF builder contract, and the PRIDE
SDRF-Proteomics specification. SDRF rows describe the relationship between
an analyzed sample and its associated data file; metadata from an ancillary
experiment must not be added merely because it occurs in the same paper.

Changes to `src/agentic-metadata/core/prompts.py`:

- Added a biological evidence ledger: enumerate every PXD-MS-linked cohort in
  source order while excluding background and non-MS models. Explicit,
  PXD-MS-linked disease labels are preserved rather than reduced to `normal`.
- Replaced the contradictory label-free guidance with direct evidence rules:
  accept explicit label-free/LFQ or directly linked quantification metadata;
  never infer label-free from the absence of a multiplex label.
- Made `1` valid for fractions only with explicit single-fraction or
  unfractionated PXD-MS evidence, and valid for biological replicates only
  with an explicitly complete single-unit PXD-MS set.
- Allowed `number_of_samples` only from an explicit total or a fully
  enumerated PXD-MS sample inventory; the prompt gives the `21 cell types plus
  plasma = 22` pattern as a conditional example.
- Aligned the experimental example and contracts so replicate fields contain
  numeric counts, never descriptions of samples, conditions, probes, or cell
  lines.
- Resolved an evidence-format conflict: literal values must occur verbatim in
  their evidence, while an allowed computed count or compact design/factor
  label may be normalized only when its evidence quotes every PXD-MS-linked
  source term used for the result.

The judge review found that most v2.1.4 removals (`fractions=1` and
`label-free`) were absence-based defaults and remain intentionally excluded.
The v2.1.5 changes recover only directly evidenced values, preserving v2.1.4's
gains in type mismatch and hallucination reduction.

Correction disposition: the 20-PXD v2.1.4 review has 114 non-high or
corrected rows across 15 fields. The multi-value suggestions for species,
organ, cell line, strain, sex, disease, and material type are handled by the
evidence ledger only when each value is linked to PXD MS samples. Suggestions
that arise from ancillary assays remain excluded. Exact instrument corrections
are covered by the PXD-linked exact-model rule. All `number_of_samples` and
`technical_replicates` corrections that proposed no replacement remain
intentionally excluded; the only recoverable count cases are explicit totals,
fully enumerated PXD-MS inventories, and explicitly complete single units.

Outcome compared with v2.1.4:

| Measure | v2.1.4 | v2.1.5 | Delta |
| --- | ---: | ---: | ---: |
| Mean judge accuracy | 0.4611 | 0.4361 | -0.0250 |
| Median judge accuracy | 0.5000 | 0.4227 | -0.0773 |
| Correct annotations | 99 | 86 | -13 |
| Extracted annotations | 214 | 191 | -23 |
| Type mismatches | 19 | 5 | -14 |
| Incorrect values | 58 | 49 | -9 |
| Incomplete values | 115 | 105 | -10 |
| Hallucinations | 27 | 33 | +6 |
| Low verdicts | 58 | 49 | -9 |

v2.1.5 improved 9 PXDs, was unchanged for 1, and regressed for 10. The major
gain was eliminating replicate type mismatches (13 to 0) and reducing low
replicate verdicts (18 to 6). The major regression was count recovery:
`number_of_samples` errors rose from 11 to 14 and hallucinations from 6 to 10.
Recovered totals such as PXD018749 `2`, PXD039394 `3`, and PXD009298 `3` were
all judged unsupported. The recovered PXD016311 fraction count `2` was also
incorrect (judge correction: `1`).

The direct-evidence label rule also removed several formerly correct
`label-free` values. This indicates that the agent prompt does not consistently
receive the linked search/PRIDE quantification evidence described in the rule;
the next solution should pass that structured value into the extraction context
or preserve it through the technical integration path, rather than restoring an
absence-based language-model inference.

## v2.1.4 - Field-Contract Refinement

Status: evaluated against v2.1.3 and v2.1.1 on the fixed 20-PXD cohort. Output
is stored in `results_hamletpxds_agentic_v2_1_4`.

Changes to `src/agentic-metadata/core/prompts.py`:

- Biological metadata: direct-evidence contracts for species, organ/tissue,
  cell type, cell line, disease, age, sex, strain, tumor site, and material
  type; removed disease and cell-type inference from cell-line lore.
- Technical metadata: field-specific source and scope rules for acquisition
  method, instrument, digestion, alkylation/reduction, enrichment,
  fractionation, fragmentation, collision energy, ionization, mass analyzer,
  labeling, tolerances, and modifications.
- Experimental metadata: removed default values for fractions and biological
  replicates; require an explicit PXD-MS-linked numeric count for every count
  field; prevent group names, factor levels, probes, and conditions from being
  emitted as replicate or sample counts.
- Experimental design: require compact study-structure labels and reserve
  `single-group profiling` for confirmed single-group studies.

Rationale: v2.1.3 retained errors in replicate counts, instruments, sample
counts, disease/cell-type inference, and incomplete multi-value extraction.

Environment update: `src/conda_envs/meti_env.yml` now installs
`litellm==1.82.0`, required by the agentic-metadata DocETL pipeline. `src/setup.sh`
uses this environment file for both new and existing `meti_env` installations.

Validation: `core/prompts.py` compiles; all prompt templates format; focused
extractor and validator tests pass (31 tests). After installing LiteLLM,
DocETL tests ran with 36 passing and one blocked test because the separate
`docetl` package is not installed.

Outcome compared with v2.1.3:

| Measure | v2.1.3 | v2.1.4 | Delta |
| --- | ---: | ---: | ---: |
| Mean judge accuracy | 0.4874 | 0.4611 | -0.0263 |
| Median judge accuracy | 0.5167 | 0.5000 | -0.0167 |
| Correct annotations | 128 | 99 | -29 |
| Extracted annotations | 261 | 214 | -47 |
| Type mismatches | 24 | 19 | -5 |
| Incorrect values | 71 | 58 | -13 |
| Incomplete values | 133 | 115 | -18 |
| Hallucinations | 32 | 27 | -5 |
| Low verdicts | 72 | 58 | -14 |

v2.1.4 improved 7 PXDs, was unchanged for 1, and regressed for 12. The
largest losses were PXD026139 (-0.1846), PXD006856 (-0.1667), and PXD016311
(-0.0983); the largest gain was PXD028480 (+0.1429). The stricter count rules
reduced errors in `number_of_samples` (15 to 11 incorrect/low) and
`replicates` (22 to 18 incorrect/low), but over-suppressed source-supported
values such as an explicit one fraction, total sample count, label-free
quantification, and disease status. A subsequent refinement should keep the
evidence gates while allowing explicitly supported single values, rather than
using a blanket no-default rule.

Outcome compared with v2.1.1: mean judge accuracy rose from 0.4068 to 0.4611
(+0.0543); 12 PXDs improved, 2 were unchanged, and 6 regressed. v2.1.4 still
has substantially fewer flagged values than the v2.1.1 baseline: 19 versus 68
type mismatches, 58 versus 123 incorrect values, 115 versus 172 incomplete
values, 27 versus 41 hallucinations, and 58 versus 122 low verdicts.

## v2.1.3 - Count and Instrument Eligibility Refinement

Status: evaluated against v2.1.2 on the fixed 20-PXD cohort.

Changes:

- Added an explicit exact-model/PXD-run linkage check for instruments.
- Added a count decision check requiring a counted unit, count role, and PXD
  MS linkage before emitting replicate or sample counts.
- Required compact design labels and prohibited `single-group profiling` when
  an eligible multi-level factor is present.

Outcome compared with v2.1.2:

| Measure | v2.1.2 | v2.1.3 | Delta |
| --- | ---: | ---: | ---: |
| Mean judge accuracy | 0.4949 | 0.4874 | -0.0075 |
| Median judge accuracy | 0.5000 | 0.5167 | +0.0167 |
| Correct annotations | 129 | 128 | -1 |
| Extracted annotations | 262 | 261 | -1 |
| Incorrect values | 76 | 71 | -5 |
| Low verdicts | 76 | 72 | -4 |
| Type mismatches | 25 | 24 | -1 |
| Hallucinations | 33 | 32 | -1 |

The intended fields improved: incorrect `replicates` values fell from 28 to
22, and `experimental_design` type mismatches fell from 3 to 1. The slight
mean decline was concentrated in a small number of variable judge outcomes,
especially PXD043087. Instrument errors did not improve, and
`number_of_samples` errors increased from 14 to 15.

## v2.1.2 - Scope and SDRF-Type Refinement

Status: evaluated against v2.1.1 on the fixed 20-PXD cohort.

Changes:

- Added PXD-MS sample eligibility gates to all three extraction agents.
- Restricted material type to controlled broad SDRF classes and prevented
  tissue inference from cell-line origin.
- Required exact instrument evidence and separated enrichment from
  fractionation.
- Added count-role checks, compact experimental-design guidance, and cautious
  defaults for experimental metadata.

Outcome compared with v2.1.1:

| Measure | v2.1.1 | v2.1.2 | Delta |
| --- | ---: | ---: | ---: |
| Mean judge accuracy | 0.4068 | 0.4949 | +0.0881 |
| Median judge accuracy | 0.3923 | 0.5000 | +0.1077 |
| Correct annotations | 119 | 129 | +10 |
| Extracted annotations | 291 | 262 | -29 |
| Type mismatches | 68 | 25 | -43 |
| Incorrect values | 123 | 76 | -47 |
| Incomplete values | 172 | 133 | -39 |
| Hallucinations | 41 | 33 | -8 |
| Low verdicts | 122 | 76 | -46 |

The largest improvement was material type: type mismatches fell from 19 to 0
and incorrect material-type values fell from 19 to 1. The conservative gates
also reduced invalid biological and design inferences, at the cost of fewer
extracted annotations.

## v2.1.1 - Baseline Release and Audit

Status: initial reviewed agentic release used as the baseline for the focused
low-accuracy cohort.

The release-level findings and wider 299-PXD judge analysis are documented in
`HAMLET_V2.1.1_sdrf_judge_report.md`. The follow-up low-accuracy integrator
audit is documented in `HAMLET_V2.1.1_LOW_ACCURACY_INTEGRATOR_AUDIT.md`.