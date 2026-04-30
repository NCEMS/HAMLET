#!/bin/bash
# ============================================================================
# HAMLET annotator Search Tools Installation Script
# Installs SAGE, PTM-Shepherd, DIA-NN, Fragpipe, MSFragger, and dotnet
# for the HAMLET annotator pipeline and search_env conda environment
# 
# Usage:
#   ./install_search_tools.sh <conda_env_path> [--all|--search-env]
#   Example: ./install_search_tools.sh $CONDA_PREFIX
#            ./install_search_tools.sh $CONDA_PREFIX --all
# 
# This script downloads and configures search tools that are not available
# as standard conda packages. It mirrors the installation from the 
# meti-unified container and supports both meti_env and search_env.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Get conda env path from argument or use current environment
CONDA_ENV_PATH="${1:-.}"
INSTALL_ROOT="${CONDA_ENV_PATH}/opt/search_tools"
INSTALL_MODE="${2:-}"

echo "=========================================="
echo "HAMLET annotator Search Tools Installation"
echo "=========================================="
echo "Installation root: $INSTALL_ROOT"
echo "Conda env path:    $CONDA_ENV_PATH"
echo ""

# Create installation directories
mkdir -p "$INSTALL_ROOT"
mkdir -p "$CONDA_ENV_PATH/tmp/matplotlib"
mkdir -p "$CONDA_ENV_PATH/tmp/numba_cache"

# ============================================================================
# Install SAGE v0.14.7
# Cross-linked peptide database search tool
# ============================================================================
install_sage() {
    local SAGE_VERSION="0.14.7"
    local SAGE_DIR="$INSTALL_ROOT/sage"
    local SAGE_URL="https://github.com/lazear/sage/releases/download/v${SAGE_VERSION}/sage-v${SAGE_VERSION}-x86_64-unknown-linux-gnu.tar.gz"
    
    echo "--- Installing SAGE v${SAGE_VERSION} ---"
    
    if [ -f "$SAGE_DIR/sage" ]; then
        echo "✓ SAGE already installed at $SAGE_DIR/sage"
        return 0
    fi
    
    mkdir -p "$SAGE_DIR"
    local tmpdir
    tmpdir="$(mktemp -d)"
    trap "rm -rf '$tmpdir'" RETURN
    
    echo "  Downloading SAGE v${SAGE_VERSION}..."
    if ! curl -L --fail --progress-bar -o "$tmpdir/sage.tar.gz" "$SAGE_URL"; then
        echo "✗ Failed to download SAGE"
        return 1
    fi
    
    echo "  Extracting..."
    tar -xzf "$tmpdir/sage.tar.gz" -C "$SAGE_DIR" --strip-components=1
    chmod +x "$SAGE_DIR/sage"
    
    # Create symlink in conda bin
    ln -sf "$SAGE_DIR/sage" "$CONDA_ENV_PATH/bin/sage"
    
    echo "✓ SAGE installed successfully"
    "$SAGE_DIR/sage" --version 2>/dev/null || true
}

# ============================================================================
# Install PTM-Shepherd v2.0.5
# PTM analysis and localization tool
# ============================================================================
install_ptm_shepherd() {
    local PTMS_DIR="$INSTALL_ROOT/ptmshepherd"
    local PTMS_JAR="$PTMS_DIR/ptmshepherd.jar"
    local PTMS_VERSION="2.0.5"
    local PTMS_URL="https://github.com/Nesvilab/PTM-Shepherd/releases/download/v${PTMS_VERSION}/ptmshepherd-${PTMS_VERSION}_CLI.jar"
    
    echo "--- Installing PTM-Shepherd v2.0.5 ---"
    
    if [ -f "$PTMS_JAR" ]; then
        echo "✓ PTM-Shepherd already installed at $PTMS_JAR"
        return 0
    fi
    
    mkdir -p "$PTMS_DIR"
    
    echo "  Downloading PTM-Shepherd JAR..."
    if ! curl -L --fail --progress-bar -o "$PTMS_JAR" "$PTMS_URL"; then
        echo "✗ Failed to download PTM-Shepherd JAR"
        return 1
    fi
    
    chmod +r "$PTMS_JAR"
    ls -lh "$PTMS_JAR"
    echo "✓ PTM-Shepherd installed successfully"
}

# ============================================================================
# Install Fragpipe with MSFragger
# Integrated proteomics analysis platform
# ============================================================================
install_fragpipe() {
    local FRAGPIPE_DIR="$INSTALL_ROOT/fragpipe"
    # Try multiple URL patterns for Fragpipe - releases may have different naming
    local FRAGPIPE_VERSION="20.0"
    local FRAGPIPE_URLS=(
        "https://github.com/Nesvilab/FragPipe/releases/download/v${FRAGPIPE_VERSION}/FragPipe-${FRAGPIPE_VERSION}.zip"
        "https://github.com/Nesvilab/FragPipe/releases/download/${FRAGPIPE_VERSION}/FragPipe-${FRAGPIPE_VERSION}.zip"
        "https://github.com/Nesvilab/FragPipe/releases/latest/download/FragPipe-21.0.zip"
    )
    
    echo "--- Installing Fragpipe with MSFragger ---"
    
    if [ -f "$FRAGPIPE_DIR/bin/fragpipe" ] || [ -L "$CONDA_ENV_PATH/bin/fragpipe" ]; then
        echo "✓ Fragpipe already installed at $FRAGPIPE_DIR"
        return 0
    fi
    
    mkdir -p "$FRAGPIPE_DIR"
    local tmpdir
    tmpdir="$(mktemp -d)"
    trap "rm -rf '$tmpdir'" RETURN
    
    # Try each URL until one works
    local FRAGPIPE_URL=""
    local success=0
    
    for url in "${FRAGPIPE_URLS[@]}"; do
        echo "  Attempting to download Fragpipe from: $url"
        if curl -L --fail --progress-bar -o "$tmpdir/fragpipe.zip" "$url" 2>/dev/null; then
            FRAGPIPE_URL="$url"
            success=1
            break
        fi
    done
    
    if [ $success -eq 0 ]; then
        echo "⚠ Could not download Fragpipe from any known release URL"
        echo "  You can manually install Fragpipe from: https://github.com/Nesvilab/FragPipe/releases"
        echo "  Or install from bioconda: conda install -c bioconda fragpipe"
        return 1
    fi
    
    echo "  Extracting Fragpipe..."
    unzip -q "$tmpdir/fragpipe.zip" -d "$tmpdir"
    
    # Find the extracted FragPipe directory (may be fragpipe, FragPipe, or versioned variants)
    local fragpipe_src
    fragpipe_src="$(find "$tmpdir" -maxdepth 2 -type d \( -name 'fragpipe' -o -name 'FragPipe' -o -name 'FragPipe-*' -o -name 'fragpipe-*' \) | head -1)"
    
    if [ -z "${fragpipe_src:-}" ] || [ ! -d "${fragpipe_src:-}" ]; then
        echo "⚠ Fragpipe extraction failed or directory structure unexpected"
        ls -la "$tmpdir" || true
        return 1
    fi
    
    # Copy Fragpipe to install location
    cp -r "$fragpipe_src"/* "$FRAGPIPE_DIR/"
    
    # Create symlinks for main tools (check for both fragpipe and fragpipe.sh)
    if [ -f "$FRAGPIPE_DIR/bin/fragpipe" ]; then
        chmod +x "$FRAGPIPE_DIR/bin/fragpipe"
        ln -sf "$FRAGPIPE_DIR/bin/fragpipe" "$CONDA_ENV_PATH/bin/fragpipe"
    elif [ -f "$FRAGPIPE_DIR/bin/fragpipe.sh" ]; then
        chmod +x "$FRAGPIPE_DIR/bin/fragpipe.sh"
        ln -sf "$FRAGPIPE_DIR/bin/fragpipe.sh" "$CONDA_ENV_PATH/bin/fragpipe"
    fi
    
    # MSFragger JAR is typically bundled with Fragpipe
    if [ -f "$FRAGPIPE_DIR/tools/MSFragger.jar" ]; then
        chmod +r "$FRAGPIPE_DIR/tools/MSFragger.jar"
        # Create wrapper script for direct MSFragger access
        cat > "$CONDA_ENV_PATH/bin/msfragger" << 'EOF'
#!/bin/bash
exec java -jar "$(dirname "$0")/../opt/search_tools/fragpipe/tools/MSFragger.jar" "$@"
EOF
        chmod +x "$CONDA_ENV_PATH/bin/msfragger"
    fi
    
    echo "✓ Fragpipe installed successfully"
    [ -f "$FRAGPIPE_DIR/bin/fragpipe.sh" ] && echo "  ✓ fragpipe command available" || true
    [ -f "$CONDA_ENV_PATH/bin/msfragger" ] && echo "  ✓ msfragger command available" || true
}

# ============================================================================
# Install dotnet 8.0 SDK
# Required runtime for DIA-NN
# ============================================================================
install_dotnet() {
    local DOTNET_DIR="$INSTALL_ROOT/dotnet"
    
    echo "--- Installing dotnet 8.0 SDK ---"
    
    if [ -f "$DOTNET_DIR/dotnet" ]; then
        echo "✓ dotnet already installed at $DOTNET_DIR/dotnet"
        "$DOTNET_DIR/dotnet" --version 2>/dev/null || true
        return 0
    fi
    
    mkdir -p "$DOTNET_DIR"
    local tmpdir
    tmpdir="$(mktemp -d)"
    trap "rm -rf '$tmpdir'" RETURN
    
    echo "  Downloading dotnet install script..."
    if ! curl -L --fail --progress-bar -o "$tmpdir/dotnet-install.sh" https://dot.net/v1/dotnet-install.sh; then
        echo "✗ Failed to download dotnet installer"
        return 1
    fi
    
    chmod +x "$tmpdir/dotnet-install.sh"
    echo "  Installing dotnet (this may take a few minutes)..."
    
    if ! "$tmpdir/dotnet-install.sh" --channel 8.0 --install-dir "$DOTNET_DIR"; then
        echo "✗ Failed to install dotnet"
        return 1
    fi
    
    # Create symlink in conda bin
    ln -sf "$DOTNET_DIR/dotnet" "$CONDA_ENV_PATH/bin/dotnet"
    
    echo "✓ dotnet installed successfully"
    "$DOTNET_DIR/dotnet" --version 2>/dev/null || true
}

# ============================================================================
# Install DIA-NN v2.2.0
# Data-independent acquisition search tool
# ============================================================================
install_diann() {
    local DIANN_DIR="$INSTALL_ROOT/diann"
    local DIANN_VERSION="2.2.0"
    # Try multiple URL patterns - the correct tag for v2.2.0 is "2.0" (not version-matched)
    local DIANN_URLS=(
        "https://github.com/vdemichev/DiaNN/releases/download/2.0/DIA-NN-${DIANN_VERSION}-Academia-Linux.zip"
        "https://github.com/vdemichev/DiaNN/releases/download/v${DIANN_VERSION}/DIA-NN-${DIANN_VERSION}-Academia-Linux.zip"
        "https://github.com/vdemichev/DiaNN/releases/download/${DIANN_VERSION}/DIA-NN-${DIANN_VERSION}-Academia-Linux.zip"
        "https://github.com/vdemichev/DiaNN/releases/latest/download/DIA-NN-Academia-Linux.zip"
    )
    
    echo "--- Installing DIA-NN v2.2.0 ---"
    
    if [ -f "$DIANN_DIR/diann" ] || [ -L "$CONDA_ENV_PATH/bin/diann" ]; then
        echo "✓ DIA-NN already installed"
        ls -lh "$DIANN_DIR" 2>/dev/null | head -3 || true
        return 0
    fi
    
    mkdir -p "$DIANN_DIR"
    local tmpdir
    tmpdir="$(mktemp -d)"
    trap "rm -rf '$tmpdir'" RETURN
    
    # Try each URL until one works
    local DIANN_URL=""
    local success=0
    
    for url in "${DIANN_URLS[@]}"; do
        echo "  Attempting to download DIA-NN from: $url"
        if curl -L --fail --progress-bar -o "$tmpdir/diann.zip" "$url" 2>/dev/null; then
            DIANN_URL="$url"
            success=1
            break
        fi
    done
    
    if [ $success -eq 0 ]; then
        echo "⚠ Could not download DIA-NN from any known release URL"
        echo "  You can manually download from: https://github.com/vdemichev/DiaNN/releases"
        echo "  Or check the bioconda package: conda search -c bioconda diann"
        return 1
    fi
    
    echo "  Extracting..."
    unzip -q "$tmpdir/diann.zip" -d "$tmpdir/diann_unzipped" || true
    
    # Find and extract the main binary
    local diann_bin
    diann_bin="$(find "$tmpdir/diann_unzipped" -maxdepth 5 -type f -name 'diann-*' ! -name '*.dll' ! -name '*.so' | head -1)"
    
    if [ -n "${diann_bin:-}" ]; then
        local diann_parent
        diann_parent="$(dirname "$diann_bin")"
        cp -a "$diann_parent"/. "$DIANN_DIR"/
        
        local installed_bin
        installed_bin="$(find "$DIANN_DIR" -maxdepth 1 -type f -name 'diann-*' ! -name '*.dll' ! -name '*.so' | head -1)"
        
        if [ -n "${installed_bin:-}" ]; then
            chmod +x "$installed_bin" || true
            ln -sf "$installed_bin" "$DIANN_DIR/diann"
            ln -sf "$DIANN_DIR/diann" "$CONDA_ENV_PATH/bin/diann"
            echo "✓ DIA-NN installed successfully"
            ls -lh "$DIANN_DIR/diann" 2>/dev/null || true
        else
            echo "⚠ DIA-NN binary found but could not locate executable"
            ls -lh "$DIANN_DIR" 2>/dev/null | head -5 || true
        fi
    else
        echo "⚠ DIA-NN archive extracted but binary not found in expected location"
        echo "  Contents:"
        find "$tmpdir/diann_unzipped" -maxdepth 3 -type f | head -10
    fi
}

# ============================================================================
# Main Installation Sequence
# ============================================================================
main() {
    local failed_tools=()
    
    echo "Starting search tools installation..."
    echo ""
    
    # Install each tool, capture failures
    if ! install_sage; then
        failed_tools+=("SAGE")
    fi
    echo ""
    
    if ! install_ptm_shepherd; then
        failed_tools+=("PTM-Shepherd")
    fi
    echo ""
    
    if ! install_fragpipe; then
        failed_tools+=("Fragpipe/MSFragger")
    fi
    echo ""
    
    if ! install_dotnet; then
        failed_tools+=("dotnet")
    fi
    echo ""
    
    if ! install_diann; then
        failed_tools+=("DIA-NN")
    fi
    echo ""
    
    # Print summary
    echo "=========================================="
    echo "Installation Summary"
    echo "=========================================="
    
    if [ ${#failed_tools[@]} -eq 0 ]; then
        echo "✓ All search tools installed successfully!"
        echo ""
        echo "Environment variables to set:"
        echo "  export SAGE_HOME=$INSTALL_ROOT/sage"
        echo "  export PTMSHEPHERD_HOME=$INSTALL_ROOT/ptmshepherd"
        echo "  export PTMSHEPHERD_JAR=$INSTALL_ROOT/ptmshepherd/ptmshepherd.jar"
        echo "  export FRAGPIPE_HOME=$INSTALL_ROOT/fragpipe"
        echo "  export DIANN_HOME=$INSTALL_ROOT/diann"
        echo "  export DOTNET_ROOT=$INSTALL_ROOT/dotnet"
        echo "  export PATH=\$DOTNET_ROOT:\$SAGE_HOME:\$DIANN_HOME:\$FRAGPIPE_HOME/bin:\$PATH"
        echo ""
        echo "Available commands:"
        echo "  - sage, ptm_shepherd, fragpipe, msfragger, diann"
        return 0
    else
        echo "✗ Failed to install the following tools:"
        printf '  - %s\n' "${failed_tools[@]}"
        echo ""
        echo "Installed tools:"
        echo "  - $([ -f "$INSTALL_ROOT/sage/sage" ] && echo "✓ SAGE" || echo "SAGE")"
        [ -f "$INSTALL_ROOT/ptmshepherd/ptmshepherd.jar" ] && echo "  - ✓ PTM-Shepherd" || echo "  - PTM-Shepherd"
        [ -f "$INSTALL_ROOT/fragpipe/bin/fragpipe" ] && echo "  - ✓ Fragpipe/MSFragger" || echo "  - Fragpipe/MSFragger"
        [ -f "$INSTALL_ROOT/dotnet/dotnet" ] && echo "  - ✓ dotnet" || echo "  - dotnet"
        [ -f "$INSTALL_ROOT/diann/diann" ] || [ -L "$CONDA_ENV_PATH/bin/diann" ] && echo "  - ✓ DIA-NN" || echo "  - DIA-NN"
        return 1
    fi
}

# Run main installation
main "$@"
