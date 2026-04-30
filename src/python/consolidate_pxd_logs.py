#!/usr/bin/env python3
"""
Consolidate pipeline logs into unified JSON format.
Reads .jsonl events and merges with metadata files.
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict


def read_jsonl_file(filepath: str) -> list:
    """Read JSONL file and return list of event dicts."""
    events = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        print(f"WARNING: Could not parse JSON line in {filepath}: {e}", file=sys.stderr)
    except FileNotFoundError:
        pass  # Log file might not exist if process didn't run
    return events


def read_json_file(filepath: str) -> dict:
    """Read JSON file, return empty dict if not found."""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def collect_and_merge_events(output_dir: Path) -> list:
    """
    Collect and merge events from all subprocess directories.
    
    Scans for events.jsonl files in subprocess directories:
    - fetch/events.jsonl
    - organism/events.jsonl
    - search/events.jsonl
    - agentic/events.jsonl
    - llm/events.jsonl
    
    Also checks for root-level events.jsonl for backward compatibility.
    
    Args:
        output_dir: Path to PXD results directory (root)
    
    Returns:
        List of events sorted by timestamp (chronological order)
    """
    all_events = []
    
    # Subdirectories that may contain subprocess events
    subprocess_dirs = ["fetch", "organism", "search", "agentic", "llm"]
    
    # First, check for root-level events.jsonl (backward compatibility)
    root_events_file = output_dir / "events.jsonl"
    if root_events_file.exists():
        root_events = read_jsonl_file(str(root_events_file))
        all_events.extend(root_events)
        print(f"  Found {len(root_events)} events in root", file=sys.stderr)
    
    # Scan subprocess directories
    for subdir in subprocess_dirs:
        subprocess_dir = output_dir / subdir
        if subprocess_dir.exists() and subprocess_dir.is_dir():
            events_file = subprocess_dir / "events.jsonl"
            if events_file.exists():
                subprocess_events = read_jsonl_file(str(events_file))
                all_events.extend(subprocess_events)
                print(f"  Found {len(subprocess_events)} events in {subdir}/", file=sys.stderr)
    
    # Sort all events by timestamp (chronological order)
    # Handle missing/invalid timestamps gracefully
    try:
        all_events.sort(key=lambda x: x.get("timestamp", ""))
    except Exception as e:
        print(f"WARNING: Could not sort events by timestamp: {e}", file=sys.stderr)
    
    return all_events


def consolidate_logs(output_dir: str, pxd_id: str) -> dict:
    """
    Consolidate all pipeline logs into unified structure.
    
    Args:
        output_dir: Path to PXD results directory
        pxd_id: PXD identifier
    
    Returns:
        Consolidated log dictionary
    """
    output_dir = Path(output_dir)
    
    # Collect and merge events from all subprocess directories
    events = collect_and_merge_events(output_dir)
    
    # Read related metadata
    taxid_mapping = read_json_file(str(output_dir / "taxid_mapping.json"))
    taxid_warnings = read_json_file(str(output_dir / "taxid_warnings.json"))
    
    # Determine overall status
    error_count = sum(1 for e in events if e.get("level") == "ERROR")
    warning_count = sum(1 for e in events if e.get("level") == "WARNING")
    
    overall_status = "completed_with_errors" if error_count > 0 else (
        "completed_with_warnings" if warning_count > 0 else "completed_successfully"
    )
    
    # Extract timestamps
    start_time = events[0].get("timestamp") if events else datetime.utcnow().isoformat() + "Z"
    end_time = events[-1].get("timestamp") if events else datetime.utcnow().isoformat() + "Z"
    
    # Categorize events
    events_by_process = defaultdict(list)
    for event in events:
        process = event.get("process", "unknown")
        events_by_process[process].append(event)
    
    # Extract key findings
    key_findings = extract_key_findings(events, taxid_warnings)
    
    # Scan for missing outputs
    missing_outputs = scan_missing_outputs(output_dir, events)
    
    # Build consolidated log
    consolidated = {
        "pxd": pxd_id,
        "timestamp_start": start_time,
        "timestamp_end": end_time,
        "pipeline_version": "v2.0.0",
        "status": overall_status,
        
        # Event history
        "events": events,
        
        # Summary statistics
        "summary": {
            "total_events": len(events),
            "errors": error_count,
            "warnings": warning_count,
            "processes": sorted(list(events_by_process.keys())),
            "events_by_level": {
                "ERROR": sum(1 for e in events if e.get("level") == "ERROR"),
                "WARNING": sum(1 for e in events if e.get("level") == "WARNING"),
                "INFO": sum(1 for e in events if e.get("level") == "INFO"),
                "DEBUG": sum(1 for e in events if e.get("level") == "DEBUG"),
            }
        },
        
        # Key findings
        "key_findings": key_findings,
        
        # Missing outputs
        "missing_outputs": missing_outputs,
        
        # Metadata references
        "taxid_mapping": taxid_mapping.get("mappings", {}),
        "taxid_warnings": taxid_warnings.get("warnings", []),
    }
    
    return consolidated


def extract_key_findings(events: list, taxid_warnings: dict) -> dict:
    """Extract key findings from events."""
    findings = {
        "quality_issues": [],
        "skipped_processes": [],
        "decisions": [],
        "file_summary": {},
    }
    
    for event in events:
        category = event.get("category", "")
        level = event.get("level", "")
        message = event.get("message", "")
        details = event.get("details", {})
        
        # Quality gate decisions
        if "quality_gate" in message.lower() or category == "decision":
            findings["decisions"].append({
                "process": event.get("process"),
                "decision": message,
                "details": details,
                "timestamp": event.get("timestamp")
            })
        
        # Skip events
        if category == "skip":
            findings["skipped_processes"].append({
                "process": event.get("process"),
                "reason": message,
                "details": details,
                "timestamp": event.get("timestamp")
            })
        
        # Quality observations
        if "spectrum_q" in str(details).lower() or "high_confidence" in str(details).lower():
            findings["quality_issues"].append({
                "process": event.get("process"),
                "message": message,
                "details": details,
                "timestamp": event.get("timestamp")
            })
    
    return findings


def scan_missing_outputs(output_dir: Path, events: list) -> dict:
    """Scan directory structure and identify missing expected outputs."""
    missing = {}
    
    # Check for PTM-Shepherd skips
    ptm_skipped = any("ptm_shepherd" in str(e).lower() and e.get("category") == "skip" 
                     for e in events)
    if ptm_skipped:
        missing["ptm_shepherd_results"] = "Process was skipped"
    
    # Check for PASS 2 skips
    pass2_skipped = any("pass 2" in str(e).lower() or "closed" in str(e).lower() 
                       and e.get("category") == "skip" for e in events)
    if pass2_skipped:
        missing["pass2_closed_search"] = "Process was skipped"
    
    # Check actual files
    search_dir = output_dir / "search" / "dda_search"
    if search_dir.exists():
        if not (search_dir / "Closed").exists():
            missing["closed_search_results"] = "Directory not created"
    
    return missing


def main():
    parser = argparse.ArgumentParser(description="Consolidate PXD pipeline logs")
    parser.add_argument('--output_dir', required=True, help='PXD output directory')
    parser.add_argument('--pxd_id', required=True, help='PXD identifier')
    parser.add_argument('--output_file', default=None, help='Output JSON file (default: PXD_pipeline.json)')
    
    args = parser.parse_args()
    
    if not args.output_file:
        args.output_file = str(Path(args.output_dir) / f"{args.pxd_id}_pipeline.json")
    
    # Consolidate
    print(f"Collecting events from {args.output_dir}...", file=sys.stderr)
    consolidated = consolidate_logs(args.output_dir, args.pxd_id)
    
    # Write output
    output_path = Path(args.output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(consolidated, f, indent=2)
    
    print(f"Consolidated log written to: {output_path}")
    print(f"Total events collected: {len(consolidated['events'])}")
    print(f"Status: {consolidated['status']}")
    if consolidated['summary']['processes']:
        print(f"Processes: {', '.join(consolidated['summary']['processes'])}")


if __name__ == "__main__":
    main()
