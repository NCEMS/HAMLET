#!/bin/bash
#
# run_parallel_pxds.sh - Run multiple PXDs in parallel using Nextflow
#
# This script demonstrates how to run the pipeline with multiple PXDs from a CSV file.
# All parallelization is handled natively by Nextflow based on the maxForks settings
# in nextflow.config.
#
# Usage:
#   # Run all PXDs from PXDs.csv
#   ./run_parallel_pxds.sh
#
#   # Run first 5 PXDs with limited files for testing
#   ./run_parallel_pxds.sh 5 3
#
#   # Run with custom CSV file
#   ./run_parallel_pxds.sh all 30 my_pxds.csv
#

set -euo pipefail

# Configuration
NUM_PXDS=${1:-all}           # Number of PXDs to process (default: all)
MAX_RAW_FILES=${2:-30}       # Max raw files per PXD (default: 30)
CSV_FILE=${3:-PXDs.csv}      # CSV file with PXDs (default: PXDs.csv)

# Set Nextflow memory options
export NEXTFLOW_OPTS="-Xms2g -Xmx4g"

echo "========================================="
echo "Parallel PXD Processing"
echo "========================================="
echo "CSV file: $CSV_FILE"
if [ "$NUM_PXDS" = "all" ]; then
    echo "Processing: ALL PXDs"
else
    echo "Processing: First $NUM_PXDS PXDs"
fi
echo "Max files per PXD: $MAX_RAW_FILES"
echo "========================================="
echo ""

# Validate CSV file exists
if [ ! -f "$CSV_FILE" ]; then
    echo "Error: CSV file '$CSV_FILE' not found"
    exit 1
fi

# Count PXDs in CSV
total_pxds=$(tail -n +2 "$CSV_FILE" | wc -l)
echo "Total PXDs in CSV: $total_pxds"

if [ "$NUM_PXDS" != "all" ]; then
    echo "Will process: $NUM_PXDS PXDs"
fi
echo ""

# Build nextflow command
cmd=(
    nextflow run main.nf
    --pxd_csv "$CSV_FILE"
    --max_raw_files "$MAX_RAW_FILES"
    --use_aria2c true
    --aria2c_threads 8
    --denovo_threshold 80
    --min_peptides_for_peptonizer 5
    -resume
)

# Add num_pxds parameter if not "all"
if [ "$NUM_PXDS" != "all" ]; then
    cmd+=(--num_pxds "$NUM_PXDS")
fi

echo "Running command:"
echo "${cmd[@]}"
echo ""

# Run nextflow
"${cmd[@]}"

# Check results
echo ""
echo "========================================="
echo "Processing Complete!"
echo "========================================="
echo ""

# Count completed results
completed=$(find results -name "*_aggregated_results.json" 2>/dev/null | wc -l)
echo "Completed PXDs: $completed"
echo ""
echo "Results directory: results/"
echo "  - Each PXD has its own subdirectory: results/<PXD>/"
echo "  - Aggregated results: results/<PXD>/<PXD>_aggregated_results.json"
echo ""
echo "Work directory: work/"
echo "  - All intermediate files preserved for -resume"
echo ""

# Show summary
if [ -d results ]; then
    echo "PXD Summary:"
    for pxd_dir in results/PXD*; do
        if [ -d "$pxd_dir" ]; then
            pxd=$(basename "$pxd_dir")
            if [ -f "$pxd_dir/${pxd}_aggregated_results.json" ]; then
                echo "  ✓ $pxd - Complete"
            else
                echo "  ✗ $pxd - Incomplete or failed"
            fi
        fi
    done
fi
