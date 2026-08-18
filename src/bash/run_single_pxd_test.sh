#!/bin/bash
##############################################################################
# run_single_pxd_test.sh
#
# Quick script to run the full HAMLET Nextflow pipeline on a single test PXD.
# 
# This runs the complete pipeline: fetch → assess → search → aggregation → 
# optional LLM/agentic stages.
#
# Usage:
#   ./run_single_pxd_test.sh PXDxxxxxx
#   ./run_single_pxd_test.sh PXDxxxxxx --max_raw_files 3
#   ./run_single_pxd_test.sh PXDxxxxxx --profile slurm
#
# Examples:
#   ./run_single_pxd_test.sh PXD000070                    # Full pipeline
#   ./run_single_pxd_test.sh PXD000070 --max_raw_files 2  # Quick test
#   ./run_single_pxd_test.sh PXD000070 --profile slurm    # Using SLURM
#
##############################################################################

set -e

# ============================================================================
# Configuration
# ============================================================================

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ============================================================================
# Parse arguments
# ============================================================================

if [ $# -lt 1 ]; then
    cat <<EOF
Usage: $0 PXDxxxxxx [nextflow options...]

Arguments:
  PXDxxxxxx         The PXD ID to process (required)
  [nextflow opts]   Optional Nextflow parameters

Examples:
  $0 PXD000070                                  # Full pipeline
  $0 PXD000070 --max_raw_files 3                # Limit to 3 RAW files
  $0 PXD000070 --max_raw_files 2 -resume        # Resume previous run
  $0 PXD000070 --profile slurm                  # Use SLURM executor
  $0 PXD000070 --profile slurm -resume          # Resume with SLURM
  $0 PXD000070 --debug_mode true                # Debug mode (verbose output)

EOF
    exit 1
fi

PXD="$1"
shift  # Remove first argument, remaining args are passed to nextflow

# ============================================================================
# Validation
# ============================================================================

# Validate PXD format
if ! [[ "$PXD" =~ ^PXD[0-9]{6}$ ]]; then
    echo "ERROR: Invalid PXD format. Expected PXDxxxxxx (e.g., PXD000070)"
    exit 1
fi

# Check if Nextflow is installed
if ! command -v nextflow &> /dev/null; then
    echo "ERROR: Nextflow not found. Please install Nextflow:"
    echo "  curl -s https://get.nextflow.io | bash"
    echo "  sudo mv nextflow /usr/local/bin/"
    exit 1
fi

# Check if main.nf exists
if [ ! -f "$REPO_ROOT/main.nf" ]; then
    echo "ERROR: main.nf not found at $REPO_ROOT/main.nf"
    exit 1
fi

echo "============================================================================"
echo "HAMLET Full Pipeline - Single PXD Test"
echo "============================================================================"
echo "PXD ID:             $PXD"
echo "Repository root:    $REPO_ROOT"
echo "Nextflow version:   $(nextflow -v)"
echo "Additional args:    $@"
echo "============================================================================"
echo ""

# ============================================================================
# Run the Nextflow pipeline
# ============================================================================

cd "$REPO_ROOT"

echo "Starting Nextflow pipeline..."
echo ""

nextflow run main.nf \
    --pxd "$PXD" \
    "$@"

# ============================================================================
# Report results
# ============================================================================

echo ""
echo "============================================================================"
echo "Pipeline Complete!"
echo "============================================================================"
echo ""
echo "Results location: $REPO_ROOT/results/$PXD/"
echo ""

# Check for key outputs
if [ -d "$REPO_ROOT/results/$PXD" ]; then
    echo "Output files:"
    ls -lh "$REPO_ROOT/results/$PXD"/ 2>/dev/null | head -20
    
    # Check for aggregated results
    if [ -f "$REPO_ROOT/results/$PXD/${PXD}_aggregated_results.json" ]; then
        echo ""
        echo "✓ Aggregated results: $REPO_ROOT/results/$PXD/${PXD}_aggregated_results.json"
        echo "  Size: $(ls -lh "$REPO_ROOT/results/$PXD/${PXD}_aggregated_results.json" | awk '{print $5}')"
    fi
    
    # Check for agentic outputs
    if [ -d "$REPO_ROOT/results/$PXD/agentic_metadata" ]; then
        echo ""
        echo "✓ Agentic metadata extraction outputs available:"
        if [ -f "$REPO_ROOT/results/$PXD/agentic_metadata/${PXD}.sdrf.tsv" ]; then
            echo "  - SDRF file: $(ls -lh "$REPO_ROOT/results/$PXD/agentic_metadata/${PXD}.sdrf.tsv" | awk '{print $5}')"
        fi
    fi
else
    echo "⚠ Warning: Results directory not created"
fi

echo ""
