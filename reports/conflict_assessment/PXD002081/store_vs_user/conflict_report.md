# Conflict assessment: PXD002081 (store vs user)

USER is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 150 | 30 | 30 | 120 | 0 | 20.0% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | 0.333 | 0.250 | 0.286 | 0.333 | 0.250 | 0.286 |
| Technical | 0.278 | 0.483 | 0.353 | 0.279 | 0.483 | 0.354 |
| ExperimentalDesign | 0.213 | 0.533 | 0.305 | 0.213 | 0.533 | 0.305 |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | NA | NA | NA |
| `characteristics[disease]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[organism part]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[organism]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[sex]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[biological replicate]` | ExperimentalDesign | 1.000 | 1.000 | 1.000 |
| `comment[fraction identifier]` | ExperimentalDesign | 0.067 | 0.067 | 0.067 |
| `comment[technical replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[disease]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[experimental design]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[cleavage agent details]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[dissociation method]` | Technical | 0.933 | 0.933 | 0.933 |
| `comment[fragment mass tolerance]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[instrument]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[label]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[ms2 mass analyzer]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[precursor mass tolerance]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[proteomics data acquisition method]` | Technical | 0.000 | 0.000 | 0.000 |
| `technology type` | Technical | 0.000 | 0.000 | 0.000 |

Metadata averages include only the 30 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
