#!/usr/bin/env python3
"""
Comprehensive benchmarking script for HAMLET pipeline results.

Reports:
- Execution time per PXD and per stage
- Acquisition mode detected
- Organism taxids used in Peptonizer2000
- Failure reasons (if applicable)
- Overall execution statistics
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import sys


def get_acquisition_mode(pxd_dir: Path) -> Tuple[Optional[str], str]:
    """Extract acquisition mode from detected_params.json."""
    detected = pxd_dir / "detected_params.json"
    if not detected.exists():
        return None, "No detected_params.json"
    
    try:
        with open(detected) as f:
            data = json.load(f)
        acq_type = data.get('detected_params', {}).get('acquisition_type', 'Unknown')
        evidence = data.get('detected_params', {}).get('acquisition_evidence', '')
        return acq_type, evidence
    except Exception as e:
        return None, f"Error: {e}"


def get_peptonizer_taxids(pxd_dir: Path) -> Optional[str]:
    """Extract taxids used in Peptonizer2000 from config YAML files."""
    organism_dir = pxd_dir / "organism_results"
    if not organism_dir.exists():
        return None
    
    # Find the first peptonizer config file
    for config_file in organism_dir.rglob("*_config.yaml"):
        try:
            with open(config_file) as f:
                content = f.read()
            # Extract taxon_query line
            match = re.search(r"taxon_query:\s*'([^']+)'", content)
            if match:
                taxids = match.group(1)
                return taxids
        except:
            continue
    
    return None


def get_pipeline_timings(pxd_dir: Path) -> Tuple[Optional[Dict], Optional[str]]:
    """Extract process timings and status from pipeline JSON."""
    pipeline_json = pxd_dir / f"{pxd_dir.name}_pipeline.json"
    if not pipeline_json.exists():
        return None, "No pipeline JSON"
    
    try:
        with open(pipeline_json) as f:
            data = json.load(f)
        
        # Calculate total time
        start = datetime.fromisoformat(data['timestamp_start'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(data['timestamp_end'].replace('Z', '+00:00'))
        total_seconds = (end - start).total_seconds()
        
        # Group events by process and calculate durations
        process_events = {}
        for event in data.get('events', []):
            process = event.get('process', 'unknown')
            timestamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
            
            if process not in process_events:
                process_events[process] = {'start': timestamp, 'end': timestamp}
            else:
                # Update end timestamp for this process
                if timestamp > process_events[process]['end']:
                    process_events[process]['end'] = timestamp
        
        # Calculate process durations
        process_timings = {}
        for process, times in process_events.items():
            duration = (times['end'] - times['start']).total_seconds()
            process_timings[process] = duration
        
        timings = {
            'total_seconds': total_seconds,
            'processes': process_timings,
            'status': data.get('status', 'unknown'),
            'events': data.get('events', [])
        }
        
        return timings, None
    except Exception as e:
        return None, f"Error parsing JSON: {e}"


def get_failure_reasons(pxd_dir: Path, timings_data: Optional[Dict]) -> List[str]:
    """Extract failure/warning reasons from pipeline events."""
    if not timings_data or 'events' not in timings_data:
        return []
    
    reasons = []
    for event in timings_data['events']:
        category = event.get('category', '')
        message = event.get('message', '')
        details = event.get('details', {})
        
        if category in ['skip', 'error', 'warning']:
            if category == 'skip':
                reason = details.get('reason', message)
                reasons.append(f"[SKIP] {reason}")
            elif category == 'error':
                reasons.append(f"[ERROR] {message}")
            elif category == 'warning':
                reasons.append(f"[WARN] {message}")
    
    return reasons


def format_seconds(seconds: float) -> str:
    """Format seconds as human-readable string."""
    if seconds is None:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    elif m > 0:
        return f"{m}m {s}s"
    else:
        return f"{s}s"


def main():
    results_dir = Path("results")
    
    if not results_dir.exists():
        print("ERROR: results/ directory not found")
        sys.exit(1)
    
    # Collect data for all PXDs
    pxd_data = []
    total_execution_time = 0.0
    
    for pxd_dir in sorted(results_dir.glob("PXD*")):
        pxd_name = pxd_dir.name
        
        # Get acquisition mode
        acq_mode, acq_evidence = get_acquisition_mode(pxd_dir)
        
        # Get Peptonizer taxids
        taxids = get_peptonizer_taxids(pxd_dir)
        taxids_display = f"{taxids[:50]}..." if taxids and len(taxids) > 50 else taxids
        
        # Get pipeline timings
        timings, timing_error = get_pipeline_timings(pxd_dir)
        
        if timings:
            total_time_fmt = format_seconds(timings['total_seconds'])
            total_execution_time += timings['total_seconds']
            status = timings['status']
            
            # Get failure reasons
            failures = get_failure_reasons(pxd_dir, timings)
            
            # Process breakdowns
            process_str = "; ".join(
                f"{p}({format_seconds(d)})"
                for p, d in sorted(timings['processes'].items(), key=lambda x: x[1], reverse=True)
                if d >= 1  # Only show processes > 1 second
            )
        else:
            total_time_fmt = timing_error if timing_error else "Unknown"
            status = "No pipeline JSON"
            failures = []
            process_str = "N/A"
        
        pxd_data.append({
            'pxd': pxd_name,
            'total_time': timings['total_seconds'] if timings else 0,
            'total_time_fmt': total_time_fmt,
            'acq_mode': acq_mode or "Unknown",
            'acq_evidence': acq_evidence[:60] + "..." if len(acq_evidence) > 60 else acq_evidence,
            'taxids': taxids_display or "N/A",
            'status': status,
            'processes': process_str,
            'failures': failures
        })
    
    # Print header
    print("\n" + "="*140)
    print("HAMLET PIPELINE BENCHMARK REPORT")
    print("="*140)
    
    # Print summary table
    print("\n{:<15} {:<18} {:<10} {:<60} {:<20}".format(
        "PXD", "Total Time", "Acq Mode", "Detection Evidence", "Status"
    ))
    print("-"*140)
    
    for pxd in sorted(pxd_data, key=lambda x: x['total_time'], reverse=True):
        print("{:<15} {:<18} {:<10} {:<60} {:<20}".format(
            pxd['pxd'],
            pxd['total_time_fmt'],
            pxd['acq_mode'],
            pxd['acq_evidence'],
            pxd['status']
        ))
    
    # Print detailed breakdown
    print("\n" + "="*140)
    print("DETAILED PROCESS BREAKDOWN")
    print("="*140)
    
    for pxd in sorted(pxd_data, key=lambda x: x['total_time'], reverse=True):
        print(f"\n{pxd['pxd']}:")
        print(f"  Total Time:      {pxd['total_time_fmt']}")
        print(f"  Acq Mode:        {pxd['acq_mode']}")
        print(f"  Evidence:        {pxd['acq_evidence']}")
        print(f"  Status:          {pxd['status']}")
        print(f"  Processes:       {pxd['processes']}")
        print(f"  Taxids Used:     {pxd['taxids']}")
        
        if pxd['failures']:
            print(f"  Issues:")
            for failure in pxd['failures']:
                print(f"    • {failure}")
    
    # Print summary statistics
    print("\n" + "="*140)
    print("SUMMARY STATISTICS")
    print("="*140)
    print(f"Total PXDs:           {len(pxd_data)}")
    print(f"Total Execution Time: {format_seconds(total_execution_time)}")
    print(f"Average per PXD:      {format_seconds(total_execution_time / len(pxd_data)) if pxd_data else 'N/A'}")
    
    # Count by acquisition mode
    acq_modes = {}
    for pxd in pxd_data:
        mode = pxd['acq_mode']
        if mode not in acq_modes:
            acq_modes[mode] = 0
        acq_modes[mode] += 1
    
    print(f"\nAcquisition Modes:")
    for mode, count in sorted(acq_modes.items()):
        print(f"  {mode}: {count} PXD(s)")
    
    # Issues summary
    all_failures = [f for pxd in pxd_data for f in pxd['failures']]
    if all_failures:
        print(f"\nTotal Issues Found: {len(all_failures)}")
        for failure in all_failures:
            print(f"  • {failure}")
    else:
        print(f"\nNo issues found!")
    
    print("\n" + "="*140)


if __name__ == "__main__":
    main()
