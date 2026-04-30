#!/usr/bin/env python3
import os, re, argparse
import pandas as pd
import numpy as np
import json
import glob
import time
import math
import requests
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Tuple

H = 1.007276466879  # proton mass

SCAN_RE = re.compile(r"scan=(\d+)")
MOD_BRACKETS_RE = re.compile(r"\[.*?\]")
MOD_NUM_RE = re.compile(r"\[([+-]?\d+\.\d+)\]")
###########################################################################
def parse_scan(x):
    s = str(x)
    m = SCAN_RE.search(s)
    if m: return int(m.group(1))
    nums = re.findall(r"\d+", s)
    return int(nums[-1]) if nums else np.nan

def strip_mods(seq):  # Peptide (unmodified)
    return MOD_BRACKETS_RE.sub("", str(seq))
###########################################################################

###########################################################################
def convert_sage_to_ptmshepherd(df: pd.DataFrame, args, static_masses=None) -> pd.DataFrame:
    """
    Convert SAGE PSM table to a PTM-Shepherd-compatible PSM table.

    - For open search (args.OpenSearch = True):
        Delta Mass = expmass - calcmass  (standard open-search behavior)

    - For closed search (default, including phospho_ClosedSearch):
        1) Infer base peptide mass by subtracting *variable* mods
           (phospho, Ox(M), N-term acetyl, etc.) from SAGE calcmass
           while KEEPING static mods (e.g., C+57.02146).
        2) Delta Mass = expmass - base_mass
    """
    if static_masses is None:
        # Static mods in your phospho pipeline: C+57.02146
        static_masses = {57.02146}

    # Core fields from SAGE
    fn_base   = df["filename"].apply(lambda p: os.path.basename(str(p)))
    file_stem = fn_base.apply(lambda b: os.path.splitext(b)[0])
    scan      = df["scannr"].apply(parse_scan)

    z        = pd.to_numeric(df["charge"],   errors="coerce")
    expmass  = pd.to_numeric(df["expmass"],  errors="coerce")
    calcmass = pd.to_numeric(df["calcmass"], errors="coerce")

    pep_mod = df["peptide"].astype(str)    # with [+xx.xxx]
    pep     = pep_mod.apply(strip_mods)    # unmodified sequence
    
    # For PTM-Shepherd compatibility: use the full filename with extension
    # PTM-Shepherd needs to match the actual mzML filenames in the directory
    ptmshepherd_fn_base = fn_base.copy()  # use full filename with extension

    # --- Compute base mass and delta mass ---

    if getattr(args, "OpenSearch", False):
        # For open search, keep your original behavior:
        base_mass  = calcmass.copy()
        delta_mass = expmass - base_mass
    else:
        # Closed search: remove VARIABLE mods from calcmass to get base_mass
        base_mass = calcmass.copy()

        def is_static(mass: float) -> bool:
            return any(abs(mass - s) < 0.01 for s in static_masses)

        for idx, seq in pep_mod.items():
            cmass = calcmass.loc[idx]
            if pd.isna(cmass):
                base_mass.loc[idx] = np.nan
                continue

            subtract = 0.0
            for m_str in MOD_NUM_RE.findall(seq):
                try:
                    m_val = float(m_str)
                except ValueError:
                    continue

                # Skip static mods (e.g., +57.02146 on C)
                if is_static(m_val):
                    continue

                # Everything else is treated as variable (phospho, Ox(M), Ac, etc.)
                subtract += m_val

            base_mass.loc[idx] = cmass - subtract

        delta_mass = expmass - base_mass

    # --- Retention time to seconds ---
    rt_raw = pd.to_numeric(df[args.rt_col], errors="coerce")
    if args.rt_unit == "min":
        rt_sec = rt_raw * 60.0
    elif args.rt_unit == "sec":
        rt_sec = rt_raw
    else:
        med = rt_raw.dropna().median()
        rt_sec = rt_raw if (med is not None and med > 300) else rt_raw * 60.0

    # --- m/z from neutral mass and charge ---
    obs_mz  = (expmass   + z * H) / z
    calc_mz = (base_mass + z * H) / z  # use base_mass, not calcmass

    # Spectrum + Spectrum File: names must match your .mzML basenames
    spectrum = (
        file_stem.astype(str) + "." +
        scan.astype("Int64").astype(str) + "." +
        scan.astype("Int64").astype(str) + "." +
        z.astype("Int64").astype(str)
    )

    # Protein (first mapping) if available
    protein = df["proteins"].astype(str).str.split(";").str[0] if "proteins" in df.columns else ""

    out = pd.DataFrame({
        "Spectrum": spectrum,
        "Spectrum File": ptmshepherd_fn_base,  # PTM-Shepherd needs just the run name (without extensions)
        "Peptide": pep,                    # stripped (no [ +mass ])
        "Modified Peptide": pep_mod,       # SAGE-style with [+xx.xxx]
        "Charge": z.astype("Int64"),
        "Retention": rt_sec,
        "Observed Mass": expmass,
        "Calibrated Observed Mass": expmass,  # no extra calibration
        "Observed M/Z": obs_mz,
        "Calibrated Observed M/Z": obs_mz,    # same as above
        "Calculated Peptide Mass": base_mass, # base mass (static mods only)
        "Calculated M/Z": calc_mz,
        "Delta Mass": delta_mass,
        "Protein": protein,
        "Isotope Error": pd.to_numeric(df.get("isotope_error", np.nan), errors="coerce"),
        "Ion Mobility": pd.to_numeric(df.get("ion_mobility", np.nan), errors="coerce"),
    })

    # Build list of actual files in the mzml_dir
    actual_files = set(os.listdir(args.mzml_dir)) if os.path.exists(args.mzml_dir) else set()
    
    # For each spectrum file, find the matching file in the directory
    # The spectrum file might have .raw.mzML or just .mzML
    corrected_spectrum_files = []
    for spec_file in out["Spectrum File"]:
        # First, try exact match
        if spec_file in actual_files:
            corrected_spectrum_files.append(spec_file)
        # Try adding .mzML if it doesn't end with it
        elif not spec_file.endswith(".mzML"):
            candidate = spec_file + ".mzML"
            if candidate in actual_files:
                corrected_spectrum_files.append(candidate)
            else:
                # Last resort: try to find any file that starts with this name
                matching = [f for f in actual_files if f.startswith(spec_file)]
                if matching:
                    corrected_spectrum_files.append(matching[0])
                else:
                    corrected_spectrum_files.append(spec_file)  # keep original, will warn
        else:
            corrected_spectrum_files.append(spec_file)
    
    out["Spectrum File"] = corrected_spectrum_files
    
    # Check for truly missing files
    missing = sorted(set(out["Spectrum File"]) - actual_files)
    if missing:
        print(
            "[WARN] These Spectrum File basenames were not found in",
            args.mzml_dir, "->",
            missing[:10],
            ("... (+%d more)" % (len(missing) - 10) if len(missing) > 10 else "")
        )

    return out
###########################################################################

###########################################################################
def run_sage(config_path: str, outdir: str) -> Tuple[int, str, str]:
    """
    Run SAGE with a given control/config file, writing full stdout/stderr to logs.
    Returns (returncode, stdout_log_path, stderr_log_path).
    Raises RuntimeError on non-zero exit with the last lines of stderr.
    """
    import resource
    
    config_path = os.path.abspath(config_path)
    outdir = os.path.abspath(outdir)
    Path(outdir).mkdir(parents=True, exist_ok=True)

    # Find sage binary using full path
    sage_path = shutil.which("sage")
    if sage_path is None:
        raise RuntimeError("Could not find 'sage' on PATH. Activate the env or install SAGE.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stdout_log = os.path.join(outdir, f"sage_stdout_{ts}.log")
    stderr_log = os.path.join(outdir, f"sage_stderr_{ts}.log")

    print("Running SAGE…")
    print(f"Config: {config_path}")
    print(f"Output dir: {outdir}")
    print(f"SAGE binary: {sage_path}")

    # Set stack limit before running subprocess
    # This is safer than using shell ulimit in Nextflow/Singularity contexts
    try:
        soft_limit = resource.getrlimit(resource.RLIMIT_STACK)[0]
        # Try to set to unlimited, but fall back to 256 MB if not allowed
        resource.setrlimit(resource.RLIMIT_STACK, (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
        print(f"Stack limit set to unlimited (was: {soft_limit} bytes)")
    except (ValueError, OSError) as e:
        print(f"Warning: Could not set unlimited stack limit: {e}")
        try:
            # Fallback: set to 256 MB (268435456 bytes)
            resource.setrlimit(resource.RLIMIT_STACK, (268435456, 268435456))
            print(f"Stack limit set to 256 MB") 
        except Exception as e2:
            print(f"Warning: Could not set stack limit: {e2}")

    # Run SAGE without shell=True (safer in Nextflow/Singularity)
    # Use list form with shell=False for direct execution
    cmd = [sage_path, config_path, "--output_directory", outdir]
    print("CMD:", " ".join(cmd))

    proc = subprocess.run(
        cmd,
        shell=False,  # Direct execution, no shell - safer in containers
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=outdir,
        env=os.environ.copy()
    )

    # Write full logs
    Path(stdout_log).write_text(proc.stdout or "", encoding="utf-8")
    Path(stderr_log).write_text(proc.stderr or "", encoding="utf-8")

    # Mirror a short summary to console
    print(f"SAGE finished with code {proc.returncode}.")
    print(f"stdout → {stdout_log}")
    print(f"stderr → {stderr_log}")

    if proc.returncode != 0:
        # Show a helpful tail of stderr in the exception
        tail = "\n".join((proc.stderr or "").splitlines()[-40:])
        raise RuntimeError(
            f"SAGE failed (exit {proc.returncode}). See logs.\n"
            f"stderr tail:\n{'-'*60}\n{tail}\n{'-'*60}"
        )

    return proc.returncode, stdout_log, stderr_log

# Example usage:
# rc, out_log, err_log = run_sage("path/to/config.json", "path/to/outdir")
###########################################################################

###########################################################################
def run_ptmshepherd(fragpipe_out: str, dataset_name: str = "Dataset1", mzml_dir: str = None):
    """
    Run PTM-Shepherd on the given FragPipe output file.
    java -Xmx64G -jar /home/ians/HAMLET/src/data/ptmshepherd-2.0.5_CLI.jar ptmshepherd.config
    """
    print("\nRunning PTM-Shepherd...")
    
    # Convert mzml_dir to absolute path for PTM-Shepherd
    if mzml_dir and not os.path.isabs(mzml_dir):
        mzml_dir = os.path.abspath(mzml_dir)
    
    # Also convert fragpipe_out to absolute path for consistency
    if not os.path.isabs(fragpipe_out):
        fragpipe_out = os.path.abspath(fragpipe_out)
    
    ptmshepherd_config = f"""# ==== PTM-Shepherd config ====
# Run:
#   java -Xmx64G -jar /opt/ptmshepherd/ptmshepherd.jar ptmshepherd.config

# --- Datasets (name, PSM file, mzML directory) ---
dataset = {dataset_name} {fragpipe_out} {mzml_dir}

# --- Common settings ---
threads = 8
histo_bindivs = 2000
histo_smoothbins = 3
peakpicking_promRatio = 0.5
peakpicking_mass_units = 0
peakpicking_width = 0.002
peakpicking_topN = 200
precursor_mass_units = 0
precursor_tol = 0.02
spectra_ppmtol = 20
spectra_condPeaks = 150
spectra_condRatio = 0.01
localization_background = 3
mass_offsets = -500 500
isotope_error = 1
output_extended = false"""
    config_path = os.path.join(os.path.dirname(fragpipe_out), "ptmshepherd.config")
    with open(config_path, 'w') as f:
        f.write(ptmshepherd_config)
    print(f"Wrote PTM-Shepherd config: {config_path}")


    # java -Xmx64G -jar /opt/ptmshepherd/ptmshepherd.jar ptmshepherd.config
    jar_path = os.environ.get('PTMSHEPHERD_JAR')
    
    # If not explicitly set, search common locations including conda environments
    if not jar_path or not os.path.exists(jar_path):
        candidate_paths = [
            os.path.expanduser('~/miniconda3/envs/search_env/opt/search_tools/ptmshepherd/ptmshepherd.jar'),
            '/opt/ptmshepherd/ptmshepherd.jar',
            os.path.expanduser('~/miniconda3/envs/meti_env/opt/search_tools/ptmshepherd/ptmshepherd.jar'),
            '/opt/search_tools/ptmshepherd/ptmshepherd.jar',
        ]
        for candidate in candidate_paths:
            if os.path.exists(candidate):
                jar_path = candidate
                break
    
    if not jar_path or not os.path.exists(jar_path):
        raise FileNotFoundError(f"PTM-Shepherd JAR not found. Searched: {candidate_paths}. Set PTMSHEPHERD_JAR env var or install FragPipe.")
    
    cmd = ["java", "-Xmx64G", "-jar", jar_path, config_path]
    print("CMD:", " ".join(cmd))

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"WARNING: PTM-Shepherd failed with error:\n{result.stderr}")
        print("Attempting fallback: checking if PTM-Shepherd output exists anyway...")
        
        # Even if PTM-Shepherd exits with an error, it might have partially completed
        ptmshepherd_output_dir = os.path.join(os.getcwd(), "ptm-shepherd-output")
        if os.path.exists(ptmshepherd_output_dir):
            print(f"PTM-Shepherd partial output found at {ptmshepherd_output_dir}")
            # Try to use partial output
            output_dir = os.path.dirname(fragpipe_out)
            key_files = ["global.modsummary.tsv", "global.profile.tsv"]
            
            any_copied = False
            for filename in key_files:
                src_path = os.path.join(ptmshepherd_output_dir, filename)
                if os.path.exists(src_path):
                    dst_path = os.path.join(output_dir, filename)
                    import shutil
                    shutil.copy2(src_path, dst_path)
                    print(f"Recovered partial {filename} from PTM-Shepherd output")
                    any_copied = True
            
            if any_copied:
                print("Successfully recovered partial PTM-Shepherd output")
                return  # Success - we have at least some output
        
        # If no output found, raise error
        raise RuntimeError(f'Error occurred while running PTM-Shepherd:\n{result.stderr}')
    print("PTM-Shepherd run complete.")
    
    # Copy PTM-Shepherd output files to the main output directory
    output_dir = os.path.dirname(fragpipe_out)
    
    # PTM-Shepherd creates output in the current working directory
    current_dir = os.getcwd()
    ptmshepherd_output_dir = os.path.join(current_dir, "ptm-shepherd-output")
    
    if os.path.exists(ptmshepherd_output_dir):
        print(f"Copying PTM-Shepherd outputs from {ptmshepherd_output_dir} to {output_dir}")
        import shutil
        
        # Copy the key PTM-Shepherd output files
        key_files = ["global.modsummary.tsv", "global.profile.tsv"]
        
        for filename in key_files:
            src_path = os.path.join(ptmshepherd_output_dir, filename)
            if os.path.exists(src_path):
                dst_path = os.path.join(output_dir, filename)
                shutil.copy2(src_path, dst_path)
                print(f"Copied {filename} to output directory")
            else:
                print(f"Warning: {filename} not found in PTM-Shepherd output")
    else:
        print(f"Warning: PTM-Shepherd output directory not found: {ptmshepherd_output_dir}")
###########################################################################

###########################################################################
def get_quantification_config(labeling_type: str) -> dict:
    """
    Generate SAGE quantification configuration based on detected labeling type.
    
    Supports: LFQ, TMT6, TMT10, TMT11, TMT16, iTRAQ4, iTRAQ8, SILAC
    
    Returns quantification dict for SAGE config, or None if unknown type.
    """
    labeling_lower = labeling_type.lower() if labeling_type else "lfq"
    
    quant_configs = {
        "lfq": {
            "kind": "label_free",
            "integration": "trapezoid"
        },
        "tmt6": {
            "kind": "isobaric",
            "type": "TMT6",
            "denoise": True
        },
        "tmt10": {
            "kind": "isobaric",
            "type": "TMT10",
            "denoise": True
        },
        "tmt11": {
            "kind": "isobaric",
            "type": "TMT11",
            "denoise": True
        },
        "tmt16": {
            "kind": "isobaric",
            "type": "TMT16",
            "denoise": True
        },
        "itraq4": {
            "kind": "isobaric",
            "type": "iTRAQ4",
            "denoise": True
        },
        "itraq8": {
            "kind": "isobaric",
            "type": "iTRAQ8",
            "denoise": True
        },
        "silac": {
            "kind": "isotope_labeling",
            "type": "SILAC",
            "dynamic": True
        }
    }
    
    return quant_configs.get(labeling_lower, None)
###########################################################################

###########################################################################
def main():

    #########################################################################
    ap = argparse.ArgumentParser()
    ap.add_argument("--sage_config", required=True, help="Input SAGE configuration file")
    ap.add_argument("-o", "--out", help="Output directory", required=True)
    ap.add_argument("--mzml_dir", required=True, help="Directory containing the .mzML files")
    ap.add_argument("--mzml_file", default=None, help="(Optional) Process only a specific .mzML file in mzml_dir (for per-file mode)")
    ap.add_argument("--taxid", required=True, help="Organism NCBI TaxID")
    ap.add_argument("--rt-col", default="rt", help="RT column in SAGE file")
    ap.add_argument("--rt-unit", choices=["min","sec"], default=None, help="Override RT units")
    ap.add_argument("--reviewed-only", action="store_true", help="Use only reviewed proteins from UniProt")
    ap.add_argument("--PSM-only", action="store_true", help="Output only PSM-level data without additional columns")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite output if it exists")
    ap.add_argument("--OpenSearch", action="store_true", help="Indicate that SAGE was run in open search mode")
    ap.add_argument("--ClosedSearch", action="store_true", help="Indicate that SAGE was run in closed search mode with specified variable mods")
    ap.add_argument("--variable_mods", default=None, help="JSON string of variable mods for closed search (e.g. '{\"S\": [79.966331], \"T\": [79.966331], \"Y\": [79.966331]}')")
    ap.add_argument("--static_mods", default=None, help="JSON string of static mods for closed search (merged into config; e.g. '{\"C\": 57.02146, \"^\": 42.010565}')")
    ap.add_argument("--labeling", default="LFQ", help="Labeling type detected by runAssessor (LFQ, TMT6, TMT10, iTRAQ4, iTRAQ8, SILAC, etc.)")
    ap.add_argument("--config", help="Path to detected_params.json from runAssessor parsing (optional)")
    ap.add_argument("--fasta_cache_dir", default=None, help="Shared FASTA cache directory to avoid re-downloading same files")
    args = ap.parse_args()
    
    # Debug: verify ClosedSearch flag
    print(f"DEBUG: args.ClosedSearch = {args.ClosedSearch}")
    print(f"DEBUG: args.variable_mods = {args.variable_mods}")
    
    # Load detected modifications if config provided
    if args.config and os.path.exists(args.config):
        print(f"Loading detected parameters from {args.config}")
        with open(args.config, 'r') as f:
            detected_config = json.load(f)
        args.labeling = detected_config['detected_params']['labeling']
        print(f"Using detected labeling: {args.labeling}")
        # TODO: Apply modifications from detected_config to SAGE config
        # This would require modifying the SAGE config file or passing different parameters

    # Validate output directory
    if os.path.isdir(args.out):
        outdir = args.out
    else:
        outdir = os.path.dirname(args.out)
        
    print(f"Output directory: {outdir}")
    if not os.path.exists(outdir):
        print("Creating output directory:", outdir)
        os.makedirs(outdir, exist_ok=True)
        
    # Use outdir as the actual output directory
    args.out = outdir


    ## check for and load the SAGE config file
    if not os.path.exists(args.sage_config):
        print("SAGE config file not found:", args.sage_config)
        quit()

    with open(args.sage_config, 'r') as f:
        sage_config = json.load(f)
    print("Loaded SAGE config:", sage_config)


    ## Validate mzML directory exists
    if not os.path.exists(args.mzml_dir):
        print(f"Error: mzML directory does not exist: {args.mzml_dir}")
        quit()
    
    # Convert mzml_dir to absolute path for reliable file resolution in containers
    mzml_dir_abs = os.path.abspath(args.mzml_dir)
    print(f"Using absolute mzML directory: {mzml_dir_abs}")
        
    ## get the list of mzML files
    if args.mzml_file:
        # Per-file mode: process only a specific file
        mzml_path = os.path.join(mzml_dir_abs, args.mzml_file)
        if not os.path.exists(mzml_path):
            print(f"Error: Specified mzML file not found: {mzml_path}")
            quit()
        mzml_files = [mzml_path]
        print(f"Per-file mode: Processing single file: {args.mzml_file}")
    else:
        # Aggregate mode: process all mzML files in directory
        mzml_files = glob.glob(os.path.join(mzml_dir_abs, "*.mzML"))
        if not mzml_files:
            print("No .mzML files found in directory:", mzml_dir_abs)
            quit()
        print(f"Aggregate mode: Found {len(mzml_files)} .mzML files in {mzml_dir_abs}")
    
    print(f"Files to process: {mzml_files}")

    # Convert mzML paths to absolute paths for SAGE (required for container compatibility)
    # Files from glob.glob are already absolute since mzml_dir_abs is absolute
    mzml_files_abs = [os.path.abspath(f) for f in mzml_files]
    print(f"Absolute paths: {mzml_files_abs}")
    
    # update the SAGE config with absolute mzML paths
    sage_config['mzml_paths'] = mzml_files_abs


    # For closed searches, force reviewed-only to avoid stack overflow with huge databases
    # The full human proteome (61K proteins × 2 for decoys = 122K) causes SAGE to overflow its stack
    # Reviewed-only (20K proteins × 2 = 40K) is manageable
    use_reviewed = args.reviewed_only or args.ClosedSearch
    
    print(f"DEBUG: use_reviewed = {use_reviewed} (args.reviewed_only={args.reviewed_only}, args.ClosedSearch={args.ClosedSearch})")
    
    # Determine FASTA filename and URL
    fasta_type = 'reviewed' if use_reviewed else 'all'
    fasta_filename = f"{args.taxid}_{fasta_type}.fasta"
    if use_reviewed:
        print(f'Using reviewed-only FASTA for taxid {args.taxid} from UniProt (closed search optimization)')
        url = f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query=organism_id:{args.taxid}+AND+reviewed:true"
    else:
        print(f'Using full FASTA for taxid {args.taxid} from UniProt')
        url = f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query=organism_id:{args.taxid}"
    
    # Centralized FASTA cache directory in results folder
    # This avoids searching multiple fallback locations and keeps all FASTA files organized in one place
    if args.fasta_cache_dir:
        # Explicit cache directory provided
        fasta_cache_dir = args.fasta_cache_dir
        fasta_path = os.path.join(fasta_cache_dir, fasta_filename)
        print(f"Using provided FASTA cache directory: {fasta_cache_dir}")
    else:
        # Fallback to original logic
        parent_dirname = os.path.basename(os.path.dirname(outdir))
        results_root = os.path.dirname(os.path.dirname(outdir)) if parent_dirname in {"sage_results", "search"} else None
        
        if results_root and os.path.exists(os.path.dirname(results_root)):
            # We're in a PXD results folder, use centralized cache
            fasta_cache_dir = os.path.join(os.path.dirname(results_root), ".fasta_cache")
            fasta_path = os.path.join(fasta_cache_dir, fasta_filename)
            print(f"Using centralized FASTA cache: {fasta_cache_dir}")
        else:
            # Fallback to output directory
            fasta_path = os.path.join(outdir, fasta_filename)
            print(f"Using local FASTA output directory: {outdir}")
    
    print(f'Using URL: {url}')
    print(f'Using FASTA file: {fasta_path}')
    
    if os.path.isfile(fasta_path):
        print(f'FASTA file already exists (reusing): {fasta_path}')
    else:
        # Ensure cache directory exists
        fasta_cache_dir = os.path.dirname(fasta_path)
        os.makedirs(fasta_cache_dir, exist_ok=True)
        
        # Download FASTA with retries and exponential backoff
        max_retries = 5
        for attempt in range(max_retries):
            try:
                print(f'Downloading FASTA (attempt {attempt + 1}/{max_retries})...')
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                with open(fasta_path, "wb") as f:
                    f.write(response.content)
                print(f'SAVED: {fasta_path}')
                break
            except (requests.exceptions.RequestException, OSError) as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt)  # Exponential backoff: 1, 2, 4, 8, 16 seconds
                    print(f'Download failed (attempt {attempt + 1}/{max_retries}): {e}')
                    print(f'Retrying in {wait_time} seconds...')
                    time.sleep(wait_time)
                else:
                    print(f'Download failed after {max_retries} attempts: {e}')
                    raise FileNotFoundError(f"Could not download FASTA for taxid {args.taxid} from UniProt. Server may be unavailable.")
    
    if not os.path.isfile(fasta_path):
        print(f'Error: {fasta_path} not found.')
        raise FileNotFoundError
    else:
        fasta_size_mb = os.path.getsize(fasta_path) / (1024 * 1024)
        print(f'FASTA file ready: {fasta_path} ({fasta_size_mb:.1f} MB)')
        
        # Fallback for closed search: if reviewed-only FASTA is empty/too small, use full FASTA
        if use_reviewed and fasta_size_mb < 0.1:
            print(f'WARNING: Reviewed-only FASTA is empty ({fasta_size_mb:.1f} MB)')
            print(f'Falling back to full FASTA database for taxid {args.taxid}')
            
            # Download/use full FASTA instead
            full_fasta_filename = f"{args.taxid}_all.fasta"
            full_fasta_path = os.path.join(os.path.dirname(fasta_path), full_fasta_filename)
            
            if os.path.isfile(full_fasta_path):
                print(f'Using existing full FASTA: {full_fasta_path}')
                fasta_path = full_fasta_path
            else:
                print(f'Downloading full FASTA database...')
                full_url = f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query=organism_id:{args.taxid}"
                max_retries = 5
                for attempt in range(max_retries):
                    try:
                        print(f'Downloading full FASTA (attempt {attempt + 1}/{max_retries})...')
                        response = requests.get(full_url, timeout=60)
                        response.raise_for_status()
                        with open(full_fasta_path, "wb") as f:
                            f.write(response.content)
                        print(f'SAVED: {full_fasta_path}')
                        fasta_path = full_fasta_path
                        break
                    except (requests.exceptions.RequestException, OSError) as e:
                        if attempt < max_retries - 1:
                            wait_time = (2 ** attempt)
                            print(f'Download failed (attempt {attempt + 1}/{max_retries}): {e}')
                            print(f'Retrying in {wait_time} seconds...')
                            time.sleep(wait_time)
                        else:
                            print(f'Download of full FASTA also failed after {max_retries} attempts')
                            print(f'Proceeding with empty FASTA (closed search will find 0 PSMs)')
            
            fasta_size_mb = os.path.getsize(fasta_path) / (1024 * 1024)
            print(f'FASTA file ready: {fasta_path} ({fasta_size_mb:.1f} MB)')
    
    # Use absolute path in SAGE config (important for container execution)
    fasta_path_abs = os.path.abspath(fasta_path)
    sage_config['database']['fasta'] = fasta_path_abs
    print(f'Using absolute FASTA path in config: {fasta_path_abs}')


    # remove quant section if PSM-only (for closed search, this should be conditional)
    if args.PSM_only and 'quant' in sage_config:
        del sage_config['quant']
        config_suffix = "_PSM-only"
    else:
        config_suffix = ""

    # add open search flag if needed
    if args.OpenSearch:
        # For open search, remove ALL mods (both variable and static) for clearest PTM discovery
        # PTM-Shepherd needs unmodified peptide masses as the baseline to detect modifications
        # Any static mod (like C+57) will shift the baseline and obscure true PTM mass shifts
        sage_config['database']['variable_mods'] = {}
        sage_config['database']['static_mods'] = {}  # Remove static mods for open search
        sage_config['precursor_tol'] = {"da": [-500, 500]}
        sage_config['fragment_tol'] = {"ppm": [-25, 25]}
        sage_config['deisotope'] = True
        print("Open search mode: removed all static and variable mods for clearest PTM mass shift detection")

    # add closed search configuration
    elif args.ClosedSearch:
        # For closed search: keep C+57 as static mod (standard from sample prep alkylation)
        # Apply variable mods from pass 1 PTM discovery via --variable_mods argument

        # Merge static mods instead of overwriting (preserve labeling/static mods from config)
        base_static_mods = sage_config.get('database', {}).get('static_mods') or {}
        if not isinstance(base_static_mods, dict):
            base_static_mods = {}
        merged_static_mods = dict(base_static_mods)

        # Always retain carbamidomethyl (C+57) as static mod - it's from sample prep, not a PTM
        merged_static_mods.setdefault("C", 57.02146)

        # Apply additional static mods if provided (e.g., high-percent PTMs from PTM-Shepherd)
        if args.static_mods:
            try:
                static_mods_dict = json.loads(args.static_mods)
                if not isinstance(static_mods_dict, dict):
                    raise ValueError("--static_mods must be a JSON object")
                for k, v in static_mods_dict.items():
                    if k in merged_static_mods and abs(float(merged_static_mods[k]) - float(v)) > 1e-6:
                        print(f"  Warning: static_mods collision for '{k}': keeping {merged_static_mods[k]}, ignoring {v}")
                        continue
                    merged_static_mods[k] = float(v)
                print(f"Applied static mods from --static_mods: {static_mods_dict}")
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Error parsing --static_mods JSON: {e}")
                print("Closed search requires valid --static_mods JSON if provided")

        sage_config['database']['static_mods'] = merged_static_mods
        
        # Apply variable mods (discovered PTMs from pass 1)
        if args.variable_mods:
            try:
                # Parse JSON string of variable mods from --variable_mods argument
                variable_mods_dict = json.loads(args.variable_mods)
                sage_config['database']['variable_mods'] = variable_mods_dict
                print(f"Applied variable mods from --variable_mods: {variable_mods_dict}")
            except json.JSONDecodeError as e:
                print(f"Error parsing --variable_mods JSON: {e}")
                print("Closed search requires valid --variable_mods JSON")
                sage_config['database']['variable_mods'] = {}
        else:
            print("WARNING: Closed search mode but no --variable_mods provided")
            sage_config['database']['variable_mods'] = {}
        
        # Set closed search tolerances (±20 ppm for precursor, ±25 ppm for fragments)
        sage_config['precursor_tol'] = {"ppm": [-20, 20]}
        sage_config['fragment_tol'] = {"ppm": [-25, 25]}
        sage_config['isotope_errors'] = [0, 2]
        sage_config['deisotope'] = True
        
        # Configure quantification based on detected labeling type
        if not args.PSM_only:
            quant_config = get_quantification_config(args.labeling)
            if quant_config:
                sage_config['quant'] = quant_config
                print(f"Applied quantification config for {args.labeling}: {quant_config}")
            elif 'quant' in sage_config:
                # Keep existing quant config if no mapping for labeling
                print(f"No specific quant config for {args.labeling}, keeping existing config")
            else:
                print(f"Warning: No quantification config found for {args.labeling}")
        
        print(f"Closed search mode with mods: {sage_config['database']['variable_mods']}")

    updated_sage_config_path = os.path.join(outdir, f"updated_sage_config{config_suffix}.json")

    # write updated SAGE config to file in outdir
    with open(updated_sage_config_path, 'w') as f:
        json.dump(sage_config, f, indent=4)
    print("Wrote updated SAGE config to:", updated_sage_config_path)

  
    #########################################################################
    # run SAGE and capture output
    sage_psm_output_file = os.path.join(outdir, "results.sage.tsv")
    if os.path.isfile(sage_psm_output_file):
        print("SAGE output file already exists and will be used:", sage_psm_output_file)
    
    else:
        print("Running SAGE...")
        rc, out_log, err_log = run_sage(updated_sage_config_path, outdir)
        print("SAGE run complete.")
        if not os.path.isfile(sage_psm_output_file):
            print("Error: SAGE output file not found:", sage_psm_output_file)
            quit()
        print("SAGE output file:", sage_psm_output_file)
    #########################################################################

    #########################################################################
    df = pd.read_csv(sage_psm_output_file, sep="\t")
    # print(df)

    out = convert_sage_to_ptmshepherd(df, args)

    fragpipe_out = os.path.join(args.out, "psm.ptmshepherd.tsv")
    out.to_csv(fragpipe_out, sep="\t", index=False)
    print("Wrote:", fragpipe_out)


    #########################################################################
    ## run PTM-Shepherd if desired
    try:
        run_ptmshepherd(fragpipe_out, dataset_name="SAGE_Output", mzml_dir=args.mzml_dir)
    except Exception as e:
        print(f"\nWARNING: PTM-Shepherd failed: {e}")
        print("Continuing without PTM modifications...")
        # The open search PSMs are still valid for analysis even without PTM-Shepherd
        # PTM-Shepherd is mainly useful for discovering new PTMs, which is optional

if __name__ == "__main__":
    main()
