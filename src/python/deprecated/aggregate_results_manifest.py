#!/usr/bin/env python3
"""
Generate manifest JSON for search results
Reports file paths instead of aggregating PSM data
"""

import argparse
import json
import os
from pathlib import Path


def load_detected_params(pxd_dir):
    """Load detected parameters to determine DIA vs DDA"""
    detected_params_path = os.path.join(pxd_dir, "detected_params.json")
    if os.path.exists(detected_params_path):
        with open(detected_params_path, 'r') as f:
            data = json.load(f)
        return data.get('detected_params', {})
    return {}


def generate_dda_manifest(sage_results_dir, pxd_id):
    """Generate manifest for DDA results (open/closed search + modifications)"""
    prefix = os.path.basename(os.path.normpath(sage_results_dir)) or "search"
    if prefix not in ("search", "sage_results"):
        prefix = "search"

    manifest = {
        "pxd_id": pxd_id,
        "detected_dia": False,
        "search_type": "dda",
        "results": {}
    }
    
    # Check for open search results
    open_dir = os.path.join(sage_results_dir, "dda_search", "Open")
    if os.path.exists(open_dir):
        results_file = os.path.join(open_dir, "search_results.tsv")
        legacy_results_file = os.path.join(open_dir, "results.sage.tsv")
        metadata_file = os.path.join(open_dir, "search_metadata.json")
        if os.path.exists(results_file):
            manifest["results"]["open_search"] = f"{prefix}/dda_search/Open/search_results.tsv"
        elif os.path.exists(legacy_results_file):
            manifest["results"]["open_search"] = f"{prefix}/dda_search/Open/results.sage.tsv"
        if os.path.exists(metadata_file):
            manifest["results"]["open_search_metadata"] = f"{prefix}/dda_search/Open/search_metadata.json"
    
    # Check for closed search results
    closed_dir = os.path.join(sage_results_dir, "dda_search", "Closed")
    if os.path.exists(closed_dir):
        results_file = os.path.join(closed_dir, "search_results.tsv")
        legacy_results_file = os.path.join(closed_dir, "results.sage.tsv")
        metadata_file = os.path.join(closed_dir, "search_metadata.json")
        if os.path.exists(results_file):
            manifest["results"]["closed_search"] = f"{prefix}/dda_search/Closed/search_results.tsv"
        elif os.path.exists(legacy_results_file):
            manifest["results"]["closed_search"] = f"{prefix}/dda_search/Closed/results.sage.tsv"
        if os.path.exists(metadata_file):
            manifest["results"]["closed_search_metadata"] = f"{prefix}/dda_search/Closed/search_metadata.json"
    
    # Check for modifications results
    mods_dir = os.path.join(sage_results_dir, "modifications")
    if os.path.exists(mods_dir):
        ptm_summary = os.path.join(mods_dir, "global.modsummary.tsv")
        validated_ptms = os.path.join(mods_dir, "validated_ptms.json")
        if os.path.exists(ptm_summary):
            manifest["results"]["ptm_summary"] = f"{prefix}/modifications/global.modsummary.tsv"
        if os.path.exists(validated_ptms):
            manifest["results"]["validated_ptms"] = f"{prefix}/modifications/validated_ptms.json"
    
    return manifest


def generate_dia_manifest(sage_results_dir, pxd_id):
    """Generate manifest for DIA results"""
    prefix = os.path.basename(os.path.normpath(sage_results_dir)) or "search"
    if prefix not in ("search", "sage_results"):
        prefix = "search"

    manifest = {
        "pxd_id": pxd_id,
        "detected_dia": True,
        "search_type": "dia",
        "results": {}
    }
    
    dia_dir = os.path.join(sage_results_dir, "dia_search")
    if os.path.exists(dia_dir):
        # Primary results (converted to SAGE TSV format)
        results_tsv = os.path.join(dia_dir, "search_results.tsv")
        legacy_results_tsv = os.path.join(dia_dir, "results.sage.tsv")
        if os.path.exists(results_tsv):
            manifest["results"]["primary_results"] = f"{prefix}/dia_search/search_results.tsv"
        elif os.path.exists(legacy_results_tsv):
            manifest["results"]["primary_results"] = f"{prefix}/dia_search/results.sage.tsv"
        
        # Raw DIA-NN output
        raw_output = os.path.join(dia_dir, "results.json")
        if os.path.exists(raw_output):
            manifest["results"]["raw_output"] = f"{prefix}/dia_search/results.json"
        
        # Search metadata
        metadata_file = os.path.join(dia_dir, "search_metadata.json")
        if os.path.exists(metadata_file):
            manifest["results"]["metadata"] = f"{prefix}/dia_search/search_metadata.json"
    
    return manifest


def main():
    parser = argparse.ArgumentParser(description='Generate search results manifest')
    parser.add_argument('--pxd_id', required=True, help='PXD identifier')
    parser.add_argument('--pxd_dir', required=True, help='PXD work directory')
    parser.add_argument('--sage_results_dir', required=True, help='Directory containing search results')
    parser.add_argument('--output_file', required=True, help='Output manifest JSON file')
    
    args = parser.parse_args()
    
    # Load detected parameters to determine DIA vs DDA
    detected_params = load_detected_params(args.pxd_dir)
    is_dia = detected_params.get('DIA', False)
    
    print(f"Generating manifest for {args.pxd_id} (DIA={is_dia})")
    
    # Generate appropriate manifest
    if is_dia:
        manifest = generate_dia_manifest(args.sage_results_dir, args.pxd_id)
    else:
        manifest = generate_dda_manifest(args.sage_results_dir, args.pxd_id)
    
    # Write manifest
    with open(args.output_file, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"Manifest written to {args.output_file}")
    print(json.dumps(manifest, indent=2))
    
    return 0


if __name__ == '__main__':
    exit(main())
