# Conflict assessment: PXD005445 (user vs pride)

PRIDE is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 196 | 196 | 196 | 0 | 0 | 100.0% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Technical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ExperimentalDesign | 0.268 | 0.268 | 0.268 | 0.349 | 0.366 | 0.357 |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[disease]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[organism part]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[organism]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[sex]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[biological replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[fraction identifier]` | ExperimentalDesign | 1.000 | 1.000 | 1.000 |
| `comment[technical replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[disease]` | ExperimentalDesign | NA | NA | NA |
| `factor value[experimental design]` | ExperimentalDesign | NA | NA | NA |
| `comment[cleavage agent details]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[dissociation method]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[fragment mass tolerance]` | Technical | NA | NA | NA |
| `comment[instrument]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[label]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[ms2 mass analyzer]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[precursor mass tolerance]` | Technical | NA | NA | NA |
| `comment[proteomics data acquisition method]` | Technical | NA | NA | NA |
| `technology type` | Technical | NA | NA | NA |

Metadata averages include only the 196 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
