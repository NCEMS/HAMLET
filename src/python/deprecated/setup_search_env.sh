#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_NAME="${ENV_NAME:-search_env}"
ENV_YML="${ENV_YML:-$ROOT_DIR/data/search_env_environment.yml}"

if [[ -n "${CONDA_EXE:-}" ]]; then
  CONDA_BIN="$CONDA_EXE"
else
  CONDA_BIN="conda"
fi

if ! command -v "$CONDA_BIN" >/dev/null 2>&1; then
  echo "ERROR: conda not found on PATH (or CONDA_EXE not set)." >&2
  echo "Hint: export CONDA_EXE=/home/ians/miniconda3/bin/conda" >&2
  exit 1
fi

if [[ ! -f "$ENV_YML" ]]; then
  echo "ERROR: env spec not found: $ENV_YML" >&2
  exit 1
fi

CONDA_BASE="$($CONDA_BIN info --base)"
# shellcheck disable=SC1091
source "$CONDA_BASE/etc/profile.d/conda.sh"

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Updating conda env: $ENV_NAME"
  conda env update -n "$ENV_NAME" -f "$ENV_YML" --prune
else
  echo "Creating conda env: $ENV_NAME"
  conda env create -n "$ENV_NAME" -f "$ENV_YML"
fi

conda activate "$ENV_NAME"

ENV_PREFIX="$CONDA_PREFIX"
INSTALL_ROOT="$ENV_PREFIX/opt/search_tools"
mkdir -p "$INSTALL_ROOT" "$ENV_PREFIX/etc/conda/activate.d"

# Optional: FragPipe is distributed as a large zip (often via the NesviLab site).
# To install it here, set:
#   INSTALL_FRAGPIPE=1
#   FRAGPIPE_ZIP=/path/to/FragPipe.zip   (or a direct URL in FRAGPIPE_URL)
INSTALL_FRAGPIPE="${INSTALL_FRAGPIPE:-0}"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $1" >&2
    exit 1
  fi
}

need_cmd curl
need_cmd tar
need_cmd unzip

# -------------------------
# SAGE
# -------------------------
SAGE_VERSION="0.14.7"
SAGE_DIR="$INSTALL_ROOT/sage"
SAGE_URL="https://github.com/lazear/sage/releases/download/v${SAGE_VERSION}/sage-v${SAGE_VERSION}-x86_64-unknown-linux-gnu.tar.gz"

if [[ ! -x "$SAGE_DIR/sage" ]]; then
  echo "Installing SAGE v${SAGE_VERSION} -> $SAGE_DIR"
  rm -rf "$SAGE_DIR"
  mkdir -p "$SAGE_DIR"
  tmpdir="$(mktemp -d)"
  curl -L --fail -o "$tmpdir/sage.tar.gz" "$SAGE_URL"
  tar -xzf "$tmpdir/sage.tar.gz" -C "$SAGE_DIR" --strip-components=1
  chmod +x "$SAGE_DIR/sage"
  rm -rf "$tmpdir"
fi
ln -sf "$SAGE_DIR/sage" "$ENV_PREFIX/bin/sage"

# -------------------------
# PTM-Shepherd
# -------------------------
PTMS_DIR="$INSTALL_ROOT/ptmshepherd"
PTMS_JAR="$PTMS_DIR/ptmshepherd.jar"
PTMS_URL="https://github.com/Nesvilab/PTM-Shepherd/releases/latest/download/ptmshepherd-2.0.5_CLI.jar"

if [[ ! -f "$PTMS_JAR" ]]; then
  echo "Installing PTM-Shepherd jar -> $PTMS_JAR"
  mkdir -p "$PTMS_DIR"
  curl -L --fail -o "$PTMS_JAR" "$PTMS_URL"
fi

# -------------------------
# dotnet (for DIA-NN .raw support)
# -------------------------
DOTNET_DIR="$INSTALL_ROOT/dotnet"
mkdir -p "$DOTNET_DIR"
if ! command -v dotnet >/dev/null 2>&1; then
  echo "Installing dotnet 8.0 SDK -> $DOTNET_DIR"
  tmpdir="$(mktemp -d)"
  curl -L --fail -o "$tmpdir/dotnet-install.sh" https://dot.net/v1/dotnet-install.sh
  chmod +x "$tmpdir/dotnet-install.sh"
  "$tmpdir/dotnet-install.sh" --channel 8.0 --install-dir "$DOTNET_DIR"
  rm -rf "$tmpdir"
else
  echo "dotnet already on PATH; skipping dotnet install"
fi

# -------------------------
# DIA-NN
# -------------------------
DIANN_DIR="$INSTALL_ROOT/diann"
DIANN_URL="https://github.com/vdemichev/DiaNN/releases/download/2.0/DIA-NN-2.2.0-Academia-Linux.zip"

if [[ ! -x "$DIANN_DIR/diann" ]]; then
  echo "Installing DIA-NN 2.2.0 -> $DIANN_DIR"
  rm -rf "$DIANN_DIR"
  mkdir -p "$DIANN_DIR"
  tmpdir="$(mktemp -d)"
  curl -L --fail -o "$tmpdir/diann.zip" "$DIANN_URL"
  unzip -q "$tmpdir/diann.zip" -d "$tmpdir/diann_unzipped"

  # The ZIP typically contains a diann-2.2.0 directory with the binary + shared libs.
  diann_bin="$(find "$tmpdir/diann_unzipped" -maxdepth 5 -type f -name 'diann-*' ! -name '*.dll' | head -1)"
  if [[ -z "$diann_bin" ]]; then
    echo "ERROR: could not locate DIA-NN binary after unzip" >&2
    find "$tmpdir/diann_unzipped" -maxdepth 3 -type f | head -50 >&2
    exit 1
  fi

  diann_parent="$(dirname "$diann_bin")"
  # Copy the full bundle to preserve any needed shared libraries.
  cp -a "$diann_parent"/. "$DIANN_DIR"/

  # Create a stable entrypoint inside the bundle.
  installed_bin="$(ls "$DIANN_DIR"/diann-* 2>/dev/null | grep -v '\.dll' | head -1)"
  if [[ -z "$installed_bin" ]]; then
    echo "ERROR: DIA-NN binary not found after copying bundle" >&2
    ls -la "$DIANN_DIR" >&2 || true
    exit 1
  fi
  chmod +x "$installed_bin" || true
  ln -sf "$installed_bin" "$DIANN_DIR/diann"
  rm -rf "$tmpdir"
fi
ln -sf "$DIANN_DIR/diann" "$ENV_PREFIX/bin/diann"

# -------------------------
# FragPipe (optional)
# -------------------------
FRAGPIPE_DIR="$INSTALL_ROOT/fragpipe"
if [[ "$INSTALL_FRAGPIPE" == "1" ]]; then
  echo "Installing FragPipe -> $FRAGPIPE_DIR"
  rm -rf "$FRAGPIPE_DIR"
  mkdir -p "$FRAGPIPE_DIR"
  tmpdir="$(mktemp -d)"
  if [[ -n "${FRAGPIPE_ZIP:-}" && -f "$FRAGPIPE_ZIP" ]]; then
    cp -f "$FRAGPIPE_ZIP" "$tmpdir/fragpipe.zip"
  elif [[ -n "${FRAGPIPE_URL:-}" ]]; then
    curl -L --fail -o "$tmpdir/fragpipe.zip" "$FRAGPIPE_URL"
  else
    echo "ERROR: set FRAGPIPE_ZIP (local zip) or FRAGPIPE_URL (direct download URL)" >&2
    exit 1
  fi
  unzip -q "$tmpdir/fragpipe.zip" -d "$FRAGPIPE_DIR"
  rm -rf "$tmpdir"
else
  echo "FragPipe install skipped (set INSTALL_FRAGPIPE=1 to enable)"
fi

# -------------------------
# Conda activation env vars
# -------------------------
ACTIVATE_D="$ENV_PREFIX/etc/conda/activate.d"
mkdir -p "$ACTIVATE_D"
cat > "$ACTIVATE_D/search_env_vars.sh" <<EOF
export SAGE_HOME="$SAGE_DIR"
export DIANN_HOME="$DIANN_DIR"
export PTMSHEPHERD_HOME="$PTMS_DIR"
export PTMSHEPHERD_JAR="$PTMS_JAR"
export DOTNET_ROOT="$DOTNET_DIR"
export PATH="\$DOTNET_ROOT:\$PATH"
export FRAGPIPE_HOME="$FRAGPIPE_DIR"
EOF

echo "OK: search_env ready"
echo "- python: $(command -v python)"
echo "- sage:   $(command -v sage)"
echo "- diann:  $(command -v diann)"
echo "- java:   $(command -v java || true)"
echo "- dotnet: $(command -v dotnet || true)"
