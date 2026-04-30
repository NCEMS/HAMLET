#!/usr/bin/env python3
"""
Aggregate all pipeline results into a single JSON output.
Combines study metadata, organism identification results, Search results, and PRIDE metadata.
"""

import argparse
import json
import os
import pandas as pd
from pathlib import Path
import glob
from datetime import datetime
import subprocess
import sys
import csv
import tempfile


def compute_modification_site_fractions(results_tsv_path: str, script_dir: str, include_hidden_mods: bool = True) -> dict:
    """
    Compute modification site fractions from a search_results.tsv file.
    
    Uses the mod_site_fractions.py script to calculate the fraction of potential
    modification sites that are actually modified for each PTM.
    
    Args:
        results_tsv_path: Path to search_results.tsv
        script_dir: Directory containing mod_site_fractions.py and unimod data
        
    Returns:
        Dict with modification site fraction data, or empty dict if computation fails
    """
    if not os.path.exists(results_tsv_path):
        print(f"Warning: Results TSV not found: {results_tsv_path}")
        return {}
    
    # Find mod_site_fractions.py
    mod_fractions_script = os.path.join(script_dir, "mod_site_fractions.py")
    if not os.path.exists(mod_fractions_script):
        print(f"Warning: mod_site_fractions.py not found at {mod_fractions_script}")
        return {}
    
    # Find unimod XML
    unimod_xml = os.path.join(script_dir, "..", "..", "assets", "unimod", "unimod_tables.xml")
    if not os.path.exists(unimod_xml):
        print(f"Warning: Unimod XML not found at {unimod_xml}")
        return {}
    
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False) as tmp:
            tmp_out = tmp.name
        
        # Run mod_site_fractions.py
        cmd = [
            sys.executable,
            mod_fractions_script,
            "--results", results_tsv_path,
            "--out", tmp_out,
            "--unimod-xml", unimod_xml,
        ]
        if include_hidden_mods:
            cmd.append("--include-hidden-mods")
            cmd.append("true")
        
        print(f"Running mod_site_fractions: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            print(f"Warning: mod_site_fractions.py failed with code {result.returncode}")
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            if os.path.exists(tmp_out):
                os.unlink(tmp_out)
            return {}
        
        # Read the output TSV
        if os.path.exists(tmp_out):
            try:
                df = pd.read_csv(tmp_out, sep='\t')
                mod_fractions_data = {
                    "num_mods_analyzed": int(len(df)),
                    "data": df.to_dict('records')
                }
                os.unlink(tmp_out)
                print(f"Successfully computed site fractions for {len(df)} modifications")
                return mod_fractions_data
            except Exception as e:
                print(f"Warning: Could not parse mod_site_fractions output: {e}")
                if os.path.exists(tmp_out):
                    os.unlink(tmp_out)
        
        return {}
        
    except subprocess.TimeoutExpired:
        print(f"Warning: mod_site_fractions.py timed out (>5 min)")
        return {}
    except Exception as e:
        print(f"Warning: Error computing modification site fractions: {e}")
        return {}


def load_runAssessor(pxd_dir):
    """Load study metadata from runAssessor/study_metadata.json"""
    # pxd_dir is passed from FetchPXD output, which creates this structure:
    # pxd_dir/runAssessor/study_metadata.json
    metadata_path = os.path.join(pxd_dir, "runAssessor", "study_metadata.json")
    
    if os.path.exists(metadata_path):
        print(f"Found study metadata at: {metadata_path}")
        with open(metadata_path, 'r') as f:
            return json.load(f)
    
    print(f"Study metadata not found at: {metadata_path}")
    return None


def load_organism_results(organism_dir):
    """Load organism identification results from peptonizer CSV files"""
    organism_results = []
    
    # Look for peptonizer result files with more flexible pattern matching
    patterns = [
        os.path.join(organism_dir, "**", "*_filtered*pct_slim", "Peptonizer2000_data", "*", "peptonizer_result.csv"),
        os.path.join(organism_dir, "**", "Peptonizer2000_data", "*_filtered*pct_slim", "peptonizer_result.csv"),
        os.path.join(organism_dir, "CasanovoSequence", "**", "Peptonizer2000_data", "*_filtered*pct_slim", "peptonizer_result.csv"),
    ]
    
    peptonizer_files = []
    for pattern in patterns:
        files = glob.glob(pattern, recursive=True)
        peptonizer_files.extend(files)
        if files:
            print(f"Found peptonizer files with pattern {pattern}: {files}")
    
    # Remove duplicates
    peptonizer_files = list(set(peptonizer_files))
    print(f"Total peptonizer files found: {len(peptonizer_files)}")
    
    for file_path in peptonizer_files:
        try:
            df = pd.read_csv(file_path)
            # Convert DataFrame to dictionary format
            result = {
                "file_path": file_path,
                "filter_threshold": extract_threshold_from_path(file_path),
                "num_predictions": len(df),
                "columns": df.columns.tolist(),
                "data": df.to_dict('records')  # Convert to list of dictionaries
            }
            organism_results.append(result)
        except Exception as e:
            print(f"Warning: Could not load {file_path}: {e}")
    
    return organism_results


def extract_threshold_from_path(file_path):
    """Extract filter threshold from file path like *_filtered70pct_slim*"""
    import re
    match = re.search(r'filtered(\d+)pct', file_path)
    return int(match.group(1)) if match else None


def load_llm_results(llm_results_dir):
    """Load LLM-extracted metadata from publications"""
    if llm_results_dir == "/dev/null":
        print("No LLM results directory provided")
        return None
    
    # Look for the LLM extraction results
    # The file should be named {PXD}_Metadata.json
    metadata_files = glob.glob(os.path.join(llm_results_dir, "**", "*_Metadata.json"), recursive=True)
    
    if not metadata_files:
        print(f"No LLM metadata files found in {llm_results_dir}")
        # Check for empty.json (created when API key not set)
        empty_json = os.path.join(llm_results_dir, "empty.json")
        if os.path.exists(empty_json):
            print("Found empty.json - LLM extraction was skipped")
        return None
    
    print(f"Found {len(metadata_files)} LLM metadata file(s)")
    
    # Load the first (should be only one) metadata file
    try:
        with open(metadata_files[0], 'r') as f:
            llm_data = json.load(f)
        print(f"Successfully loaded LLM metadata from {metadata_files[0]}")
        return llm_data
    except Exception as e:
        print(f"Error loading LLM metadata: {e}")
        return None


def load_sage_results(sage_results_dir):
    """Load search results.

    Supports both:
      - Current layout from src/python/search_orchestrator.py:
          search/dda_search/Open + Closed
          search/modifications
          search/dia_search
      - Legacy layout:
          search/pass1_open_search + pass2_closed_search
    """

    if sage_results_dir == "/dev/null":
        print("SAGE results directory is /dev/null - skipping")
        return None

    if not os.path.exists(sage_results_dir):
        print(f"SAGE results directory does not exist: {sage_results_dir}")
        return None

    published_prefix = os.path.basename(os.path.normpath(sage_results_dir)) or "search"
    if published_prefix not in ("search", "sage_results"):
        published_prefix = "search"

    def _pub(rel_path: str) -> str:
        return f"{published_prefix}/{rel_path.lstrip('/')}"

    def _safe_unique(series):
        try:
            return int(series.nunique())
        except Exception:
            return None

    def _protein_count(df):
        if 'proteins' not in df.columns:
            return None
        try:
            return int(df['proteins'].fillna('').astype(str).str.split(';').str.len().sum())
        except Exception:
            return None

    # --- New layout ---
    has_new_layout = any(
        os.path.exists(os.path.join(sage_results_dir, p))
        for p in ["dda_search", "dia_search", "modifications"]
    )

    if has_new_layout:
        print(f"Detected new search results layout in {sage_results_dir}")

        sage_data = {
            "PTM-shepherd_open_search": None,
            "PTM-shepherd_closed_search": None,
            "Search_and_modification_results": {},
        }

        # PTM-Shepherd summary + validated PTMs
        mods_dir = os.path.join(sage_results_dir, "modifications")
        ptm_summary_path = os.path.join(mods_dir, "global.modsummary.tsv")
        if os.path.exists(ptm_summary_path):
            try:
                ptm_df = pd.read_csv(ptm_summary_path, sep='\t')
                sage_data["PTM-shepherd_open_search"] = {
                    "file_path": _pub("modifications/global.modsummary.tsv"),
                    "num_modifications": int(len(ptm_df)),
                    "data": ptm_df.to_dict('records'),
                }
            except Exception as e:
                print(f"Warning: Could not load PTM summary: {e}")

        validated_ptms_path = os.path.join(mods_dir, "validated_ptms.json")
        if os.path.exists(validated_ptms_path):
            try:
                with open(validated_ptms_path, 'r') as f:
                    validated = json.load(f)
                sage_data["validated_ptms"] = {
                    "file_path": _pub("modifications/validated_ptms.json"),
                    "data": validated,
                }
            except Exception as e:
                print(f"Warning: Could not load validated PTMs: {e}")

        # DDA open/closed
        open_psm_path = os.path.join(sage_results_dir, "dda_search", "Open", "search_results.tsv")
        open_psm_legacy_path = os.path.join(sage_results_dir, "dda_search", "Open", "results.sage.tsv")
        closed_psm_path = os.path.join(sage_results_dir, "dda_search", "Closed", "search_results.tsv")
        closed_psm_legacy_path = os.path.join(sage_results_dir, "dda_search", "Closed", "results.sage.tsv")

        if os.path.exists(open_psm_path) or os.path.exists(open_psm_legacy_path):
            try:
                psm_path = open_psm_path if os.path.exists(open_psm_path) else open_psm_legacy_path
                df = pd.read_csv(psm_path, sep='\t')
                sage_data["Search_and_modification_results"]["pass1_open_search"] = {
                    "psm_file": _pub(f"dda_search/Open/{os.path.basename(psm_path)}"),
                    "results_json": _pub("dda_search/Open/results.json"),
                    "num_psms": int(len(df)),
                    "num_unique_peptides": _safe_unique(df.get('peptide')) if 'peptide' in df.columns else None,
                    "num_unique_proteins": _protein_count(df),
                }
            except Exception as e:
                print(f"Warning: Could not load DDA open results: {e}")

        if os.path.exists(closed_psm_path) or os.path.exists(closed_psm_legacy_path):
            try:
                psm_path = closed_psm_path if os.path.exists(closed_psm_path) else closed_psm_legacy_path
                df = pd.read_csv(psm_path, sep='\t')
                closed_entry = {
                    "psm_file": _pub(f"dda_search/Closed/{os.path.basename(psm_path)}"),
                    "results_json": _pub("dda_search/Closed/results.json"),
                    "num_psms": int(len(df)),
                    "num_unique_peptides": _safe_unique(df.get('peptide')) if 'peptide' in df.columns else None,
                    "num_unique_proteins": _protein_count(df),
                }

                # Per-file statistics if available
                if all(c in df.columns for c in ['filename', 'psm_id', 'peptide']):
                    by_file = df.groupby('filename').agg({'psm_id': 'count', 'peptide': 'nunique'})
                    closed_entry["quantification"] = {
                        "method": "LFQ",
                        "per_file_statistics": {
                            str(fname): {
                                "num_psms": int(row['psm_id']),
                                "num_unique_peptides": int(row['peptide']),
                            }
                            for fname, row in by_file.iterrows()
                        },
                    }

                sage_data["Search_and_modification_results"]["pass2_closed_search"] = closed_entry
            except Exception as e:
                print(f"Warning: Could not load DDA closed results: {e}")

        # DIA (DIA-NN)
        dia_dir = os.path.join(sage_results_dir, "dia_search")
        if os.path.exists(dia_dir):
            dia_entry = {}

            dia_results_path = os.path.join(dia_dir, "search_results.tsv")
            dia_legacy_results_path = os.path.join(dia_dir, "results.sage.tsv")
            dia_psm_path = dia_results_path if os.path.exists(dia_results_path) else dia_legacy_results_path
            if os.path.exists(dia_psm_path):
                dia_entry["psm_file"] = _pub(f"dia_search/{os.path.basename(dia_psm_path)}")
                try:
                    df = pd.read_csv(dia_psm_path, sep='\t')
                    dia_entry["num_rows"] = int(len(df))
                    dia_entry["num_unique_peptides"] = (
                        _safe_unique(df.get('Peptide')) if 'Peptide' in df.columns else
                        _safe_unique(df.get('peptide')) if 'peptide' in df.columns else
                        None
                    )
                except Exception as e:
                    print(f"Warning: Could not load DIA results.sage.tsv: {e}")

            diann_report_tsv = os.path.join(dia_dir, "report.tsv")
            diann_report_parquet = os.path.join(dia_dir, "report.parquet")
            diann_stats_tsv = os.path.join(dia_dir, "report.stats.tsv")
            diann_log_txt = os.path.join(dia_dir, "report.log.txt")

            if os.path.exists(diann_report_parquet):
                dia_entry["diann_report"] = _pub("dia_search/report.parquet")
            elif os.path.exists(diann_report_tsv):
                dia_entry["diann_report"] = _pub("dia_search/report.tsv")

            if os.path.exists(diann_stats_tsv):
                dia_entry["diann_stats"] = {"file_path": _pub("dia_search/report.stats.tsv")}
                try:
                    stats_df = pd.read_csv(diann_stats_tsv, sep='\t')
                    dia_entry["diann_stats"]["data"] = stats_df.to_dict('records')
                    if len(stats_df) > 0:
                        dia_entry["precursors_identified"] = int(stats_df.iloc[0].get('Precursors.Identified')) if 'Precursors.Identified' in stats_df.columns else None
                        dia_entry["proteins_identified"] = int(stats_df.iloc[0].get('Proteins.Identified')) if 'Proteins.Identified' in stats_df.columns else None
                except Exception as e:
                    print(f"Warning: Could not load DIA-NN stats TSV: {e}")

            if os.path.exists(diann_log_txt):
                dia_entry["diann_log"] = _pub("dia_search/report.log.txt")

            results_json_path = os.path.join(dia_dir, "results.json")
            if os.path.exists(results_json_path):
                dia_entry["results_json"] = _pub("dia_search/results.json")

            if dia_entry:
                sage_data["Search_and_modification_results"]["dia_search"] = dia_entry

        if any(v is not None for v in sage_data.values() if v is not None):
            return sage_data

        print(f"No recognizable search results found in {sage_results_dir}")
        return None

    # --- Legacy layout fallback ---
    print(f"Detected legacy search results layout in {sage_results_dir}")

    sage_data = {}

    ptm_open_path = os.path.join(sage_results_dir, "pass1_open_search", "global.modsummary.tsv")
    ptm_closed_path = os.path.join(sage_results_dir, "pass2_closed_search", "global.modsummary.tsv")

    if os.path.exists(ptm_open_path):
        print(f"Found open search PTM-Shepherd results at: {ptm_open_path}")
        try:
            ptm_open_df = pd.read_csv(ptm_open_path, sep='\t')
            sage_data["PTM-shepherd_open_search"] = {
                "file_path": _pub("pass1_open_search/global.modsummary.tsv"),
                "num_modifications": len(ptm_open_df),
                "data": ptm_open_df.to_dict('records')
            }
        except Exception as e:
            print(f"Warning: Could not load open search PTM results: {e}")
            sage_data["PTM-shepherd_open_search"] = None

    if os.path.exists(ptm_closed_path):
        print(f"Found closed search PTM-Shepherd results at: {ptm_closed_path}")
        try:
            ptm_closed_df = pd.read_csv(ptm_closed_path, sep='\t')
            sage_data["PTM-shepherd_closed_search"] = {
                "file_path": _pub("pass2_closed_search/global.modsummary.tsv"),
                "num_modifications": len(ptm_closed_df),
                "data": ptm_closed_df.to_dict('records')
            }
        except Exception as e:
            print(f"Warning: Could not load closed search PTM results: {e}")
            sage_data["PTM-shepherd_closed_search"] = None
    else:
        sage_data["PTM-shepherd_closed_search"] = None

    pass1_psm_path = os.path.join(sage_results_dir, "pass1_open_search", "search_results.tsv")
    pass1_psm_legacy_path = os.path.join(sage_results_dir, "pass1_open_search", "results.sage.tsv")
    pass2_psm_path = os.path.join(sage_results_dir, "pass2_closed_search", "search_results.tsv")
    pass2_psm_legacy_path = os.path.join(sage_results_dir, "pass2_closed_search", "results.sage.tsv")

    sage_results = {}

    if os.path.exists(pass1_psm_path) or os.path.exists(pass1_psm_legacy_path):
        psm_path = pass1_psm_path if os.path.exists(pass1_psm_path) else pass1_psm_legacy_path
        print(f"Found pass 1 PSM results at: {psm_path}")
        try:
            pass1_psm = pd.read_csv(psm_path, sep='\t')
            sage_results["pass1_open_search"] = {
                "psm_file": _pub(f"pass1_open_search/{os.path.basename(psm_path)}"),
                "results_json": _pub("pass1_open_search/results.json"),
                "num_psms": int(len(pass1_psm)),
                "num_unique_peptides": int(pass1_psm['peptide'].nunique()) if 'peptide' in pass1_psm.columns else None,
                "num_unique_proteins": _protein_count(pass1_psm),
            }
        except Exception as e:
            print(f"Warning: Could not load pass 1 PSM results: {e}")
            sage_results["pass1_open_search"] = None

    if os.path.exists(pass2_psm_path) or os.path.exists(pass2_psm_legacy_path):
        psm_path = pass2_psm_path if os.path.exists(pass2_psm_path) else pass2_psm_legacy_path
        print(f"Found pass 2 PSM results at: {psm_path}")
        try:
            pass2_psm = pd.read_csv(psm_path, sep='\t')

            closed_entry = {
                "psm_file": _pub(f"pass2_closed_search/{os.path.basename(psm_path)}"),
                "results_json": _pub("pass2_closed_search/results.json"),
                "num_psms": int(len(pass2_psm)),
                "num_unique_peptides": int(pass2_psm['peptide'].nunique()) if 'peptide' in pass2_psm.columns else None,
                "num_unique_proteins": _protein_count(pass2_psm),
            }

            if all(c in pass2_psm.columns for c in ['filename', 'psm_id', 'peptide']):
                by_file = pass2_psm.groupby('filename').agg({'psm_id': 'count', 'peptide': 'nunique'})
                closed_entry["quantification"] = {
                    "method": "LFQ",
                    "per_file_statistics": {
                        str(fname): {
                            "num_psms": int(row['psm_id']),
                            "num_unique_peptides": int(row['peptide']),
                        }
                        for fname, row in by_file.iterrows()
                    },
                }

            sage_results["pass2_closed_search"] = closed_entry
        except Exception as e:
            print(f"Warning: Could not load pass 2 PSM results: {e}")
            sage_results["pass2_closed_search"] = None

    if sage_data or sage_results:
        return {
            "PTM-shepherd_open_search": sage_data.get("PTM-shepherd_open_search"),
            "PTM-shepherd_closed_search": sage_data.get("PTM-shepherd_closed_search"),
            "Search_and_modification_results": sage_results if sage_results else None
        }

    print(f"SAGE results not found in {sage_results_dir}")
    return None


def load_pride_metadata(pride_json_dir, pxd_id, pxd_dir=None):
    """Load PRIDE metadata from JSON file
    
    First looks in pxd_dir for {pxd_id}_PRIDEmetadata.json (created by FetchPXD.py)
    Then falls back to pride_json_dir for {pxd_id}.json (legacy external source)
    """
    # First check: FetchPXD.py creates this file in pxd_dir
    if pxd_dir:
        fetched_pride_file = os.path.join(pxd_dir, f"{pxd_id}_PRIDEmetadata.json")
        if os.path.exists(fetched_pride_file):
            with open(fetched_pride_file, 'r') as f:
                return json.load(f)
    
    # Fallback: Legacy external PRIDE metadata directory
    pride_file = os.path.join(pride_json_dir, f"{pxd_id}.json")
    if os.path.exists(pride_file):
        with open(pride_file, 'r') as f:
            return json.load(f)
    
    return None


def aggregate_results(pxd_id, pxd_dir, organism_dir, sage_results_dir, llm_results_dir, pride_json_dir, taxid_warnings, output_file, include_hidden_mods=True):
    """
    Aggregate all pipeline results for a single PXD into a unified JSON structure
    """
    
    print(f"Aggregating results for {pxd_id}...")
    print(f"Input paths: pxd_dir={pxd_dir}, organism_dir={organism_dir}, sage_results_dir={sage_results_dir}, llm_results_dir={llm_results_dir}")
    
    # Debug: List what's actually in the directories
    print("=== Debugging directory contents ===")
    for name, path in [("PXD dir", pxd_dir), ("Organism dir", organism_dir), ("SAGE dir", sage_results_dir), ("LLM dir", llm_results_dir)]:
        if os.path.exists(path) and path != "/dev/null":
            print(f"{name} contents:")
            for root, dirs, files in os.walk(path):
                level = root.replace(path, '').count(os.sep)
                indent = ' ' * 2 * level
                print(f"{indent}{os.path.basename(root)}/")
                subindent = ' ' * 2 * (level + 1)
                for file in files[:5]:  # Limit to first 5 files per directory
                    print(f"{subindent}{file}")
                if len(files) > 5:
                    print(f"{subindent}... and {len(files)-5} more files")
                if level > 3:  # Limit depth
                    break
        else:
            print(f"{name}: Not found or is /dev/null")
    print("=" * 40)
    
    # Initialize the main results structure
    aggregated_results = {
        "pxd_id": pxd_id,
        "pipeline_version": "1.0",
        "aggregation_timestamp": datetime.now().isoformat(),
        "input_paths": {
            "pxd_dir": pxd_dir,
            "organism_dir": organism_dir,
            "sage_results_dir": sage_results_dir,
            "llm_results_dir": llm_results_dir,
            "pride_json_dir": pride_json_dir,
            "taxid_warnings": taxid_warnings
        },
        "runAssessor": None,
        "organism_identification": {
            "results": [],
            "summary": {}
        },
        "PTM-shepherd_open_search": None,
        "PTM-shepherd_closed_search": None,
        "Search_and_modification_results": None,
        "modification_site_fractions": None,
        "pride_metadata": None,
        "taxid_warnings": None,
        "processing_summary": {}
    }
    
    # Load study metadata
    print("Loading study metadata...")
    runAssessor = load_runAssessor(pxd_dir)
    aggregated_results["runAssessor"] = runAssessor
    
    # Load organism identification results
    print("Loading organism identification results...")
    organism_results = load_organism_results(organism_dir)
    aggregated_results["organism_identification"]["results"] = organism_results
    
    # Create organism summary
    if organism_results:
        total_predictions = sum(r.get("num_predictions", 0) for r in organism_results)
        thresholds = [r.get("filter_threshold") for r in organism_results if r.get("filter_threshold")]
        aggregated_results["organism_identification"]["summary"] = {
            "num_files_processed": len(organism_results),
            "total_predictions": total_predictions,
            "filter_thresholds_used": sorted(set(thresholds)) if thresholds else []
        }
    
    # Load SAGE results
    print("Loading SAGE analysis results...")
    sage_results = load_sage_results(sage_results_dir)
    if sage_results:
        # Unpack the combined structure
        aggregated_results["PTM-shepherd_open_search"] = sage_results.get("PTM-shepherd_open_search")
        aggregated_results["PTM-shepherd_closed_search"] = sage_results.get("PTM-shepherd_closed_search")
        aggregated_results["Search_and_modification_results"] = sage_results.get("Search_and_modification_results")
    
    # Load LLM extraction results
    print("Loading LLM extracted metadata...")
    llm_results = load_llm_results(llm_results_dir)
    aggregated_results["llm_extracted_metadata"] = llm_results
    
    # Load taxid warnings
    print("Loading taxid determination warnings...")
    taxid_warnings_data = None
    if taxid_warnings and os.path.exists(taxid_warnings):
        try:
            with open(taxid_warnings, 'r') as f:
                taxid_warnings_data = json.load(f)
            print(f"Successfully loaded taxid warnings from {taxid_warnings}")
        except Exception as e:
            print(f"Error loading taxid warnings: {e}")
    aggregated_results["taxid_warnings"] = taxid_warnings_data
    
    # Load PRIDE metadata
    print("Loading PRIDE metadata...")
    pride_metadata = load_pride_metadata(pride_json_dir, pxd_id, pxd_dir=pxd_dir)
    aggregated_results["pride_metadata"] = pride_metadata
    
    # Compute modification site fractions for DDA (closed search) and DIA
    print("Computing modification site fractions...")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    mod_fractions_data = {}
    
    # For DDA closed search - load per-file mod_site_fractions from AGGREGATED directories
    if (aggregated_results.get("Search_and_modification_results") and 
        aggregated_results["Search_and_modification_results"].get("pass2_closed_search")):
        dda_closed_psm = aggregated_results["Search_and_modification_results"]["pass2_closed_search"].get("psm_file")
        if dda_closed_psm:
            # Get the Closed directory path (e.g., search/dda_search/Closed)
            closed_dir_path = os.path.dirname(os.path.join(sage_results_dir, dda_closed_psm.split("/", 1)[1]))
            aggregated_dir = os.path.join(closed_dir_path, "AGGREGATED")
            
            print(f"Looking for per-file mod_site_fractions in: {aggregated_dir}")
            
            if os.path.exists(aggregated_dir):
                # Find all sample file directories in AGGREGATED
                sample_dirs = []
                try:
                    sample_dirs = [d for d in os.listdir(aggregated_dir) 
                                   if os.path.isdir(os.path.join(aggregated_dir, d))]
                    sample_dirs.sort()
                except Exception as e:
                    print(f"Warning: Could not list AGGREGATED directories: {e}")
                
                print(f"Found {len(sample_dirs)} sample file directories: {sample_dirs}")
                
                # Load mod_site_fractions for each sample
                per_file_fractions = {}
                for sample_dir in sample_dirs:
                    mod_frac_file = os.path.join(aggregated_dir, sample_dir, "mod_site_fractions.tsv")
                    if os.path.exists(mod_frac_file):
                        try:
                            df = pd.read_csv(mod_frac_file, sep='\t')
                            per_file_fractions[sample_dir] = {
                                "num_mods_analyzed": int(len(df)),
                                "data": df.to_dict('records')
                            }
                            print(f"  Loaded mod_site_fractions for {sample_dir}: {len(df)} modifications")
                        except Exception as e:
                            print(f"  Warning: Could not load mod_site_fractions for {sample_dir}: {e}")
                    else:
                        print(f"  Warning: mod_site_fractions.tsv not found for {sample_dir}")
                
                if per_file_fractions:
                    mod_fractions_data["dda_closed_search"] = {
                        "per_sample_files": per_file_fractions,
                        "summary": {
                            "num_sample_files": len(per_file_fractions),
                            "sample_files": list(per_file_fractions.keys())
                        }
                    }
                    print(f"Successfully loaded per-file mod_site_fractions for {len(per_file_fractions)} samples")
            else:
                print(f"AGGREGATED directory not found at: {aggregated_dir}")
    
    # For DIA search
    if (aggregated_results.get("Search_and_modification_results") and 
        aggregated_results["Search_and_modification_results"].get("dia_search")):
        dia_psm = aggregated_results["Search_and_modification_results"]["dia_search"].get("psm_file")
        if dia_psm:
            # psm_file is like "search/dia_search/search_results.tsv"
            # Remove "search/" prefix and join with sage_results_dir
            rel_path = dia_psm.split("/", 1)[1] if "/" in dia_psm else dia_psm
            dia_path = os.path.join(sage_results_dir, rel_path)
            print(f"Computing DIA search site fractions from: {dia_path}")
            dia_fractions = compute_modification_site_fractions(dia_path, script_dir, include_hidden_mods=include_hidden_mods)
            if dia_fractions:
                mod_fractions_data["dia_search"] = dia_fractions
    
    if mod_fractions_data:
        aggregated_results["modification_site_fractions"] = mod_fractions_data
        print(f"Added modification site fractions for {len(mod_fractions_data)} search types")
    
    # Create processing summary
    aggregated_results["processing_summary"] = {
        "runAssessor_found": runAssessor is not None,
        "organism_results_found": len(organism_results) > 0,
        "ptm_shepherd_open_search_found": aggregated_results["PTM-shepherd_open_search"] is not None,
        "ptm_shepherd_closed_search_found": aggregated_results["PTM-shepherd_closed_search"] is not None,
        "sage_results_found": aggregated_results["Search_and_modification_results"] is not None,
        "modification_site_fractions_found": aggregated_results.get("modification_site_fractions") is not None,
        "llm_metadata_found": llm_results is not None,
        "pride_metadata_found": pride_metadata is not None,
        "consolidated_pipeline_found": True,  # Will be added after consolidation
        "total_data_files": len(organism_results) + (1 if aggregated_results["Search_and_modification_results"] else 0)
    }
    
    # Save aggregated results
    print(f"Saving aggregated results to {output_file}...")
    output_dir = os.path.dirname(output_file)
    if output_dir:  # Only create directory if output_file has a directory path
        os.makedirs(output_dir, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(aggregated_results, f, indent=2, default=str)
    
    print(f"Successfully aggregated results for {pxd_id}")
    print(f"Summary: {aggregated_results['processing_summary']}")
    
    return aggregated_results


def main():
    parser = argparse.ArgumentParser(description='Aggregate all pipeline results into a single JSON file')
    parser.add_argument('--pxd_id', required=True, help='PXD identifier (e.g., PXD023343)')
    parser.add_argument('--pxd_dir', required=True, help='Directory containing the PXD data with runAssessor subdirectory')
    parser.add_argument('--organism_dir', required=True, help='Directory containing organism identification results')
    parser.add_argument('--sage_results_dir', required=True, help='Directory containing SAGE results')
    parser.add_argument('--llm_results_dir', required=True, help='Directory containing LLM extraction results')
    parser.add_argument('--taxid_warnings', help='JSON file containing taxid determination warnings')
    parser.add_argument('--pride_json_dir', default='/data/20250927/pride_json', 
                       help='Directory containing PRIDE metadata JSON files')
    parser.add_argument('--output_file', required=True, help='Output JSON file path')
    
    args = parser.parse_args()
    
    # Validate input paths
    for path_name, path_value in [("pxd_dir", args.pxd_dir), ("organism_dir", args.organism_dir), 
                                  ("sage_results_dir", args.sage_results_dir), ("llm_results_dir", args.llm_results_dir),
                                  ("pride_json_dir", args.pride_json_dir)]:
        if not os.path.exists(path_value):
            print(f"Warning: {path_name} does not exist: {path_value}")
    
    # Run aggregation
    results = aggregate_results(
        pxd_id=args.pxd_id,
        pxd_dir=args.pxd_dir,
        organism_dir=args.organism_dir,
        sage_results_dir=args.sage_results_dir,
        llm_results_dir=args.llm_results_dir,
        pride_json_dir=args.pride_json_dir,
        taxid_warnings=args.taxid_warnings,
        output_file=args.output_file
    )
    
    # Consolidate pipeline logs if they exist
    try:
        # Import consolidation tools
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from consolidate_pxd_logs import consolidate_logs
        from format_pxd_summary import format_markdown
        
        # Use current working directory as output_dir (where script is running from)
        # In Nextflow context, this is the PXD directory
        output_dir = os.getcwd()
        
        # Run consolidation
        consolidated_log = consolidate_logs(output_dir, args.pxd_id)
        log_file = os.path.join(output_dir, f"{args.pxd_id}_pipeline.json")
        
        with open(log_file, 'w') as f:
            json.dump(consolidated_log, f, indent=2)
        print(f"Consolidated pipeline log written to: {log_file}")
        
        # Replace taxid_warnings with consolidated log in aggregated results
        # The consolidated log contains all event history including warnings, so it replaces the old taxid_warnings
        results["consolidated_pipeline"] = consolidated_log
        del results["taxid_warnings"]  # Remove redundant taxid_warnings section
        
        # Re-write aggregated results with consolidated log included (replacing taxid_warnings)
        output_file = args.output_file
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"Updated aggregated results with consolidated pipeline log: {output_file}")
        
        # Generate markdown summary
        markdown_file = os.path.join(output_dir, f"{args.pxd_id}_pipeline_summary.md")
        markdown_content = format_markdown(consolidated_log)
        
        with open(markdown_file, 'w') as f:
            f.write(markdown_content)
        print(f"Markdown summary written to: {markdown_file}")
        
    except Exception as e:
        print(f"Warning: Could not consolidate logs: {e}")
    
    print("Aggregation completed successfully!")


if __name__ == "__main__":
    main()