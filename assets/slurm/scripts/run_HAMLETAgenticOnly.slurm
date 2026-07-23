#!/bin/bash
#SBATCH -J HAMLETAgenticOnly
#SBATCH --partition=standard
#SBATCH -N 1
#SBATCH -n 10
#SBATCH -t 24:00:00
#SBATCH --account=read_crch_ims86
#SBATCH --mem=64G
#SBATCH -o assets/slurm/logs/%x-%j.out
#SBATCH -e assets/slurm/logs/%x-%j.err

# This script runs HAMLET in AGENTIC-ONLY MODE:
# - Runs: fetch → run_assessor → determine_acquisition_params → create_minimal_aggregated_results → agentic_metadata_extraction → llm_judge → finalize_sdrf
# - Skips: organism_id, determine_taxids, search
# Input: PXD list from CSV (e.g., GSlist0.csv)
# Output: Minimal aggregated results, SDRF files, metadata extraction results

# Redirect Nextflow home away from /storage/home (limited quota)
export NXF_HOME=/storage/group/epo2/default/ims86/.nextflow

cd /storage/group/epo2/default/ims86/git_repos/HAMLET

source /storage/group/epo2/default/ims86/miniconda3/etc/profile.d/conda.sh
conda activate meti_env

# Set OpenRouter API key for LLM-based metadata extraction
# This enables agentic_metadata_extraction to call OpenRouter Gemma model
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY}"

# Run agentic-only workflow
nextflow run main.nf \
    --agentic_only true \
    --pxd PXD006195 \
    --conda_base /storage/work/ims86/.conda \
    -resume
