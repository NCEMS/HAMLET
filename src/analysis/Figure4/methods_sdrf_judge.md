## LLM-as-judge evaluation of SDRF metadata extraction

### Rationale

The hierarchical semantic matching strategy quantifies surface-level agreement
between extracted and ground-truth values but cannot distinguish semantically
valid extractions that differ in phrasing from genuinely incorrect outputs. To
complement string- and embedding-based comparison, we implemented an
LLM-as-a-judge framework that validates each extracted value directly against
the source manuscript text, without reference to any gold-standard
annotation.

### Evaluation set and extraction sources

We evaluated HAMLET's metadata extraction on a set of 30 published proteomics
datasets (PXD accessions), each with a manuscript text (title, abstract, and
methods section) and a matching expert-curated SDRF file. For every dataset we
compared three extraction sources against the manuscript text:

1. **HAMLET raw** -- the unreconciled, per-agent output of HAMLET's three
   extraction agents (Biological, ExperimentalDesign, Technical), before any
   cross-agent harmonization.
2. **HAMLET harmonized** -- the tool-reconciled output of HAMLET's Integrated
   Agent, which merges the three agents' extractions and resolves them
   against structured technical metadata (PRIDE project metadata,
   PTM-Shepherd output, and RunAssessor search-parameter inference) where
   available.
3. **SDRF-Proteomics** -- the expert-curated ground-truth SDRF for that
   dataset, serving as the human baseline against which HAMLET is compared,
   not merely as a label source.

Each source's per-field values were mapped onto a shared set of canonical
metadata fields (e.g. `organ`, `instrument`, `cleavage_agent`, `replicates`,
`experimental_design`), spanning three categories: Biological, Technical, and
ExperimentalDesign metadata.

### Judge model and prompting

The judge model, Gemma-4-31B-Instruct (`google/gemma-4-31b-it`), was accessed
via OpenRouter at zero temperature with extended thinking enabled and
integrated through the G-Eval framework [32] as implemented in DeepEval, which
uses chain-of-thought prompting to produce structured assessments via a
form-filling paradigm. For each paper, the judge received the title, abstract,
and materials and methods sections as its sole source of truth, together with
the field name, its definition, the candidate value, and the full set of
values extracted for that field.

Each extracted value was assessed through four sequential checks:

- **Type check** -- the value must belong to the correct metadata category.
  Values of the right category but the wrong specific entity were classified
  as value errors rather than type mismatches.
- **Source check** -- the value must be present in or inferable from the
  manuscript. A curated set of safe defaults was accepted without explicit
  textual support, including "normal"/"healthy" for disease state in healthy
  controls, "label-free" when no labelling is described, developmental-stage
  terms like "adult" when inferable from subject descriptions, and "1" for
  unreported replicate or fraction counts. Values outside both the text and
  this default set were flagged as hallucinations. For `material_type` and
  `acquisition_method`, values could additionally be accepted as inferable
  from the broader experimental context.
- **Truth check** -- the value must be factually correct, with synonyms,
  abbreviation expansions, and common-to-scientific-name equivalences (e.g.
  "human" and "Homo sapiens") all treated as correct.
- **Completeness check** -- completeness was evaluated against the full set
  of values extracted for that field rather than the individual candidate in
  isolation (the sibling-value rule). If the complete extraction set
  collectively covered the information described in the manuscript, each
  value within it was marked complete; medium verdicts were assigned only
  when the full set remained genuinely insufficient (e.g. subtype drift or
  partial extraction from a multi-value field). An explicit exception was
  applied to concentration fields (`reduction_concentration` and
  `alkylation_concentration`): because the reagent name is captured as a
  separate entity, a numeric quantity paired with a unit (e.g. "10 mM") was
  treated as complete in isolation.

Each assessment produced a three-level verdict of high, medium, or low.

### Two-pass evaluation

To prevent false extractions from biasing completeness assessment, evaluation
proceeded in two passes. In pass one, all values were judged with the
unfiltered sibling list for their field. Values rated low -- those flagged as
hallucinated, type-mismatched, or factually incorrect -- were then pruned from
the sibling context, and in pass two, only medium-rated values were re-judged
with the cleaned list. This two-pass design ensures that a hallucinated value
does not mislead the judge into concluding that a genuinely correct sibling is
incomplete.

### Caching

API calls were minimised by a SHA-256-keyed disk cache indexed on the model
identifier, paper identifier, task type, field name, and candidate value, with
responses reused across runs. The static system prompt, containing all field
definitions, evaluation criteria, and domain rules, was additionally separated
from the per-paper text to enable prefix caching at the provider layer; both
the system prompt and the per-paper text were marked for caching, reducing
token processing costs for repeated judge calls within the same session.

### Strict vs. inference judge mode

For the multi-source comparison described above, each (source, field, value)
triple was judged twice, under two different standards for the source check:

- **Strict mode** accepts a value only under the source-check rules described
  above: explicit textual support, a named safe default, or the narrow
  `material_type`/`acquisition_method` inference allowance.
- **Inference mode** extends that same inference allowance to every field: a
  value not literally written in the text but confidently derivable by a
  domain expert from context stated elsewhere (e.g. inferring `disease` from
  a well-characterized cell line's known origin, or `number_of_samples` by
  summing explicitly stated per-group replicate counts) is accepted rather
  than flagged as a hallucination. Values accepted only under this relaxed
  standard are flagged with an additional `INFERENCE: yes` field and tallied
  separately (`judge_n_inferred`) -- they are never merged into either the
  correct or hallucinated counts. The `modification` field is always judged
  under the strict, explicit-only standard in both modes, since PTM identity
  cannot be safely inferred.

Strict mode thus measures what is explicitly extractable from text alone,
while inference mode measures the additional headroom available if
expert-level inference is credited.

### Correcting for real, non-fabricated technical metadata

A value can be correct without being stated anywhere in the manuscript text --
for example, an instrument parameter recovered from the raw PRIDE submission
or inferred by RunAssessor from the search-engine configuration. To avoid
scoring these as fabrications, we built a per-dataset technical reference set
from the pipeline's own structured metadata (PRIDE project metadata,
PTM-Shepherd output, RunAssessor-inferred search parameters) and matched each
text-judged hallucination against it (exact match after normalization, or
token-subset/overlap matching for longer controlled-vocabulary names). Values
matching this reference were reclassified out of "hallucinated" into a
separate category ("technical origin, not in text") and credited in an
adjusted accuracy metric, reported alongside the raw, text-only accuracy.

### Error categories and accuracy metrics

In its base form, each annotation was assigned to one of five mutually
exclusive outcome classes: **correct** (type correct, factually valid,
complete, not hallucinated), **hallucinated** (absent from the manuscript and
not a safe default), **type mismatch** (belongs to a fundamentally different
field), **wrong value** (present in the text but incorrectly applied or
factually wrong), and **incomplete** (correct, but the full extraction set
does not cover the complete picture). Per-paper accuracy was computed as the
fraction of correct annotations over all predicted annotations and aggregated
across the corpus to produce per-paper and per-model performance profiles.

For the multi-source, multi-mode comparison, this scheme was extended with
the two categories introduced above, giving seven mutually exclusive
categories in a fixed precedence order: technical origin is checked before
hallucination (so a value matching real technical metadata is never
double-counted as a hallucination), followed by hallucinated, inferred
(inference mode only), type mismatch, wrong value, incomplete, and correct.
Per-paper accuracy metrics were computed from these counts:

- `judge_accuracy` = correct / total (the strict, text-only rate; comparable
  between strict and inference mode as a sanity check, since it excludes
  inferred values in both).
- `judge_accuracy_adjusted` = (correct + technical-origin) / total.
- `judge_accuracy_with_inference` = (correct + inferred) / total (inference
  mode only) -- the effective accuracy once expert-level inference is
  credited.

### Reproducibility of the LLM judge

Because the judge is itself a generative model, its verdict on a given value
can vary between calls. To quantify this, the full judging pipeline (all
three sources, both modes, all 30 papers) was run three independent times
against the identical input data, each with its own response cache so every
call was answered fresh rather than replayed. Per-field and per-paper
agreement was computed as the proportion of values on which all three runs
returned the identical error category (or verdict), and run-to-run noise was
summarized as the standard deviation of `judge_accuracy` across the three
runs, both overall and broken down by source, judge mode, and metadata field.
Fields with fewer than 10 judged rows for a given source were excluded from
per-field reproducibility estimates as too sparse to give a stable rate.
