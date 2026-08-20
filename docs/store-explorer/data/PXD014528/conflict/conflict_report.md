# Conflict assessment: PXD014528 (store vs pride)

PRIDE is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 48 | 48 | 48 | 0 | 0 | 100.0% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | 0.400 | 1.000 | 0.571 | 0.400 | 1.000 | 0.571 |
| Technical | 0.333 | 0.500 | 0.400 | 0.333 | 0.500 | 0.400 |
| ExperimentalDesign | 0.267 | 0.667 | 0.381 | 0.267 | 0.667 | 0.381 |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | NA | NA | NA |
| `characteristics[cell line]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[cell type]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[cellosaurus accession]` | Biological | NA | NA | NA |
| `characteristics[disease]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[organism part]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[organism]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[sex]` | Biological | NA | NA | NA |
| `characteristics[biological replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[fraction identifier]` | ExperimentalDesign | 1.000 | 1.000 | 1.000 |
| `comment[technical replicate]` | ExperimentalDesign | 0.333 | 0.333 | 0.333 |
| `factor value[disease]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[experimental design]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[cleavage agent details]` | Technical | 1.000 | 0.500 | 0.667 |
| `comment[dissociation method]` | Technical | NA | NA | NA |
| `comment[instrument]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[label]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[modification parameters]` | Technical | NA | NA | NA |
| `comment[ms2 mass analyzer]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[proteomics data acquisition method]` | Technical | NA | NA | NA |
| `comment[reduction reagent]` | Technical | 0.000 | 0.000 | 0.000 |
| `technology type` | Technical | 0.000 | 0.000 | 0.000 |

Metadata averages include only the 48 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
