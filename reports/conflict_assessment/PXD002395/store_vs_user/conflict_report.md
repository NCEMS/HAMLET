# Conflict assessment: PXD002395 (store vs user)

USER is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.

## File coverage

| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |
|---:|---:|---:|---:|---:|---:|
| 198 | 30 | 30 | 168 | 0 | 15.2% |

## Metadata agreement across matched files

| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |
|---|---:|---:|---:|---:|---:|---:|
| Biological | 0.283 | 0.334 | 0.304 | 0.283 | 0.336 | 0.307 |
| Technical | 0.571 | 0.571 | 0.571 | 0.571 | 0.571 | 0.571 |
| ExperimentalDesign | 0.087 | 0.217 | 0.124 | 0.087 | 0.217 | 0.124 |

## Metadata type agreement across matched files

| Metadata type | Category | Mean precision | Mean recall | Mean F1 |
|---|---|---:|---:|---:|
| `characteristics[age]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[cell line]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[cell type]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[cellosaurus accession]` | Biological | NA | NA | NA |
| `characteristics[disease]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[organism part]` | Biological | 0.000 | 0.000 | 0.000 |
| `characteristics[organism]` | Biological | 1.000 | 1.000 | 1.000 |
| `characteristics[sex]` | Biological | 0.700 | 0.700 | 0.700 |
| `characteristics[biological replicate]` | ExperimentalDesign | 0.200 | 0.200 | 0.200 |
| `comment[fraction identifier]` | ExperimentalDesign | 0.233 | 0.233 | 0.233 |
| `comment[technical replicate]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[disease]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `factor value[experimental design]` | ExperimentalDesign | 0.000 | 0.000 | 0.000 |
| `comment[cleavage agent details]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[dissociation method]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[fragment mass tolerance]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[instrument]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[label]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[ms2 mass analyzer]` | Technical | 1.000 | 1.000 | 1.000 |
| `comment[precursor mass tolerance]` | Technical | 0.000 | 0.000 | 0.000 |
| `comment[proteomics data acquisition method]` | Technical | NA | NA | NA |
| `technology type` | Technical | 0.000 | 0.000 | 0.000 |

Metadata averages include only the 30 uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.

Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.
