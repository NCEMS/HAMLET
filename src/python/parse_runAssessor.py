#!/usr/bin/env python3
"""
Parse runAssessor results to automatically detect:
1. Acquisition type (DDA vs DIA)
2. Labeling type (LFQ, TMT variants, iTRAQ variants, SILAC)

This enables intelligent pipeline configuration without manual parameter specification.
"""

import json
import argparse
import os
import glob
from pathlib import Path


def find_runAssessor_json(directory, central_mzml_dir=None, pxd=None):
    """
    Find the runAssessor JSON file in the directory structure.
    
    First checks central storage if central_mzml_dir and pxd are provided.
    Falls back to searching in the provided directory.
    
    Looks for files matching *_runAssessor_results.json, study_metadata.json, or similar patterns.
    """
    # First check central storage (fastest path, truly cached)
    if central_mzml_dir and pxd:
        central_path = os.path.join(central_mzml_dir, pxd, 'runAssessor', 'study_metadata.json')
        if os.path.exists(central_path):
            print(f"✓ Found cached runAssessor results in central storage: {central_path}")
            return central_path
    
    # Try common patterns in input directory (study_metadata.json is the output from mzML_assessor.py)
    patterns = [
        "**/study_metadata.json",
        "**/*runAssessor*.json",
        "**/*assessor*.json",
        "**/runAssessor_results.json"
    ]
    
    for pattern in patterns:
        matches = list(Path(directory).glob(pattern))
        if matches:
            return str(matches[0])
    
    return None


def parse_runAssessor_json(json_path):
    """
    Parse runAssessor JSON and extract key parameters.
    
    Supports two formats:
    1. Direct runAssessor output (root has search_criteria, files, etc.)
    2. Aggregated results format (runAssessor nested under 'runAssessor' key)
    
    Returns:
        dict with keys:
            - acquisition_type: 'DDA' or 'DIA'
            - labeling: 'LFQ', 'TMT6', 'TMT10', 'TMT11', 'TMTpro', 'iTRAQ4', 'iTRAQ8', 'SILAC', etc.
            - fragmentation_type: e.g., 'HR_HCD', 'HR_IT_CID', etc.
            - high_accuracy_precursors: 'true' or 'false'
            - confidence: float (0-1) indicating confidence in labeling detection
    """
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    # Handle both direct runAssessor output and aggregated results format
    if 'runAssessor' in data:
        # Aggregated results format - extract runAssessor section
        runAssessor_data = data['runAssessor']
    else:
        # Direct runAssessor output
        runAssessor_data = data
    
    # Extract from search_criteria (aggregated across all files) as fallback
    search_criteria = runAssessor_data.get('search_criteria', {})
    
    # Check individual files first for acquisition_type (most reliable)
    files = runAssessor_data.get('files', {})
    acquisition_type = 'DDA'  # Default fallback
    fragmentation_type = 'HR_HCD'  # Default fallback
    high_accuracy_precursors = 'true'  # Default fallback
    labeling = 'LFQ'  # Default fallback
    labeling_scores = {}
    
    # Track whether we found values in spectra_stats (to avoid false fallback)
    found_acquisition_type = False
    found_fragmentation_type = False
    found_high_accuracy = False
    found_labeling = False
    
    if files:
        # Get parameters from first file (all files in a PXD should be the same)
        first_file = next(iter(files.values()))
        spectra_stats = first_file.get('spectra_stats', {})
        summary = first_file.get('summary', {})
        
        # Extract from spectra_stats (most reliable source)
        if spectra_stats:
            if 'acquisition_type' in spectra_stats:
                acquisition_type = spectra_stats.get('acquisition_type')
                found_acquisition_type = True
            if 'fragmentation_type' in spectra_stats:
                fragmentation_type = spectra_stats.get('fragmentation_type')
                found_fragmentation_type = True
            if 'high_accuracy_precursors' in spectra_stats:
                high_accuracy_precursors = str(spectra_stats.get('high_accuracy_precursors'))
                found_high_accuracy = True
        
        # Get labeling scores from summary
        labeling_info = summary.get('labeling', {})
        if 'call' in labeling_info:
            labeling = labeling_info.get('call')
            found_labeling = True
        labeling_scores = labeling_info.get('scores', {})
    
    # Fall back to search_criteria only if we didn't find the values in spectra_stats
    if not found_acquisition_type:
        acquisition_type = search_criteria.get('acquisition_type', acquisition_type)
    if not found_fragmentation_type:
        fragmentation_type = search_criteria.get('fragmentation_type', fragmentation_type)
    if not found_high_accuracy:
        high_accuracy_precursors = search_criteria.get('high_accuracy_precursors', high_accuracy_precursors)
    if not found_labeling:
        labeling = search_criteria.get('labeling', labeling)
    
    # Calculate confidence (max score from labeling_scores)
    confidence = 0.0
    if labeling_scores:
        # For labeled data, use the max score
        if labeling != 'LFQ':
            confidence = max(labeling_scores.values()) if labeling_scores else 0.0
        else:
            # For LFQ, confidence is high if all other scores are low
            max_label_score = max(labeling_scores.values()) if labeling_scores else 0.0
            confidence = 1.0 - max_label_score  # Inverse of max labeled score
    
    result = {
        'acquisition_type': acquisition_type,
        'labeling': labeling,
        'fragmentation_type': fragmentation_type,
        'high_accuracy_precursors': high_accuracy_precursors,
        'confidence': confidence,
        'labeling_scores': labeling_scores
    }
    
    return result


def map_labeling_to_modifications(labeling):
    """
    Map detected labeling type to appropriate modification configurations
    for SAGE and DIA-NN.
    
    Returns:
        dict with keys:
            - sage_mods: List of modifications for SAGE config
            - diann_mods: List of modifications for DIA-NN
            - reporter_ions: Whether to extract reporter ions (TMT/iTRAQ)
    """
    config = {
        'sage_mods': [],
        'diann_mods': [],
        'reporter_ions': False,
        'quantification_type': 'LFQ'  # Default
    }
    
    # Common modifications (always included)
    # Goal: include a broader, commonly-used DIA-NN modification set by default.
    # Note: DIA-NN expects one site per entry (e.g., phospho on S/T/Y as 3 entries).
    common_sage = []
    common_diann = [
        "UniMod:35,15.994915,M",    # Oxidation (M)
        "UniMod:1,42.010565,*n",    # Acetyl (Any N-term)
        "UniMod:7,0.984016,N",      # Deamidated (N)
        "UniMod:7,0.984016,Q",      # Deamidated (Q)
        "UniMod:21,79.966331,S",    # Phospho (S)
        "UniMod:21,79.966331,T",    # Phospho (T)
        "UniMod:21,79.966331,Y",    # Phospho (Y)
        "UniMod:28,-17.026549,Qn",  # Pyro-glu from Q (N-term)
        "UniMod:27,-18.010565,En",  # Pyro-glu from E (N-term)
    ]
    
    # Fixed modifications (always included)
    fixed_sage = []
    fixed_diann = [
        "UniMod:4,57.021464,C",  # Carbamidomethyl (C)
    ]
    
    if labeling == 'LFQ':
        # Label-free: just common modifications
        config['sage_mods'] = common_sage + fixed_sage
        config['diann_mods'] = common_diann + fixed_diann
        config['quantification_type'] = 'LFQ'
        
    elif 'TMT' in labeling:
        # TMT variants: add TMT modifications
        config['reporter_ions'] = True
        config['quantification_type'] = 'TMT'
        
        # TMT on N-terminus and K
        tmt_mass = 229.162932  # TMT 6/10/11-plex have same mass
        if 'TMTpro' in labeling:
            tmt_mass = 304.207146  # TMTpro has different mass
        
        config['sage_mods'] = common_sage + fixed_sage + [
            f"TMT,{tmt_mass},K",     # TMT on lysine
            f"TMT,{tmt_mass},^"      # TMT on N-terminus
        ]
        config['diann_mods'] = common_diann + fixed_diann + [
            f"UniMod:737,{tmt_mass},K",   # TMT6plex on K
            f"UniMod:737,{tmt_mass},*n"   # TMT6plex on N-term
        ]
        
    elif 'iTRAQ' in labeling:
        # iTRAQ variants: add iTRAQ modifications
        config['reporter_ions'] = True
        config['quantification_type'] = 'iTRAQ'
        
        # iTRAQ on N-terminus and K
        itraq_mass = 144.102063  # iTRAQ 4-plex
        if 'iTRAQ8' in labeling:
            itraq_mass = 304.205360  # iTRAQ 8-plex
        
        config['sage_mods'] = common_sage + fixed_sage + [
            f"iTRAQ,{itraq_mass},K",     # iTRAQ on lysine
            f"iTRAQ,{itraq_mass},^"      # iTRAQ on N-terminus
        ]
        config['diann_mods'] = common_diann + fixed_diann + [
            f"UniMod:214,{itraq_mass},K",   # iTRAQ4plex on K
            f"UniMod:214,{itraq_mass},*n"   # iTRAQ4plex on N-term
        ]
        
    elif labeling == 'SILAC':
        # SILAC: add heavy lysine and arginine
        config['quantification_type'] = 'SILAC'
        
        config['sage_mods'] = common_sage + fixed_sage + [
            "SILAC_K,8.014199,K",    # Heavy K (+8)
            "SILAC_R,10.008269,R"    # Heavy R (+10)
        ]
        config['diann_mods'] = common_diann + fixed_diann + [
            "UniMod:259,8.014199,K",   # Label:13C(6)15N(2) on K
            "UniMod:267,10.008269,R"   # Label:13C(6)15N(4) on R
        ]
    
    return config


def generate_pipeline_config(runAssessor_results, mod_config, output_path):
    """
    Generate a configuration file for the pipeline based on runAssessor results.
    
    This file will be sourced by Nextflow to override user parameters.
    """
    config = {
        'detected_params': {
            'DIA': runAssessor_results['acquisition_type'] == 'DIA',
            'acquisition_type': runAssessor_results['acquisition_type'],
            'labeling': runAssessor_results['labeling'],
            'fragmentation_type': runAssessor_results['fragmentation_type'],
            'high_accuracy_precursors': runAssessor_results['high_accuracy_precursors'],
            'confidence': runAssessor_results['confidence']
        },
        'modifications': mod_config,
        'labeling_scores': runAssessor_results['labeling_scores']
    }
    
    # Write as JSON
    with open(output_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"Generated pipeline configuration: {output_path}")
    return config


def main():
    parser = argparse.ArgumentParser(
        description='Parse runAssessor results to configure pipeline automatically'
    )
    parser.add_argument(
        '--input_dir',
        required=True,
        help='Directory containing runAssessor results (typically the PXD download directory)'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output JSON file for pipeline configuration'
    )
    parser.add_argument(
        '--central_mzml_dir',
        help='Central storage directory for mzML files (optional, enables reuse of cached runAssessor results)'
    )
    parser.add_argument(
        '--pxd',
        help='PXD accession ID (required if --central_mzml_dir is provided)'
    )
    parser.add_argument(
        '--runAssessor_json',
        help='Explicit path to runAssessor JSON file (optional, will auto-detect if not provided)'
    )
    
    args = parser.parse_args()
    
    # Find runAssessor JSON
    if args.runAssessor_json:
        json_path = args.runAssessor_json
    else:
        print(f"Searching for runAssessor JSON...")
        if args.central_mzml_dir and args.pxd:
            print(f"  First checking central storage: {args.central_mzml_dir}/{args.pxd}/runAssessor/")
        print(f"  Then checking input directory: {args.input_dir}")
        json_path = find_runAssessor_json(args.input_dir, args.central_mzml_dir, args.pxd)
    
    if not json_path or not os.path.exists(json_path):
        print(f"ERROR: Could not find runAssessor JSON file")
        if args.central_mzml_dir and args.pxd:
            print(f"  Checked: {args.central_mzml_dir}/{args.pxd}/runAssessor/study_metadata.json")
        print(f"  Checked: {args.input_dir} (expected patterns: *runAssessor*.json, *assessor*.json)")
        
        # Create a default config for LFQ DDA
        print("Generating default configuration (DDA, LFQ)")
        default_config = {
            'detected_params': {
                'DIA': False,
                'acquisition_type': 'DDA',
                'labeling': 'LFQ',
                'fragmentation_type': 'HR_HCD',
                'high_accuracy_precursors': 'true',
                'confidence': 0.0
            },
            'modifications': map_labeling_to_modifications('LFQ'),
            'labeling_scores': {}
        }
        with open(args.output, 'w') as f:
            json.dump(default_config, f, indent=2)
        return
    
    print(f"Found runAssessor JSON: {json_path}")
    
    # Parse runAssessor results
    print("Parsing runAssessor results...")
    results = parse_runAssessor_json(json_path)
    
    print("\nDetected parameters:")
    print(f"  Acquisition type: {results['acquisition_type']}")
    print(f"  Labeling: {results['labeling']} (confidence: {results['confidence']:.2f})")
    print(f"  Fragmentation: {results['fragmentation_type']}")
    print(f"  High accuracy precursors: {results['high_accuracy_precursors']}")
    
    if results['labeling_scores']:
        print("\n  Labeling scores:")
        for label, score in sorted(results['labeling_scores'].items(), key=lambda x: x[1], reverse=True):
            print(f"    {label}: {score:.4f}")
    
    # Map to modifications
    print("\nMapping to modification configurations...")
    mod_config = map_labeling_to_modifications(results['labeling'])
    
    print(f"  Quantification type: {mod_config['quantification_type']}")
    print(f"  Reporter ions: {mod_config['reporter_ions']}")
    
    # Generate pipeline config
    config = generate_pipeline_config(results, mod_config, args.output)
    
    print(f"\n✅ Pipeline configuration generated successfully!")
    print(f"   DIA mode: {config['detected_params']['DIA']}")
    print(f"   Labeling: {config['detected_params']['labeling']}")
    print(f"   Output: {args.output}")


if __name__ == '__main__':
    main()
