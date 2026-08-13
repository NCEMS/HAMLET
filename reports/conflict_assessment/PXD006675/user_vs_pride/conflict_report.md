# Conflict assessment: PXD006675 (user vs pride)

PRIDE is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 610 | 594 | 594 | 16 | 0 | 97.4% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Technical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ExperimentalDesign | 1.000 | 0.627 | 0.768 | 1.000 | 0.638 | 0.779 |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[cell type]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[disease]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[organism part]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[organism]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[sex]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[biological replicate]` | ExperimentalDesign | 1.000 | 1.000 | 1.000 |
| `comment[fraction identifier]` | ExperimentalDesign | 1.000 | 1.000 | 1.000 |
| `comment[technical replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[disease]` | ExperimentalDesign | NA | NA | NA |
| `factor value[experimental design]` | ExperimentalDesign | NA | NA | NA |
| `comment[cleavage agent details]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[dissociation method]` | Technical | NA | NA | NA |
| `comment[fragment mass tolerance]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[instrument]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[label]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[ms2 mass analyzer]` | Technical | NA | NA | NA |
| `comment[precursor mass tolerance]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[proteomics data acquisition method]` | Technical | NA | NA | NA |
| `technology type` | Technical | NA | NA | NA |

Metadata averages include only the 594 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
