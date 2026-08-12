#!/usr/bin/env bash
#rebuild every before and after file for fix1
#run this from the root folder of the HAMLET repository
set -euo pipefail

FIX1="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATASETS="PXD005463 PXD001061 PXD000534 PXD001454 PXD009281 PXD041775"

clean_tree() {
  git checkout -- src/python/sdrf_builder.py
  git -C src/agentic-metadata checkout -- agents/integration_agent.py
  find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
}

build_all() {   # $1 = output folder name (before or after)
  for p in $DATASETS; do
    python3 "$FIX1/_tools/build_sdrf.py" "$p" "$FIX1/work/$1/$p"
    cp "$FIX1/work/$1/$p/$p.sdrf.tsv" "$FIX1/$1/$p.sdrf.tsv"
    mkdir -p "$FIX1/evidence/$1"
    cp "$FIX1/work/$1/$p/integrated_output/TechnicalAgent/temp_0.0/${p}_PubText_enriched.json" \
       "$FIX1/evidence/$1/${p}_TechnicalAgent_enriched.json"
  done
}

rm -rf "$FIX1/before" "$FIX1/after" "$FIX1/after_silac_demo" "$FIX1/evidence" "$FIX1/work"
mkdir -p "$FIX1/before" "$FIX1/after"

clean_tree
build_all before

clean_tree
git -C src/agentic-metadata apply "$FIX1/_tools/Fix1_agentic-metadata.patch"
git apply "$FIX1/_tools/Fix1_HAMLET.patch"
build_all after

python3 "$FIX1/_tools/build_sdrf.py" PXD005463 "$FIX1/work/silac" SILAC
mkdir -p "$FIX1/after_silac_demo"
cp "$FIX1/work/silac/PXD005463.sdrf.tsv" "$FIX1/after_silac_demo/PXD005463.sdrf.tsv"

clean_tree
rm -rf "$FIX1/work"
echo "Done. The code is clean again."
