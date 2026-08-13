# Conflict assessment: PXD004987 (user vs pride)

PRIDE is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 9 | 9 | 9 | 0 | 0 | 100.0% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| Technical | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| ExperimentalDesign | 0.500 | 1.000 | 0.667 | 0.500 | 1.000 | 0.667 |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | NA | NA | NA |
| `characteristics[cell type]` | Biological | NA | NA | NA |
| `characteristics[disease]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[organism part]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[organism]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[sex]` | Biological | NA | NA | NA |
| `characteristics[biological replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[fraction identifier]` | ExperimentalDesign | 1.000 | 1.000 | 1.000 |
| `comment[technical replicate]` | ExperimentalDesign | NA | NA | NA |
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

Metadata averages include only the 9 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
