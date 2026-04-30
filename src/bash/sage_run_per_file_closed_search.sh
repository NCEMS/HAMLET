#!/bin/bash
# SAGE Per-File Closed Search Runner
# Executes per-file closed searches with pooled PTMs
# Usage: sage_run_per_file_closed_search.sh <mzml_list_file> <output_dir> <taxid> <labeling> <detected_params> <variable_mods_json>

set -o pipefail  # Catch errors in pipelines

MZML_LIST="$1"
OUTPUT_DIR="$2"
TAXID="$3"
LABELING="$4"
DETECTED_PARAMS="$5"
VARIABLE_MODS_JSON="$6"

mkdir -p "$OUTPUT_DIR"

# ===== RESOURCE CONSTRAINTS FOR PER-FILE CLOSED SEARCH =====
# Force single-threaded execution to avoid recursive algorithm stack exhaustion
# SAGE's PTM-matching uses deep recursion - nested parallelism can overflow thread stacks
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1

# Increase thread stack size from 8 MB (default) to 32 MB
# This accommodates SAGE's recursive algorithms with many PTMs
ulimit -s 32768 || true

# Set resource limits to prevent cascade failures
# Each per-file search is limited but processes sequentially
echo "Resource configuration:"
echo "  Thread stack size: $(ulimit -s) KB"
echo "  OMP threads: $OMP_NUM_THREADS"

# Create a log file
LOG_FILE="$OUTPUT_DIR/per_file_search.log"
echo "Starting per-file closed search at $(date)" > "$LOG_FILE"

# Count files for progress reporting
total_files=$(wc -l < "$MZML_LIST")
current=0
successful=0
failed=0

echo "Running per-file closed searches for $total_files files"
echo "Output directory: $OUTPUT_DIR"
echo "Taxid: $TAXID"
echo "Labeling: $LABELING"

echo "=== Per-File Closed Search Log ===" >> "$LOG_FILE"
echo "Total files to process: $total_files" >> "$LOG_FILE"
echo "Taxid: $TAXID" >> "$LOG_FILE"
echo "Labeling: $LABELING" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

while IFS= read -r mzml_file; do
    current=$((current + 1))
    
    if [ -z "$mzml_file" ]; then
        continue
    fi
    
    # Extract file name without extension
    file_name=$(basename "$mzml_file" .mzML)
    file_dir="$OUTPUT_DIR/$file_name"
    
    echo ""
    echo "[$current/$total_files] Processing: $file_name"
    echo "[$current/$total_files] Processing: $file_name" >> "$LOG_FILE"
    mkdir -p "$file_dir"
    
    # Get the directory containing the mzML file
    mzml_dir=$(dirname "$mzml_file")
    
    # Run closed search for this file
    python /workspace/src/python/SAGE.py \
        --sage_config /workspace/assets/default_sage.config \
        --mzml_dir "$mzml_dir" \
        --mzml_file "$(basename "$mzml_file")" \
        -o "$file_dir" \
        --taxid "$TAXID" \
        --labeling "$LABELING" \
        --config "$DETECTED_PARAMS" \
        --ClosedSearch \
        --variable_mods "$VARIABLE_MODS_JSON" > "$file_dir/sage.log" 2>&1
    
    exit_code=$?
    
    if [ $exit_code -eq 0 ] && [ -f "$file_dir/results.sage.tsv" ]; then
        psm_count=$(tail -n +2 "$file_dir/results.sage.tsv" | wc -l)
        echo "  ✓ Success: $psm_count PSMs"
        echo "  ✓ Success: $psm_count PSMs" >> "$LOG_FILE"
        successful=$((successful + 1))
    else
        echo "  ✗ Failed with exit code $exit_code"
        echo "  ✗ Failed with exit code $exit_code" >> "$LOG_FILE"
        echo "Failed" > "$file_dir/error.txt"
        failed=$((failed + 1))
        # Continue with next file instead of failing entire job
    fi
done < "$MZML_LIST"

echo ""
echo "Per-file closed searches complete"
echo "  Successful: $successful/$total_files"
echo "  Failed: $failed/$total_files"

echo "" >> "$LOG_FILE"
echo "Per-file closed searches complete at $(date)" >> "$LOG_FILE"
echo "  Successful: $successful/$total_files" >> "$LOG_FILE"
echo "  Failed: $failed/$total_files" >> "$LOG_FILE"

if [ $successful -eq 0 ]; then
    echo "ERROR: No per-file searches succeeded!"
    exit 1
fi

exit 0
