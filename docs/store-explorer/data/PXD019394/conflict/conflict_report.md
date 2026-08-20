# Conflict assessment: PXD019394 (store vs pride)

PRIDE is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 347 | 347 | 347 | 0 | 0 | 100.0% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 | 0.500 |
| Technical | 0.270 | 0.299 | 0.284 | 0.270 | 0.299 | 0.284 |
| ExperimentalDesign | 0.033 | 0.084 | 0.048 | 0.033 | 0.084 | 0.048 |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[cell type]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[disease]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[organism part]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[organism]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[sex]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[biological replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[fraction identifier]` | ExperimentalDesign | 0.043 | 0.043 | 0.043 |
| `comment[technical replicate]` | ExperimentalDesign | 0.124 | 0.124 | 0.124 |
| `factor value[disease]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[experimental design]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[cleavage agent details]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[dissociation method]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[fragment mass tolerance]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[instrument]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[label]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[modification parameters]` | Technical | 0.692 | 0.173 | 0.277 |
| `comment[ms2 mass analyzer]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[precursor mass tolerance]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[proteomics data acquisition method]` | Technical | 0.000 | 0.000 | 0.000 |
| `technology type` | Technical | 0.000 | 0.000 | 0.000 |

Metadata averages include only the 347 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
