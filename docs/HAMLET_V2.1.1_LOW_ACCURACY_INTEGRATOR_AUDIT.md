# HAMLET v2.1.1 Low-Accuracy SDRF Integrator Audit

## Purpose and scope

This report identifies recurring causes of low HAMLET SDRF judge accuracy and
recommends changes to the `agentic-metadata` integration branch. It is an
evidence review only: no application, submodule, result, or store files were
changed while preparing it.

The audit uses completed v2.1.1 outputs under
`results_hamletpxds_agentic_v2_1_1/<PXD>/judge_output/`:

- `llm_judge_per_paper.csv` supplies each PXD's `judge_accuracy`.
- `llm_judge_annotation_review.csv` supplies field-level verdicts and the
  literal `type_mismatch`, `value_correct`, `value_complete`, and
  `hallucination` flags.

"Low accuracy" means `judge_accuracy <= 0.55`. This includes 115 of 299
completed PXD reports, with scores from `0.1429` through `0.5500`. All 115
review CSVs were readable and contributed 1,749 judged annotation rows.

The review flags overlap. For example, a value can be both incorrect and
incomplete. Counts below are therefore indicators of recurring failure modes,
not a partition of the rows or PXDs.

## Reproducible 20-PXD review sample

The detailed examples were independently checked in a reproducible sample of
20 low-score PXDs selected using `random.Random(42).sample(sorted(low_pxds),
20)`:

| PXD | Accuracy | PXD | Accuracy |
|---|---:|---|---:|
| PXD043087 | 0.3333 | PXD016814 | 0.5455 |
| PXD006856 | 0.3077 | PXD053353 | 0.2857 |
| PXD028480 | 0.2857 | PXD026139 | 0.4000 |
| PXD023959 | 0.3529 | PXD018749 | 0.4667 |
| PXD016311 | 0.5000 | PXD044788 | 0.4545 |
| PXD070229 | 0.3846 | PXD039394 | 0.3846 |
| PXD013685 | 0.3529 | PXD041051 | 0.3333 |
| PXD034074 | 0.5000 | PXD009298 | 0.2857 |
| PXD023906 | 0.4667 | PXD024642 | 0.4667 |
| PXD037907 | 0.5294 | PXD041561 | 0.5000 |

These 20 reports contain 291 annotation-review rows: 122 low, 50 medium, and
119 high verdicts. The full-cohort rankings below are the basis for the
recommendations; the sample supplies inspectable examples.

## Full low-score cohort findings

| Judge finding | Flagged rows | Interpretation |
|---|---:|---|
| Incomplete value set | 978 | A returned value may be valid, but the final set omits other values relevant to the MS study. |
| Incorrect value | 686 | The field value does not satisfy the field contract or is unsupported for the profiled material. |
| Low verdict | 684 | The judge's combined assessment is low. This largely tracks incorrect values but is not identical to them. |
| Type mismatch | 349 | The value is scientifically meaningful but placed in a field with incompatible semantics or abstraction level. |
| Hallucinated value | 270 | The value is absent from, or not supportable for, the MS experiment described in the paper. |

### Highest-frequency field failures

The strongest common patterns are shown below. These are field-level findings
across the 115 low-score reports.

| Agent and field | Type mismatch | Incorrect | Incomplete | Hallucinated | Primary diagnosis |
|---|---:|---:|---:|---:|---|
| ExperimentalDesignAgent: `replicates` | 100 | 159 | 166 | 36 | Numbers and sample descriptions are not tied to biological replication in the MS experiment. |
| BiologicalAgent: `material_type` | 102 | 102 | 108 | 0 | Specific sources or entities are emitted where a broad SDRF material class is required. |
| ExperimentalDesignAgent: `experimental_design` | 82 | 83 | 95 | 3 | Procedures or study objectives are emitted instead of a compact experimental-design category. |
| ExperimentalDesignAgent: `number_of_samples` | 0 | 96 | 97 | 53 | Counts from unrelated groups or assays are treated as the MS sample total. |
| TechnicalAgent: `instrument` | 0 | 76 | 90 | 76 | Plausible instrument models survive without direct study-specific support. |
| BiologicalAgent: `cell_line` | 2 | 4 | 63 | 0 | The primary line is found, but study-relevant additional lines are often omitted. |
| BiologicalAgent: `species` | 0 | 7 | 61 | 3 | The primary organism is found but multi-species study material is incomplete. |
| BiologicalAgent: `cell_type` | 12 | 44 | 54 | 35 | Cell-line lineage and actual sample cell type are not consistently distinguished. |
| BiologicalAgent: `organ` | 9 | 37 | 49 | 25 | Tissue of origin, material preparation, and actual sampled organ are conflated. |
| ExperimentalDesignAgent: `factor_value` | 6 | 9 | 89 | 2 | Conditions are under-enumerated or not associated with the profiled sample set. |

The first five rows account for the dominant actionable failure modes. The
results show that improving biological extraction alone will not move the
overall score enough: the experimental-design contract is the largest error
surface in this cohort.

## Specific evidence

### 1. Material type is consistently too specific

`material_type` must be a broad SDRF category such as `tissue`, `cell line`,
`primary cells`, `biofluid`, `whole organism`, `plasma`, `serum`, or
`organoid`. The agents frequently extract a source entity that is factually in
the paper but invalid as the categorical output.

| PXD | Output | Judge correction or result | Why it fails |
|---|---|---|---|
| PXD043087 | `human umbilical cord` | `primary cells` | Anatomical source is not a broad material class. |
| PXD006856 | `HAP1 cells` | `cell line` | A cell-line name belongs in `cell_line`; `material_type` needs the class. |
| PXD033469 | `human cartilages` | `tissue, primary cells` | Specific tissues/cells were returned instead of study material classes. |
| PXD016814 | `LAMP fraction` | no valid material type | A protein fraction is not a sample material class. |

This is mainly a field-contract and normalization failure, not a failure to
find paper facts.

### 2. Replicate and count fields lack MS-specific semantics

The judge found 100 type mismatches, 159 incorrect values, 166 incomplete
values, and 36 hallucinations for `replicates` alone. `number_of_samples` adds
96 incorrect, 97 incomplete, and 53 hallucinated values.

| PXD | Field | Output | Why it fails |
|---|---|---|---|
| PXD043087 | `replicates` | `hUC-MSCs` | A cell type was placed in a numeric biological-replicate field. |
| PXD033469 | `replicates` | `human chondrocytes (HCs)` | A sample description is not a biological replicate count. |
| PXD018749 | `replicates` | `cultured OSCs` | A cell/sample source is not a count. |
| PXD033469 | `number_of_samples` | `2` | The paper contains multiple group counts; the output is not tied to the MS sample total. |
| PXD021444 | `replicates` | `5` | The number appears in the paper but is not supported as biological replication for the MS experiment. |

The core problem is scope binding: a number is accepted because it occurs in a
paper, rather than because the evidence says it counts biological replicates,
technical replicates, fractions, or profiled samples in the MS experiment.

### 3. Instrument values are invented or over-specified

`instrument` has 76 incorrect, 90 incomplete, and 76 hallucinated values in the
low-score cohort. The pattern is an exact model inference from generic mass
spectrometry context or incomplete methods, despite the absence of a direct
source claim.

| PXD | Output | Judge finding |
|---|---|---|
| PXD043087 | `Q Exactive HF-X` | The named model is not supported by the paper. |
| PXD033469 | `Q Exactive` | The paper mentions MS analysis but not that instrument model. |
| PXD018749 | `Orbitrap Elite` | The paper defers details to supplementary material and does not state this model. |

When RunAssessor or PRIDE provides direct instrument data, it should be the
only eligible source for an exact model. When neither direct source nor a
study-specific textual mention exists, the candidate must remain unknown rather
than become a plausible model name.

### 4. Multi-value coverage is incomplete

Incomplete values are the most frequent finding. The agents often identify a
valid primary entity but do not enumerate all values associated with material
actually profiled by MS.

| PXD | Field | Output | Missing or incomplete evidence |
|---|---|---|---|
| PXD043087 | `species` | `Homo sapiens` | The review requires `Mus musculus` as well. |
| PXD043087 | `organ` | `umbilical cord` | Other study-relevant material includes serum, bone marrow, and mouse tissues. |
| PXD006856 | `cell_line` | `HAP1` | `HeLa` is also relevant to the reviewed study set. |
| PXD033469 | `factor_value` | partial condition set | The field is frequently incomplete: 89 rows in the low-score cohort. |

The correction is not simply "collect every entity mentioned in the paper." The
agents need a collection pass that retains entities attributable to the MS
material and records their evidence and scope before resolving the final list.

### 5. Scope errors turn real paper facts into wrong SDRF values

A value can be present in the manuscript but still be invalid when it describes
a host, background biology, cell-line provenance, ancillary assay, or sample
preparation product rather than the profiled MS material.

Examples observed in the review data include:

- `kidney` inferred from HEK293-derived cell lines even though the study used
  cell lines, not kidney tissue.
- `epithelial cell` inferred from cell-line background rather than established
  as the type of the profiled material.
- `extracellular vesicles` emitted as an `organ`, which confuses a prepared
  biological material with anatomical origin.
- In PXD002030, `Bos taurus` is a true host/background organism but not the
  actual proteomics source, which is *Trypanosoma brucei* extracellular
  vesicles.

## Root-cause assessment

There is no recurring evidence that the SDRF builder changes an otherwise
correct resolved value into an invalid one. The failures are visible already in
the judge's field-level inputs. The priority work is in upstream extraction,
normalization, and integration policy.

| Root cause | Evidence | Required responsibility |
|---|---|---|
| Field contract not enforced | `material_type`, `replicates`, and `experimental_design` contribute 284 of 349 type mismatches. | Define and enforce output type, allowed abstraction level, permitted vocabulary, and safe fallback for each field. |
| MS-sample scope not represented | Wrong organs, cell types, species, counts, and experimental conditions are usually supported somewhere in the paper but not for the profiled material. | Preserve evidence span plus role/scope (`ms_sample`, `ancillary_assay`, `background`, `unknown`) and allow only eligible candidates into SDRF resolution. |
| Scalar-first integration | Integration selects one resolved value, while the judge evaluates complete sets for many fields. | Support ordered, deduplicated multi-value candidates with independent evidence and scope. |
| Direct technical evidence underused | Exact instrument models are hallucinated despite technical pipeline and PRIDE metadata channels. | Require a direct technical source or explicit text for exact models; do not promote LLM-only guesses. |
| Validation is report-only | Existing cross-field checking detects relationships but does not currently reject or reroute invalid resolutions. | Make validation produce `retain`, `remap`, `suppress`, or `needs_review` decisions before rendering. |

## Recommended `agentic-metadata` changes

The relevant submodule branch is `feature/hamlet-per-raw-integration`, whose
working tree was clean during this audit.

### P0: Add post-extraction field-contract validation

Create a reusable contract layer after extraction and before final integration.
It should operate on the agent field schema, not on ad hoc strings.

Initial required rules:

| Field | Rule | Action on violation |
|---|---|---|
| `material_type` | Emit only the approved broad categories. | Deterministically map supported specific entities where possible; otherwise suppress. |
| `replicates`, `technical_replicates`, `number_of_samples`, `fractions` | Require a numeric value with evidence that names the count's MS-specific semantic role. | Suppress unsupported or mis-scoped numbers; use documented safe defaults only where the policy permits them. |
| `experimental_design` | Require a compact study-design category, not objective, assay protocol, or method name. | Normalize known patterns or leave unresolved. |
| `enrichment_method` | Distinguish biochemical enrichment from chromatography/fractionation and from the enrichment target. | Route to the correct field or suppress. |
| `instrument` | Exact model needs direct technical metadata or explicit source text. | Retain direct source; otherwise emit unresolved rather than infer a model. |

Likely implementation locations:

- `src/agentic-metadata/validation/schema.py` for declarative field contracts.
- `src/agentic-metadata/agents/integration_agent.py` for enforcement after
  source enrichment and before a value is marked resolved.
- `src/agentic-metadata/docetl_pipeline/pipeline_biological.yaml`,
  `pipeline_technical.yaml`, and `pipeline_experimental.yaml` for agent
  instructions and field-specific negative examples.

### P0: Make experimental-design extraction MS-scoped

Do not accept a number merely because it is in the paper. Require evidence that
identifies:

1. the MS/proteomics experiment,
2. the counted unit,
3. whether the count is biological replicate, technical replicate, fraction,
   or total profiled sample.

This targets the most common incorrect-field pattern. Add fixtures for the
examples above and for competing counts from clinical cohorts, non-MS assays,
clone generation, and treatment groups.

### P1: Make biological resolution collection-aware and scope-aware

For `species`, `organ`, `cell_line`, `cell_type`, `disease`, and factor values:

1. extract all candidate values with evidence spans;
2. assign the candidate's experimental role;
3. normalize and deduplicate values;
4. retain only values associated with profiled material; and
5. resolve the final set without collapsing it prematurely to a scalar.

Do not apply a blanket text-match rule. The judge permits specific, documented
inference in some fields. The contract should instead state which fields permit
inference, which inference sources are allowed, and when direct sample evidence
is mandatory.

### P1: Turn cross-field checks into integration decisions

The submodule already tests cell-line/species and cell-line/tissue consistency
in `tests/test_cross_field_checker.py`. Feed these findings into the resolver:

- block an organ/tissue derived only from a cell line when the MS material is a
  cell line;
- flag incompatible cell-line/species combinations for review or suppression;
- prevent a prepared material such as extracellular vesicles from being used as
  an anatomical organ; and
- retain rejected evidence in provenance rather than discarding it silently.

### P2: Add regression tests from this audit

Extend these existing test surfaces:

- `tests/test_integration_agent.py`: direct-source instrument wins over an
  unsupported LLM candidate; nested `pride_metadata.project.organisms` is read;
  multiple eligible values are preserved.
- `tests/test_validator.py`: material-type category mapping; numeric count
  contract; explicit suppression of unsupported counts and instruments.
- `tests/test_cross_field_checker.py`: MS-sample versus cell-line-origin organ
  cases; species/cell-line conflicts; invalid material/organ routing.
- pipeline fixtures: the concrete PXD examples in this report as minimal,
  source-grounded regression inputs.

The historical organism-path issue should be covered by a regression test, but
not reimplemented: current `IntegrationAgent._get_pride_organisms()` already
supports both top-level and `pride_metadata.project.organisms` layouts.

## Expected impact and measurement

The implementation should be measured with the same frozen review inputs,
first on the 20-PXD sample and then on all 115 low-score reports. Track both
per-field accuracy and the four independent review flags; do not use only a
single global average.

Success criteria for the first iteration:

1. Eliminate category-level type mismatches for `material_type` and numeric
   fields when the evidence is available.
2. Reduce unsupported exact instrument outputs by preferring direct technical
   evidence or unresolved output.
3. Ensure every retained count is explicitly tied to the proteomics experiment.
4. Increase completeness only through MS-scope-qualified values, avoiding a
   counterproductive "all entities in paper" strategy.
5. Add regression coverage before rerunning the full v2.1.1 cohort.

## Limitations

- The judge review is the operational quality signal for this audit, not an
  infallible biological ground truth.
- The full-cohort results establish recurrence and priority, but each proposed
  mapping must be confirmed against the HAMLET SDRF contract before being made
  automatic.
- The audit does not demonstrate a builder defect; a separate agent-output to
  rendered-SDRF trace would be needed to make that claim.
- Earlier release documentation counted `< 0.55`; this report intentionally uses
  `<= 0.55`, which explains a one-PXD difference at the boundary.