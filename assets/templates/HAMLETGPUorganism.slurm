#!/bin/bash
#SBATCH --job-name=PXD######_v3org
#SBATCH --partition=standard
#SBATCH --account=ncems_cr_default
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=10
#SBATCH --gres=gpu:1
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD######_GPU_v3organism/slurm_%j.log

set -euo pipefail

HAMLET=/storage/group/epo2/default/ims86/git_repos/HAMLET
HAMLET_MINICONDA=/storage/group/epo2/default/ims86/miniconda3
RUN_DIR=/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns/PXD######_GPU_v3organism
PXD=PXD######
EXISTING_RESULTS="__EXISTING_RESULTS__"
TAXONOMY_DIR=/storage/group/epo2/default/ims86/git_repos/MassSpecOrganismID/assets/taxonomy
CASCADIA_MODEL=/storage/group/epo2/default/ims86/git_repos/MassSpecOrganismID/assets/cascadia.ckpt

for reference in "$TAXONOMY_DIR/nodes.dmp" "$TAXONOMY_DIR/names.dmp" "$CASCADIA_MODEL"; do
  if [[ ! -r "$reference" || ! -s "$reference" ]]; then
    echo "ERROR: Missing or unreadable input: $reference" >&2
    exit 1
  fi
done

mkdir -p "$RUN_DIR"
cd "$RUN_DIR"
export CONDA_ENVS_PATH="$HAMLET_MINICONDA/envs"
export CONDA_PKGS_DIRS="$HAMLET_MINICONDA/pkgs"
source "$HAMLET_MINICONDA/etc/profile.d/conda.sh"
# Conda activation hooks are not nounset-safe.
set +u
conda activate meti_env
set -u

# Fetch restores missing spectra; only organism results are refreshed in the aggregate.
/storage/home/ims86/nextflow -log "$RUN_DIR/nextflow_update.log" run "$HAMLET/main.nf" \
  -profile roar_basic,roar_basic_gpu,casanovo_group_storage \
  -w "$RUN_DIR/work_update" \
  --pxd "$PXD" \
  --outdir "$RUN_DIR/results_updated" \
  --update_stage_manifest "$RUN_DIR/results_updated/update_stage_manifest.json" \
  --central_mzml_dir "$RUN_DIR/spectral_files" \
  --taxonomy_dir "$TAXONOMY_DIR" \
  --cascadia_model_path "$CASCADIA_MODEL" \
  --num_gpus 1 \
  --max_parallel_pxds 1 \
  --update_from_existing true \
  --existing_results_dir "$EXISTING_RESULTS" \
  --mode 'organism only' \
  --run_llm_extraction false \
  -resume
