#!/bin/bash

# Installation script for aMEW conda environment
# Installs: Cascadia, Casanovo, SAGE, DIA-NN, PTM-Shepherd, ProteoWizard
# Run this after: conda env create -f aMEW_environment.yml

set -e

echo "=================================="
echo "Setting up aMEW tools"
echo "=================================="

# Activate the aMEW environment
eval "$(conda shell.bash hook)"
conda activate aMEW

# Create tool installation directories
mkdir -p /opt/aMEW/{cascadia,casanovo,sage,diann,ptmshepherd}

# 1. Install Cascadia from GitHub
echo ""
echo "[1/5] Installing Cascadia..."
cd /opt/aMEW/cascadia
pip install --no-cache-dir git+https://github.com/Noble-Lab/cascadia.git

# 2. Install Casanovo from GitHub (latest version)
echo ""
echo "[2/5] Installing Casanovo..."
cd /opt/aMEW/casanovo
pip install --no-cache-dir git+https://github.com/Noble-Lab/casanovo.git

# 3. Install SAGE from GitHub release
echo ""
echo "[3/5] Installing SAGE..."
cd /opt/aMEW/sage
wget -q https://github.com/lazear/sage/releases/download/v0.14.7/sage-v0.14.7-x86_64-unknown-linux-gnu.tar.gz
tar -xzf sage-v0.14.7-x86_64-unknown-linux-gnu.tar.gz
rm sage-v0.14.7-x86_64-unknown-linux-gnu.tar.gz
chmod +x /opt/aMEW/sage/sage
ln -sf /opt/aMEW/sage/sage $(conda info --base)/envs/aMEW/bin/sage || true
echo "SAGE installed at /opt/aMEW/sage/sage"

# 4. Install DIA-NN from GitHub release (requires .NET 8.0)
echo ""
echo "[4/5] Installing DIA-NN..."
cd /opt/aMEW/diann
# Check if .NET is installed, if not skip DIA-NN
if command -v dotnet &> /dev/null; then
    wget -q https://github.com/vdemichev/DiaNN/releases/download/2.0/DIA-NN-2.2.0-Academia-Linux.zip
    unzip -q DIA-NN-2.2.0-Academia-Linux.zip
    cd diann-2.2.0 && chmod +x diann-* && mv * /opt/aMEW/diann/ || true
    cd /opt/aMEW/diann && rm -rf diann-2.2.0 DIA-NN-2.2.0-Academia-Linux.zip
    DIANN_BIN=$(ls /opt/aMEW/diann/diann-* 2>/dev/null | grep -v "\.dll" | head -1)
    ln -sf "$DIANN_BIN" $(conda info --base)/envs/aMEW/bin/diann || true
    echo "DIA-NN installed at /opt/aMEW/diann/"
else
    echo "WARNING: .NET 8.0 not found. Skipping DIA-NN installation."
    echo "To use DIA-NN, install .NET 8.0: https://dotnet.microsoft.com/download"
fi

# 5. Install PTM-Shepherd JAR
echo ""
echo "[5/5] Installing PTM-Shepherd..."
cd /opt/aMEW/ptmshepherd
wget -q -O ptmshepherd.jar https://github.com/Nesvilab/PTM-Shepherd/releases/latest/download/ptmshepherd-2.0.5_CLI.jar
chmod +x ptmshepherd.jar
# Create wrapper script for convenient CLI access
cat > $(conda info --base)/envs/aMEW/bin/ptmshepherd << 'EOF'
#!/bin/bash
java -jar /opt/aMEW/ptmshepherd/ptmshepherd.jar "$@"
EOF
chmod +x $(conda info --base)/envs/aMEW/bin/ptmshepherd
echo "PTM-Shepherd installed at /opt/aMEW/ptmshepherd/"

# 6. ProteoWizard is already available as a container
# Users can run it via: singularity exec containers/proteowizard/pwiz.sif msconvert ...

echo ""
echo "=================================="
echo "✓ aMEW environment setup complete!"
echo "=================================="
echo ""
echo "Installed tools:"
echo "  - Cascadia (DIA de novo): cascadia"
echo "  - Casanovo (DDA de novo): casanovo"
echo "  - SAGE (DDA search): sage"
echo "  - DIA-NN (DIA search): diann"
echo "  - PTM-Shepherd (PTM analysis): ptmshepherd"
echo "  - ProteoWizard (mzML conversion): containers/proteowizard/pwiz.sif"
echo ""
echo "Usage:"
echo "  conda activate aMEW"
echo ""
