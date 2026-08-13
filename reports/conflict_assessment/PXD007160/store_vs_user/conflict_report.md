# Conflict assessment: PXD007160 (store vs user)

USER is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 11 | 30 | 0 | 11 | 30 | 0.0% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | NA | NA | NA | NA | NA | NA |
| Technical | NA | NA | NA | NA | NA | NA |
| ExperimentalDesign | NA | NA | NA | NA | NA | NA |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | NA | NA | NA |
| `characteristics[disease]` | Biological | NA | NA | NA |
| `characteristics[organism part]` | Biological | NA | NA | NA |
| `characteristics[organism]` | Biological | NA | NA | NA |
| `characteristics[sex]` | Biological | NA | NA | NA |
| `characteristics[biological replicate]` | ExperimentalDesign | NA | NA | NA |
| `comment[fraction identifier]` | ExperimentalDesign | NA | NA | NA |
| `comment[technical replicate]` | ExperimentalDesign | NA | NA | NA |
| `factor value[disease]` | ExperimentalDesign | NA | NA | NA |
| `factor value[experimental design]` | ExperimentalDesign | NA | NA | NA |
| `comment[cleavage agent details]` | Technical | NA | NA | NA |
| `comment[dissociation method]` | Technical | NA | NA | NA |
| `comment[fragment mass tolerance]` | Technical | NA | NA | NA |
| `comment[instrument]` | Technical | NA | NA | NA |
| `comment[label]` | Technical | NA | NA | NA |
| `comment[ms2 mass analyzer]` | Technical | NA | NA | NA |
| `comment[precursor mass tolerance]` | Technical | NA | NA | NA |
| `comment[proteomics data acquisition method]` | Technical | NA | NA | NA |
| `technology type` | Technical | NA | NA | NA |

Metadata averages include only the 0 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
