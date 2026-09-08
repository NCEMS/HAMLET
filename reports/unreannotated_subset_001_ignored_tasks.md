# Ignored Fetch and runAssessor Tasks

## Scope and evidence

This report covers `assets/pxd_lists/unreannotated_subset_batches/unreannotated_subset_001.csv` (100 PXDs; Sep 4 run). Task identities and exit statuses come from `.nextflow.log`; preserved Nextflow `work/` logs supplied the runAssessor traceback classifications below.

`fetch_pxd` and `run_assessor` are configured with `errorStrategy 'ignore'`, so the workflow continued after these task failures.

## FetchPXD: 32 skipped projects

Every project below completed `fetch_pxd` with exit code `42`. In `src/python/FetchPXD.py`, code `42` means that no usable spectral file was successfully downloaded and converted. The preserved task logs classify the failures as follows: 30 projects had no eligible `.raw` record with a PRIDE FTP location; `PXD000038` downloaded its selected RAW files but they all failed ThermoRawFileParser CRC validation; and `PXD000596` exhausted `aria2c` retries for all 30 selected RAW files.

| PXD | Verified failure reason |
| --- | --- |
| PXD000008 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000038 | All 30 selected RAW files downloaded but failed ThermoRawFileParser CRC validation as likely corrupted RAW files. |
| PXD000062 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000123 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000145 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000224 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000227 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000249 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000276 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000318 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000326 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000330 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000347 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000349 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000411 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000431 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000435 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000492 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000493 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000532 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000537 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000538 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000541 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000557 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000573 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000577 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000579 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000583 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000589 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000596 | All 30 selected RAW downloads exhausted `aria2c` retries over HTTPS and FTP (exit codes 3, 21, and 22). |
| PXD000635 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |
| PXD000659 | No eligible PRIDE `.raw` record with an FTP location; no download attempted. |

## runAssessor: 11 skipped projects

Every project below completed `run_assessor` with exit code `1`. Five projects contain scans with multiple fragmentation types; runAssessor reports `MultipleFragTypes` and then crashes while accessing a low-end fragmentation profile that was not created. Four projects crash on missing fitted peak data. `PXD000187` has an unrecognized detector value in its Thermo filter strings, which causes missing scan summaries and a later aggregation crash.

| PXD | Verified failure reason |
| --- | --- |
| PXD000134 | Mixed fragmentation types; `KeyError: 'lowend_LR_IT_ETD'` in `assess_ROIs`. |
| PXD000187 | Filter-string detector `+` is unrecognized, leading to `NoMS2Scans` and a later `KeyError: 'summary'` during search-criteria aggregation. |
| PXD000260 | Missing fitted peak data: `KeyError: 'fit'` in `assess_ROIs`. |
| PXD000298 | Missing fitted peak data: `KeyError: 'fit'` in `assess_ROIs`. |
| PXD000328 | Missing fitted peak data: `KeyError: 'fit'` in `assess_ROIs`. |
| PXD000424 | Mixed fragmentation types; `KeyError: 'lowend_LR_IT_ETD'` in `assess_ROIs`. |
| PXD000478 | Mixed fragmentation types; `KeyError: 'lowend_HR_IT_CID'` in `assess_ROIs`. |
| PXD000497 | Mixed fragmentation types; `KeyError: 'lowend_LR_IT_ETD'` in `assess_ROIs`. |
| PXD000507 | Missing fitted peak data: `KeyError: 'fit'` in `assess_ROIs`. |
| PXD000508 | Mixed fragmentation types; `KeyError: 'lowend_HR_IT_CID'` in `assess_ROIs`. |
| PXD000601 | Missing fitted peak data: `KeyError: 'fit'` in `assess_ROIs`. |

### Representative preserved traceback excerpts

`PXD000328` is representative of the five missing-fit failures. The error occurs when runAssessor requires a fitted water-loss peak even though that peak has no `fit` result.

```text
File ".../runassessor.py", line 32, in process_job
	assessor.assess_ROIs()
File ".../mzML_assessor.py", line 1533, in assess_ROIs
	...['water_z2']['peak']['fit']['sigma_mz'] < 0.1
KeyError: 'fit'
```

`PXD000134` is representative of the mixed-fragmentation failures. The log first reports `MultipleFragTypes`, then `assess_ROIs` indexes the missing low-end profile.

```text
ERROR: [MultipleFragTypes]: There are multiple fragmentation types in this MS run. Split them.
File ".../runassessor.py", line 32, in process_job
	assessor.assess_ROIs()
File ".../mzML_assessor.py", line 1518, in assess_ROIs
	for ROI in ...['lowend_peaks'][ROI_type]:
KeyError: 'lowend_LR_IT_ETD'
```

`PXD000187` is the detector/filter-string case. The retained log contains repeated `UnrecognizedDetector` messages for detector value `+`, followed by this aggregation traceback.

```text
INFO: Inferring search criteria from the available information
File ".../runassessor.py", line 153, in main
	study.infer_search_criteria()
File ".../metadata_handler.py", line 552, in infer_search_criteria
	if isinstance(fileinfo['summary']['combined summary']['fragmentation tolerance'], dict):
KeyError: 'summary'
```

## Recommended follow-up

Review the preserved FetchPXD logs before retrying the 32 fetch failures to separate unavailable source files from transfer or conversion errors. The runAssessor groupings above support targeted robustness fixes for unsupported detector syntax, mixed fragmentation types, and missing fitted peaks.