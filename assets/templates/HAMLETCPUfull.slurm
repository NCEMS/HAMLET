#!/bin/bash
#SBATCH --job-name=PXD######_CPU
#SBATCH --partition=basic
#SBATCH --account=ncems_cr_default
#SBATCH --nodes=1
#SBATCH --ntasks=10
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD######_CPU/slurm_%j.log

set -euo pipefail

HAMLET=/storage/group/epo2/default/ims86/git_repos/HAMLET
RUN_DIR=/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD######_CPU
PXD=PXD######

mkdir -p "$RUN_DIR"
cd "$RUN_DIR"

source /storage/group/epo2/default/ims86/miniconda3/etc/profile.d/conda.sh
# conda's own (de)activate hooks (e.g. meti_env's dotnet-root.sh) aren't nounset-safe,
# so relax -u just around activation.
set +u
conda activate meti_env
set -u

nextflow -log "$RUN_DIR/nextflow.log" run "$HAMLET/main.nf" \
  -profile roar_basic,roar_basic_gpu,casanovo_group_storage \
  -w "$RUN_DIR/work" \
  --pxd "$PXD" \
  --outdir "$RUN_DIR/results" \
  --stage_manifest "$RUN_DIR/results/pipeline_stage_manifest.json" \
  --central_mzml_dir "$RUN_DIR/spectral_files" \
  --mode full \
  --run_llm_extraction true \
  -resume
