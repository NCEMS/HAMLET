# Standalone organism identification

The standalone [MassSpecOrganismID](https://github.com/SparkyDaBear/MassSpecOrganismID)
repository is pinned at [submodules/MassSpecOrganismID](../submodules/MassSpecOrganismID).
It includes the approved nontryptic/species lookup, skin/hair contaminant filtering,
and PRIDE-guided genus rollup changes. Its README documents their semantics.

In the v3.0.1 draft, Nextflow uses this submodule for combined fetch/conversion/RunAssessor
and for organism identification. The installed Casanovo/Cascadia packages are
used; HAMLET's Bolt sources are retained but no longer executed or installed.
The existing taxid-selection and search decisions are unchanged.

Initialize dependencies after cloning:

```bash
git submodule update --init --recursive submodules/MassSpecOrganismID
cd submodules/MassSpecOrganismID
```

Install the patched Peptonizer package into the actual Nextflow `meti_env`:

```bash
conda run -p /path/to/meti_env --no-capture-output \
  python ../../src/python/install_organism_id.py --submodule .
```

The installer builds the expected patched files from the pinned upstream commit,
supports repeated installation, and refuses conflicting local modifications.
Dependency patches remain local working-tree changes, not modifications to the
pinned upstream commits.

Use the standalone README for environment installation and the untracked model
checkpoint/taxonomy downloads required for actual dataset runs. When reusing a
shared environment, confirm its installed `peptonizer` package points at a
checkout containing these patches; a patched submodule does not redirect an
existing Python installation automatically.

Validate with the existing `meti_env` interpreter:

```bash
python -m unittest discover -s tests -p 'test_organism_id_pr_changes.py' -v
python src/OrganismID.py --help
```

The offline tests cover I/L normalization, human/nonhuman contaminant filtering,
nontryptic requests, species recovery, approved metadata-guided genus assignment,
and ambiguous PRIDE targets.

## Nextflow execution and modes

The `fetch_pxd` task combines download/conversion and RunAssessor while retaining
separate `fetch` and `run_assessor` manifest records. A cached fetch can reuse
spectra and rerun assessment independently. Optional LLM extraction then precedes
HAMLET's refreshed acquisition detection. `--acquisition_type DDA|DIA` produces
one explicit task-local acquisition JSON consumed by both organism ID and search.

`--mode 'runassessor only'` runs combined fetch/assessment and aggregation (the
standalone fetch may also produce its preliminary acquisition JSON).
`--mode 'agentic only'` reads stored aggregates without launching either standalone
script. `--mode 'organism only'` and `--mode 'search only'` also stop after
aggregation, without agentic/judge/SDRF stages.
`--update_from_existing` refreshes the selected mode's sections into a different
output directory, using the prior aggregate as the base even when unselected
stage source files are missing. If the aggregate is absent, it is rebuilt from
available stage outputs. See the [mode reference](../README.md#pipeline-modes-and-updating-existing-results).
All stages share one resolved manifest path: `--update_stage_manifest` in update
mode or `--stage_manifest` otherwise, defaulting to `update_stage_manifest.json`
or `pipeline_stage_manifest.json` under the selected output directory. Resolution
does not reassign Nextflow parameters, whose configured values may be immutable.
An organism-ID task failure terminates update mode rather than silently ending
without regenerated aggregates.

Organism ID receives explicit acquisition, skin-contaminant, taxonomy, model,
and nested Peptonizer paths. It is run in `meti_env` and launches the two
sequencers in their own environments. Snakemake uses the task's CPU allocation.
GPU tasks hold an exclusive per-host device lock; CPU configurations hide GPUs.
Manifest commands use the configured `meti_env` interpreter rather than relying
on a `python` executable in the launching shell.

Execution fingerprints include code, patched Peptonizer files, configuration,
metadata, references, and resource locations. On a fingerprint change,
downstream manifest checkpoints are invalidated. Once the manifest requests a
rerun, the standalone script bypasses its internal caches. Completed attempts
with no predictions are distinct from execution failures and intentional skips;
the status is included in `organism_identification.status` alongside the unchanged
`results` and `summary` fields. Publication overwrites refreshed organism/taxid/
search results; use a new output directory to keep earlier runs.

HAMLET's retained legacy Python and Bolt files are not used by this workflow.
The first real-PXD validation is pending; offline interface tests do not prove
model inference or downstream searches work on a dataset.
The workflow integration changes are published in the pinned submodule revision.
Initialize the pinned revision recursively; do not substitute another checkout's
uncommitted sources.

## Generating one-PXD Slurm jobs

The tracker-based v3.0.1 job set is in
[`slurm/v3.0.1`](../slurm/v3.0.1/README.md). Its ordered manifest contains
7,854 GPU full jobs, 988 GPU organism-only jobs, and 749 CPU search-only jobs.
It skips the 1,013 complete PXDs and chains the 390 two-stage reruns through
their updated aggregates. Its submission helper defaults to dry-run.

To generate an additional custom batch from a CSV with a `PXD` or `accession`
column, use the existing template generator:

```bash
python src/job_scripts/gen_slurm_per_pxd.py assets/templates/HAMLETGPUfull.slurm \
  /path/to/full_batch.csv \
  -o assets/slurm/generated/full_batch_001

python src/job_scripts/gen_slurm_per_pxd.py assets/templates/HAMLETGPUorganism.slurm \
  /path/to/organism_batch.csv \
  -o assets/slurm/generated/organism_batch_001 --skip-unavailable
```

Existing generated scripts are not overwritten. Generation creates the Slurm log
directories because Slurm opens logs before executing the script.

The full template uses `--mode full`. The organism template uses
`--mode 'organism only' --update_from_existing`, refreshes organism ID, preserves
other aggregate sections, and stops after aggregation. Both use
one GPU, ten CPUs, 32 GB RAM, and separate v3 run directories. Both require
reference assets from the sibling MassSpecOrganismID checkout. Only the full template needs
`OPENROUTER_API_KEY` in the submission environment. Missing spectra are restored
by fetch/conversion/assessment; the default download limit is 30 RAW files.

For organism reruns, the generator derives the prior results root from the
tracker's aggregate path and accepts a readable per-PXD aggregate alone. If that
aggregate is absent, it checks the legacy stage inputs needed for reconstruction.
Archive members cannot be reused directly. Restore the per-PXD aggregate (or
search, LLM, RunAssessor, and taxid-warning inputs), then supply
`--existing-results-root /path/to/restored/results` (containing `PXD*/`).
Alternatively, `--skip-unavailable` explicitly reports and skips rows lacking
local reuse inputs; retain those rows for later restoration. A new output
directory should be used when generating scripts for the restored rows.

Generation alone never submits jobs. The existing `--submit` option is opt-in;
omit it while preparing and reviewing scripts.
