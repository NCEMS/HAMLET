#!/usr/bin/env python3
"""
Unified Search Orchestrator for DDA and DIA Experiments

Routes DDA experiments through SAGE two-pass search (open + PTM-Shepherd + closed)
Routes DIA experiments through DIA-NN search
Harmonizes output to SAGE TSV format for downstream compatibility
Organizes results into nested directory structure with metadata
"""

import argparse
import json
import os
import re
import subprocess
import shutil
from pathlib import Path
import sys
import pandas as pd

# Add parent directory to path for importing PipelineLogger
sys.path.insert(0, str(Path(__file__).parent))
from PipelineLogger import PipelineLogger
from unimod_utils import load_unimod_index


SAGE_PSM_COLUMNS = [
    "psm_id",
    "peptide",
    "proteins",
    "num_proteins",
    "filename",
    "scannr",
    "rank",
    "label",
    "expmass",
    "calcmass",
    "charge",
    "peptide_len",
    "missed_cleavages",
    "semi_enzymatic",
    "isotope_error",
    "precursor_ppm",
    "fragment_ppm",
    "hyperscore",
    "delta_next",
    "delta_best",
    "rt",
    "aligned_rt",
    "predicted_rt",
    "delta_rt_model",
    "ion_mobility",
    "predicted_mobility",
    "delta_mobility",
    "matched_peaks",
    "longest_b",
    "longest_y",
    "longest_y_pct",
    "matched_intensity_pct",
    "scored_candidates",
    "poisson",
    "sage_discriminant_score",
    "posterior_error",
    "spectrum_q",
    "peptide_q",
    "protein_q",
    "ms2_intensity",
]


def load_detected_params(detected_params_path):
    """Load detected parameters JSON to determine DIA vs DDA"""
    with open(detected_params_path, 'r') as f:
        data = json.load(f)
    return data['detected_params'], data.get('modifications', {})


def convert_diann_report_to_sage_tsv(diann_report_path, output_tsv_path):
    """
    Convert DIA-NN report.tsv to SAGE TSV format for downstream compatibility.
    DIA-NN columns: File.Name, Peptide, Modified.Peptide, Precursor.Charge, etc.
    SAGE columns: File, Peptide, Modified.Peptide, Charge, Score, etc.
    """
    try:
        # Read DIA-NN report
        df = pd.read_csv(diann_report_path, sep='\t')
        
        # Rename DIA-NN columns to SAGE equivalents
        column_mapping = {
            'File.Name': 'File',
            'Peptide': 'Peptide',
            'Modified.Peptide': 'Modified.Peptide',
            'Precursor.Charge': 'Charge',
            'Precursor.MZ': 'PrecursorMZ',
            'ProductMZ': 'ProductMZ',
            'Intensity': 'Intensity',
            'ProteinGroups': 'ProteinGroups',
            'Proteins': 'Proteins'
        }
        
        # Only keep columns that exist in the source file
        existing_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
        
        if existing_cols:
            df = df.rename(columns=existing_cols)
        
        # Ensure key columns exist
        if 'Peptide' not in df.columns:
            # Fallback: try to extract from Modified.Peptide
            if 'Modified.Peptide' in df.columns:
                df['Peptide'] = df['Modified.Peptide'].str.extract(r'([A-Z]+)')[0]
        
        # Add source tool identifier
        df['search_engine'] = 'DiaNN'
        
        # Save as SAGE-compatible TSV
        df.to_csv(output_tsv_path, sep='\t', index=False)
        print(f"Converted DIA-NN report to SAGE format: {output_tsv_path}")
        print(f"Rows: {len(df)}, Columns: {len(df.columns)}")
        return True
        
    except Exception as e:
        print(f"ERROR converting DIA-NN report to SAGE format: {e}")
        # Create empty file for compatibility
        with open(output_tsv_path, 'w') as f:
            f.write("File\tPeptide\tModified.Peptide\tCharge\tPrecursorMZ\tIntensity\tsearch_engine\n")
        return False


def convert_diann_report_parquet_to_sage_tsv(diann_report_parquet_path, output_tsv_path):
    """Convert DIA-NN report.parquet to a multi-row TSV.

    DIA-NN's Parquet schema differs from the older report.tsv schema.
    For downstream compatibility, we emit a SAGE-like table with the canonical
    SAGE column names where possible, and add DIA-NN-specific columns at the end.
    """

    def _col(df, name, default=pd.NA):
        if name in df.columns:
            return df[name]
        return pd.Series([default] * len(df))

    unimod_index = None

    def _load_unimod_index():
        nonlocal unimod_index
        if unimod_index is not None:
            return unimod_index
        unimod_xml = _infer_unimod_xml(Path(__file__).resolve().parent)
        if not unimod_xml:
            return None
        try:
            unimod_index = load_unimod_index(unimod_xml)
        except Exception as exc:
            print(f"WARNING: Failed to load Unimod index for DIA normalization: {exc}")
            unimod_index = None
        return unimod_index

    def _normalize_diann_modified_sequence(sequence):
        if pd.isna(sequence):
            return ""

        text = str(sequence)
        if "(UniMod:" not in text:
            return text

        index = _load_unimod_index()
        if index is None:
            return text

        def repl(match):
            mod_id = match.group(1)
            record = index.mods_by_id.get(str(mod_id))
            if record is None:
                return match.group(0)
            return f"[{record.mono_mass:+.6f}]"

        return re.sub(r"\(UniMod:(\d+)\)", repl, text)

    try:
        df = pd.read_parquet(diann_report_parquet_path)

        if len(df) == 0:
            out = pd.DataFrame(columns=SAGE_PSM_COLUMNS + ["search_engine"])
            out.to_csv(output_tsv_path, sep="\t", index=False)
            print(f"Wrote empty DIA results TSV: {output_tsv_path}")
            return True

        proteins = _col(df, "Protein.Ids", "").fillna("").astype(str)
        has_proteins = proteins.str.len() > 0
        num_proteins = pd.Series([0] * len(df))
        if has_proteins.any():
            num_proteins.loc[has_proteins] = proteins.loc[has_proteins].str.count(";") + 1

        # Normalize DIA-NN UniMod annotations to bracket-mass form for downstream parity with DDA/SAGE.
        peptide = _col(df, "Modified.Sequence")
        peptide_str = peptide.apply(_normalize_diann_modified_sequence).fillna("").astype(str)

        out = pd.DataFrame({
            "psm_id": range(1, len(df) + 1),
            "peptide": peptide_str,
            "proteins": proteins,
            "num_proteins": num_proteins.astype("Int64"),
            "filename": _col(df, "Run").fillna("").astype(str),
            "scannr": pd.NA,
            "rank": pd.NA,
            "label": pd.NA,
            "expmass": pd.NA,
            "calcmass": pd.NA,
            "charge": _col(df, "Precursor.Charge"),
            "peptide_len": peptide_str.str.len().astype("Int64"),
            "missed_cleavages": pd.NA,
            "semi_enzymatic": pd.NA,
            "isotope_error": pd.NA,
            "precursor_ppm": pd.NA,
            "fragment_ppm": pd.NA,
            "hyperscore": pd.NA,
            "delta_next": pd.NA,
            "delta_best": pd.NA,
            "rt": _col(df, "RT"),
            "aligned_rt": pd.NA,
            "predicted_rt": _col(df, "Predicted.RT"),
            "delta_rt_model": pd.NA,
            "ion_mobility": _col(df, "IM"),
            "predicted_mobility": _col(df, "Predicted.IM"),
            "delta_mobility": pd.NA,
            "matched_peaks": pd.NA,
            "longest_b": pd.NA,
            "longest_y": pd.NA,
            "longest_y_pct": pd.NA,
            "matched_intensity_pct": pd.NA,
            "scored_candidates": pd.NA,
            "poisson": pd.NA,
            "sage_discriminant_score": pd.NA,
            "posterior_error": pd.NA,
            "spectrum_q": _col(df, "Q.Value"),
            "peptide_q": _col(df, "Peptidoform.Q.Value" if "Peptidoform.Q.Value" in df.columns else "Q.Value"),
            "protein_q": _col(df, "Protein.Q.Value" if "Protein.Q.Value" in df.columns else "PG.Q.Value"),
            "ms2_intensity": _col(df, "Precursor.Quantity"),
        })

        # Ensure canonical column ordering first
        out = out.reindex(columns=SAGE_PSM_COLUMNS)

        # Add a few DIA-NN-native columns for traceability.
        out["search_engine"] = "DiaNN"
        out["diann_precursor_id"] = _col(df, "Precursor.Id").fillna("").astype(str)
        out["diann_modified_sequence"] = _col(df, "Modified.Sequence").fillna("").astype(str)
        out["diann_precursor_mz"] = _col(df, "Precursor.Mz")
        out["diann_global_q_value"] = _col(df, "Global.Q.Value")
        out["diann_pep"] = _col(df, "PEP")
        out["diann_channel"] = _col(df, "Channel").fillna("").astype(str)

        out.to_csv(output_tsv_path, sep="\t", index=False)
        print(f"Converted DIA-NN report.parquet to TSV: {output_tsv_path}")
        print(f"Rows: {len(out)}, Columns: {len(out.columns)}")
        return True

    except Exception as e:
        print(f"ERROR converting DIA-NN report.parquet to TSV: {e}")
        with open(output_tsv_path, "w") as f:
            f.write("\t".join(SAGE_PSM_COLUMNS + ["search_engine"]) + "\n")
        return False


def get_labeling_static_mods(labeling):
    """
    Map detected labeling type to corresponding static modifications.
    
    Args:
        labeling: Labeling type string (e.g., 'TMTpro', 'TMT', 'iTRAQ', 'none', 'unknown', etc.)
    
    Returns:
        dict: Static mods to apply for this labeling (e.g., {"^": 304.207, "K": 304.207} for TMTpro)
    """
    labeling = str(labeling).strip().lower() if labeling else "none"
    
    # TMTpro: 304.207 Da on N-terminus and lysine
    if "tmtpro" in labeling:
        return {
            "^": 304.207,
            "K": 304.207
        }
    
    # TMT 6/10/11-plex: 229.162932 Da on N-terminus and lysine
    if "tmt" in labeling and "tmtpro" not in labeling:
        return {
            "^": 229.162932,
            "K": 229.162932
        }
    
    # iTRAQ 8-plex: 304.205360 Da on N-terminus, lysine, and tyrosine
    if "itraq8" in labeling:
        return {
            "^": 304.205360,
            "K": 304.205360,
            "Y": 304.205360
        }
    
    # iTRAQ 4-plex: 144.102063 Da on N-terminus, lysine, and tyrosine
    if "itraq" in labeling and "itraq8" not in labeling:
        return {
            "^": 144.102063,
            "K": 144.102063,
            "Y": 144.102063
        }
    
    # No labeling or unknown: return empty dict
    return {}


def run_dda_search(
    mzml_dir,
    output_dir,
    detected_params,
    taxid,
    labeling,
    min_ptm_psms=150,
    min_ptm_percent=0.005,
    max_ptm_classes=3,
    sage_config=None,
    high_confidence_q_threshold=0.01,
    min_high_confidence_peptides=10,
    logger=None,
):
    """
    Run two-pass SAGE DDA search:
    Pass 1: Open search for PTM discovery (SAGE + PTM-Shepherd)
    Pass 2: Closed search with validated PTMs
    """
    print("\n" + "="*70)
    print("RUNNING DDA TWO-PASS SAGE SEARCH")
    print("="*70)
    
    # Log search start
    if logger:
        logger.process_start("search", {
            "search_type": "dda_two_pass",
            "taxid": taxid,
            "labeling": labeling,
        })
    
    # Create output directories
    dda_search_dir = os.path.join(output_dir, "dda_search")
    open_dir = os.path.join(dda_search_dir, "Open")
    closed_dir = os.path.join(dda_search_dir, "Closed")
    modifications_dir = os.path.join(output_dir, "modifications")
    fasta_cache_dir = os.path.join(output_dir, ".fasta_cache")  # Shared FASTA cache for all files
    
    os.makedirs(open_dir, exist_ok=True)
    os.makedirs(closed_dir, exist_ok=True)
    os.makedirs(modifications_dir, exist_ok=True)
    os.makedirs(fasta_cache_dir, exist_ok=True)
    
    print(f"Using shared FASTA cache directory: {fasta_cache_dir}")
    
    try:
        script_dir = Path(__file__).resolve().parent
        sage_py = str(script_dir / "SAGE.py")
        parse_modsummary_py = str(script_dir / "parse_modsummary.py")

        if not sage_config:
            sage_config = str(script_dir.parents[1] / "assets" / "default_sage.config")

        # ===== PASS 1: Open Search (Per-File Mode) =====
        print("\n[PASS 1] Running SAGE open search for PTM discovery (per-file mode)...")
        
        # Get list of mzML files
        import glob
        mzml_files = sorted(glob.glob(os.path.join(mzml_dir, "*.mzML")))
        
        if not mzml_files:
            print("ERROR: No mzML files found in directory")
            return False
        
        print(f"Found {len(mzml_files)} mzML files for per-file processing")
        
        # Track per-file results
        per_file_open_dirs = []
        pass1_errors = []
        ptm_shepherd_errors = []  # Track PTM-Shepherd failures with details
        
        # PASS 1: Loop through each file
        for mzml_file in mzml_files:
            mzml_basename = os.path.basename(mzml_file)
            file_stem = os.path.splitext(mzml_basename)[0]
            
            # Create per-file output directory
            file_open_dir = os.path.join(open_dir, file_stem)
            os.makedirs(file_open_dir, exist_ok=True)
            per_file_open_dirs.append(file_open_dir)
            
            print(f"\n  [File {len(per_file_open_dirs)}/{len(mzml_files)}] Processing {mzml_basename}...")
            
            cmd_open = [
                sys.executable, sage_py,
                "--sage_config", sage_config,
                "--mzml_dir", mzml_dir,
                "--mzml_file", mzml_basename,
                "-o", file_open_dir,
                "--taxid", taxid,
                "--labeling", labeling,
                "--config", detected_params,
                "--fasta_cache_dir", fasta_cache_dir,
                "--PSM-only",
                "--OpenSearch"
            ]
            
            result = subprocess.run(cmd_open, capture_output=True, text=True)
            if result.returncode != 0:
                error_msg = f"ERROR: SAGE open search failed for {mzml_basename}"
                print(error_msg)
                print("STDERR:", result.stderr)
                pass1_errors.append((mzml_basename, result.stderr))
            else:
                print(f"    ✓ Completed {mzml_basename}")
                # Show warnings/errors from stdout even on success (e.g., PTM-Shepherd failures)
                if result.stdout and ('WARNING' in result.stdout or 'ERROR' in result.stdout):
                    print(f"      Output warnings/errors:\n{result.stdout}")
                    # Extract PTM-Shepherd specific errors for logging
                    if 'PTM-Shepherd failed' in result.stdout:
                        for line in result.stdout.split('\n'):
                            if 'Fatal error:' in line or 'could not find mzData' in line:
                                ptm_shepherd_errors.append((mzml_basename, line.strip()))
                if result.stderr:
                    print(f"      STDERR: {result.stderr}")
        
        if pass1_errors:
            print(f"\nWARNING: {len(pass1_errors)} files failed in PASS 1:")
            for fname, err in pass1_errors:
                print(f"  - {fname}: {err[:100]}")
            if len(pass1_errors) == len(mzml_files):
                print("ERROR: All files failed in PASS 1")
                return False

        # ===== Aggregate PASS 1 Results =====
        print("\n[PASS 1] Aggregating per-file results...")
        
        # Aggregate open search results
        aggregated_open_results = []
        for file_open_dir in per_file_open_dirs:
            file_result_path = os.path.join(file_open_dir, "results.sage.tsv")
            if os.path.exists(file_result_path):
                try:
                    df = pd.read_csv(file_result_path, sep='\t')
                    aggregated_open_results.append(df)
                except Exception as e:
                    print(f"  WARNING: Could not read results from {file_open_dir}: {e}")
        
        if aggregated_open_results:
            combined_df = pd.concat(aggregated_open_results, ignore_index=True)
            open_results_path = os.path.join(open_dir, "results.sage.tsv")
            combined_df.to_csv(open_results_path, sep='\t', index=False)
            print(f"  Aggregated {len(aggregated_open_results)} files: {len(combined_df)} PSMs")
        else:
            open_results_path = None
            print("  WARNING: No individual PASS 1 results to aggregate")

        # Create canonical unified output name alongside tool-native output
        open_results_native = os.path.join(open_dir, "results.sage.tsv")
        open_results_canonical = os.path.join(open_dir, "search_results.tsv")
        if os.path.exists(open_results_native):
            try:
                shutil.copy(open_results_native, open_results_canonical)
            except Exception as e:
                print(f"WARNING: Could not write {open_results_canonical}: {e}")
        
        # ===== QUALITY GATE: Check high-confidence PSM count =====
        print("\n[PASS 1] Checking data quality (high-confidence PSM threshold)...")
        high_confidence_count = 0
        if 'combined_df' in locals() and combined_df is not None:
            # Column index for spectrum_q is 36 (0-indexed in SAGE_PSM_COLUMNS list above)
            if 'spectrum_q' in combined_df.columns:
                high_confidence_count = int((combined_df['spectrum_q'] < high_confidence_q_threshold).sum())
            
            mean_spectrum_q = combined_df['spectrum_q'].mean() if 'spectrum_q' in combined_df.columns else None
            print(f"  Total PSMs: {len(combined_df)}")
            print(f"  High-confidence PSMs (spectrum_q < {high_confidence_q_threshold}): {high_confidence_count}")
            
            # Log quality check
            if logger:
                logger.process_step("search", "quality_gate_check", {
                    "total_psms": len(combined_df),
                    "high_confidence_count": high_confidence_count,
                    "mean_spectrum_q": float(mean_spectrum_q) if mean_spectrum_q else None,
                    "threshold": min_high_confidence_peptides,
                    "spectrum_q_threshold": high_confidence_q_threshold,
                })
            
            if high_confidence_count < min_high_confidence_peptides:
                print(f"\n  ⚠️  WARNING: Only {high_confidence_count} high-confidence PSMs detected")
                print(f"     Threshold requirement: {min_high_confidence_peptides} PSMs")
                print(f"     Quality score: {high_confidence_count}/{min_high_confidence_peptides} ({100*high_confidence_count/min_high_confidence_peptides:.1f}%)")
                print(f"\n     Not enough high-confidence PSMs for reliable PTM detection.")
                print(f"     Skipping PTM-Shepherd and closed search. Proceeding to next process.")
                print(f"\n[PASS 1] Search completed without PTM-Shepherd analysis")
                
                # Log skip decision
                if logger:
                    logger.process_skip("ptm_shepherd_and_pass2", "insufficient_high_confidence_psms", {
                        "high_confidence_count": high_confidence_count,
                        "threshold": min_high_confidence_peptides,
                        "mean_spectrum_q": float(mean_spectrum_q) if mean_spectrum_q else None,
                        "reason": "Quality gate triggered - insufficient high-confidence PSMs for reliable PTM detection"
                    })
                
                return True  # Exit gracefully, don't crash
        
        # Check for PTM-Shepherd output - aggregate from per-file results
        modsummary_files = []
        for file_open_dir in per_file_open_dirs:
            file_modsummary = os.path.join(file_open_dir, "global.modsummary.tsv")
            if os.path.exists(file_modsummary):
                modsummary_files.append(file_modsummary)
        
        # Use first available modsummary as reference (they should all be from PASS 1)
        # In per-file mode, PTM-Shepherd runs per-file, so we aggregate the files' mod summaries
        modsummary = None
        if modsummary_files:
            # For simplicity, use the first file's results as the reference
            # In a more sophisticated implementation, these could be merged
            modsummary = modsummary_files[0]
            print(f"  Using modsummary from first file as PTM reference ({len(modsummary_files)} files had results)")

        if not modsummary or not os.path.exists(modsummary):
            print("WARNING: PTM-Shepherd did not produce results. Proceeding with closed search without PTM discovery.")
            print("\n[PASS 1] Open search completed successfully.")
            print("Skipping PASS 2 (closed search) due to lack of PTM-Shepherd results.")
            
            # Save open search results for reference
            if os.path.exists(os.path.join(open_dir, "results.sage.tsv")):
                shutil.copy(os.path.join(open_dir, "results.sage.tsv"),
                           os.path.join(dda_search_dir, "results.open.sage.tsv"))
                # Also create canonical search_results.tsv for downstream processes
                shutil.copy(os.path.join(open_dir, "results.sage.tsv"),
                           os.path.join(dda_search_dir, "search_results.tsv"))
                print(f"Saved open search results to {dda_search_dir}/search_results.tsv")
            
            # Log skip decision with PTM-Shepherd error details if available
            if logger:
                skip_details = {
                    "reason": "PTM-Shepherd did not produce modsummary results, cannot discover PTMs for closed search",
                    "files_processed": len(mzml_files),
                    "modsummary_files_found": len(modsummary_files)
                }
                if ptm_shepherd_errors:
                    skip_details["ptm_shepherd_errors"] = [
                        {"file": fname, "error": err} for fname, err in ptm_shepherd_errors
                    ]
                logger.process_skip("pass2_closed_search", "ptm_shepherd_failed", skip_details)
            
            print("\n[SUCCESS] DDA search completed (open search only)")
            return True
        else:
            # Copy PTM summary to modifications directory
            shutil.copy(modsummary, os.path.join(modifications_dir, "global.modsummary.tsv"))
            if os.path.exists(os.path.join(open_dir, "global.profile.tsv")):
                shutil.copy(
                    os.path.join(open_dir, "global.profile.tsv"),
                    os.path.join(modifications_dir, "global.profile.tsv"),
                )

            # ===== Parse and validate PTMs =====
            print("\n[PASS 1] Extracting validated PTMs...")
            print(f"  Filtering criteria: min_percent={min_ptm_percent*100:.1f}%, max_classes={max_ptm_classes}")
            cmd_ptm = [
                sys.executable,
                parse_modsummary_py,
                modsummary,
                "--min-percent",
                str(min_ptm_percent),
                "--max-ptm-classes",
                str(max_ptm_classes),
                "--sage-mods",
                "--unimod-xml",
                str(script_dir.parents[1] / "assets" / "unimod" / "unimod_tables.xml"),
                "--output-json",
                os.path.join(modifications_dir, "validated_ptms.json"),
            ]

            result = subprocess.run(cmd_ptm, capture_output=True, text=True)
            print(result.stdout)

            validated_ptms_file = os.path.join(modifications_dir, "validated_ptms.json")
            if result.returncode != 0:
                print("WARNING: PTM parsing failed. Proceeding with closed search without PTM discovery.")
                variable_mods_json = "{}"
                # But still apply labeling-specific static mods
                labeling_static = get_labeling_static_mods(labeling)
                if labeling_static:
                    print(f"Applying labeling-specific static mods for '{labeling}': {labeling_static}")
                    static_mods_json = json.dumps(labeling_static)
                else:
                    static_mods_json = "{}"
            elif not os.path.exists(validated_ptms_file) or os.path.getsize(validated_ptms_file) == 0:
                print("No validated PTMs found. Proceeding with closed search without PTM discovery.")
                variable_mods_json = "{}"
                # But still apply labeling-specific static mods
                labeling_static = get_labeling_static_mods(labeling)
                if labeling_static:
                    print(f"Applying labeling-specific static mods for '{labeling}': {labeling_static}")
                    static_mods_json = json.dumps(labeling_static)
                else:
                    static_mods_json = "{}"
            else:
                # Extract and limit PTM classes
                with open(validated_ptms_file, 'r') as f:
                    ptm_data = json.load(f)

                variable_mods = ptm_data.get('variable_mods', {})
                static_mods = ptm_data.get('static_mods', {})
                validated_ptms = ptm_data.get('validated_ptms', [])

                # Limit to top N PTM classes by abundance
                ptm_class_psms = {}
                mass_shift_to_class = {}

                for ptm in validated_ptms:
                    ptm_class = ptm.get('name', 'Unknown')
                    mass_shift = ptm.get('mass_shift')
                    psm_count = ptm.get('psms', 0)

                    if ptm_class not in ptm_class_psms:
                        ptm_class_psms[ptm_class] = 0
                    ptm_class_psms[ptm_class] += psm_count
                    if mass_shift is not None:
                        mass_shift_to_class[round(float(mass_shift), 5)] = ptm_class

                sorted_classes = sorted(ptm_class_psms.items(), key=lambda x: x[1], reverse=True)[:max_ptm_classes]
                selected_classes = {cls for cls, _ in sorted_classes}

                limited_mods = {}
                for residue, masses in variable_mods.items():
                    residue_masses = [m for m in masses if mass_shift_to_class.get(round(float(m), 5)) in selected_classes]
                    if residue_masses:
                        limited_mods[residue] = residue_masses

                variable_mods_json = json.dumps(limited_mods)

                limited_static = {}
                for key, mass in (static_mods or {}).items():
                    try:
                        cls = mass_shift_to_class.get(round(float(mass), 5))
                    except Exception:
                        cls = None
                    if cls in selected_classes:
                        limited_static[key] = mass

                static_mods_json = json.dumps(limited_static)
        
        # Add labeling-specific static mods for closed search
        labeling_static = get_labeling_static_mods(labeling)
        
        # ===== PASS 2: Closed Search (Per-PTM Mode, Per-File Mode) =====
        print("\n[PASS 2] Running SAGE closed search (per-PTM class, per-file)...")
        
        # Load validated PTMs (use only top 3)
        try:
            with open(os.path.join(modifications_dir, 'validated_ptms.json')) as f:
                ptm_data = json.load(f)
            top_ptms = ptm_data.get('validated_ptms', [])[:3]  # Top 3 only
            all_variable_mods = ptm_data.get('variable_mods', {})
            all_static_mods = ptm_data.get('static_mods', {})
        except Exception as e:
            print(f"  ERROR: Could not load validated PTMs: {e}")
            return False
        
        if not top_ptms:
            print("  No validated PTMs found (no PTMs met filtering criteria)")
            print("  Skipping PASS 2 (closed search) - using PASS 1 open search results as final results")
            
            # Save open search results as canonical search_results.tsv
            if os.path.exists(os.path.join(open_dir, "results.sage.tsv")):
                shutil.copy(os.path.join(open_dir, "results.sage.tsv"),
                           os.path.join(dda_search_dir, "results.open.sage.tsv"))
                # Create canonical search_results.tsv for downstream processes
                shutil.copy(os.path.join(open_dir, "results.sage.tsv"),
                           os.path.join(dda_search_dir, "search_results.tsv"))
                print(f"  Saved open search results to {dda_search_dir}/search_results.tsv")
            
            # Log skip decision
            if logger:
                skip_details = {
                    "reason": "No PTMs passed filtering criteria (min_percent=0.5%, max_classes=3), using open search results only",
                    "files_processed": len(mzml_files)
                }
                logger.process_skip("pass2_closed_search", "no_ptms_found", skip_details)
            
            print("\n[SUCCESS] DDA search completed (open search only, no PTMs found)")
            return True
        
        print(f"  Processing {len(top_ptms)} PTM classes across {len(mzml_files)} files")
        
        # Track results per file across all PTMs
        per_file_ptm_results = {}  # {file_stem: [ptm1_path, ptm2_path, ptm3_path]}
        ptm_search_errors = []  # [(file_stem, ptm_name, error_msg), ...]
        
        # Import aggregate function
        from aggregate_ptm_results import aggregate_ptm_results
        
        # Loop: each mzML file
        for file_idx, mzml_file in enumerate(mzml_files):
            mzml_basename = os.path.basename(mzml_file)
            file_stem = os.path.splitext(mzml_basename)[0]
            per_file_ptm_results[file_stem] = []
            
            print(f"\n  [File {file_idx+1}/{len(mzml_files)}] {mzml_basename}")
            
            # Loop: each PTM class
            for ptm_idx, ptm in enumerate(top_ptms):
                ptm_name_raw = ptm.get('name', f'PTM_{ptm_idx}')
                mass_shift = ptm.get('mass_shift')
                
                # Create safe directory name (replace problematic chars)
                ptm_name_dir = ptm_name_raw.replace('/', '_').replace(' ', '_').replace('(', '').replace(')', '')
                
                # Create output directory
                ptm_output_dir = os.path.join(closed_dir, ptm_name_dir, file_stem)
                os.makedirs(ptm_output_dir, exist_ok=True)
                
                # Filter variable_mods: only keep residues with this mass_shift
                filtered_variable_mods = {}
                for residue, masses in all_variable_mods.items():
                    if mass_shift in masses:
                        filtered_variable_mods[residue] = [mass_shift]
                
                # Add labeling-specific static mods if present
                filtered_static_mods = dict(all_static_mods) if all_static_mods else {}
                if labeling_static:
                    filtered_static_mods.update(labeling_static)
                
                variable_mods_json = json.dumps(filtered_variable_mods)
                static_mods_json = json.dumps(filtered_static_mods)
                
                num_var_mods = sum(len(v) for v in filtered_variable_mods.values())
                print(f"    [{ptm_idx+1}/3] {ptm_name_raw} ({num_var_mods} variable mods on {len(filtered_variable_mods)} residues)")
                
                # Run SAGE
                cmd_closed = [
                    sys.executable, sage_py,
                    "--sage_config", sage_config,
                    "--mzml_dir", mzml_dir,
                    "--mzml_file", mzml_basename,
                    "-o", ptm_output_dir,
                    "--taxid", taxid,
                    "--labeling", labeling,
                    "--config", detected_params,
                    "--fasta_cache_dir", fasta_cache_dir,
                    "--ClosedSearch",
                    "--static_mods", static_mods_json,
                    "--variable_mods", variable_mods_json
                ]
                
                result = subprocess.run(cmd_closed, capture_output=True, text=True)
                ptm_result_path = os.path.join(ptm_output_dir, "results.sage.tsv")
                
                if result.returncode != 0:
                    error_msg = result.stderr[:200] if result.stderr else f"Exit code {result.returncode}"
                    print(f"      ✗ Failed: {error_msg}")
                    ptm_search_errors.append((file_stem, ptm_name_raw, result.stderr))
                elif os.path.exists(ptm_result_path):
                    print(f"      ✓ Success")
                    per_file_ptm_results[file_stem].append(ptm_result_path)
                else:
                    print(f"      ✗ No results file")
        
        # Report errors
        if ptm_search_errors:
            print(f"\n  [PASS 2] {len(ptm_search_errors)} PTM searches failed:")
            for file_stem, ptm_name, error in ptm_search_errors:
                print(f"    - {file_stem} / {ptm_name}: {error[:100]}")
        
        # ===== Aggregate PTM Results Per File =====
        print("\n[PASS 2] Aggregating PTM results per file...")
        
        aggregated_files = []  # Track which files were aggregated
        
        for mzml_file in mzml_files:
            file_stem = os.path.splitext(os.path.basename(mzml_file))[0]
            available_results = per_file_ptm_results.get(file_stem, [])
            
            if not available_results:
                print(f"  WARNING: No PTM results for {file_stem}, skipping aggregation")
                continue
            
            # Create aggregated output directory
            agg_output_dir = os.path.join(closed_dir, "AGGREGATED", file_stem)
            os.makedirs(agg_output_dir, exist_ok=True)
            agg_output_path = os.path.join(agg_output_dir, "results.sage.tsv")
            
            # Aggregate (deduplicate by hyperscore)
            try:
                aggregate_ptm_results(
                    ptm_result_files=available_results,
                    output_file=agg_output_path,
                    score_column="hyperscore"
                )
                aggregated_files.append(agg_output_path)
            except Exception as e:
                print(f"  ERROR aggregating results for {file_stem}: {e}")
                continue
        
        # ===== Combine All Aggregated Files into Master Results =====
        # Merge all per-file aggregated results into a single master file
        if aggregated_files:
            print(f"\n[PASS 2] Combining {len(aggregated_files)} aggregated files into master results...")
            
            # Read all aggregated files and combine
            all_dfs = []
            for agg_file in aggregated_files:
                try:
                    df = pd.read_csv(agg_file, sep='\t')
                    all_dfs.append(df)
                except Exception as e:
                    print(f"  WARNING: Could not read {agg_file}: {e}")
            
            if all_dfs:
                # Concatenate all dataframes
                combined_df = pd.concat(all_dfs, ignore_index=True)
                
                # Save to dda_search_dir
                master_results_path = os.path.join(dda_search_dir, "results.sage.tsv")
                combined_df.to_csv(master_results_path, sep='\t', index=False)
                
                # Also copy to Closed directory for compatibility with aggregate_results.py
                closed_results_path = os.path.join(closed_dir, "results.sage.tsv")
                shutil.copy(master_results_path, closed_results_path)
                
                print(f"  Created master results: {master_results_path} ({len(combined_df)} PSMs)")
        
        # Create canonical unified output name
        try:
            master_search_results = os.path.join(dda_search_dir, "search_results.tsv")
            shutil.copy(os.path.join(dda_search_dir, "results.sage.tsv"), master_search_results)
            # Also create in Closed for compatibility
            shutil.copy(os.path.join(dda_search_dir, "results.sage.tsv"),
                       os.path.join(closed_dir, "search_results.tsv"))
        except Exception as e:
            print(f"  WARNING: Could not create canonical search_results.tsv: {e}")
        
        print("\n[SUCCESS] Per-PTM closed searches complete")

        # Postprocess: mod-site fractions (on aggregated results per file)
        print("\n[POST] Running mod-site fractions on aggregated per-file results...")
        
        for file_stem in mzml_files:
            file_stem_base = os.path.splitext(os.path.basename(file_stem))[0]
            agg_output_dir = os.path.join(closed_dir, "AGGREGATED", file_stem_base)
            results_tsv = os.path.join(agg_output_dir, "results.sage.tsv")
            
            if not os.path.exists(results_tsv):
                print(f"  WARNING: Aggregated results not found for {file_stem_base}, skipping mod-site fractions")
                continue
            
            try:
                mod_site_py = str(script_dir / "mod_site_fractions.py")
                out_tsv = os.path.join(agg_output_dir, "mod_site_fractions.tsv")
                
                cmd = [
                    sys.executable, mod_site_py,
                    "--results", results_tsv,
                    "--out", out_tsv,
                ]
                unimod_xml = _infer_unimod_xml(script_dir)
                if unimod_xml:
                    cmd += ["--unimod-xml", unimod_xml]
                
                proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
                if proc.returncode != 0:
                    print(f"  WARNING: mod-site fractions failed for {file_stem_base}: {proc.returncode}")
            except Exception as e:
                print(f"  WARNING: mod-site fraction postprocess failed for {file_stem_base}: {e}")
        
        # Per-file mod_site_fractions are left in AGGREGATED/{file_stem}/ directories for per-sample reporting
        print("\n[POST] Per-file mod-site fractions are available in AGGREGATED/{file_stem}/ directories")
        
        # Save open search results for reference
        if os.path.exists(os.path.join(open_dir, "results.sage.tsv")):
            shutil.copy(os.path.join(open_dir, "results.sage.tsv"),
                       os.path.join(dda_search_dir, "results.open.sage.tsv"))
        
        print("\n[SUCCESS] DDA two-pass search completed")
        return True
        
    except Exception as e:
        print(f"ERROR in DDA search: {e}")
        return False


def run_dia_search(mzml_dir, output_dir, detected_params, taxid, labeling, diann_modifications):
    """
    Run DIA-NN search for DIA experiments
    """
    print("\n" + "="*70)
    print("RUNNING DIA-NN SEARCH FOR DIA DATA")
    print("="*70)
    
    dia_search_dir = os.path.join(output_dir, "dia_search")
    os.makedirs(dia_search_dir, exist_ok=True)
    
    try:
        script_dir = Path(__file__).resolve().parent
        diann_py = str(script_dir / "DiaNN.py")

        # Run DIA-NN (inference only; defaults handled inside DiaNN.py)
        # Pass explicit cache directory to ensure consistent library caching
        diann_cache = os.path.join(os.path.dirname(output_dir), "assets", "diann_libraries")
        cmd_diann = [
            sys.executable, diann_py,
            "--mzml_dir", mzml_dir,
            "-o", dia_search_dir,
            "--taxid", taxid,
            "--labeling", labeling,
            "--config", detected_params,
            "--diann_cache_dir", diann_cache
        ]
        
        # Do not pass modifications; DiaNN.py will use detected_params.json or defaults.
        
        result = subprocess.run(cmd_diann, capture_output=True, text=True)
        print(result.stdout)
        
        if result.returncode != 0:
            print(f"ERROR: DIA-NN failed with exit code {result.returncode}")
            print("STDERR:", result.stderr)
            return False
        
        # DIA-NN output: older versions wrote report.tsv; newer (e.g. 2.2.x) may write report.parquet.
        diann_report_tsv = os.path.join(dia_search_dir, "report.tsv")
        diann_report_parquet = os.path.join(dia_search_dir, "report.parquet")
        search_tsv = os.path.join(dia_search_dir, "search_results.tsv")
        
        # Convert DIA-NN report to SAGE-compatible search_results.tsv (priority: parquet > tsv)
        conversion_success = False
        if os.path.exists(diann_report_parquet):
            print("[CONVERT] Converting DIA-NN report.parquet to SAGE-compatible search_results.tsv...")
            conversion_success = convert_diann_report_parquet_to_sage_tsv(diann_report_parquet, search_tsv)
        elif os.path.exists(diann_report_tsv):
            print("[CONVERT] Converting DIA-NN report.tsv to SAGE-compatible search_results.tsv...")
            conversion_success = convert_diann_report_to_sage_tsv(diann_report_tsv, search_tsv)
        else:
            print("ERROR: DIA-NN report not found (expected report.tsv or report.parquet)")
            return False
        
        if not conversion_success:
            print("ERROR: Failed to convert DIA-NN report to SAGE format")
            return False
        
        # Validate that search_results.tsv contains PSM-level data (not statistics)
        try:
            df_validate = pd.read_csv(search_tsv, sep='\t', nrows=1)
            col_count = len(df_validate.columns)
            
            # SAGE format should have 40+ columns (40 SAGE + 6+ DIA-NN-specific columns)
            if col_count < 30:
                print(f"ERROR: search_results.tsv has only {col_count} columns - appears to be statistics file")
                print("       Expected PSM-level format with 40+ columns")
                return False
            
            if 'peptide' not in df_validate.columns:
                print("ERROR: search_results.tsv missing 'peptide' column (requires PSM-level data)")
                return False
            
            # Count total rows (PSMs)
            psm_count = sum(1 for line in open(search_tsv)) - 1  # Exclude header
            if psm_count < 10:
                print(f"WARNING: search_results.tsv has only {psm_count} PSMs (expected >100)")
            else:
                print(f"✓ Validated search_results.tsv: {psm_count} PSMs, {col_count} columns (SAGE-compatible)")
        except Exception as e:
            print(f"ERROR: Could not validate search_results.tsv: {e}")
            return False

        # Postprocess: mod-site fractions
        try:
            mod_site_py = str(script_dir / "mod_site_fractions.py")
            results_tsv = os.path.join(dia_search_dir, "search_results.tsv")
            out_tsv = os.path.join(dia_search_dir, "mod_site_fractions.tsv")
            if os.path.exists(results_tsv):
                cmd = [
                    sys.executable, mod_site_py,
                    "--results", results_tsv,
                    "--out", out_tsv,
                ]
                unimod_xml = _infer_unimod_xml(script_dir)
                if unimod_xml:
                    cmd += ["--unimod-xml", unimod_xml]
                proc = subprocess.run(cmd, check=False, capture_output=False, text=True)
                if proc.returncode != 0:
                    print(f"WARNING: mod-site fractions exited {proc.returncode}")
        except Exception as e:
            print(f"WARNING: mod-site fraction postprocess failed: {e}")
        
        print("\n[SUCCESS] DIA-NN search completed")
        return True
        
    except Exception as e:
        print(f"ERROR in DIA search: {e}")
        return False


def _infer_unimod_xml(script_dir: Path) -> str | None:
    for parent in (script_dir, *script_dir.parents):
        candidate = parent / "assets" / "unimod" / "unimod_tables.xml"
        if candidate.exists():
            return str(candidate)
    return None


def create_metadata_json(output_dir, search_type, detected_params, labeling):
    """Create search metadata JSON files in appropriate directories"""
    
    if search_type == "dda":
        # Metadata for Open search
        open_metadata = {
            "source_tool": "SAGE",
            "search_pass": "Open",
            "detected_dia": False,
            "labeling": labeling,
            "ptm_discovery": True
        }
        with open(os.path.join(output_dir, "dda_search", "Open", "search_metadata.json"), 'w') as f:
            json.dump(open_metadata, f, indent=2)
        
        # Metadata for Closed search
        closed_metadata = {
            "source_tool": "SAGE",
            "search_pass": "Closed",
            "detected_dia": False,
            "labeling": labeling,
            "ptm_discovery": False
        }
        with open(os.path.join(output_dir, "dda_search", "Closed", "search_metadata.json"), 'w') as f:
            json.dump(closed_metadata, f, indent=2)
    
    elif search_type == "dia":
        # Metadata for DIA search
        dia_metadata = {
            "source_tool": "DiaNN",
            "detected_dia": True,
            "labeling": labeling,
            "ptm_discovery": False
        }
        with open(os.path.join(output_dir, "dia_search", "search_metadata.json"), 'w') as f:
            json.dump(dia_metadata, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description='Unified search orchestrator for DDA and DIA experiments')
    parser.add_argument('--mzml_dir', required=True, help='Directory containing mzML files')
    parser.add_argument('--output_dir', required=True, help='Output directory for search results')
    parser.add_argument('--detected_params', required=True, help='Path to detected_params.json')
    parser.add_argument('--taxid', required=True, help='NCBI taxid for organism')
    parser.add_argument('--labeling', default='unknown', help='Labeling type (unknown, TMT6plex, iTRAQ4plex, etc.)')
    parser.add_argument('--diann_modifications', default='[]', help='JSON string of DIA-NN modifications')
    parser.add_argument('--min_ptm_psms', type=int, default=150, help='Minimum PSMs for PTM validation (DDA only)')
    parser.add_argument('--min_ptm_percent', type=float, default=0.005, help='Minimum percent PSMs for PTM validation (default 0.005 = 0.5%)')
    parser.add_argument('--max_ptm_classes', type=int, default=3, help='Maximum PTM classes to include (DDA only)')
    parser.add_argument('--sage_config', default=None, help='Path to SAGE config file')
    parser.add_argument('--high_confidence_q_threshold', type=float, default=0.01, help='spectrum_q < this value counts as high-confidence PSM')
    parser.add_argument('--min_high_confidence_peptides', type=int, default=10, help='If fewer high-confidence PSMs than this, skip PTM-Shepherd and closed search')
    parser.add_argument('--pxd', default='UNKNOWN', help='PXD identifier for logging')
    parser.add_argument('--log_file', default=None, help='Event log file (JSONL format)')
    
    args = parser.parse_args()
    
    # Initialize logger
    if args.log_file:
        logger = PipelineLogger(args.log_file, args.pxd)
    else:
        logger = None
    
    # Load detected parameters
    detected_params_dict, modifications = load_detected_params(args.detected_params)
    is_dia = detected_params_dict.get('DIA', False)
    
    print(f"\nDetected acquisition type: {'DIA' if is_dia else 'DDA'}")
    print(f"Labeling: {args.labeling}")
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Route to appropriate search method
    success = False
    if is_dia:
        # Parse DIA-NN modifications
        try:
            diann_mods = json.loads(args.diann_modifications)
        except:
            diann_mods = []
        
        success = run_dia_search(
            args.mzml_dir, args.output_dir, args.detected_params,
            args.taxid, args.labeling, diann_mods
        )
        search_type = "dia"
    else:
        success = run_dda_search(
            args.mzml_dir, args.output_dir, args.detected_params,
            args.taxid, args.labeling,
            min_ptm_psms=args.min_ptm_psms,
            min_ptm_percent=args.min_ptm_percent,
            max_ptm_classes=args.max_ptm_classes,
            sage_config=args.sage_config,
            high_confidence_q_threshold=args.high_confidence_q_threshold,
            min_high_confidence_peptides=args.min_high_confidence_peptides,
            logger=logger,
        )
        search_type = "dda"
    
    if success:
        # Create metadata files
        create_metadata_json(args.output_dir, search_type, detected_params_dict, args.labeling)
        print("\n" + "="*70)
        print("SEARCH ORCHESTRATION COMPLETE")
        print("="*70)
        return 0
    else:
        print("\n" + "="*70)
        print("SEARCH ORCHESTRATION FAILED")
        print("="*70)
        return 1


if __name__ == '__main__':
    exit(main())
