# HAMLET v3.0.1 job set

These are generated, **not submitted**, cluster-specific jobs from
[`Trackers/ResultsTracker.csv`](../../Trackers/ResultsTracker.csv), in tracker
order. Filenames start with the one-based tracker row and per-PXD step.

| Mode | Jobs | Resource |
|---|---:|---|
| Full | 7,854 | One GPU |
| Organism only | 988 | One GPU |
| Search only | 749 | CPU |

The 1,013 fully populated PXDs have no jobs. There are 9,591 jobs across 9,201
PXDs; 390 PXDs need organism-only followed by search-only. No RunAssessor-only
jobs are needed by this tracker snapshot.

[`jobs.csv`](jobs.csv) records the source aggregate, output directory, shared
spectral directory, and predecessor of every job. Partial jobs use
`--update_from_existing` and preserve prior aggregate sections. Search jobs in
two-job chains use the organism job's aggregate as their base, not the original
aggregate. Each job verifies the expected populated sections before/after
execution; missing predictions or modification fractions fail the job rather
than treating an empty structure as success.

## Review or submit later

```bash
# Dry-run only: prints counts; does not call sbatch.
python3 slurm/v3.0.1/submit_jobs.py

# After validation and explicit approval, submit the first 10 jobs.
# Full jobs require OPENROUTER_API_KEY exported in the submission environment.
python3 slurm/v3.0.1/submit_jobs.py --limit 10 --submit
```

Use the helper rather than submitting a wildcard of Slurm files: it enforces
per-PXD `afterok` dependencies. It records job IDs immediately in a new receipt
and refuses to overwrite an existing receipt. Review that receipt after an
interrupted submission; rerunning with a different receipt can submit duplicates.
Do not run two copies of a PXD's job concurrently.

Jobs use the existing `ncems_cr_default` account, `standard` GPU or `basic` CPU
partition, 10 CPUs, 32 GB RAM, and 24 hours. [`pipeline.config`](pipeline.config)
bounds the local Nextflow executor to the allocation and terminates failed
stages. Run outputs go under `HAMLETruns/<PXD>_v3.0.1/`, with separate stage
directories and a shared per-PXD spectral directory.

The scripts and manifest contain absolute paths for this ROAR checkout, prior
aggregates, conda environments, taxonomy, and model checkpoint. They are not
portable job templates. Adjust paths and confirm inputs before using another
checkout. Create `slurm/v3.0.1/logs` before submission because Slurm opens its
log before the script executes. Source spectra may be downloaded when absent.

The integrated v3.0.1 revision still requires real-PXD validation before a broad
launch; syntax, routing, aggregate checks, and dependency checks are offline
validation only.
