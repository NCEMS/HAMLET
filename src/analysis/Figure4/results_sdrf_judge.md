## LLM-as-judge evaluation results

### Strict vs. inference accuracy

Averaged across the 30 papers, effective judge accuracy (`judge_accuracy` in
strict mode; `judge_accuracy_with_inference` in inference mode) was highest
for HAMLET raw (85.2% strict, 87.5% inference), intermediate for HAMLET
harmonized (73.1% strict, 75.5% inference), and lowest for SDRF-Proteomics
(54.1% strict, 57.1% inference). The strict-to-inference gain was modest for
all three sources (+2.3 pp HAMLET raw, +2.4 pp HAMLET harmonized, +3.0 pp
SDRF-Proteomics), indicating that allowing expert-level inference recovers
only a small amount of additional credit once genuinely explicit extractions
are already counted; most of the remaining gap to 100% reflects real errors
rather than an overly strict judge standard (Fig. panel3, "inference
headroom").

### Error composition (strict mode, Fig. panel4)

Pooling all judged annotations per source (inference mode disabled), the
error composition differed markedly by source:

- **HAMLET raw** (n = 638): 85.1% correct, 5.6% incomplete, 3.3%
  hallucinated, 3.1% wrong value, 2.8% type mismatch, 0% technical-origin
  (no technical-reference reclassification needed, since nothing was
  reclassified as harmonization-introduced format drift).
- **HAMLET harmonized** (n = 673): 73.0% correct, 6.7% type mismatch, 6.7%
  technical-origin (values not stated in text but matched to real
  RunAssessor/technical-pipeline metadata), 6.7% incomplete, 4.3% wrong
  value, 3.1% hallucinated.
- **SDRF-Proteomics** (n = 789): 45.8% correct, 37.0% hallucinated, 8.6% type
  mismatch, 4.6% incomplete, 3.9% wrong value.

Harmonization trades a ~12 pp drop in raw "correct" share (85.1% -> 73.0%)
mostly for two new/enlarged categories -- type mismatch (2.8% -> 6.7%) and a
technical-origin credit that did not exist in raw output at all (0% -> 6.7%)
-- rather than a genuine increase in fabrication (hallucination is, if
anything, slightly lower after harmonization: 3.3% -> 3.1%). SDRF-Proteomics'
large hallucinated share is the dominant driver of its lower accuracy, not
type or value errors, which are comparable in magnitude to the two HAMLET
sources.

### Error composition (inference mode, Fig. panel6)

Enabling inference mode redistributes 6-12% of each source's annotations
from "correct" into a new "inferred" bucket (not a hallucination, but not a
literal textual match either), without changing the underlying
hallucination/type-mismatch/wrong-value error rates by more than ~1 pp per
category:

- **HAMLET raw**: 75.1% correct (explicit) + 12.4% inferred = 87.5%
  effective accuracy; hallucinated drops slightly to 2.0% (some values
  previously judged hallucinated under strict mode's narrower source check
  are now accepted as expert-inferable).
- **HAMLET harmonized**: 63.9% correct + 11.6% inferred = 75.5%; technical-
  origin remains at 5.9%, type mismatch at 7.1%.
- **SDRF-Proteomics**: 41.3% correct + 6.2% inferred = 47.5% (vs. 54.1%
  judge_accuracy under strict mode's correct-only definition, and 57.1%
  once inference is credited); hallucinated remains the dominant error
  category at 36.0%, essentially unchanged from strict mode (37.0%) -- i.e.
  most of SDRF-Proteomics' hallucination-flagged annotations are not
  borderline/inferable cases that a more permissive standard would rescue,
  but values the judge could not connect to the manuscript text under
  either standard.

### Judge reproducibility across three independent runs

Running the complete judging pipeline three independent times on identical
input (all three sources, both modes, all 30 papers) gave an overall
unanimous (3/3) agreement rate of 94.4% on verdict and 90.0% on the finer
`error_category` label. Run-to-run noise in per-paper `judge_accuracy`, as
standard deviation across the three runs, was consistently higher in
inference mode than strict mode for every source (Fig.
`variability_by_source_mode.png`):

| Source | Strict std | Inference std |
|---|---|---|
| HAMLET raw | 2.9 pp | 3.7 pp |
| HAMLET harmonized | 2.5 pp | 3.4 pp |
| SDRF-Proteomics | 2.2 pp | 2.7 pp |

This is expected: inference mode asks the judge to make a probabilistic call
("would a domain expert confidently infer this?") on every field rather than
a comparatively mechanical explicit-match check, and that extra judgment
call is where most of the added run-to-run variance concentrates. Notably,
SDRF-Proteomics -- despite having the lowest accuracy -- had the *lowest*
noise of the three sources in both modes, meaning its low accuracy is a
stable, reproducible measurement rather than an artifact of judge
inconsistency.

### Class-level error drivers and variance (Fig. `error_class_variance_*`)

Breaking hallucination, type-mismatch, and wrong-value rates down by
metadata field (inference mode, mean over the 3 runs, fields with >= 10
judged rows per source) shows that errors are concentrated in a small
number of fields per source, and that those fields are not the same across
sources:

- **HAMLET raw / HAMLET harmonized** share nearly identical rates for most
  fields, since harmonization leaves most fields untouched. The two
  exceptions are `experimental_design` (0% type mismatch in raw -> 67% in
  harmonized) and `organ` (0% -> 26% type mismatch), both introduced
  entirely by the harmonization step. `material_type` (23% type mismatch),
  `replicates`/`number_of_samples` (14-18% wrong value), and `fractions`/
  `technical_replicates` (21-30% run-to-run disagreement, the highest
  variance fields in either HAMLET source) are shared between raw and
  harmonized essentially unchanged.
- **SDRF-Proteomics** is dominated by hallucination rather than type/value
  errors: `factor_value` (83%), `fractions` (81%), `technical_replicates`
  (72%), and `age` (66%) are the largest single-field hallucination rates
  observed in the whole comparison. `cell_type` (73%) and `material_type`
  (60%) are the exceptions, driven by type mismatch instead. Disagreement
  (variance) across the three judge runs is comparatively low for most of
  these fields (<= 28%), meaning the high hallucination rates for
  `factor_value`, `fractions`, and `technical_replicates` are stable
  findings rather than judge noise; `material_type` (28% disagreement) is
  the field where source-level accuracy conclusions should be treated most
  cautiously.

Taken together, the class-level breakdown indicates that (i) harmonization's
apparent accuracy cost is concentrated in two fields it actively rewrites
(`experimental_design`, `organ`), not a broad regression, and (ii)
SDRF-Proteomics' lower overall accuracy is driven by a handful of
high-hallucination fields (`factor_value`, `fractions`,
`technical_replicates`, `age`) whose flagged hallucination rate is
reproducible across independent judge runs rather than an evaluation
artifact.
