#!/usr/bin/env python3
"""
Create a minimal aggregated_results.json for agentic-only mode.

This takes the outputs from fetch_pxd, run_assessor, and determine_acquisition_params,
and creates a lightweight aggregated_results.json suitable for feeding into
agentic_metadata_extraction without having run organism_id or search.

Input:
  - pxd: PXD accession ID
  - fetched_dir: Directory containing mzML files
  - study_metadata_file: study_metadata.json from run_assessor
  - detected_params_file: detected_params.json from determine_acquisition_params

Output:
  - aggregated_results.json with minimal but valid structure
"""

import json
import argparse
import sys
from pathlib import Path
from datetime import datetime
import glob


def create_minimal_aggregated_results(pxd, fetched_dir, study_metadata_file, detected_params_file):
    """Create minimal aggregated results JSON."""
    
    # Load study metadata from run_assessor
    try:
        with open(study_metadata_file) as f:
            study_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"ERROR: Could not load study_metadata.json: {e}", file=sys.stderr)
        return None
    
    # Load detected params
    detected_params = {}
    if detected_params_file and Path(detected_params_file).exists():
        try:
            with open(detected_params_file) as f:
                detected_params = json.load(f)
        except json.JSONDecodeError as e:
            print(f"WARNING: Could not load detected_params.json: {e}", file=sys.stderr)
    
    # Find all mzML files in fetched_dir
    mzml_files = []
    for pattern in [f"{fetched_dir}/*.mzML", f"{fetched_dir}/*.mzML.gz"]:
        mzml_files.extend(glob.glob(pattern))
    
    # Build minimal aggregated results
    aggregated = {
        "pxd_id": pxd,
        "pipeline_version": "agentic_only_1.0",
        "aggregation_timestamp": datetime.utcnow().isoformat(),
        "input_paths": {
            "pxd_dir": pxd,
            "organism_dir": None,
            "sage_results_dir": None,
            "llm_results_dir": None,
            "pride_json_dir": None,
            "taxid_warnings": None
        },
        "runAssessor": study_data.get("runAssessor", study_data),  # Use as-is from run_assessor
        "organism_identification": {
            "status": "skipped_agentic_only",
            "results": {}
        },
        "PTM-shepherd_open_search": {
            "status": "skipped_agentic_only",
            "results": {}
        },
        "PTM-shepherd_closed_search": {
            "status": "skipped_agentic_only",
            "results": {}
        },
        "Search_and_modification_results": {
            "status": "skipped_agentic_only",
            "files": {}
        },
        "modification_site_fractions": {
            "status": "skipped_agentic_only",
            "data": {}
        },
        "pride_metadata": study_data.get("pride_metadata", {}),
        "processing_summary": {
            "total_files": len(mzml_files),
            "files_processed": 0,
            "status": "minimal_agentic_only",
            "acquisition_type": detected_params.get("detected_params", {}).get("DIA", False) and "DIA" or "DDA"
        },
        "llm_extracted_metadata": {},
        "consolidated_pipeline": {
            "status": "minimal_agentic_only",
            "data": {}
        }
    }
    
    return aggregated


def main():
    parser = argparse.ArgumentParser(
        description="Create minimal aggregated_results.json for agentic-only mode"
    )
    parser.add_argument("--pxd", required=True, help="PXD accession ID")
    parser.add_argument("--fetched_dir", required=True, help="Directory with mzML files")
    parser.add_argument("--study_metadata", required=True, help="study_metadata.json from run_assessor")
    parser.add_argument("--detected_params", help="detected_params.json from determine_acquisition_params")
    parser.add_argument("--output", required=True, help="Output aggregated_results.json path")
    
    args = parser.parse_args()
    
    minimal_agg = create_minimal_aggregated_results(
        args.pxd,
        args.fetched_dir,
        args.study_metadata,
        args.detected_params
    )
    
    if minimal_agg is None:
        sys.exit(1)
    
    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(minimal_agg, f, indent=2)
    
    print(f"Created minimal aggregated_results.json: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
