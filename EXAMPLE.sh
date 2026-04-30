#!/bin/bash
# Example pipeline invocations for HAMLET
# See README.md for full parameter reference.

# ---------------------------------------------------------------------------
# Before running with LLM/agentic features, set your API key:
#   export OPENAI_API_KEY="sk-..."
# ---------------------------------------------------------------------------

# Example 1: Quick test — single PXD, 3 files, no search
nextflow run main.nf \
  --pxd PXD000070 \
  --max_raw_files 3 \
  -resume

# Example 2: Batch from CSV, limit files per PXD (good for testing)
# master.csv must have a "PXD" column
# nextflow run main.nf \
#   --pxd_csv master.csv \
#   --num_pxds 5 \
#   --max_raw_files 3 \
#   -resume

# Example 3: Batch with database search enabled (auto-routes DDA→SAGE, DIA→DIA-NN)
# nextflow run main.nf \
#   --pxd_csv master.csv \
#   --num_pxds 10 \
#   --run_search true \
#   -resume

# Example 4: Force DDA search with a fallback taxid
# nextflow run main.nf \
#   --pxd PXD000070 \
#   --run_search true \
#   --acquisition_type DDA \
#   --taxid 9606 \
#   -resume

# Example 5: With LLM metadata extraction from publications
# export OPENAI_API_KEY="sk-..."
# nextflow run main.nf \
#   --pxd_csv master.csv \
#   --num_pxds 5 \
#   --run_llm_extraction true \
#   -resume

# Example 6: Full pipeline — search + LLM + agentic metadata enrichment
# export OPENAI_API_KEY="sk-..."
# nextflow run main.nf \
#   --pxd_csv master.csv \
#   --num_pxds 5 \
#   --run_search true \
#   --run_llm_extraction true \
#   --run_agentic_metadata true \
#   -resume

# Example 7: Run in background, log to file
# nohup nextflow run main.nf \
#   --pxd_csv master.csv \
#   --run_search true \
#   -resume > logs/pipeline_$(date +%Y%m%d_%H%M%S).log 2>&1 &

# ---------------------------------------------------------------------------
# Output structure (under --outdir, default: results/):
#
# results/
#   └── PXDxxxxxx/
#       ├── mzML/                                # Converted mzML files
#       ├── organism_results/                    # Casanovo + Peptonizer outputs
#       ├── search/                              # SAGE or DIA-NN results
#       ├── llm_results/                         # LLM-extracted metadata
#       ├── agentic_metadata/                    # Agentic enrichment outputs
#       ├── taxid_mapping.json
#       └── PXDxxxxxx_aggregated_results.json    # Main output
# ---------------------------------------------------------------------------

