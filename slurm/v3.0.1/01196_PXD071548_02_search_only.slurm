#!/bin/bash
#SBATCH --job-name=PXD071548_v301_search_only
#SBATCH --partition=basic
#SBATCH --account=ncems_cr_default
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=10
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=/storage/group/epo2/default/ims86/git_repos/HAMLET/slurm/v3.0.1/logs/%x_%j.log

# Use submit_jobs.py to preserve tracker order and afterok dependencies.
# Previous job: 01196_PXD071548_01_organism_only.slurm
set -euo pipefail

HAMLET=/storage/group/epo2/default/ims86/git_repos/HAMLET
JOB_ROOT=/storage/group/epo2/default/ims86/git_repos/HAMLET/slurm/v3.0.1
HAMLET_MINICONDA=/storage/group/epo2/default/ims86/miniconda3
RUN_DIR=/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD071548_v3.0.1/search_only
PXD=PXD071548
PRIOR_RESULTS=/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD071548_v3.0.1/organism_only/results

mkdir -p "$RUN_DIR"
cd "$RUN_DIR"
export CONDA_ENVS_PATH="$HAMLET_MINICONDA/envs"
export CONDA_PKGS_DIRS="$HAMLET_MINICONDA/pkgs"
source "$HAMLET_MINICONDA/etc/profile.d/conda.sh"
set +u
conda activate meti_env
set -u
export CUDA_VISIBLE_DEVICES=''

python "$JOB_ROOT/verify_aggregate.py" "$PRIOR_RESULTS/$PXD/${PXD}_aggregated_results.json" --pxd "$PXD" --require runAssessor organism_identification.results

/storage/home/ims86/nextflow -log "$RUN_DIR/nextflow.log" run "$HAMLET/main.nf" \
  -profile roar_basic \
  -c "$JOB_ROOT/pipeline.config" \
  -w "$RUN_DIR/work" \
  --pxd "$PXD" \
  --outdir "$RUN_DIR/results" \
  --central_mzml_dir /storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD071548_v3.0.1/spectral_files \
  --max_parallel_pxds 1 \
  --max_raw_files 30 \
  --num_gpus 0 \
  --mode 'search only' \
  --run_llm_extraction false \
  --update_from_existing true \
  --existing_results_dir "$PRIOR_RESULTS" \
  --update_stage_manifest "$RUN_DIR/results/update_stage_manifest.json" \
  -resume

python "$JOB_ROOT/verify_aggregate.py" "$RUN_DIR/results/$PXD/${PXD}_aggregated_results.json" --pxd "$PXD" --require runAssessor organism_identification.results modification_site_fractions
