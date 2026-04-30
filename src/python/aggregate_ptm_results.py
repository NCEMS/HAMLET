#!/usr/bin/env python3
"""
Aggregate per-PTM SAGE search results by deduplicating spectra.

For each spectrum, keeps the PSM with the highest hyperscore across all PTM searches.
This ensures each spectrum appears only once in the final output, with the best scoring match.
"""

import pandas as pd
import sys
from pathlib import Path


def aggregate_ptm_results(
    ptm_result_files: list,
    output_file: str,
    score_column: str = "hyperscore"
) -> None:
    """
    Combine multiple PTM-specific SAGE result files into one deduplicated output.
    
    Args:
        ptm_result_files: List of paths to results.sage.tsv files (one per PTM)
        output_file: Path to write deduplicated output
        score_column: Column name to use for deduplication scoring (default: hyperscore)
    
    Returns:
        None (writes to output_file)
    
    Algorithm:
        1. Read all input TSV files
        2. Concatenate into single DataFrame
        3. Group by spectrum identifier (filename + scannr)
        4. For each spectrum group: keep row with maximum score_column value
        5. Sort and write deduplicated output
    """
    
    print(f"\n[AGGREGATE] Combining {len(ptm_result_files)} PTM result files...")
    
    # Read all result files
    dfs = []
    for result_file in ptm_result_files:
        if not Path(result_file).exists():
            print(f"  WARNING: Result file not found: {result_file}")
            continue
        
        try:
            df = pd.read_csv(result_file, sep='\t')
            print(f"  Loaded {len(df)} PSMs from {Path(result_file).parent.name}/results.sage.tsv")
            dfs.append(df)
        except Exception as e:
            print(f"  ERROR reading {result_file}: {e}")
            continue
    
    if not dfs:
        print("  ERROR: No result files could be read")
        raise ValueError("No valid PTM result files to aggregate")
    
    # Combine all results
    combined_df = pd.concat(dfs, ignore_index=True)
    print(f"\n  Total PSMs before deduplication: {len(combined_df)}")
    
    # Deduplicate by spectrum
    # Create spectrum identifier from filename + scannr
    combined_df['spectrum_id'] = combined_df['filename'] + '_' + combined_df['scannr'].astype(str)
    
    # Group by spectrum and keep highest scoring PSM
    if score_column not in combined_df.columns:
        print(f"  ERROR: Score column '{score_column}' not found in data")
        print(f"  Available columns: {list(combined_df.columns)}")
        raise ValueError(f"Score column '{score_column}' not in result files")
    
    # Sort by score_column descending, then drop duplicates keeping first (highest score)
    combined_df_sorted = combined_df.sort_values(
        by=score_column,
        ascending=False,
        na_position='last'
    )
    
    deduplicated_df = combined_df_sorted.drop_duplicates(
        subset=['spectrum_id'],
        keep='first'
    )
    
    # Remove temporary spectrum_id column
    deduplicated_df = deduplicated_df.drop(columns=['spectrum_id'])
    
    # Restore original column order (remove spectrum_id from columns list)
    original_columns = [col for col in combined_df.columns if col != 'spectrum_id']
    deduplicated_df = deduplicated_df[original_columns]
    
    # Sort by filename and scannr for consistency
    deduplicated_df = deduplicated_df.sort_values(
        by=['filename', 'scannr'],
        key=lambda x: x.astype('str') if x.name == 'scannr' else x
    )
    
    print(f"  Total PSMs after deduplication: {len(deduplicated_df)}")
    print(f"  Removed duplicates: {len(combined_df) - len(deduplicated_df)}")
    
    # Write output
    deduplicated_df.to_csv(output_file, sep='\t', index=False)
    print(f"\n[SUCCESS] Aggregated results written to: {output_file}")


def main():
    """Command-line interface for aggregation."""
    if len(sys.argv) < 3:
        print("Usage: aggregate_ptm_results.py <output_file> <input_file1> [input_file2] [input_file3] ...")
        print("  output_file: Path where aggregated results will be written")
        print("  input_files: One or more results.sage.tsv files from PTM searches")
        sys.exit(1)
    
    output_file = sys.argv[1]
    input_files = sys.argv[2:]
    
    aggregate_ptm_results(input_files, output_file)


if __name__ == '__main__':
    main()
