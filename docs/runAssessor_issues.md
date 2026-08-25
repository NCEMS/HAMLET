# RunAssessor Task Failures

This document records failures of the **runAssessor program or its Nextflow
task**. It is not a record of HAMLET's `sdrf_builder.py` output quality or of
SDRF values derived from runAssessor metadata.

## Issue 1: SDRF Export Crashes After Unknown Fragmentation Analysis

### Failure

The pinned runAssessor revision `eb5cbb98c3c1cea0d97e5da99fba3c902946c21d`
reproducibly exits with code `1` when its standalone CLI processes each of the
nine locally available files below. The CLI reads the mzML spectra and completes
per-file analysis, then fails while generating its own SDRF table:

```text
INFO: Inferring search criteria from the available information
ERROR: Unable to compute fragmentation tolerance: TypeError - string indices must be integers, not 'str'
Traceback (most recent call last):
  File ".../src/runassessor.py", line 196, in <module>
    if __name__ == "__main__": main()
                               ^^^^^^
  File ".../src/runassessor.py", line 154, in main
    study.generate_sdrf_table(include_provenance=params.include_sdrf_provenance)
  File ".../src/runassessor/metadata_handler.py", line 860, in generate_sdrf_table
    if self.metadata['files'][file]['spectra_stats']['high_accuracy_precursors'] == 'true' and self.metadata['files'][file]['summary']['combined summary']['recommended precursor tolerance (ppm)'] != None:
                                                                                               ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
KeyError: 'recommended precursor tolerance (ppm)'
```

This is a complete runAssessor failure, not a HAMLET `sdrf_builder.py` failure.
It occurs after raw/mzML analysis, in runAssessor's internal metadata export,
because `generate_sdrf_table()` assumes a recommended precursor tolerance was
written to every combined summary. The preceding fragmentation-tolerance
calculation logs a `TypeError` and leaves that field absent.

### Standalone Reproduction

The validation ran the normal CLI with one file per invocation, using the
`meti_env` environment and a fresh `--metadata_filepath` for each run:

```bash
PYTHONPATH=/tmp/runassessor-pre-key-guard/src \
  /home/ubuntu/miniconda3/envs/meti_env/bin/python \
  /tmp/runassessor-pre-key-guard/src/runassessor.py \
  --verbose --n_threads 1 --metadata_filepath study_metadata.json input.mzML
```

All nine invocations completed `read_spectra()` and the per-file ROI assessment,
then failed with the traceback above. The captured validation artifacts are in
`/tmp/runassessor-cli-validation/` for this session.

| PXD | Input mzML files | Exit code |
|---|---|---|
| PXD001454 | `Zou_Rappsilber_7TAF_2014_01.mzML`, `Zou_Rappsilber_7TAF_2014_02.mzML`, `Zou_Rappsilber_8TAF_2014_01.mzML`, `Zou_Rappsilber_8TAF_2014_02.mzML` | 1 |
| PXD006156 | `NONO-KGG-RAW.mzML`, `RNF8-BirA-RAW.mzML` | 1 |
| PXD008215 | `Zou_Rappsilber_JW_MCAK_MT.mzML`, `Zou_Rappsilber_JW_MCAK_Phosphorylated.mzML`, `Zou_Rappsilber_JW_MCAK_Unphosphorylated.mzML` | 1 |

### ROI Fallback Observation

The nine files above all emit `UnknownFragmentation` warnings and produce a
combined summary with `call`, `fragmentation tolerance`, `has water_loss`, and
`has phospho_spectra` set to `"unavailable"` during direct per-file analysis.
That analysis path exits successfully on the pinned revision. It demonstrates
the existing top-level ROI fallback; it does **not** reproduce a missing
specific-ROI-key `KeyError`.

A local, uncommitted runAssessor patch adds a narrower key-level guard for
`lowend_<fragmentation>` and `precursor_loss_<fragmentation>`. The patch does
not fix this issue because the reproducible exception is later in
`metadata_handler.py`. Do not characterize this guard as part of the pinned
revision unless its own triggering traceback is recovered and it is committed.

The following two stored fallback outputs cannot yet be retested because their
mzML inputs are absent from local spectral storage:

| PXD | Affected mzML files |
|---|---|
| PXD009777 | `HSP90-p53-CHIPEThcD.mzML` |
| PXD030978 | `Andrew_45kDa_digest.mzML` |

## Other Complete RunAssessor Failures

The standalone reproduction above is sufficient evidence of a runAssessor CLI
failure. Any additional Nextflow task incidents should be documented only after
recovering the original Nextflow trace and the corresponding work-directory
`.command.err` or `.command.log` files. The retained
`/data/HAMLETvol/.nextflow.log` and `/data/HAMLETvol/.nextflow.log.1` files are
failed launcher attempts from the wrong working directory; they do not contain
scheduled `run_assessor` tasks or the missing tracebacks.

Do not list metadata-quality warnings or HAMLET SDRF-builder symptoms as
runAssessor crashes. Each additional issue needs the failed PXD, input RAW/mzML
file, task work directory, nonzero exit code, and traceback.

## What Counts as a RunAssessor Failure

A documented pipeline incident requires all of the following:

1. A scheduled `run_assessor` task in the Nextflow trace or `.nextflow.log`.
2. A nonzero task exit code.
3. The task's `.command.err` or `.command.log`, including the runAssessor
   traceback or the `ERROR: runAssessor failed for <PXD>` wrapper message.
4. The PXD accession, task work directory, command, and failure signature.

A standalone runAssessor incident instead requires the executable source
revision, environment, exact command, input mzML, nonzero exit code, and
captured traceback.

Warnings about mixed instruments, acquisition types, fragmentation types, or
labels are metadata-quality observations. They are not task failures unless the
assessor process exits nonzero.

## Current Pipeline Behavior

`run_assessor` in [main.nf](../main.nf) invokes the runAssessor CLI, captures
its exit code, and exits with that same nonzero code after printing:

```text
ERROR: runAssessor failed for <PXD> with exit code <code>
```

The process currently uses `errorStrategy 'ignore'`. Thus a failed assessor task
is visible as a nonzero task exit but does not stop the rest of the batch. The
limited `--runAssessorOnly` workflow remains the appropriate way to isolate and
rerun a failing PXD.

## Evidence to Preserve for Future Batches

Run dedicated batches from the HAMLET repository and retain:

- the complete `.nextflow.log`;
- a `-with-trace` report containing task name, PXD, work directory, and exit
  status;
- `.command.err`, `.command.out`, and `.command.log` for every nonzero
  `run_assessor` task; and
- the exact Nextflow command, configuration, input PXD list, and run date.

With these artifacts, this document can list real runAssessor crashes by PXD and
traceback signature without conflating them with downstream SDRF behavior.