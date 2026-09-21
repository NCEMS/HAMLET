# Student-Reported SDRF Modification Review

## Scope and status

This document tracks the modification-parameter discrepancies identified by the student for the ten PXDs in `assets/pxd_lists/student_modification_review_pxds.csv`. It compares the saved PRIDE SDRF at `reports/conflict_assessment/<PXD>/pride.sdrf.tsv` with the authoritative HAMLET v2.1.0 SDRF at `store/agentic_results_files/<PXD>/<PXD>.sdrf.tsv`.

The findings began as investigation results. A first implementation was then run for all ten PXDs into `update_results/`; it did not modify the durable `store/` artifacts. The status column records what that run demonstrates, including unresolved remediation work.

### Cross-project remediation work

| ID | General problem | Proposed remediation | Affected PXDs | Status |
| --- | --- | --- | --- | --- |
| M1 | Modification parameters are incomplete because the builder does not aggregate the three available modification sources. | Add source-specific adapters that parse the supplied formats for structured PRIDE `identifiedPTMStrings`, TechnicalAgent `ptm`/`modification`, and aggregated `modification_site_fractions`. Build the final modification set from their normalized union, including every non-null reported modification and deduplicating only equivalent records. Retain source-specific provenance and every supplied accession, target, terminal position, and fixed/variable value. | All modification-reviewed PXDs; directly demonstrated in PXD000651, PXD002084, PXD049224, PXD068894, and PXD051952 | Partly implemented and verified in `update_results/`: all three streams render; PRIDE `PRIDE:0000398` no-PTM declarations are excluded; and directly equivalent TechnicalAgent/search records merge. Cross-vocabulary equivalence remains unresolved. |
| M2 | Free-text protocol matching and hardcoded ontology defaults cause missed variants and invented modification semantics. | Remove protocol-prose regex inference and hardcoded modification-to-Unimod/target/type assignments from SDRF construction. The builder should only validate non-null normalized records from M1, deduplicate equivalent records, and render supplied values; it must not infer a modification from an input-text keyword or invent accession, residue, terminal position, or fixed/variable status. | PXD001725, PXD002084, PXD004682, PXD013765, PXD049224, PXD001819, PXD005445 | Implemented and verified in the builder/output: protocol-derived modifications and hardcoded Unimod/type/target defaults are absent; explicit no-PTM declarations do not render as modifications. |
| M3 | Sources can disagree on fixed/variable status, while other records supply no status at all. | Preserve every explicitly supplied `MT` value. For equivalent records with conflicting explicit Fixed and Variable values, render `MT=!`; where no input stream supplies a fixed/variable value, render `MT=?`. Neither state may be inferred from a reagent, modification name, or PTM-Shepherd occurrence. Retain each source value and the conflict/no-status reason in the confidence sidecar. | PXD004682, PXD051952; applies to all modification records lacking a declared status | Partly implemented: the renderer supports `MT=?` and `MT=!`, and the run uses `MT=?` without inference. Adapters do not yet extract explicit statuses, so no real conflict is reconciled or demonstrated. |
| M4 | Modification applicability must be scoped to the correct raw file and channel row, particularly for multiplex experiments. | Carry scope and raw-file/channel applicability on every normalized modification record. For TMT, SILAC, and other multi-channel experiments, expand one raw file into its required channel rows while assigning only the modifications applicable to that raw file and channel. Project-scoped records must not be copied to every row unless their scope explicitly covers every run/channel. | PXD004682; all multi-channel TMT, SILAC, and similar experiments | Not implemented: source scope is recorded in the sidecar, but project-level modifications are still rendered for every raw-file row and no source-driven channel applicability exists. |
| M5 | The final SDRF and confidence sidecar do not distinguish declared modifications from PTM-Shepherd detections or TechnicalAgent values. | Under M1's three-source inclusion policy, record the source(s), supplied value, evidence class, scope, and source path for every emitted modification. Preserve whether it came from PRIDE structured metadata, TechnicalAgent metadata, or PTM-Shepherd detection; include PTM-Shepherd fraction when applicable, and record `MT=!` conflicts or `MT=?` missing-status decisions rather than describing all values as a generic derivation. | PXD049224, PXD068894, PXD051952; applies to all emitted modifications | Implemented: all emitted modification sidecar rows contain source, source path, scope, supplied value, raw stem, and PTM-Shepherd fraction when applicable. |
| I1 | Instrument metadata loses assay scope and provenance: the renderer can select an aggregate or agent value for a run, while CV accession output is conditional on an exact string match; incompatible source values are silently replaced. | Normalize each supplied instrument record into `{value, accession, source, scope, raw_file}` without deriving an instrument from another field. Resolve only among records applicable to that raw file. Render a source-supplied CV accession when it maps unambiguously to the selected source value; otherwise preserve the supplied value, record all competing values in the sidecar, and use an explicit unresolved/conflict state rather than inventing an accession or project-wide replacement. | PXD000651, PXD001725, PXD049224, PXD068894 | Partly implemented: runAssessor-selected instruments retain their supplied accession and candidate records appear in the sidecar. Scope filtering and explicit conflict/unresolved output remain unimplemented. |
| A1 | Acquisition, MS2 analyzer, and dissociation values are altered after evidence resolution: fixed maps can discard supplied run-level values, and MS2 analyzer is guessed from instrument name rather than supplied directly. | Carry separate per-run records for acquisition, dissociation, and MS2 analyzer with source, scope, and raw-file provenance. Normalize a supplied value to an SDRF CV term only for an unambiguous mapping. Do not infer MS2 analyzer from instrument model or fill acquisition/dissociation from broad project text; render `not available` when no applicable structured value exists and retain conflicting or unmapped source values in the sidecar. | PXD000651, PXD001725; behavior also affects structured `LR_IT_CID`/`TMTpro` inputs such as PXD001819 | Partly implemented: MS2 analyzer is no longer inferred from instrument model and unavailable direct evidence is omitted. Acquisition/dissociation still rely on fixed maps and lack scope-aware conflict handling. |
| C1 | Cleavage-agent output is recovered from protocol/agent prose and reduces specific supplied terms, so absent structured evidence can become a guessed enzyme and Trypsin/P can collapse to Trypsin. | Prefer explicit structured cleavage-agent records from PRIDE, TechnicalAgent, or run/search metadata, preserving the supplied name, accession, specificity, scope, and raw-file applicability. Remove protocol-keyword inference from SDRF construction. A controlled parser may normalize an explicit source value only when it retains its full specificity; otherwise render `not available` and record the unnormalized source evidence and ambiguity in the sidecar. | PXD000651, PXD013765, PXD001819 | Partly implemented: protocol inference is removed and an explicit TechnicalAgent `Trypsin/P` is preserved in regression coverage. No adapter yet consumes structured PRIDE or run/search enzyme records, so cohort outputs are `not available` when TechnicalAgent does not supply a value. |
| T1 | Precursor and fragment tolerances can come from protocol regex fallback, can be emitted despite invalid values, or can combine incompatible recommendations into a project-wide list. | Represent each supplied precursor and fragment tolerance independently with numeric value, unit, source, scope, and raw-file applicability. Prefer applicable structured runAssessor/search or PRIDE records; normalize only the supplied number and unit, never derive a tolerance from prose. Retain distinct applicable values per run, record conflicts and invalid supplied values in the sidecar, and render `not available` where no valid applicable structured value exists. | PXD000651, PXD004682, PXD051952, PXD001819, PXD005445 | Partly implemented: protocol fallback is removed and non-positive structured recommendations are rejected. Tolerances are still study-level values; PXD001819 demonstrates unresolved combined values, with no per-run records or conflict state. |
| B1 | Biological values of different scopes are merged or filtered: a project-level/LLM value can replace structured PRIDE sample evidence, multiple organisms can be combined, and multi-valued sex is discarded by a single-value whitelist. | Normalize biological evidence into records with field, value, accession, source, and sample/run/study scope. Resolve each field only against the most specific applicable records, then apply a judge-approved correction only within that same scope. Preserve supplied multi-values as distinct, scoped values where SDRF permits them; otherwise emit an explicit unresolved/conflict state with full provenance rather than merging values or dropping them. | PXD002084, PXD049224, PXD005445 | Partly implemented: `PXD005445` now retains `male and female` and candidate records are serialized. `PXD049224` still merges *Mus musculus* with *Homo sapiens*, and `PXD002084` still appends `normal` to the disease value. |
| S1 | The current row count treats one RAW file as one SDRF row except for a hardcoded label-channel expansion, so incomplete or unsupported channel mapping can silently omit valid assays. | Build an authoritative expected-row inventory from source-provided raw-file, sample/assay, fraction, replicate, and channel records. Validate the generated SDRF as a mapping of expected `(raw_file, channel)` rows, allowing one RAW file to produce multiple rows only where an explicit label/channel source requires it. Block publication for unexplained missing, duplicate, or extra rows and write the reconciliation evidence to the sidecar/report. | PXD068894; applies to all multiplex and fractionated studies | Not implemented: `PXD068894` remains 6 HAMLET rows versus 12 PRIDE rows. PRIDE includes repeated assay rows for the same raw file and label, which the current output collapses. |
| L1 | Label values are selected from mixed scopes and then passed through a fixed scheme map; valid supplied forms can become `not available`, while channel expansion is based on hardcoded scheme assumptions. | Preserve per-run label records with source, scope, raw-file, and explicit channel information. Normalize a supplied label to its SDRF CV representation only when the mapping is unambiguous; do not infer a label scheme or channels from unrelated protocol/project text. Emit `not available` for absent or unmapped labels, preserve raw source values and conflicts in the sidecar, and expand channels only from an explicit source-supported channel scheme. | PXD000651, PXD004682, PXD013765, PXD051952, PXD001819 | Partly implemented: expansion now requires an explicit recognized scheme, including the archived `10plex tandem mass tag (TMT)` form. Mixed/unmapped values still become `not available`; `PXD000651` still renders label-free despite structured `TMTpro` evidence. |

### Regenerated final-SDRF run: `update_results/`

The agentic-only cohort run completed finalization for all ten PXDs. Each `update_results/<PXD>/agentic_metadata/` directory contains the final SDRF, confidence sidecar, refinement report, and refinement metrics.

- **M1/M2:** All three modification streams are rendered without protocol-text modification inference. `PXD001725` and `PXD004682` now render `comment[modification parameters] = not available`, so the PRIDE `No PTMs are included in the dataset` declaration no longer becomes a modification. The current outputs also merge directly equivalent TechnicalAgent/search records and omit missing `nan` targets. Cross-vocabulary equivalence is still intentionally unresolved.
- **M3/M5:** Every output modification without a supplied status is rendered `MT=?`. Modification sidecar records include source, source path, scope, raw stem, and PTM-Shepherd fraction. No fixed/variable conflict was rendered because the current adapters do not extract explicit source statuses.
- **Technical fields:** Instrument accessions are preserved when runAssessor supplies them. Direct MS2 analyzer evidence is absent in the reviewed output, so the analyzer column is omitted rather than inferred. Cleavage is now `not available` where no direct TechnicalAgent value exists. Tolerance protocol fallback is absent, but per-run tolerance resolution is not yet implemented.
- **Biological fields:** `PXD005445` preserves `male and female`; source scope conflicts remain unresolved for `PXD049224` organism and `PXD002084` disease.
- **Structure:** Nine PXDs retain their previous row count. `PXD068894` remains at 6 HAMLET rows while PRIDE has 12, because repeated source assay rows are still collapsed.

### Additional final-artifact review

The final `update_results/<PXD>/agentic_metadata/<PXD>.sdrf.tsv` artifacts were compared with the corresponding saved PRIDE SDRFs for all ten projects. All ten expected final SDRFs and confidence sidecars are present, and the regeneration completed with 31 successful workflow tasks and no failed or ignored tasks.

No additional remediation item was added. The remaining recurrent differences fall within existing work items: label selection and run scope (L1), instrument/acquisition/dissociation scope (I1/A1), biological metadata scope (B1), and project-level modification applicability (M4). Per-row fraction, technical-replicate, and biological-replicate assignments are present in the comparison SDRFs but not in HAMLET's structured input as raw-file mappings; current agent values are study-level counts or prose-derived summaries, so populating those cells would require unsupported inference. The `PXD068894` row-count difference remains the accepted S1 limitation.

### Per-PXD status

| PXD | Student concern validated? | Discrepancy class | Primary cause | Proposed remediation |
| --- | --- | --- | --- | --- |
| PXD000651 | Yes | Omission | Structured PRIDE PTMs are not consumed; no usable free-text or search evidence was stored. | M1 |
| PXD001725 | Yes | HAMLET-only addition | Iodoacetamide in the project protocol triggers fixed Carbamidomethyl despite the PRIDE SDRF declaring no PTMs. | M1, M3 |
| PXD002084 | Partly | Omission plus addition | Iodoacetamide triggers Carbamidomethyl; structured Oxidation is ignored. | M1 |
| PXD004682 | Yes | Type conflict plus addition | Global protocol parsing forces Carbamidomethyl fixed and applies a project-wide TMT mention to a label-free row. | M3, M4 |
| PXD013765 | Yes | Omission | The parser misses `acetylation` / terminal wording. | M1, M2 |
| PXD049224 | Yes | Additions | Protocol supports Acetyl and Deamidation; PTM-Shepherd adds Formylation. | M1, M5 |
| PXD068894 | Yes | HAMLET-only addition | PTM-Shepherd-derived Loss of Lysine is emitted as an SDRF modification. | M5 |
| PXD051952 | Yes | Omission, type conflict, and additions | PTM-Shepherd provides all final modifications because no protocol modifications are parsed. | M1, M3, M5 |
| PXD001819 | Yes | Omission | The parser misses `N-ter` terminal-acetyl notation. | M1, M2 |
| PXD005445 | Yes | Omission | The parser misses `N-acetylation`. | M1, M2 |

## Per-PXD findings

### PXD000651

**Observed values**

- PRIDE: Carbamidomethyl, `UNIMOD:4`, Fixed on C; Oxidation, `UNIMOD:35`, Variable on M.
- HAMLET v2.1.0: no modification parameters.

**Evidence and diagnosis**

- The stored PRIDE project metadata contains structured `identifiedPTMStrings`, including acetylated residue and iodoacetamide-related entries, but both sample- and data-processing protocol text are `Not available`.
- No closed-search PTM-Shepherd per-file results were stored for this PXD.
- The SDRF builder only parses free-text protocols and PTM-Shepherd fractions; it does not consume `identifiedPTMStrings`.

**Tracking**

- Status: confirmed omission.
- Proposed remediation: M1. Structured PRIDE PTM descriptors need a supported mapping to SDRF modification parameters.

### PXD001725

**Observed values**

- PRIDE: no modification parameters.
- HAMLET v2.1.0: Carbamidomethyl, `UNIMOD:4`, Fixed on C.

**Evidence and diagnosis**

- The saved PRIDE project metadata says no PTMs are included in the dataset.
- Its sample-processing protocol nevertheless states that the samples were alkylated using iodoacetamide.
- Replaying the current parser with that protocol produces fixed Carbamidomethyl. No closed-search PTM-Shepherd results were stored.

**Tracking**

- Status: confirmed SDRF mismatch; the HAMLET value is protocol-backed, but it conflicts with the saved PRIDE SDRF's explicit no-PTM declaration.
- Proposed remediation: M1 and M3. Define precedence between an explicit PRIDE no-PTM descriptor and preparation/search evidence, without assuming every alkylation step is a fixed search modification.

### PXD002084

**Observed values**

- PRIDE: Oxidation, `UNIMOD:35`, Variable on M.
- HAMLET v2.1.0: Carbamidomethyl, `UNIMOD:4`, Fixed on C.

**Evidence and diagnosis**

- The saved PRIDE SDRF does not contain Carbamidomethyl, despite the student's original note reporting it. That part of the student concern is not supported by the saved comparison file.
- The structured PRIDE metadata includes Carbamidomethyl and Oxidation. The protocol records iodoacetamide, and the parser consequently emits fixed Carbamidomethyl.
- Oxidation is not present in the protocol text and is not recovered from structured PRIDE metadata. No closed-search PTM-Shepherd results were stored.

**Tracking**

- Status: confirmed final-SDRF mismatch, with the saved PRIDE artifact qualification above.
- Proposed remediation: M1. Use structured descriptors to preserve Oxidation and establish an explicit policy for conflicts between descriptors and preparation evidence.

### PXD004682

**Observed values**

- PRIDE: Carbamidomethyl, `UNIMOD:4`, Variable on C; Oxidation, `UNIMOD:35`, Variable on M.
- HAMLET v2.1.0: Carbamidomethyl, Fixed on C; Oxidation, Variable on M; TMT6plex, `UNIMOD:730`, Fixed on K.

**Evidence and diagnosis**

- The stored project protocol describes label-free, TMT, and DIA parts of the project. The HAMLET output row under review is a label-free `bRPLC` RAW file.
- The parser searches the entire project protocol. It detects both iodoacetamide/Carbamidomethyl and `TMT`, generating fixed Carbamidomethyl and TMT6plex for every row.
- No PTM-Shepherd per-file data was stored, so it did not cause this TMT addition.

**Tracking**

- Status: confirmed type conflict and run-level attribution error.
- Proposed remediation: M3 and M4. Preserve explicit Carbamidomethyl type, and attach label modifications only to the matching experimental runs.

### PXD013765

**Observed values**

- PRIDE: Acetyl, `UNIMOD:1`, Variable at protein C-terminus; Carbamidomethyl, Fixed on C; Oxidation, Variable on M.
- HAMLET v2.1.0: Carbamidomethyl, Fixed on C; Oxidation, Variable on M.

**Evidence and diagnosis**

- The saved project protocol explicitly states that search criteria included fixed Carbamidomethyl, variable Oxidation, and variable N-terminal protein acetylation.
- Replaying the parser returns Carbamidomethyl and Oxidation but not Acetyl because it searches for the word `acetyl`, which does not match `acetylation`.
- The PRIDE SDRF additionally records protein C-terminal specificity, which the current formatter cannot preserve.

**Tracking**

- Status: confirmed omission and terminal-specificity loss.
- Proposed remediation: M1 and M2. Recognize spelling variants and retain the terminal target from structured SDRF/PRIDE evidence.

### PXD049224

**Observed values**

- PRIDE: Carbamidomethylation, Fixed on C; Oxidation, Variable on M.
- HAMLET v2.1.0: Carbamidomethyl, Fixed on C; Oxidation, Variable on M; Acetyl, Variable on K; Deamidation, Variable on NQ; Formylation, `UNIMOD:122`, Variable on K.

**Evidence and diagnosis**

- The project protocol explicitly declares Carbamidomethyl as static and Oxidation, Deamidation, and protein N-terminal Acetyl as variable modifications. Thus, the Acetyl and Deamidation additions have protocol evidence, even though they are absent from the saved PRIDE SDRF.
- The protocol parser renders Acetyl as target `K`, losing the protein N-terminal scope.
- PTM-Shepherd reports Formylation at 11.7-12.7% in the stored per-file closed-search results. The builder's 5% threshold therefore emits it. This is the demonstrated origin of Formylation.

**Tracking**

- Status: confirmed additions; Acetyl and Deamidation are protocol-backed, while Formylation is search-derived.
- Proposed remediation: M1, M2, and M5. Preserve terminal specificity and decide whether detected PTMs should be included as declared SDRF search modifications.

### PXD068894

**Observed values**

- PRIDE: no modification parameters.
- HAMLET v2.1.0: Loss of Lysine, `UNIMOD:313`, Variable on K.

**Evidence and diagnosis**

- No PRIDE modification parameters or usable protocol modification text were stored.
- PTM-Shepherd reports Loss of Lysine in every stored closed-search file at fractions from 54.7% to 69.5%.
- The technical agent records it as a METI-only/PTM-Shepherd value, and the builder's fraction threshold causes it to be emitted.

**Tracking**

- Status: confirmed search-derived HAMLET-only addition.
- Proposed remediation: M5. Do not represent PTM-Shepherd discovery output as a declared SDRF modification without an explicit, documented policy and provenance.

### PXD051952

**Observed values**

- PRIDE: Acetyl, Variable at protein N-terminus; Carbamidomethyl, Fixed on C; Oxidation, Variable on M.
- HAMLET v2.1.0: Carbamidomethyl, Variable on C; Gln-to-Trp substitution, `UNIMOD:1187`, Variable on Q; aminoethylcysteine, `UNIMOD:472`, Variable on S.

**Evidence and diagnosis**

- No usable protocol modification text was stored, so the parser contributes no modifications.
- PTM-Shepherd reports Iodoacetamide derivative at 7.1-7.5%, Gln-to-Trp substitution at 7.1-7.2%, and aminoethylcysteine at 5.8-6.2%.
- The technical agent records these as METI-only/PTM-Shepherd values. The builder then renders them all because each exceeds the 5% threshold.
- The result omits PRIDE Acetyl and Oxidation, adds two search-derived values, and changes Carbamidomethyl from PRIDE Fixed to HAMLET Variable.

**Tracking**

- Status: confirmed omission, type conflict, and search-derived additions.
- Proposed remediation: M1, M3, and M5. Structured PRIDE values need to be available when protocol text is absent, and search-derived calls need a separate inclusion policy.

### PXD001819

**Observed values**

- PRIDE: Acetyl, `UNIMOD:67`, Variable at protein N-terminus; Carbamidomethyl, Fixed on C; Oxidation, Variable on M.
- HAMLET v2.1.0: Carbamidomethyl, Fixed on C; Oxidation, Variable on M.

**Evidence and diagnosis**

- The project protocol explicitly describes acetyl or acetylation at `Protein N-ter`, variable Oxidation, and fixed Carbamidomethyl.
- Replaying the parser returns only Carbamidomethyl and Oxidation. Its terminal-acetyl pattern requires `term`, so it misses `N-ter`.
- No closed-search PTM-Shepherd results were stored.

**Tracking**

- Status: confirmed omission and terminal-specificity loss.
- Proposed remediation: M1 and M2. Support `N-ter` and preserve PRIDE's `UNIMOD:67` and protein N-terminal target.

### PXD005445

**Observed values**

- PRIDE: Acetyl, `UNIMOD:1`, Variable at protein N-terminus; Carbamidomethyl, Fixed on C; Oxidation, Variable on M.
- HAMLET v2.1.0: Carbamidomethyl, Fixed on C; Oxidation, Variable on M.

**Evidence and diagnosis**

- The project data-processing protocol explicitly says that the search used fixed cysteine Carbamidomethylation plus variable N-acetylation and methionine Oxidation.
- Replaying the parser returns Carbamidomethyl and Oxidation but misses Acetyl because its pattern does not match `N-acetylation`.
- No closed-search PTM-Shepherd results were stored.

**Tracking**

- Status: confirmed omission and terminal-specificity loss.
- Proposed remediation: M1 and M2. Support hyphenated acetylation wording and retain protein N-terminal specificity.

## Technical evidence

- The first implementation replaces builder-level protocol modification parsing with adapters for the three agreed input streams: structured PRIDE `identifiedPTMStrings`, TechnicalAgent `ptm`/`modification`, and per-file PTM-Shepherd records. The `update_results/` run confirms that all three sources are emitted and that the former `fraction_modified >= 0.05` inclusion threshold is absent.
- The builder now renders supplied accessions and targets without hardcoded Unimod/residue/type defaults. The normalizer excludes PRIDE's explicit no-PTM declaration, merges directly equivalent TechnicalAgent/search records, and filters missing target sentinels. It intentionally does not infer cross-vocabulary semantic equivalence from superficially similar names.
- The renderer supports `MT=!` for an explicit Fixed-versus-Variable conflict and `MT=?` when no source supplies status. The cohort run uses `MT=?` as intended, but adapters do not yet extract source-declared Fixed/Variable status, so a real conflict has not been reconciled.
- Each emitted modification has sidecar source records containing source, source path, supplied value, scope, raw stem, and PTM-Shepherd fraction. Scope is audit-only at this point: project-level records still broadcast to all output rows, and channel applicability remains unimplemented.
- The prior v2.1 sidecars used generic `legacy_derivation`; the `update_results/` sidecars use `normalized_source_union` and preserve the individual source records.

## Next review checkpoint

Before publishing `update_results/` or treating this remediation as complete, finish the normalized modification-record contract: classify explicit no-PTM declarations, semantically deduplicate equivalent terms across the three sources, extract supplied Fixed/Variable statuses, and enforce raw-file/channel applicability during row construction. The contract must preserve source, `MT` status or status marker, raw-file/channel applicability, and run-level provenance without reintroducing protocol-text keyword inference.