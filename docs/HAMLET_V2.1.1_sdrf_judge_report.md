**Investigation Results**

I reviewed every completed `llm_judge_per_paper.csv` currently present under results_hamletpxds_agentic_v2_1_1 and their paired detailed llm_judge_annotation_review.csv reports.

At the time of inspection there were **299 completed PXD reports** and **4,992 judged annotations**.

| Judge-accuracy range | PXDs |
|---|---:|
| `< 0.30` | 8 |
| `0.30 - <0.40` | 25 |
| `0.40 - <0.55` | 81 |
| `0.55 - <0.70` | 86 |
| `0.70 - <0.80` | 57 |
| `>= 0.80` | 42 |

Overall accuracy is `0.6025` mean / `0.6000` median, with a range of `0.1429` to `0.9500`. **114 PXDs score below 0.55**, which is the useful threshold for the recurring-error analysis below.

The eight critical reports are:

- `PXD026142`: `0.1429`
- `PXD026512`: `0.2143`
- `PXD002030`: `0.2727`
- `PXD043500`: `0.2727`
- `PXD009298`: `0.2857`
- `PXD028480`: `0.2857`
- `PXD053353`: `0.2857`
- `PXD055157`: `0.2941`

**What Drives Low Scores**

Across the 1,729 judged annotations from PXDs below `0.55`, the judge flags:

| Flag | Count | Affected PXDs |
|---|---:|---:|
| Incomplete value set | 969 | 114 |
| Incorrect value | 680 | 114 |
| Type mismatch | 346 | 114 |
| Hallucinated value | 267 | 108 |

These flags overlap. For example, a fabricated value can be both incorrect and incomplete.

The main pattern is not a broken output renderer. It is a combination of strict SDRF field semantics, incomplete multi-value extraction, and unsupported LLM inference.

**1. Field-Type Confusion Is the Largest Systemic Problem**

Of the 346 type mismatches in the low-score cohort, **281 (81%)** occur in only three fields:

| Field | Type mismatches |
|---|---:|
| `material_type` | 101 |
| `replicates` | 99 |
| `experimental_design` | 81 |

The recurring failure is that the model extracts a scientifically relevant value but puts it in the wrong SDRF field or wrong level of abstraction.

- `material_type` requires a broad class such as `cell line`, `tissue`, `primary cells`, or `biofluid`.
- The model instead emits a particular biological entity, such as `HAP1 cells`, `HEK-293T cells`, `purified EVs`, or `human cartilage`.
- `replicates` requires a numeric count, but the model often supplies a cell line, condition, sample description, or a number mentioned for a different experiment.
- `experimental_design` is often populated with a method, objective, or detailed comparison instead of a compact study-design category.

Examples:

- llm_judge_annotation_review.csv correctly identifies `HAP1 cells` in the paper but rejects it for `material_type`; the required output is `cell line`.
- llm_judge_annotation_review.csv has the same `HEK-293T cells` versus `cell line` error.
- llm_judge_annotation_review.csv rejects `extracellular vesicles` as an `organ`, and llm_judge_annotation_review.csv rejects `purified EVs` as a `material_type` because it is not a broad SDRF class.

This is primarily a **prompt/schema-contract problem**, not a factual extraction problem. The extracted facts are frequently reasonable but invalid for the destination field.

**2. The Workflow Misses Valid Secondary Values**

Incomplete values are the most frequent low-score flag: 969 occurrences. The highest-impact fields are:

| Field | Incomplete annotations |
|---|---:|
| `replicates` | 165 |
| `material_type` | 107 |
| `number_of_samples` | 96 |
| `experimental_design` | 94 |
| `instrument` | 89 |
| `factor_value` | 88 |
| `cell_line` | 62 |
| `species` | 60 |
| `cell_type` | 53 |
| `organ` | 49 |

The model tends to identify the main biological system but miss secondary organisms, cell lines, sample types, conditions, or organs mentioned elsewhere in the paper.

Examples:

- llm_judge_annotation_review.csv extracts `blood` but misses the explicitly mentioned `bone marrow`.
- llm_judge_annotation_review.csv extracts `Homo sapiens` but misses `Mus musculus` from the 3T3 experiments.
- llm_judge_annotation_review.csv correctly extracts `HAP1` but misses `HeLa`.

This is an **upstream extraction coverage issue**. The current agents seem biased toward the central experiment and do not reliably enumerate all study-relevant values before constructing a field’s final set.

**3. Unsupported Inference Produces Hallucinations**

There are 267 hallucination flags in the low-score cohort. They cluster in:

| Field | Hallucinations |
|---|---:|
| `instrument` | 75 |
| `number_of_samples` | 52 |
| `replicates` | 36 |
| `cell_type` | 34 |
| `organ` | 25 |
| `technical_replicates` | 21 |

The common failure is domain-knowledge completion: the model infers a value that is plausible but not explicitly supported by the paper text.

The clearest biological example is llm_judge_annotation_review.csv:

- `kidney` is inferred from HEK-293T’s origin, but the study analyzed cell lines rather than kidney tissue.
- `epithelial cell` is inferred from cell-line background, but it is neither consistently true across the sample set nor stated in the source text.

Other recurring cases include:

- Exact or upgraded instrument models supplied without explicit source evidence.
- Sample counts inferred from unrelated group counts or non-proteomics experiments.
- Biological and technical replicate counts inferred from nearby experiments rather than the MS experiment.
- `trypsin`, `SCX`, disease state, organ, or cell type inferred from common laboratory context.

This is a **strict-grounding issue**: the model should prefer `not available` or omission where a value is not directly asserted for the proteomics material.

**4. Scope Confusion: Background Biology vs. Proteomics Sample**

A smaller but scientifically important class of low-score errors comes from choosing the wrong context within a paper.

llm_judge_annotation_review.csv is the clean example:

- The extracted species is `Bos taurus`.
- Cattle is mentioned as a disease host/background context.
- The proteomics source is *Trypanosoma brucei* extracellular vesicles.

The model recognizes a valid species but does not distinguish:

```text
host or disease context
!=
material actually profiled by mass spectrometry
```

This same issue appears when cell-line derivation is confused with tissue, a sample-preparation product is confused with an organ, or assay controls are treated as disease states.

**5. Counts and Replicate Fields Need Much Tighter Constraints**

`replicates`, `technical_replicates`, and `number_of_samples` collectively account for:

- **276 incorrect values**
- **283 incomplete values**
- **109 hallucinations**
- **111 type mismatches**

These fields are difficult because papers often contain multiple counts from different experiments. The current prompts/judge do not consistently tie a count to the actual proteomics experiment, its sample unit, and whether it describes biological replicates, technical replicates, or total samples.

Typical failures include:

- Treating a cell-line list as a replicate count.
- Using a clone count as biological replicates.
- Using an assay replicate count from a non-MS experiment.
- Selecting one valid count while silently omitting other applicable experimental groups.

**Root-Cause Assessment**

| Cause | Definition | Concrete evidence from the judge reports | Ownership and implication |
|---|---|---|---|
| Field-contract ambiguity | The extraction prompt or validation contract does not define the semantic type and permitted abstraction level of a field tightly enough. The model therefore finds a source-grounded fact but emits it in the wrong SDRF field or at the wrong level of specificity. | In `PXD006856`, `HAP1 cells` is present in the paper, but it is rejected for `material_type`: the SDRF field requires a broad class, such as `cell line`. In `PXD026512`, `HEK-293T cells` has the same problem. In `PXD002030`, `purified EVs` is scientifically relevant but is not a permitted broad `material_type`; `extracellular vesicles` is also incorrectly placed in `organ`. Across PXDs below 0.55, `material_type` (101), `replicates` (99), and `experimental_design` (81) account for 281 of 346 type-mismatch flags. | Primarily an agent prompt/schema-contract issue. Define expected value type, allowed vocabulary or hierarchy, and negative examples for each field. A renderer cannot reliably repair this without inventing semantics. |
| Incomplete upstream extraction | The extraction agents return one valid value but fail to enumerate all source-supported values applicable to the study. The judge records this as `value_complete = False`, even when the returned value itself is correct. | In `PXD026142`, `blood` is correct for `organ`, but `bone marrow` is omitted. In `PXD026512`, `Homo sapiens` is correct, but the 3T3 experiments require `Mus musculus` as well. In `PXD006856`, `HAP1` is correctly extracted as a `cell_line`, but `HeLa` is missed. The below-0.55 cohort has 969 incomplete annotations, concentrated in `replicates` (165), `material_type` (107), `number_of_samples` (96), `experimental_design` (94), and `instrument` (89). | Upstream extraction and aggregation issue. Each field needs a source-backed enumeration step before selecting or normalizing values, with explicit rules about whether ancillary experiments belong in the final study-level value set. |
| Insufficient source grounding | The model supplies a plausible domain-derived value that is not directly supported by the relevant source text. This is a hallucination when it is absent from the text, or an unsupported inference when it is derived from background knowledge rather than the assayed material. | In `PXD026512`, `kidney` is inferred from the HEK-293T cell-line origin even though the experiment uses cell lines rather than kidney tissue; `epithelial cell` is also inferred despite not being stated and not fitting every cell line in the study. In the low-score cohort, hallucination flags occur most often for `instrument` (75), `number_of_samples` (52), `replicates` (36), and `cell_type` (34). The judge also identifies instrument models and sample counts that are not explicitly tied to the proteomics experiment. | Agent grounding and judge-policy issue. Require a direct evidence span for these fields and emit `not available` or no value when the evidence does not identify the value for the profiled material. |
| Context/scope selection | The model extracts a fact from the paper but associates it with the wrong experimental role: host instead of assayed organism, cell-line origin instead of sampled tissue, an ancillary assay instead of mass spectrometry, or a control description instead of disease state. Unlike hallucination, the value may be present and factually true in the paper. | In `PXD002030`, `Bos taurus` is a valid species mentioned in the paper, but it is a trypanosomiasis host/background organism. The proteomics source is *Trypanosoma brucei* extracellular vesicles. This same report classifies extracellular vesicles as an `organ`, illustrating a sample-preparation material being confused with tissue of origin. | Agent extraction and study-level resolution issue. Prompts and structured evidence need to distinguish the material profiled by MS from hosts, disease background, cell-line provenance, and non-proteomics experiments before a value is rendered. |
| SDRF rendering defect | A fault in the final builder that changes, drops, invents, or misplaces a correctly resolved upstream value while producing the SDRF. This diagnosis requires evidence that the agent/judge result is correct and the rendered TSV is not. | No recurring example met that criterion in the reviewed reports. The observed errors are already present in the judge annotation review as bad, incomplete, hallucinated, or type-mismatched candidate values. For example, `PXD006856` is rejected before rendering because `HAP1 cells` violates the `material_type` contract; the builder is not shown converting a correct `cell line` value into the wrong output. | No renderer change is justified from this audit alone. Retest the builder only after correcting upstream contracts and extraction behavior, using agent JSON-to-TSV comparisons to detect any later rendering-specific discrepancy. |

The low `judge_accuracy` values therefore should not be read simply as “the final SDRF is bad.” A meaningful portion reflects the evaluator enforcing field-specific format rules against source-grounded but incorrectly categorized values. Still, the **969 incomplete**, **680 incorrect**, and **267 hallucinated** annotations show that there are real upstream quality issues to address.

**Recommended Priority Order**

1. Make field contracts explicit and machine-checkable for `material_type`, `replicates`, `number_of_samples`, and `experimental_design`.
2. Require direct evidence spans for instrument, sample count, replicate count, organ, cell type, disease, and enrichment method; otherwise emit no value.
3. Add a per-field multi-value enumeration pass before value selection, particularly for `species`, `cell_line`, `organ`, `factor_value`, and disease.
4. Add source-scope instructions: profile material versus host, background organism, disease context, cell-line origin, and non-proteomics experiments.
5. Treat counts as invalid unless the source ties them explicitly to the mass-spectrometry sample set and identifies the count type.

No application source code or result artifacts were modified during this investigation; this Markdown report was updated after the 299-PXD run completed.
