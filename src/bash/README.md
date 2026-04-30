# src/bash - Pipeline Utilities

This folder contains utility scripts for the HAMLET annotator pipeline.

## Main Setup

**→ Use `bash src/setup.sh` after cloning the repository**

This script:
1. Installs Miniconda (if not already installed)
2. Initializes conda
3. Creates three conda environments: `meti_env`, `cascadia_env`, `casanovo_env`
4. Provides next steps for running the pipeline

## Specialized Utilities

### sage_run_per_file_closed_search.sh
**For Advanced Users Only**

Specialized script for running SAGE closed searches with per-file PTM constraints. This handles:
- Resource configuration (single-threaded execution to prevent stack overflow)
- Per-file search execution
- Progress tracking and logging

This is NOT part of the standard setup; it's available for users who need fine-grained control over SAGE search parameters.

## Deprecated Scripts (Deleted)

- `setup_containers.sh` - Deprecated (container-free pipeline)
- `install_miniconda.sh` - Merged into `setup.sh`
- `setup_meti_env.sh` - Merged into `setup.sh`
- `setup_pipeline_envs.sh` - Merged into `setup.sh`

---

**For setup instructions, see:** [CONTAINER_FREE_SETUP.md](../CONTAINER_FREE_SETUP.md)
