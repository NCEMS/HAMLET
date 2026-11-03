# Standalone organism identification

The standalone [MassSpecOrganismID](https://github.com/SparkyDaBear/MassSpecOrganismID)
repository is pinned at [submodules/MassSpecOrganismID](../submodules/MassSpecOrganismID).
It includes the approved nontryptic/species lookup, skin/hair contaminant filtering,
and PRIDE-guided genus rollup changes. Its README documents their semantics.

This is a source installation, not a change to HAMLET's Nextflow routing.
HAMLET continues to use its existing `src/python/OrganismID.py`. Shared conda
environments are not recreated or modified by adding this submodule.

Initialize dependencies after cloning:

```bash
git submodule update --init --recursive submodules/MassSpecOrganismID
cd submodules/MassSpecOrganismID
```

For a fresh nested Peptonizer2000 checkout, apply the three patches in order:

```bash
git -C submodules/peptonizer2000 apply ../../patches/peptonizer2000/pandas_compat.patch
git -C submodules/peptonizer2000 apply ../../patches/peptonizer2000/unipept_nontryptic_species_rollup.patch
git -C submodules/peptonizer2000 apply ../../patches/peptonizer2000/pride_genus_rollup.patch
```

These patches are already applied in the current installation. Do not reapply
them blindly to a patched checkout. Dependency patches are local working-tree
changes, not modifications to the pinned upstream commits.

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
