# runAssessor Issues

## Latest `--runAssessorOnly` batch

The most recent dedicated runAssessor execution was launched on 2026-08-12 and completed on 2026-08-14:

```bash
nextflow run main.nf \
  -c assets/nextflow_configs/nextflow_JS2.config \
  -profile js2_large \
  --runAssessorOnly \
  --pxd_csv assets/pxd_lists/completedAsOf08112026_part3.csv \
  -resume
```

The Nextflow log records 987 completed `run_assessor` tasks: 941 exited successfully and 46 exited with status 1. At the time of that run, `run_assessor` used `errorStrategy 'ignore'`, so the batch continued after each failed PXD.

All 46 failures occurred during runAssessor's final SDRF-table generation after spectra had been read. The quality warnings about mixed instruments, fragmentation, acquisition, or labeling types explain why expected metadata is absent; they are not themselves task failures.

| Failure signature | Failed PXDs | Count |
|---|---|---:|
| Missing `recommended precursor tolerance (ppm)` in the combined summary | PXD006156, PXD006246, PXD006403, PXD008215, PXD010154, PXD015793, PXD015949, PXD019599, PXD019827, PXD019713, PXD019868, PXD019944, PXD019939, PXD021263, PXD012083, PXD012437, PXD012466, PXD012143, PXD012886, PXD013057, PXD013601, PXD014547, PXD015833 | 23 |
| Missing peak-fit data (`KeyError: 'fit'`) | PXD006506, PXD006504, PXD005699, PXD007078, PXD007114, PXD007073, PXD007681, PXD007867, PXD008510, PXD008310, PXD017239, PXD021960, PXD022278, PXD010989, PXD013292, PXD012627, PXD014473, PXD014342 | 18 |
| Per-file record has no `summary` block | PXD008465, PXD016146, PXD022833, PXD012045, PXD015349 | 5 |

Representative failures:

- `PXD015349` contains mixed acquisition and fragmentation types; final SDRF generation assumes every file has `summary` and raises `KeyError: 'summary'`.
- `PXD015833` contains mixed instruments, fragmentation, and labeling types; tolerance inference emits `TypeError` diagnostics, then SDRF generation raises `KeyError: 'recommended precursor tolerance (ppm)'`.

## Submodule crash guard

The HAMLET-pinned `submodules/runassessor` revision has a local, uncommitted fix in `src/runassessor/mzML_assessor.py`. Per project policy, this change is not committed or pushed to the runAssessor submodule and HAMLET continues to reference its published revision.

Before the fix, assessment of a fragmentation type assumed both of these structures existed:

- `lowend_peaks["lowend_<fragmentation>"]`
- `neutral_loss_peaks["precursor_loss_<fragmentation>"]`

Some runs do not populate one or both structures. The assessor then raised `KeyError` while computing water-loss and phospho-spectrum metrics. The guard now detects either missing structure, marks the affected fragment summary as `"unavailable"` for `call`, `has water_loss`, and `has phospho_spectra`, and continues processing the remaining data.

This guard prevents that low-level assessment crash only. It does not address the 46 historical failures above, which occur later in `metadata_handler.py` while generating the runAssessor SDRF table. Those need separate null-safe handling for missing `summary`, peak-fit, and tolerance fields.

## Pipeline behavior after this update

HAMLET now exposes `--runAssessorOnly` as a supported limited workflow (`fetch_pxd -> run_assessor`). The workflow also passes the process CPU allocation to runAssessor, retains RAW files until their corresponding mzML files validate, and fails a dedicated runAssessor task when the assessor exits nonzero. This makes failed PXDs observable for reruns instead of creating placeholder assessor output.