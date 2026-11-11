#!/bin/bash
#SBATCH --job-name=PXD059664_v301_full
#SBATCH --partition=standard
#SBATCH --account=ncems_cr_default
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=10
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=/storage/group/epo2/default/ims86/git_repos/HAMLET/slurm/v3.0.1/logs/%x_%j.log
#SBATCH --gres=gpu:1

# Use submit_jobs.py to preserve tracker order and afterok dependencies.
# Previous job: none
set -euo pipefail

HAMLET=/storage/group/epo2/default/ims86/git_repos/HAMLET
JOB_ROOT=/storage/group/epo2/default/ims86/git_repos/HAMLET/slurm/v3.0.1
HAMLET_MINICONDA=/storage/group/epo2/default/ims86/miniconda3
RUN_DIR=/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD059664_v3.0.1/full
PXD=PXD059664
PRIOR_RESULTS=''

mkdir -p "$RUN_DIR"
cd "$RUN_DIR"
export CONDA_ENVS_PATH="$HAMLET_MINICONDA/envs"
export CONDA_PKGS_DIRS="$HAMLET_MINICONDA/pkgs"
source "$HAMLET_MINICONDA/etc/profile.d/conda.sh"
set +u
conda activate meti_env
set -u

TAXONOMY_DIR=/storage/group/epo2/default/ims86/git_repos/MassSpecOrganismID/assets/taxonomy
CASCADIA_MODEL=/storage/group/epo2/default/ims86/git_repos/MassSpecOrganismID/assets/cascadia.ckpt
for reference in "$TAXONOMY_DIR/nodes.dmp" "$TAXONOMY_DIR/names.dmp" "$CASCADIA_MODEL"; do
  if [[ ! -r "$reference" || ! -s "$reference" ]]; then
    echo "ERROR: Missing reference: $reference" >&2
    exit 1
  fi
done

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "ERROR: Export OPENROUTER_API_KEY before submitting full mode." >&2
  exit 1
fi

/storage/home/ims86/nextflow -log "$RUN_DIR/nextflow.log" run "$HAMLET/main.nf" \
  -profile roar_basic,roar_basic_gpu,casanovo_group_storage \
  -c "$JOB_ROOT/pipeline.config" \
  -w "$RUN_DIR/work" \
  --pxd "$PXD" \
  --outdir "$RUN_DIR/results" \
  --central_mzml_dir /storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD059664_v3.0.1/spectral_files \
  --max_parallel_pxds 1 \
  --max_raw_files 30 \
  --num_gpus 1 \
  --mode full \
  --run_llm_extraction true \
  --taxonomy_dir "$TAXONOMY_DIR" \
  --cascadia_model_path "$CASCADIA_MODEL" \
  --stage_manifest "$RUN_DIR/results/pipeline_stage_manifest.json" \
  -resume

python "$JOB_ROOT/verify_aggregate.py" "$RUN_DIR/results/$PXD/${PXD}_aggregated_results.json" --pxd "$PXD" --require runAssessor organism_identification.results modification_site_fractions
