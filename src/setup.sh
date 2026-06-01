#!/bin/bash
set -euo pipefail

# HAMLET annotator Pipeline - Container-Free Setup
# This script sets up the complete environment to run the HAMLET annotator pipeline
# Requirements: Linux, curl or wget
# Usage: bash src/setup.sh

echo "================================"
echo "HAMLET annotator Pipeline Setup"
echo "================================"

# API KEYS
# API KEYS — set these in your shell environment, not here.
# export OPENAI_API_KEY="sk-..."
# export LLM_API_KEY="sk-..."

# Configuration
CONDA_PREFIX="${HOME}/miniconda3"
MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
INSTALL_DIR="${TMPDIR:-/tmp}/miniconda_installer"

# Get project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ============================================
# Step 1: Check if conda is available
# ============================================
if command -v conda &> /dev/null; then
    echo "✓ Conda found: $(conda --version)"
else
    echo "ℹ Conda not found. Installing Miniconda..."
    
    # Create install directory
    mkdir -p "$INSTALL_DIR"
    INSTALLER_PATH="$INSTALL_DIR/Miniconda3-latest-Linux-x86_64.sh"
    
    # Download Miniconda
    if command -v curl &> /dev/null; then
        curl -L "$MINICONDA_URL" -o "$INSTALLER_PATH"
    elif command -v wget &> /dev/null; then
        wget -O "$INSTALLER_PATH" "$MINICONDA_URL"
    else
        echo "ERROR: curl or wget required to download Miniconda" >&2
        exit 1
    fi
    
    # Install Miniconda
    bash "$INSTALLER_PATH" -b -p "$CONDA_PREFIX"
    rm -f "$INSTALLER_PATH"
    
    # Initialize conda
    "$CONDA_PREFIX/bin/conda" init bash >/dev/null 2>&1 || true
    
    echo "✓ Miniconda installed to: $CONDA_PREFIX"
    echo "  Run: source ~/.bashrc"
    echo "  Then: bash src/setup.sh"
    exit 0
fi

# ============================================
# Step 2: Source conda environment
# ============================================
# Detect actual conda installation location (handles system-wide installs like Cyverse)
CONDA_PREFIX="$(conda info --base)"
if [[ ! -f "$CONDA_PREFIX/etc/profile.d/conda.sh" ]]; then
    echo "ERROR: Conda found but conda.sh not at $CONDA_PREFIX/etc/profile.d/conda.sh" >&2
    exit 1
fi

source "$CONDA_PREFIX/etc/profile.d/conda.sh"
echo "✓ Conda initialized: $CONDA_PREFIX"

# ============================================
# Step 3: Create/Update Conda Environments
# ============================================
create_or_update_env() {
    local env_file="$1"
    local env_name="$2"
    
    if conda env list | awk '{print $1}' | grep -Fxq "$env_name"; then
        echo "  Updating: $env_name"
        conda env update -n "$env_name" -f "$env_file" --prune -q
    else
        echo "  Creating: $env_name"
        conda env create -f "$env_file" -q
    fi
}

echo ""
echo "✓ Setting up conda environments:"
create_or_update_env "$PROJECT_ROOT/src/conda_envs/meti_env.yml" "meti_env"
create_or_update_env "$PROJECT_ROOT/src/conda_envs/search_env.yml" "search_env"
create_or_update_env "$PROJECT_ROOT/src/conda_envs/cascadia_env.yml" "cascadia_env"
create_or_update_env "$PROJECT_ROOT/src/conda_envs/casanovo_env.yml" "casanovo_env"

# casanovoBolt uses relative imports from a 'data' subpackage that lives in the
# installed casanovo package.  Symlink it into the source tree so the import
# 'from .data.psm import PepSpecMatch' resolves correctly at runtime.
CASANOVO_DATA="$(conda run -n casanovo_env python -c \
    'import casanovo, os; print(os.path.join(os.path.dirname(casanovo.__file__), "data"))' 2>/dev/null || echo "")"
if [ -n "$CASANOVO_DATA" ] && [ -d "$CASANOVO_DATA" ]; then
    ln -sfn "$CASANOVO_DATA" "$PROJECT_ROOT/src/casanovoBolt/data"
    echo "✓ Linked casanovo data package into casanovoBolt"
else
    echo "⚠ Could not locate installed casanovo data package; casanovoBolt may fail to import"
fi

# ============================================
# Step 4: Install Search Tools
# ============================================
echo ""
echo "✓ Installing search tools (SAGE, PTM-Shepherd, Fragpipe/MSFragger, DIA-NN)..."

# Install search tools in search_env
SEARCH_ENV_PATH="$(conda run -n search_env python -c 'import sys; print(sys.prefix)')"
echo ""
echo "Installing search tools in search_env..."
if ! bash "$PROJECT_ROOT/src/bash/install_search_tools.sh" "$SEARCH_ENV_PATH"; then
    echo ""
    echo "⚠ Warning: Some search tools failed to install in search_env."
    echo "  This may be OK if you don't need those specific tools."
    echo "  See README.md for manual installation instructions."
    echo ""
fi

# Also install in meti_env for backwards compatibility
METI_ENV_PATH="$(conda run -n meti_env python -c 'import sys; print(sys.prefix)')"
echo ""
echo "Installing search tools in meti_env for backwards compatibility..."
if ! bash "$PROJECT_ROOT/src/bash/install_search_tools.sh" "$METI_ENV_PATH"; then
    echo ""
    echo "⚠ Warning: Some search tools failed to install in meti_env."
    echo "  This may be OK if you don't need those specific tools."
    echo "  See README.md for manual installation instructions."
    echo ""
fi

# ============================================
# Step 5: Check Cascadia Model
# ============================================
CASCADIA_MODEL_PATH="${PROJECT_ROOT}/assets/cascadia.ckpt"
echo ""
echo "Checking for Cascadia model..."

if [ -f "$CASCADIA_MODEL_PATH" ]; then
    CASCADIA_SIZE=$(du -h "$CASCADIA_MODEL_PATH" | cut -f1)
    echo "✓ Found Cascadia model at: $CASCADIA_MODEL_PATH ($CASCADIA_SIZE)"
else
    echo "⚠ Cascadia model not found at: $CASCADIA_MODEL_PATH"
    echo ""
    echo "  Required for DIA peptide identification (organism_id process)"
    echo ""
    echo "  Download from Google Drive:"
    echo "  → https://drive.google.com/drive/folders/1UTrZIrCdUqYqscbqga_KdX8kc8ZjMMfr?usp=sharing"
    echo ""
    echo "  Setup instructions:"
    echo "    1. Visit the link above"
    echo "    2. Download cascadia.ckpt (558 MB)"
    echo "    3. Place in repo: mv ~/Downloads/cascadia.ckpt ${PROJECT_ROOT}/assets/"
    echo ""
    echo "  Note: The file is gitignored (too large for GitHub)"
    echo "  After downloading, the pipeline will automatically find it at:"
    echo "  ${PROJECT_ROOT}/assets/cascadia.ckpt"
    echo ""

    pip install gdown
    echo "Attempting to download Cascadia model with gdown..."
    gdown "1G4lkGajGtFEz0dzbrovla6LJ5EUyx8hP" -O "${PROJECT_ROOT}/assets/cascadia.ckpt" || {
        echo ""
        echo "ERROR: Failed to download Cascadia model with gdown."
        echo "Please download manually from the link above and place it in ${PROJECT_ROOT}/assets/"
        exit 1
    }
fi

# ============================================
# Step 6: GPU Setup and Validation
# ============================================
echo ""
echo "Checking for NVIDIA GPU..."

# Detect NVIDIA GPU presence via lspci or existing device nodes
GPU_PRESENT=false
if command -v lspci &>/dev/null && lspci 2>/dev/null | grep -qi nvidia; then
    GPU_PRESENT=true
    GPU_INFO=$(lspci 2>/dev/null | grep -i nvidia | head -1)
    echo "✓ NVIDIA GPU detected: $GPU_INFO"
elif [ -e /dev/nvidia0 ]; then
    GPU_PRESENT=true
    echo "✓ NVIDIA GPU device node found (/dev/nvidia0)"
fi

if [ "$GPU_PRESENT" = true ]; then
    # Check whether the required kernel modules are already loaded
    MODULES_LOADED=false
    if lsmod 2>/dev/null | grep -q "^nvidia "; then
        MODULES_LOADED=true
        echo "✓ NVIDIA kernel modules already loaded"
    else
        echo "  NVIDIA kernel modules not loaded — attempting to load..."

        # Determine if we have passwordless sudo; if not, prompt once
        HAS_SUDO=false
        if sudo -n true 2>/dev/null; then
            HAS_SUDO=true
        elif sudo true 2>/dev/null; then
            HAS_SUDO=true
        else
            echo "  ⚠ Cannot load NVIDIA modules: sudo access unavailable."
            echo "    Run manually after setup:"
            echo "      sudo modprobe nvidia nvidia_uvm nvidia_drm"
            echo "    Then re-run this script to complete GPU validation."
        fi

        if [ "$HAS_SUDO" = true ]; then
            LOAD_OK=true
            for mod in nvidia nvidia_uvm nvidia_drm; do
                if sudo modprobe "$mod" 2>/dev/null; then
                    : # module loaded silently
                else
                    echo "  ⚠ Failed to load kernel module: $mod"
                    LOAD_OK=false
                fi
            done

            if [ "$LOAD_OK" = true ]; then
                MODULES_LOADED=true
                echo "✓ NVIDIA kernel modules loaded: nvidia, nvidia_uvm, nvidia_drm"

                # Persist modules across reboots
                MODULES_CONF="/etc/modules-load.d/nvidia.conf"
                if [ ! -f "$MODULES_CONF" ] || ! grep -q "nvidia_uvm" "$MODULES_CONF" 2>/dev/null; then
                    printf 'nvidia\nnvidia_uvm\nnvidia_drm\n' | sudo tee "$MODULES_CONF" >/dev/null
                    echo "✓ NVIDIA modules configured to load on boot ($MODULES_CONF)"
                else
                    echo "✓ NVIDIA boot persistence already configured ($MODULES_CONF)"
                fi
            fi
        fi
    fi

    # Verify device nodes exist after module load
    if [ "$MODULES_LOADED" = true ]; then
        if ls /dev/nvidia0 &>/dev/null; then
            echo "✓ NVIDIA device nodes present: $(ls /dev/nvidia* 2>/dev/null | tr '\n' ' ')"
        else
            echo "  ⚠ NVIDIA modules loaded but /dev/nvidia0 not present."
            echo "    Try: sudo nvidia-smi   (this can trigger device-node creation)"
        fi
    fi

    # ---- casanovo_env: PyTorch CUDA check ----
    echo ""
    echo "  Checking PyTorch CUDA in casanovo_env..."
    CASANOVO_CUDA=$(conda run -n casanovo_env python -c \
        "import torch; print('available' if torch.cuda.is_available() else 'not_available')" \
        2>/dev/null || echo "error")
    if [ "$CASANOVO_CUDA" = "available" ]; then
        GPU_NAME=$(conda run -n casanovo_env python -c \
            "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null || echo "unknown")
        GPU_MEM=$(conda run -n casanovo_env python -c \
            "import torch; print(torch.cuda.get_device_properties(0).total_memory // 1024**3)" \
            2>/dev/null || echo "?")
        echo "  ✓ casanovo_env: CUDA available — $GPU_NAME (${GPU_MEM} GB)"
    else
        echo "  ⚠ casanovo_env: CUDA not available — casanovo will use CPU (slower)."
        if [ "$MODULES_LOADED" = true ]; then
            TORCH_CUDA_VER=$(conda run -n casanovo_env python -c \
                "import torch; print(torch.version.cuda)" 2>/dev/null || echo "unknown")
            echo "    Modules are loaded but PyTorch reports no CUDA (torch.version.cuda=$TORCH_CUDA_VER)."
            echo "    The PyTorch build may not match the installed driver CUDA version."
            echo "    Reinstall PyTorch matching driver CUDA: https://pytorch.org/get-started/locally/"
        fi
    fi

    # ---- cascadia_env: PyTorch CUDA check ----
    echo "  Checking PyTorch CUDA in cascadia_env..."
    CASCADIA_CUDA=$(conda run -n cascadia_env python -c \
        "import torch; print('available' if torch.cuda.is_available() else 'not_available')" \
        2>/dev/null || echo "error")
    if [ "$CASCADIA_CUDA" = "available" ]; then
        echo "  ✓ cascadia_env: CUDA available"
    elif [ "$CASCADIA_CUDA" = "not_available" ]; then
        echo "  ⚠ cascadia_env: CUDA not available — cascadia will use CPU (slower)."
    else
        echo "  ⚠ cascadia_env: could not import torch (env may not include PyTorch)."
    fi
else
    echo "  No NVIDIA GPU detected — pipeline will run CPU-only."
    echo "  casanovo and cascadia de-novo sequencing will use CPU (slower inference)."
fi

# ============================================
# Step 7: Final Checks & Instructions
# ============================================
echo ""
echo "✓ Setup complete!"
echo ""
echo "Installed environments:"
echo "  - search_env      (SAGE, PTM-Shepherd, Fragpipe/MSFragger, DIA-NN, Nextflow)"
echo "  - meti_env        (core analysis tools + Nextflow)"
echo "  - cascadia_env    (DIA peptide identification)"
echo "  - casanovo_env    (DDA de novo sequencing)"
echo ""
echo "Available search tools (in search_env or meti_env):"
echo "  - sage            (SAGE)"
echo "  - ptm_shepherd    (PTM-Shepherd)"
echo "  - fragpipe        (Fragpipe)"
echo "  - msfragger       (MSFragger)"
echo "  - diann           (DIA-NN)"
echo ""
echo "Next steps:"
echo "  1. Activate search_env: conda activate search_env"
echo "  2. Verify installations: sage --version && fragpipe --help && diann --help"
echo ""
echo "For pipeline execution:"
echo "  1. Activate environment: conda activate meti_env"
echo "  2. (Optional) Set search tool environment variables:"
echo "     source <(conda run -n search_env env | grep -E 'SAGE_|PTMSHEPHERD_|FRAGPIPE_|DIANN_|DOTNET_')"
echo "  3. Run pipeline: nextflow run main.nf --pxd PXD003539 -resume"
echo ""
echo "For more information, see:"
echo "  - README.md - Project overview & setup guide"
echo "  - EXAMPLE.sh - Example pipeline invocations"

