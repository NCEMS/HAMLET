#!/usr/bin/env python3
"""
Two-pass SAGE search workflow:
1. Open search to discover PTMs
2. PTM-Shepherd to validate PTMs
3. Closed search with discovered PTMs as variable mods

This orchestrates the complete workflow.
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path

# Import functions from SAGE.py and parse_modsummary.py
sys.path.insert(0, os.path.dirname(__file__))
from parse_modsummary import parse_modsummary, convert_to_sage_variable_mods


def run_sage_search(sage_config_path, mzml_dir, output_dir, search_type="open"):
    """
    Run SAGE.py with appropriate parameters.
    
    Args:
        sage_config_path: Base SAGE config file
        mzml_dir: Directory with mzML files
        output_dir: Where to write results
        search_type: "open" or "closed"
    """
    cmd = [
        "python", os.path.join(os.path.dirname(__file__), "SAGE.py"),
        "--sage_config", sage_config_path,
        "--mzml_dir", mzml_dir,
        "-o", output_dir,
        "--taxid", str(args.taxid),
        "--PSM-only"
    ]
    
    if args.labeling:
        cmd.extend(["--labeling", args.labeling])
    
    if args.config:
        cmd.extend(["--config", args.config])
    
    if search_type == "open":
        cmd.append("--OpenSearch")
    
    print(f"\nRunning {search_type} search:")
    print(" ".join(cmd))
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Error running {search_type} search:")
        print(result.stderr)
        raise RuntimeError(f"SAGE {search_type} search failed")
    
    print(result.stdout)
    return output_dir


def extract_validated_ptms(open_search_dir, min_psms=15, min_percent=0.01):
    """
    Parse global.modsummary.tsv from open search to get validated PTMs.
    """
    modsummary_path = os.path.join(open_search_dir, "global.modsummary.tsv")
    
    if not os.path.exists(modsummary_path):
        print(f"Warning: {modsummary_path} not found")
        return []
    
    print(f"\nParsing PTM-Shepherd results from {modsummary_path}")
    
    validated_ptms = parse_modsummary(modsummary_path, min_psms, min_percent)
    
    print(f"Found {len(validated_ptms)} validated PTMs")
    for ptm in validated_ptms:
        print(f"  {ptm['name']:40s} {ptm['mass_shift']:+10.6f} Da  "
              f"({ptm['psms']:4d} PSMs, {ptm['percent']:5.2f}%)")
    
    return validated_ptms


def create_closed_search_config(base_config_path, validated_ptms, output_path):
    """
    Create a SAGE config for closed search with validated PTMs as variable mods.
    """
    with open(base_config_path, 'r') as f:
        config = json.load(f)
    
    # Convert PTMs to SAGE variable_mods format
    variable_mods = convert_to_sage_variable_mods(validated_ptms)
    
    # Always include common static mods
    if 'database' not in config:
        config['database'] = {}
    
    config['database']['static_mods'] = {"C": 57.02146}  # Carbamidomethyl
    config['database']['variable_mods'] = variable_mods
    
    # Also add common variable mods that might not be detected in open search
    # Oxidation of Met
    if 'M' not in variable_mods:
        variable_mods['M'] = []
    if 15.994915 not in variable_mods['M']:
        variable_mods['M'].append(15.994915)
    
    # N-terminal acetylation
    if '[' not in variable_mods:
        variable_mods['['] = []
    if 42.010565 not in variable_mods['[']:
        variable_mods['['].append(42.010565)
    
    # Set closed search parameters
    config['precursor_tol'] = {"ppm": [-20, 20]}
    config['fragment_tol'] = {"ppm": [-25, 25]}
    config['isotope_errors'] = [0, 1, 2]
    config['deisotope'] = True
    
    # Write config
    with open(output_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"\nCreated closed search config: {output_path}")
    print(f"Variable mods: {json.dumps(variable_mods, indent=2)}")
    
    return output_path


def main():
    global args
    
    parser = argparse.ArgumentParser(
        description="Two-pass SAGE search: open discovery + closed validation"
    )
    parser.add_argument("--sage_config", required=True, help="Base SAGE config file")
    parser.add_argument("--mzml_dir", required=True, help="Directory with mzML files")
    parser.add_argument("--output_dir", required=True, help="Base output directory")
    parser.add_argument("--taxid", required=True, help="Organism NCBI TaxID")
    parser.add_argument("--labeling", default="LFQ", help="Labeling type (LFQ, TMT, iTRAQ, SILAC)")
    parser.add_argument("--config", help="detected_params.json from runAssessor")
    parser.add_argument("--min-ptm-psms", type=int, default=15, help="Min PSMs to validate a PTM")
    parser.add_argument("--min-ptm-percent", type=float, default=0.015, help="Min percent for PTM validation")
    parser.add_argument("--skip-open", action="store_true", help="Skip open search (use existing)")
    parser.add_argument("--skip-closed", action="store_true", help="Skip closed search")
    
    args = parser.parse_args()
    
    # Create output directories
    open_search_dir = os.path.join(args.output_dir, "open_search")
    closed_search_dir = os.path.join(args.output_dir, "closed_search")
    
    Path(open_search_dir).mkdir(parents=True, exist_ok=True)
    Path(closed_search_dir).mkdir(parents=True, exist_ok=True)
    
    # Step 1: Open search (if not skipped)
    if not args.skip_open:
        print("="*80)
        print("STEP 1: Open Search for PTM Discovery")
        print("="*80)
        run_sage_search(args.sage_config, args.mzml_dir, open_search_dir, "open")
    else:
        print("Skipping open search (using existing results)")
    
    # Step 2: Extract validated PTMs
    print("\n" + "="*80)
    print("STEP 2: Extract Validated PTMs from PTM-Shepherd")
    print("="*80)
    validated_ptms = extract_validated_ptms(
        open_search_dir,
        min_psms=args.min_ptm_psms,
        min_percent=args.min_ptm_percent
    )
    
    if not validated_ptms:
        print("No validated PTMs found - using default variable mods for closed search")
        validated_ptms = []
    
    # Save validated PTMs
    ptms_json = os.path.join(args.output_dir, "validated_ptms.json")
    with open(ptms_json, 'w') as f:
        json.dump(validated_ptms, f, indent=2)
    print(f"Saved validated PTMs to {ptms_json}")
    
    # Step 3: Closed search with validated PTMs (if not skipped)
    if not args.skip_closed:
        print("\n" + "="*80)
        print("STEP 3: Closed Search with Validated PTMs")
        print("="*80)
        
        # Create closed search config
        closed_config_path = os.path.join(args.output_dir, "closed_search_config.json")
        create_closed_search_config(args.sage_config, validated_ptms, closed_config_path)
        
        # Run closed search
        run_sage_search(closed_config_path, args.mzml_dir, closed_search_dir, "closed")
    else:
        print("Skipping closed search")
    
    print("\n" + "="*80)
    print("Two-pass search complete!")
    print("="*80)
    print(f"Open search results:   {open_search_dir}")
    print(f"Closed search results: {closed_search_dir}")
    print(f"Validated PTMs:        {ptms_json}")


if __name__ == "__main__":
    main()
