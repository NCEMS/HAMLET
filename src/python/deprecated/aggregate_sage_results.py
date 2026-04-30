#!/usr/bin/env python3
"""
Aggregate per-file SAGE quantification results into a single results file.

When using per-file pooling strategy (open_only, closed_only, or none), each file
gets its own SAGE results file. This script combines them into a master results file
while preserving per-file metadata.

Usage:
    python aggregate_sage_results.py \
        --per_file_dir pass2_closed_search \
        --output_file results.sage.tsv \
        --output_metadata per_file_metadata.json
"""

import argparse
import json
import re
from pathlib import Path
from collections import defaultdict


def aggregate_sage_results(per_file_dir, output_file, output_metadata):
    """
    Aggregate per-file SAGE TSV results into a single file.
    
    Args:
        per_file_dir: Directory containing per-file subdirectories with results.sage.tsv
        output_file: Output aggregated results file
        output_metadata: Output metadata tracking file
    """
    per_file_dir = Path(per_file_dir)
    per_file_metadata = {}
    all_psms = []
    header = None
    failed_files = []
    
    # Find all per-file result directories
    per_file_subdirs = sorted([d for d in per_file_dir.iterdir() 
                               if d.is_dir() and not d.name.startswith('.')])
    
    if not per_file_subdirs:
        print(f"WARNING: No per-file subdirectories found in {per_file_dir}")
        # If no subdirs, check if results.sage.tsv exists at top level (already aggregated)
        if (per_file_dir / "results.sage.tsv").exists():
            print(f"Found aggregated results at {per_file_dir / 'results.sage.tsv'}")
            return True
        return False
    
    for file_dir in per_file_subdirs:
        result_file = file_dir / "results.sage.tsv"
        error_file = file_dir / "error.txt"
        
        # Check for error file first
        if error_file.exists():
            with open(error_file) as f:
                error_msg = f.read().strip()
            print(f"WARNING: {file_dir.name} failed with error: {error_msg}")
            failed_files.append(file_dir.name)
            continue
        
        if not result_file.exists():
            print(f"WARNING: No results.sage.tsv in {file_dir}")
            failed_files.append(file_dir.name)
            continue
        
        file_name = file_dir.name
        print(f"Processing {file_name}...")
        
        psm_count = 0
        with open(result_file) as f:
            for line_idx, line in enumerate(f):
                line = line.rstrip('\n')
                
                if line_idx == 0:
                    # Header line
                    if header is None:
                        header = line
                    else:
                        # Verify header matches
                        if line != header:
                            print(f"WARNING: Header mismatch in {file_name}")
                    continue
                
                # Data line - add file source column
                psm_count += 1
                all_psms.append((file_name, line))
        
        per_file_metadata[file_name] = {
            "directory": str(file_dir),
            "psm_count": psm_count,
            "result_file": str(result_file),
            "status": "success"
        }
        print(f"  {file_name}: {psm_count} PSMs")
    
    # Track failed files in metadata
    for failed_file in failed_files:
        per_file_metadata[failed_file] = {
            "status": "failed"
        }
    
    # Write aggregated results
    if header:
        with open(output_file, 'w') as f:
            f.write(header + '\n')
            for file_name, psm_line in all_psms:
                f.write(psm_line + '\n')
        
        total_psms = len(all_psms)
        print(f"\nWrote {total_psms} total PSMs to {output_file}")
    else:
        print(f"ERROR: No header found in any results file!")
        return False
    
    # Write metadata
    metadata = {
        "aggregation_strategy": "per_file",
        "total_files_attempted": len(per_file_subdirs),
        "total_files_successful": len(per_file_metadata) - len(failed_files),
        "total_files_failed": len(failed_files),
        "total_psms": len(all_psms),
        "files": per_file_metadata
    }
    
    with open(output_metadata, 'w') as f:
        json.dump(metadata, f, indent=2)
    
    print(f"Wrote per-file metadata to {output_metadata}")
    
    if failed_files:
        print(f"WARNING: {len(failed_files)} files failed: {', '.join(failed_files)}")
        if total_psms == 0:
            print("ERROR: No successful per-file searches!")
            return False
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description='Aggregate per-file SAGE quantification results'
    )
    parser.add_argument('--per_file_dir', required=True,
                       help='Directory containing per-file SAGE results subdirectories')
    parser.add_argument('--output_file', required=True,
                       help='Output aggregated results.sage.tsv file')
    parser.add_argument('--output_metadata', required=True,
                       help='Output per-file metadata JSON')
    
    args = parser.parse_args()
    
    success = aggregate_sage_results(
        args.per_file_dir,
        args.output_file,
        args.output_metadata
    )
    
    if not success:
        print("ERROR: Aggregation failed!")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
