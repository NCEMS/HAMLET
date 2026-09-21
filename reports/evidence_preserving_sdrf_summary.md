# HAMLET SDRF Remediation Summary

## Purpose

This document explains the problems found while running and reviewing HAMLET, and the changes made to address them. It is written for readers who are new to the repository and to the pipeline.

HAMLET is a Nextflow pipeline for proteomics data sets from PRIDE. In a full run, it downloads spectral data, converts and assesses the runs, performs a proteomics search, combines the resulting evidence into one aggregate JSON document, uses metadata agents and an LLM judge to extract study metadata, and finally writes an SDRF file.

An SDRF is a tab-separated metadata table. Each row normally represents a mass-spectrometry data file and records the sample, instrument, acquisition method, labels, modifications, and other information needed to interpret that file. HAMLET's final SDRF is built from three types of input:

1. Structured PRIDE project metadata.
2. Data-derived evidence produced by runAssessor and search tools.
3. Metadata extracted by HAMLET's Technical, Biological, and Experimental Design agents, optionally reviewed by a judge.

The central design principle for these changes is evidence preservation: HAMLET should render values that its inputs explicitly supply, preserve their provenance, and avoid deriving biological or analytical claims from loose protocol text, naming conventions, or assumptions.

## Additional Operational Fixes

The three items in this section made HAMLET easier to set up and run. They are separate from the 12 SDRF remediation issues below.

### Environment and dependency setup

**Problem:** A new machine could not reliably start HAMLET because Java and Nextflow were available only inside the `meti_env` Conda environment. Conda could also halt before environment creation until the Anaconda Terms of Service were accepted. The private `agentic-metadata` submodule was not consistently initialized by generic submodule commands.

**Solution:** `src/setup.sh` now explicitly initializes both required submodules and the setup guide explains the Conda Terms of Service step, GitHub HTTPS authentication, external model and taxonomy assets, and the correct way to launch Nextflow. The supported pattern is to activate `meti_env` before running `nextflow run main.nf`.

**Result:** Setup and recovery instructions are now collected in [docs/guides/GETTING_STARTED.md](../docs/guides/GETTING_STARTED.md), rather than being knowledge required from a previous developer's shell history.

### Casanovo checkpoint name handling

**Problem:** The DDA organism-identification stage could fail even when a Casanovo checkpoint was already cached locally, because the checkpoint parser recognized only one version-name spelling.

**Solution:** The cache parser now accepts both underscore and hyphen variants of the version suffix.

**Result:** A valid cached checkpoint is reused instead of causing an avoidable download or parsing failure.

### Finalization artifacts were incomplete

**Problem:** The SDRF finalization process produced a final SDRF but did not reliably publish the refinement report and refinement metrics beside it. An initial attempt to copy these artifacts in a shell loop also failed because Nextflow interpreted a Bash variable as a Groovy variable.

**Solution:** `main.nf` now copies the SDRF, confidence sidecar, refinement report, and refinement metrics through explicit file-copy blocks. It also explicitly publishes the judge's `post_judge` directory because Nextflow cannot select nested files from a directory output using `publishDir` alone.

**Result:** Every completed PXD has a self-contained finalization directory containing the final SDRF, confidence sidecar, refinement report, and refinement metrics. The ten-PXD agentic-only regeneration completed with 31 successful tasks and no failed or ignored tasks.

## Complete SDRF Problem Inventory

The following are the 12 issues identified during the SDRF review. They are separate issues because each has a different failure mode, source of evidence, or remaining implementation boundary. The statuses describe the state of the current branch and regenerated `update_results/` artifacts.

### M1: Use all structured modification sources

**Problem:** The final SDRF did not consistently combine PRIDE `identifiedPTMStrings`, TechnicalAgent `ptm`/`modification`, and per-file PTM-Shepherd results. Modifications could therefore be omitted, duplicated, or derived from protocol prose instead of structured input.

**Fix:** Added `ModificationEvidence` adapters and build the modification column from the source-preserving union of those three inputs. Directly equivalent TechnicalAgent and PTM-Shepherd records now merge; `PRIDE:0000398` is recognized as a no-PTM declaration; and absent targets such as `nan` are discarded.

**Status:** Partly fixed. Cross-vocabulary names that merely look similar remain separate because equating them would require an explicit crosswalk.

### M2: Stop inventing modification semantics from prose

**Problem:** Protocol keyword matching and hardcoded maps could turn preparation prose into a modification, or invent an accession, target residue, terminal position, or fixed/variable state.

**Fix:** Removed protocol-derived modifications and builder-level hardcoded modification defaults from the final-SDRF path. Only source-supplied modification information is rendered.

**Status:** Fixed. The regenerated outputs no longer render the explicit PRIDE no-PTM declaration as a modification.

### M3: Represent unknown and conflicting modification status honestly

**Problem:** A modification may be Fixed, Variable, unknown, or disputed between sources. The old renderer had no explicit way to distinguish unknown status from an inferred value.

**Fix:** Added `MT=?` for no supplied status and `MT=!` for an explicit Fixed-versus-Variable conflict. The sidecar records the evidence behind the decision.

**Status:** Partly fixed. The renderer works, but the current adapters do not yet extract all source-declared status values, so a real conflict has not been demonstrated in the cohort.

### M4: Apply modifications only to supported runs and channels

**Problem:** Project-level modification records can be copied to every SDRF row, even when only some raw files or multiplex channels used that modification.

**Fix:** Modification provenance now carries scope and raw-file information when available, making the missing mapping visible in the sidecar.

**Status:** Not yet fixed. HAMLET still needs an authoritative raw-file/channel applicability map before it can safely restrict project-level records.

### M5: Preserve modification provenance in the confidence sidecar

**Problem:** The final SDRF and confidence sidecar did not make clear whether a modification came from PRIDE, the TechnicalAgent, or a search observation.

**Fix:** Each emitted modification now has source records containing the source, source path, scope, source value, raw stem, and PTM-Shepherd fraction where applicable.

**Status:** Fixed.

### I1: Keep instrument evidence and CV accessions together

**Problem:** The chosen instrument could lose its source-supplied CV accession if its display name differed from another source. Study-level values could also override run-specific evidence.

**Fix:** Instrument evidence now retains its source, scope, and CV details; the selected record supplies its own accession, and candidate records are written to the sidecar.

**Status:** Partly fixed. Full raw-file-aware scope filtering and explicit unresolved-conflict output are still needed.

### A1: Do not derive acquisition, MS2 analyser, or dissociation values

**Problem:** Fixed maps could discard supplied technical values, and the builder could guess an MS2 analyser from an instrument model.

**Fix:** The builder now uses direct technical evidence for acquisition, dissociation, and MS2 analyser fields. It no longer guesses the analyser from the instrument name and renders `not available` when direct evidence is absent.

**Status:** Partly fixed. Source records exist, but final resolution is not yet fully raw-file aware for conflicting evidence.

### C1: Do not infer cleavage agents from protocol keywords

**Problem:** Protocol text could cause HAMLET to guess an enzyme, and a specific supplied value such as `Trypsin/P` could be reduced to `Trypsin`.

**Fix:** Removed protocol-derived cleavage output. The controlled mapping preserves an explicitly supplied `Trypsin/P` value rather than reducing its specificity.

**Status:** Partly fixed. The cohort has no direct TechnicalAgent enzyme value for many rows; a future adapter is needed for a structured PRIDE or run/search enzyme record.

### T1: Avoid unsupported or combined mass tolerances

**Problem:** Tolerance values could come from protocol regex matching, include invalid recommendations, or be joined into one study-wide value despite differing runs.

**Fix:** Disabled the protocol fallback in the final-SDRF path and reject non-positive structured recommendations. Structured runAssessor tolerance values remain available.

**Status:** Partly fixed. Tolerance values are still study-level where the inputs lack a per-run mapping, as demonstrated by `PXD001819`.

### B1: Do not merge biological metadata from incompatible scopes

**Problem:** Study-level or LLM-derived organism, disease, sex, or other biological values could replace sample-level values or combine incompatible values. A narrow sex whitelist also discarded valid multi-valued data.

**Fix:** The sidecar now records competing biological evidence, and the renderer preserves `male and female` rather than dropping it.

**Status:** Partly fixed. `PXD049224` organism and `PXD002084` disease remain examples requiring full scope-aware resolution.

### S1: Build SDRF rows from an authoritative assay inventory

**Problem:** HAMLET normally writes one SDRF row per raw file, but a raw file can correspond to multiple logical assay rows. `PXD068894` has six source raw files and twelve PRIDE rows.

**Fix:** No row reconstruction was implemented because the available HAMLET inputs do not provide an authoritative mapping from raw files to the repeated assay rows.

**Status:** Accepted limitation. It is intentionally not solved by copying PRIDE's row structure or guessing sample assignments.

### L1: Do not infer label schemes and channel expansion

**Problem:** Labels were selected across mixed scopes and broad text matching could infer a multiplex scheme or channel expansion without direct evidence.

**Fix:** Channel expansion now requires an explicitly recognized label scheme. A known archived `10plex tandem mass tag (TMT)` alias is retained, while broad substring inference was removed.

**Status:** Partly fixed. Unmapped or mixed-scope labels correctly remain `not available`; full raw-file label and channel resolution is future work.

## How the Changes Were Checked

1. The Nextflow script was parsed successfully with `conda run -n meti_env nextflow run main.nf --help`.
2. The focused SDRF builder suite completed successfully: 31 tests passed.
3. The ten-PXD list in `assets/pxd_lists/student_modification_review_pxds.csv` was regenerated in agentic-only mode into `update_results/`, without overwriting durable store-backed agentic artifacts.
4. Final SDRFs were compared with the saved PRIDE SDRFs. Nine projects retained the same row count; the `PXD068894` row-count limitation was confirmed and retained as an explicit limitation.
5. Modification output was checked for no-PTM handling, direct duplicate merging, and invalid `nan` targets. The generated confidence sidecars were checked for source records.

## Remaining Work and Boundaries

The changes make HAMLET more conservative and more transparent, but they do not claim to reconstruct every field in a curated PRIDE SDRF.

- Per-row fraction, biological-replicate, and technical-replicate identifiers are often present only in the comparison SDRF. HAMLET currently has study-level counts or prose summaries, not a supported raw-file-to-assignment mapping. Filling these cells would require inference and is intentionally deferred.
- Project-level modification records are still rendered across output rows when no source supplies raw-file or channel applicability. Capturing that mapping is necessary before fully resolving multiplex studies.
- Full scope-aware conflict handling is still needed for labels, instrument values, acquisition, dissociation, organism, and disease.
- Some structured terms remain unmapped to SDRF controlled vocabulary. The current policy is to retain source information in the sidecar or use `not available`, rather than convert a similar-looking term by assumption.
- The ignored fetch and runAssessor failures from a separate 100-PXD batch were diagnosed and documented, but not solved by this branch. Most fetch failures reflect unavailable PRIDE RAW files; the runAssessor failures need targeted robustness changes for mixed fragmentation types, missing fitted peaks, and an unsupported detector syntax. See [reports/unreannotated_subset_001_ignored_tasks.md](unreannotated_subset_001_ignored_tasks.md).

## Practical Takeaway

The revised pipeline favors traceable evidence over apparent completeness. A field in a final SDRF should be either directly supported by the applicable source record or explicitly unavailable. The confidence sidecar is the audit trail that explains where each rendered value came from and what alternatives were considered.