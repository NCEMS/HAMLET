#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HAMLET="${HAMLET_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"
JOB_ROOT="$SCRIPT_DIR"
PXD=PXD005463
RUN_DIR="${RUN_DIR:-$HAMLET/HAMLETruns/${PXD}_v3.0.1/full}"
CENTRAL_MZML_DIR="${CENTRAL_MZML_DIR:-$HAMLET/HAMLETruns/${PXD}_v3.0.1/spectral_files}"
LOG_DIR="$JOB_ROOT/logs"

mkdir -p "$RUN_DIR" "$LOG_DIR"
SCRIPT_LOG="$LOG_DIR/${PXD}_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$SCRIPT_LOG") 2>&1

if [[ -z "${CONDA_BASE:-}" ]]; then
  if command -v conda >/dev/null 2>&1; then
    CONDA_BASE="$(conda info --base)"
  elif [[ -x "$HOME/miniconda3/bin/conda" ]]; then
    CONDA_BASE="$HOME/miniconda3"
  else
    echo "ERROR: Set CONDA_BASE or make conda available on PATH." >&2
    exit 1
  fi
fi

if [[ ! -r "$CONDA_BASE/etc/profile.d/conda.sh" ]]; then
  echo "ERROR: Conda initialization script not found under $CONDA_BASE." >&2
  exit 1
fi

CONDA_ENVS_DIR="${CONDA_ENVS_DIR:-$CONDA_BASE/envs}"
export CONDA_ENVS_PATH="$CONDA_ENVS_DIR"
export CONDA_PKGS_DIRS="${CONDA_PKGS_DIRS:-$CONDA_BASE/pkgs}"
source "$CONDA_BASE/etc/profile.d/conda.sh"
set +u
conda activate "$CONDA_ENVS_DIR/meti_env"
set -u

NEXTFLOW_BIN="${NEXTFLOW_BIN:-nextflow}"
if ! command -v "$NEXTFLOW_BIN" >/dev/null 2>&1; then
  echo "ERROR: Nextflow not found; set NEXTFLOW_BIN or add it to PATH." >&2
  exit 1
fi

TAXONOMY_DIR="$HAMLET/assets/taxonomy"
CASCADIA_MODEL="$HAMLET/assets/cascadia.ckpt"
for reference in \
  "$TAXONOMY_DIR/nodes.dmp" \
  "$TAXONOMY_DIR/names.dmp" \
  "$CASCADIA_MODEL" \
  "$HAMLET/assets/casanovo_cpu.config"; do
  if [[ ! -r "$reference" || ! -s "$reference" ]]; then
    echo "ERROR: Missing reference: $reference" >&2
    exit 1
  fi
done

for env_name in meti_env casanovo_env cascadia_env search_env; do
  if [[ ! -d "$CONDA_ENVS_DIR/$env_name" ]]; then
    echo "ERROR: Conda environment not found: $CONDA_ENVS_DIR/$env_name" >&2
    exit 1
  fi
done

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "ERROR: Export OPENROUTER_API_KEY before running full mode." >&2
  exit 1
fi
export OPENROUTER_API_KEY
export NXF_ANSI_LOG=false

cd "$RUN_DIR"
"$NEXTFLOW_BIN" -log "$RUN_DIR/nextflow.log" run "$HAMLET/main.nf" \
  -profile roar_basic \
  -c "$JOB_ROOT/jet2_cpu.config" \
  -w "$RUN_DIR/work" \
  --pxd "$PXD" \
  --outdir "$RUN_DIR/results" \
  --central_mzml_dir "$CENTRAL_MZML_DIR" \
  --mode full \
  --run_llm_extraction true \
  --conda_base "$CONDA_BASE" \
  --conda_init "source $CONDA_BASE/etc/profile.d/conda.sh || true" \
  --meti_env_path "$CONDA_ENVS_DIR/meti_env" \
  --casanovo_env_path "$CONDA_ENVS_DIR/casanovo_env" \
  --cascadia_env_path "$CONDA_ENVS_DIR/cascadia_env" \
  --search_env_path "$CONDA_ENVS_DIR/search_env" \
  --casanovo_config_path "$HAMLET/assets/casanovo_cpu.config" \
  --taxonomy_dir "$TAXONOMY_DIR" \
  --cascadia_model_path "$CASCADIA_MODEL" \
  --stage_manifest "$RUN_DIR/results/pipeline_stage_manifest.json" \
  -resume

python "$JOB_ROOT/verify_aggregate.py" \
  "$RUN_DIR/results/$PXD/${PXD}_aggregated_results.json" \
  --pxd "$PXD" \
  --require runAssessor organism_identification.results modification_site_fractions
