#!/bin/bash
set -euo pipefail

# Download NCBI Taxonomy Database Files
# This script downloads nodes.dmp and names.dmp from NCBI's FTP server
# These files are required for accurate organism identification via Peptonizer2000
# Size: ~500 MB total (206 MB nodes.dmp + 277 MB names.dmp)

echo "========================================"
echo "Downloading NCBI Taxonomy Database"
echo "========================================"
echo ""

# Get project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TAXONOMY_DIR="$PROJECT_ROOT/assets/taxonomy"

# Create directory if it doesn't exist
mkdir -p "$TAXONOMY_DIR"

# NCBI FTP URLs
NCBI_FTP="https://ftp.ncbi.nlm.nih.gov/pub/taxonomy"
TAXDUMP_URL="$NCBI_FTP/taxdump.tar.gz"
TAXDUMP_FILE="$TAXONOMY_DIR/taxdump.tar.gz"

# Check if files already exist
if [ -f "$TAXONOMY_DIR/nodes.dmp" ] && [ -f "$TAXONOMY_DIR/names.dmp" ]; then
    echo "✓ NCBI taxonomy files already present:"
    echo "  - $TAXONOMY_DIR/nodes.dmp"
    echo "  - $TAXONOMY_DIR/names.dmp"
    echo ""
    echo "Skipping download. If you need to refresh, remove the files and run again:"
    echo "  rm $TAXONOMY_DIR/{nodes,names}.dmp"
    exit 0
fi

echo "Downloading NCBI taxdump archive (~500 MB)..."
echo "Source: $NCBI_FTP"
echo ""

# Download with retries
MAX_RETRIES=3
RETRY=0
while [ $RETRY -lt $MAX_RETRIES ]; do
    if curl -L --progress-bar "$TAXDUMP_URL" -o "$TAXDUMP_FILE"; then
        echo ""
        echo "✓ Downloaded successfully"
        break
    else
        RETRY=$((RETRY + 1))
        if [ $RETRY -lt $MAX_RETRIES ]; then
            echo ""
            echo "⚠ Download failed, retrying ($RETRY/$MAX_RETRIES)..."
            sleep 2
        else
            echo ""
            echo "✗ Failed to download after $MAX_RETRIES attempts"
            exit 1
        fi
    fi
done

echo ""
echo "Extracting nodes.dmp and names.dmp from archive..."
cd "$TAXONOMY_DIR"

# Extract only the files we need to save time and space
tar -xzf "$TAXDUMP_FILE" nodes.dmp names.dmp

if [ -f "$TAXONOMY_DIR/nodes.dmp" ] && [ -f "$TAXONOMY_DIR/names.dmp" ]; then
    echo "✓ Extracted successfully:"
    NODES_SIZE=$(du -h "$TAXONOMY_DIR/nodes.dmp" | cut -f1)
    NAMES_SIZE=$(du -h "$TAXONOMY_DIR/names.dmp" | cut -f1)
    echo "  - nodes.dmp ($NODES_SIZE)"
    echo "  - names.dmp ($NAMES_SIZE)"
else
    echo "✗ Extraction failed"
    exit 1
fi

# Clean up archive
rm -f "$TAXDUMP_FILE"

echo ""
echo "========================================"
echo "NCBI Taxonomy database ready!"
echo "========================================"
echo ""
echo "These files enable accurate species-level organism identification"
echo "by deduplicating taxonomy during Peptonizer2000 scoring."
echo ""
echo "Location: $TAXONOMY_DIR"
