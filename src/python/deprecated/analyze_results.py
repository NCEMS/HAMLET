#!/usr/bin/env python3
"""
HAMLET annotator Pipeline Test Results Analysis Tool

This script provides interactive exploration of aggregated pipeline results.
Generates summaries, statistics, and comparisons across test runs.
"""

import json
import os
from pathlib import Path
from collections import defaultdict
import argparse


def load_aggregated_results(pxd_id: str, results_dir: Path) -> dict:
    """Load aggregated results for a specific PXD."""
    json_file = results_dir / pxd_id / f"{pxd_id}_aggregated_results.json"
    if not json_file.exists():
        return None
    
    with open(json_file) as f:
        return json.load(f)


def analyze_sage_results(pxd_id: str, results_dir: Path) -> dict:
    """Analyze SAGE search results (Pass 1 and Pass 2)."""
    pxd_path = results_dir / pxd_id
    sage_results_dir = pxd_path / "sage_results"
    
    analysis = {
        'pass1_open_search': {
            'found': False,
            'psm_count': 0,
            'ptm_summary_found': False,
            'files': []
        },
        'pass2_closed_search': {
            'found': False,
            'directory_exists': False,
            'psm_count': 0,
            'has_meaningful_results': False,
            'files': []
        },
        'primary_output': {
            'found': False,
            'psm_count': 0,
        },
        'pass2_in_aggregated_json': False
    }
    
    if not sage_results_dir.exists():
        return analysis
    
    # Check Pass 1 (Open search)
    pass1_dir = sage_results_dir / "pass1_open_search"
    if pass1_dir.exists():
        analysis['pass1_open_search']['found'] = True
        analysis['pass1_open_search']['files'] = [f.name for f in pass1_dir.iterdir()]
        
        # Count PSMs in results.sage.tsv
        results_file = pass1_dir / "results.sage.tsv"
        if results_file.exists():
            try:
                with open(results_file) as f:
                    analysis['pass1_open_search']['psm_count'] = sum(1 for _ in f) - 1  # -1 for header
            except:
                pass
        
        # Check for PTM summary
        ptm_summary = pass1_dir / "global.modsummary.tsv"
        if ptm_summary.exists():
            analysis['pass1_open_search']['ptm_summary_found'] = True
    
    # Check Pass 2 (Closed search)
    pass2_dir = sage_results_dir / "pass2_closed_search"
    if pass2_dir.exists():
        analysis['pass2_closed_search']['directory_exists'] = True
        analysis['pass2_closed_search']['files'] = [f.name for f in pass2_dir.iterdir()]
        
        # Count PSMs in results.sage.tsv
        results_file = pass2_dir / "results.sage.tsv"
        if results_file.exists():
            try:
                with open(results_file) as f:
                    analysis['pass2_closed_search']['psm_count'] = sum(1 for _ in f) - 1  # -1 for header
                    # Mark as "meaningful" only if has PSMs
                    if analysis['pass2_closed_search']['psm_count'] > 0:
                        analysis['pass2_closed_search']['has_meaningful_results'] = True
                        analysis['pass2_closed_search']['found'] = True
            except:
                pass
    
    # Check if Pass 2 is in the aggregated JSON
    json_file = pxd_path / f"{pxd_id}_aggregated_results.json"
    if json_file.exists():
        try:
            with open(json_file) as f:
                data = json.load(f)
                if data.get('SAGE_results', {}).get('pass2_closed_search'):
                    analysis['pass2_in_aggregated_json'] = True
        except:
            pass
    
    # Check for primary output (should be in main sage_results dir)
    primary_results = sage_results_dir / "results.sage.tsv"
    if primary_results.exists():
        analysis['primary_output']['found'] = True
        try:
            with open(primary_results) as f:
                analysis['primary_output']['psm_count'] = sum(1 for _ in f) - 1  # -1 for header
        except:
            pass
    
    return analysis


def get_all_pxds(results_dir: Path) -> list:
    """Get all PXD directories in results folder."""
    return sorted([d.name for d in results_dir.iterdir() if d.is_dir()])


def print_pxd_summary(pxd_id: str, data: dict, results_dir: Path = None):
    """Print summary for a single PXD."""
    if not data:
        print(f"❌ {pxd_id}: No results found\n")
        return
    
    print(f"\n{'='*70}")
    print(f"PXD: {pxd_id}")
    print(f"{'='*70}")
    
    # Pride metadata
    pride = data.get('pride_metadata', {})
    print(f"\nTitle: {pride.get('title', 'N/A')}")
    if pride.get('organisms'):
        org = pride['organisms'][0]
        print(f"Organism: {org.get('name', 'Unknown')} (taxid: {org.get('accession', 'N/A')})")
    
    # Auto-detected params
    detected = data.get('detected_params', {}).get('detected_params', {})
    print(f"\nAcquisition: {detected.get('acquisition_type', 'Unknown')}")
    print(f"Labeling: {detected.get('labeling', 'Unknown')}")
    print(f"Fragmentation: {detected.get('fragmentation_type', 'Unknown')}")
    
    # Organism identification
    org_id = data.get('organism_identification', {}).get('summary', {})
    print(f"\nOrganism ID:")
    print(f"  Files processed: {org_id.get('num_files_processed', 'N/A')}")
    print(f"  Predictions: {org_id.get('total_predictions', 'N/A')}")
    print(f"  Threshold: {org_id.get('filter_thresholds_used', [80])}")
    
    # Processing status
    proc_summary = data.get('processing_summary', {})
    print(f"\nProcessing Status:")
    print(f"  runAssessor: {'✓' if proc_summary.get('runAssessor_found') else '✗'}")
    print(f"  Organism ID: {'✓' if proc_summary.get('organism_results_found') else '✗'}")
    print(f"  SAGE results: {'✓' if proc_summary.get('sage_results_found') else '✗'}")
    print(f"  PTM-Shepherd (open): {'✓' if proc_summary.get('ptm_shepherd_open_search_found') else '✗'}")
    print(f"  PTM-Shepherd (closed): {'✓' if proc_summary.get('ptm_shepherd_closed_search_found') else '✗'}")
    print(f"  LLM metadata: {'✓' if proc_summary.get('llm_metadata_found') else '✗'}")
    
    # SAGE search analysis (if results_dir provided)
    if results_dir:
        sage_analysis = analyze_sage_results(pxd_id, results_dir)
        print(f"\nSAGE Search Status:")
        print(f"  Pass 1 (Open Search):")
        if sage_analysis['pass1_open_search']['found']:
            psm_count = sage_analysis['pass1_open_search']['psm_count']
            ptm_found = "✓" if sage_analysis['pass1_open_search']['ptm_summary_found'] else "✗"
            print(f"    ✓ Found - {psm_count} PSMs | PTM Summary: {ptm_found}")
        else:
            print(f"    ✗ Not found")
        
        print(f"  Pass 2 (Closed Search):")
        if sage_analysis['pass2_closed_search']['found']:
            psm_count = sage_analysis['pass2_closed_search']['psm_count']
            print(f"    ✓ Found - {psm_count} PSMs")
        else:
            print(f"    ✗ Not found")
        
        print(f"  Primary Output:")
        if sage_analysis['primary_output']['found']:
            psm_count = sage_analysis['primary_output']['psm_count']
            print(f"    ✓ Found - {psm_count} PSMs")
        else:
            print(f"    ✗ Not found")
    
    # Taxid mapping
    taxid_map = data.get('taxid_mapping', {}).get('mappings', {})
    if taxid_map:
        print(f"\nTaxid Assignments:")
        for raw_file, info in list(taxid_map.items())[:3]:  # Show first 3
            print(f"  {raw_file[:50]}...")
            print(f"    → taxid: {info.get('taxid', 'N/A')} ({info.get('source', 'Unknown')})")
        if len(taxid_map) > 3:
            print(f"  ... and {len(taxid_map) - 3} more files")


def print_batch_statistics(results_dir: Path):
    """Print statistics across all PXDs."""
    pxds = get_all_pxds(results_dir)
    
    stats = {
        'total': 0,
        'runAssessor_success': 0,
        'organism_id_success': 0,
        'sage_success': 0,
        'ptm_shepherd_success': 0,
        'sage_pass1_found': 0,
        'sage_pass2_meaningful': 0,
        'sage_pass2_empty_dirs': 0,
        'sage_pass2_not_attempted': 0,
        'sage_pass2_in_json': 0,
        'sage_primary_output_found': 0,
        'pass1_total_psms': 0,
        'pass2_total_psms': 0,
        'pass2_empty_total_dirs': 0,
        'primary_total_psms': 0,
        'acquisition_types': defaultdict(int),
        'labeling_types': defaultdict(int),
        'organisms': defaultdict(int),
        'total_predictions': 0,
        'files_count': defaultdict(int),
    }
    
    print(f"\n{'='*70}")
    print(f"BATCH STATISTICS ({len(pxds)} PXDs)")
    print(f"{'='*70}\n")
    
    for pxd_id in pxds:
        data = load_aggregated_results(pxd_id, results_dir)
        if not data:
            continue
        
        stats['total'] += 1
        
        proc_summary = data.get('processing_summary', {})
        stats['runAssessor_success'] += 1 if proc_summary.get('runAssessor_found') else 0
        stats['organism_id_success'] += 1 if proc_summary.get('organism_results_found') else 0
        stats['sage_success'] += 1 if proc_summary.get('sage_results_found') else 0
        stats['ptm_shepherd_success'] += 1 if proc_summary.get('ptm_shepherd_open_search_found') else 0
        
        # SAGE search analysis
        sage_analysis = analyze_sage_results(pxd_id, results_dir)
        if sage_analysis['pass1_open_search']['found']:
            stats['sage_pass1_found'] += 1
            stats['pass1_total_psms'] += sage_analysis['pass1_open_search']['psm_count']
        
        # Detailed Pass 2 analysis
        if sage_analysis['pass2_closed_search']['directory_exists']:
            if sage_analysis['pass2_closed_search']['has_meaningful_results']:
                stats['sage_pass2_meaningful'] += 1
                stats['pass2_total_psms'] += sage_analysis['pass2_closed_search']['psm_count']
            else:
                # Directory exists but no PSMs
                stats['sage_pass2_empty_dirs'] += 1
                stats['pass2_empty_total_dirs'] += 1
        else:
            # No directory created (Pass 2 not attempted)
            stats['sage_pass2_not_attempted'] += 1
        
        if sage_analysis['pass2_in_aggregated_json']:
            stats['sage_pass2_in_json'] += 1
        
        if sage_analysis['primary_output']['found']:
            stats['sage_primary_output_found'] += 1
            stats['primary_total_psms'] += sage_analysis['primary_output']['psm_count']
        
        # Acquisition types
        detected = data.get('detected_params', {}).get('detected_params', {})
        acq_type = detected.get('acquisition_type', 'Unknown')
        stats['acquisition_types'][acq_type] += 1
        
        # Labeling types
        labeling = detected.get('labeling', 'Unknown')
        stats['labeling_types'][labeling] += 1
        
        # Organisms
        pride = data.get('pride_metadata', {})
        if pride.get('organisms'):
            org = pride['organisms'][0]
            org_name = org.get('name', 'Unknown')
            stats['organisms'][org_name] += 1
        
        # Predictions
        org_id = data.get('organism_identification', {}).get('summary', {})
        stats['total_predictions'] += org_id.get('total_predictions', 0)
        
        # Files
        num_files = org_id.get('num_files_processed', 0)
        stats['files_count'][num_files] += 1
    
    print(f"Total PXDs processed: {stats['total']}")
    print(f"\nProcessing Success Rates:")
    print(f"  runAssessor: {stats['runAssessor_success']}/{stats['total']} ({100*stats['runAssessor_success']/stats['total']:.1f}%)")
    print(f"  Organism ID: {stats['organism_id_success']}/{stats['total']} ({100*stats['organism_id_success']/stats['total']:.1f}%)")
    print(f"  SAGE search: {stats['sage_success']}/{stats['total']} ({100*stats['sage_success']/stats['total']:.1f}%)")
    print(f"  PTM-Shepherd: {stats['ptm_shepherd_success']}/{stats['total']} ({100*stats['ptm_shepherd_success']/stats['total']:.1f}%)")
    
    print(f"\nSAGE Search Results (DETAILED):")
    print(f"  Pass 1 (Open search): {stats['sage_pass1_found']}/{stats['total']} (100.0%)")
    if stats['sage_pass1_found'] > 0:
        print(f"    Total PSMs: {stats['pass1_total_psms']:,} (avg: {stats['pass1_total_psms']/stats['sage_pass1_found']:.0f} per PXD)")
    
    print(f"\n  Pass 2 (Closed search) - WITH MEANINGFUL RESULTS:")
    print(f"    {stats['sage_pass2_meaningful']}/{stats['total']} ({100*stats['sage_pass2_meaningful']/stats['total']:.1f}%)")
    if stats['sage_pass2_meaningful'] > 0:
        print(f"    Total PSMs: {stats['pass2_total_psms']:,} (avg: {stats['pass2_total_psms']/stats['sage_pass2_meaningful']:.0f} per PXD)")
    
    print(f"\n  Pass 2 (Closed search) - EMPTY DIRECTORIES (0 PSMs):")
    print(f"    {stats['sage_pass2_empty_dirs']}/{stats['total']} ({100*stats['sage_pass2_empty_dirs']/stats['total']:.1f}%)")
    
    print(f"\n  Pass 2 (Closed search) - NOT ATTEMPTED:")
    print(f"    {stats['sage_pass2_not_attempted']}/{stats['total']} ({100*stats['sage_pass2_not_attempted']/stats['total']:.1f}%)")
    
    print(f"\n  Pass 2 in aggregated JSON files:")
    print(f"    {stats['sage_pass2_in_json']}/{stats['total']} ({100*stats['sage_pass2_in_json']/stats['total']:.1f}%)")
    
    print(f"\n  Primary output: {stats['sage_primary_output_found']}/{stats['total']} (100.0%)")
    if stats['sage_primary_output_found'] > 0:
        print(f"    Total PSMs: {stats['primary_total_psms']:,} (avg: {stats['primary_total_psms']/stats['sage_primary_output_found']:.0f} per PXD)")
    
    print(f"\nAcquisition Types:")
    for acq_type, count in stats['acquisition_types'].items():
        print(f"  {acq_type}: {count}")
    
    print(f"\nLabeling Types:")
    for labeling, count in stats['labeling_types'].items():
        print(f"  {labeling}: {count}")
    
    print(f"\nOrganism Distribution:")
    for org, count in stats['organisms'].items():
        print(f"  {org}: {count}")
    
    print(f"\nFiles per Dataset:")
    for num_files, count in sorted(stats['files_count'].items()):
        print(f"  {num_files} files: {count} PXDs")
    
    print(f"\nTotal De Novo Predictions: {stats['total_predictions']}")
    if stats['total'] > 0:
        print(f"Average predictions per PXD: {stats['total_predictions']/stats['total']:.1f}")


def print_detailed_sage_analysis(pxd_id: str, data: dict):
    """Print detailed SAGE/PTM-Shepherd analysis."""
    if not data:
        print(f"No results for {pxd_id}")
        return
    
    print(f"\n{'='*70}")
    print(f"SAGE/PTM-Shepherd Analysis: {pxd_id}")
    print(f"{'='*70}\n")
    
    sage_results = data.get('SAGE_results', {})
    ptm_open = data.get('PTM-shepherd_open_search', {})
    ptm_closed = data.get('PTM-shepherd_closed_search', {})
    
    print("SAGE Results Structure:")
    if 'pass1_open_search' in sage_results:
        print("  ✓ Pass 1 (Open search) completed")
        if isinstance(sage_results['pass1_open_search'], dict):
            print(f"    Keys: {list(sage_results['pass1_open_search'].keys())[:5]}")
    else:
        print("  ✗ Pass 1 (Open search) not found")
    
    print("\nPTM-Shepherd Results:")
    if ptm_open:
        print(f"  Open search found: {len(ptm_open)} entries")
        if isinstance(ptm_open, dict):
            for key in list(ptm_open.keys())[:3]:
                print(f"    - {key}")
    else:
        print("  ✗ Open search results not found")
    
    if ptm_closed:
        print(f"  Closed search found: {len(ptm_closed)} entries")
    else:
        print("  ✗ Closed search results not found")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze HAMLET annotator pipeline test results'
    )
    parser.add_argument(
        '--results-dir',
        type=Path,
        default=Path('/mnt/storage_2/Pool1/results'),
        help='Path to results directory'
    )
    parser.add_argument(
        '--pxd',
        help='Specific PXD to analyze (default: show batch statistics)'
    )
    parser.add_argument(
        '--detailed-sage',
        action='store_true',
        help='Show detailed SAGE analysis for specified PXD'
    )
    parser.add_argument(
        '--all-summaries',
        action='store_true',
        help='Print summaries for all PXDs'
    )
    
    args = parser.parse_args()
    
    if not args.results_dir.exists():
        print(f"Error: Results directory not found: {args.results_dir}")
        return
    
    if args.pxd:
        data = load_aggregated_results(args.pxd, args.results_dir)
        print_pxd_summary(args.pxd, data, args.results_dir)
        
        if args.detailed_sage:
            print_detailed_sage_analysis(args.pxd, data)
    elif args.all_summaries:
        pxds = get_all_pxds(args.results_dir)
        for pxd_id in pxds:
            data = load_aggregated_results(pxd_id, args.results_dir)
            print_pxd_summary(pxd_id, data, args.results_dir)
    else:
        print_batch_statistics(args.results_dir)


if __name__ == '__main__':
    main()
