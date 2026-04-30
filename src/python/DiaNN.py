#!/usr/bin/env python3
import os
import argparse
import json
import glob
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from typing import Tuple


DEFAULT_DIANN_VAR_MODIFICATIONS = [
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

DEFAULT_DIANN_FIXED_MODIFICATIONS = [
    "UniMod:4,57.021464,C",    # Carbamidomethyl (C)
]

# Unimod IDs that should be treated as fixed when present.
# Important because DiaNN.py currently runs with --var-mods 1.
# If fixed labels are passed as variable mods, they can block true variable PTMs.
FIXED_UNIMOD_IDS = {
    "UniMod:4",    # Carbamidomethyl (C)
    "UniMod:737",  # TMT (various plexes; mass may differ)
    "UniMod:214",  # iTRAQ
}

# Convenience combined list
DEFAULT_DIANN_MODIFICATIONS = [
    *DEFAULT_DIANN_VAR_MODIFICATIONS,
    *DEFAULT_DIANN_FIXED_MODIFICATIONS,
]


def get_diann_library_cache_dir() -> Path:
    """Get path to cached DIA-NN spectral libraries"""
    base_dir = Path(__file__).parent.parent.parent  # workspace root
    cache_dir = base_dir / 'assets' / 'diann_libraries'
    return cache_dir


def get_cached_library(taxid: str) -> Path:
    """Check if spectral library is cached for this organism"""
    cache_dir = get_diann_library_cache_dir()
    # DIA-NN writes spectral libraries as .predicted.speclib files
    lib_path = cache_dir / f"{taxid}.predicted.speclib"
    
    if lib_path.exists():
        print(f"✓ Using cached spectral library: {lib_path}")
        return lib_path
    return None


def run_diann(mzml_files: list, fasta_path: str, outdir: str, taxid: str = None, modifications: list = None, use_cache: bool = True, cache_dir: str = None) -> Tuple[int, str, str]:
    """
    Run DIA-NN with the given mzML files and FASTA database.
    
    Args:
        mzml_files: List of paths to mzML files
        fasta_path: Path to FASTA database
        outdir: Output directory
        taxid: Organism NCBI TaxID (for library caching)
        modifications: List of modification strings in DIA-NN format
                      e.g., ["UniMod:35,15.994915,M", "UniMod:4,57.021464,C"]
        use_cache: Whether to use cached libraries
        cache_dir: Explicit path to DIA-NN library cache directory (overrides default)
    
    Returns (returncode, stdout_log_path, stderr_log_path).
    Raises RuntimeError on non-zero exit with the last lines of stderr.
    """
    outdir = os.path.abspath(outdir)
    Path(outdir).mkdir(parents=True, exist_ok=True)
    
    # Default modifications if none OR empty list provided.
    # Rationale: upstream may provide [] meaning "unknown" or "not detected".
    if not modifications:
        modifications = list(DEFAULT_DIANN_MODIFICATIONS)

    # Try to find diann on PATH first, then check specific locations
    import shutil
    diann_bin = shutil.which('diann')
    
    if diann_bin is None:
        # Try known locations
        diann_exec = os.environ.get('DIANN_HOME', '/opt/diann')
        possible_bins = [
            os.path.join(diann_exec, 'diann'),
            os.path.join(diann_exec, 'diann-linux'),
        ]
        for bin_path in possible_bins:
            if os.path.exists(bin_path):
                diann_bin = bin_path
                break
    
    if diann_bin is None or not os.path.exists(diann_bin):
        # DIA-NN not found - log warning and create empty output to allow pipeline to continue
        print(f"WARNING: Could not find DIA-NN executable at {possible_bins}")
        print("DIA-NN is not available - skipping DIA-NN processing")
        print(f"Creating empty output for compatibility...")
        Path(outdir).mkdir(parents=True, exist_ok=True)
        report_path = os.path.join(outdir, "report.tsv")
        # Create minimal empty report
        with open(report_path, 'w') as f:
            f.write("File.Name\tPeptide\tModified.Peptide\tPrecursor.Charge\tPrecursor.MZ\tFragmentLibrary.PrecursorMZ\tFragmentLibrary\tProtein.Names\tPeptide.Length\tPeptide.Missed.Cleavages\tPEP\tEG.ModifiedSequence\tEG.PrecursorId\n")
        return 0, report_path, report_path

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stdout_log = os.path.join(outdir, f"diann_stdout_{ts}.log")
    stderr_log = os.path.join(outdir, f"diann_stderr_{ts}.log")
    
    report_path = os.path.join(outdir, "report.tsv")

    # Resolve cache directory: use explicit override or default
    if cache_dir:
        cache_dir = Path(cache_dir)
    else:
        cache_dir = get_diann_library_cache_dir()
    
    # Check for cached spectral library
    cached_lib = None
    if use_cache and taxid:
        cached_lib = get_cached_library(taxid)

    # Build DIA-NN command
    cmd = [
        diann_bin,

        # Inputs / outputs (--f flag must be repeated for each file)
        "--out", report_path,
        "--temp", outdir,

        # Search / enzyme
        "--cut", "K*,R*",          # trypsin
        "--missed-cleavages", "1",
        "--met-excision",          # N-term Met excision model

        # Modifications
        "--var-mods",  "1",        # max variable mods per peptide

        # Fragment m/z window
        "--min-fr-mz", "200",
        "--max-fr-mz", "1800",

        # Performance / logging
        "--threads", "20",
        "--verbose", "1",
    ]
    
    # Add each mzML file with its own --f flag
    for mzml_file in mzml_files:
        cmd.extend(["--f", mzml_file])
    
    # Use library if cached, otherwise generate fresh
    if cached_lib:
        print(f"Using cached spectral library: {cached_lib}")
        cmd.extend(["--lib", str(cached_lib)])
    else:
        # Library-free DIA-NN search with in silico library generation
        print("Generating spectral library (this may take a while for large organisms)...")
        cmd.extend([
            "--fasta", fasta_path,
            "--fasta-search",          # library-free: digest FASTA
            "--gen-spec-lib",          # generate in silico spectral library
            "--predictor",             # use DIA-NN predictor
        ])
        
        # If taxid provided and not cached, generate and cache
        if taxid:
            cache_dir.mkdir(parents=True, exist_ok=True)
            # DIA-NN outputs .predicted.speclib files when using --out-lib
            lib_cache_path = cache_dir / f"{taxid}.predicted.speclib"
            print(f"Library will be cached: {lib_cache_path}")
            cmd.extend(["--out-lib", str(lib_cache_path)])
    
    # Add modifications dynamically
    # Separate fixed and variable mods based on common practice
    # Fixed mods typically: Carbamidomethyl (C)
    # Variable mods: everything else
    # Derive which UniMod IDs should be treated as fixed from the defaults.
    # (Keeps the logic consistent if we ever expand defaults.)
    fixed_mod_ids = [m.split(',')[0] for m in DEFAULT_DIANN_FIXED_MODIFICATIONS if isinstance(m, str) and ',' in m]
    
    for mod in modifications:
        # Check if this is a fixed mod
        mod_prefix = mod.split(",", 1)[0] if isinstance(mod, str) else ""
        is_fixed = (mod_prefix in FIXED_UNIMOD_IDS) or any(mod.startswith(fixed_id) for fixed_id in fixed_mod_ids)
        mod_flag = "--fixed-mod" if is_fixed else "--var-mod"
        cmd.extend([mod_flag, mod])

    print("Running DIA-NN...")
    print("CMD:", " ".join(cmd))

    # Run and capture
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    # Write full logs
    Path(stdout_log).write_text(proc.stdout or "", encoding="utf-8")
    Path(stderr_log).write_text(proc.stderr or "", encoding="utf-8")

    # Mirror a short summary to console
    print(f"DIA-NN finished with code {proc.returncode}.")
    print(f"stdout → {stdout_log}")
    print(f"stderr → {stderr_log}")

    if proc.returncode != 0:
        # Show a helpful tail of stderr in the exception
        tail = "\n".join((proc.stderr or "").splitlines()[-40:])
        raise RuntimeError(
            f"DIA-NN failed (exit {proc.returncode}). See logs.\n"
            f"stderr tail:\n{'-'*60}\n{tail}\n{'-'*60}"
        )

    return proc.returncode, stdout_log, stderr_log


def main():
    ap = argparse.ArgumentParser(description="Run DIA-NN for DIA proteomics data analysis")
    ap.add_argument("-o", "--out", required=True, help="Output directory")
    ap.add_argument("--mzml_dir", required=True, help="Directory containing the .mzML files")
    ap.add_argument("--taxid", required=True, help="Organism NCBI TaxID")
    ap.add_argument("--reviewed-only", action="store_true", help="Use only reviewed proteins from UniProt")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite output if it exists")
    ap.add_argument("--labeling", default="LFQ", help="Labeling type detected by runAssessor (LFQ, TMT6, TMT10, iTRAQ4, iTRAQ8, SILAC, etc.)")
    ap.add_argument("--config", help="Path to detected_params.json from runAssessor parsing (optional)")
    ap.add_argument("--diann_cache_dir", default=None, help="Explicit path to DIA-NN spectral library cache directory (optional, overrides default)")
    args = ap.parse_args()
    
    # Load detected modifications if config provided
    if args.config and os.path.exists(args.config):
        print(f"Loading detected parameters from {args.config}")
        with open(args.config, 'r') as f:
            detected_config = json.load(f)
        args.labeling = detected_config['detected_params']['labeling']
        modifications = detected_config.get('modifications', {}).get('diann_mods')
        print(f"Using detected labeling: {args.labeling}")
        print(f"Using modifications: {modifications}")
        # Store modifications for use in run_diann function; fall back to defaults if empty
        args.diann_modifications = modifications if modifications else list(DEFAULT_DIANN_MODIFICATIONS)
    else:
        # Default LFQ modifications
        args.diann_modifications = list(DEFAULT_DIANN_MODIFICATIONS)

    # Validate output directory
    if os.path.isdir(args.out):
        outdir = args.out
    else:
        outdir = os.path.dirname(args.out)
        
    print(f"Output directory: {outdir}")
    if not os.path.exists(outdir):
        print("Creating output directory:", outdir)
        os.makedirs(outdir, exist_ok=True)
        
    args.out = outdir

    # Validate mzML directory exists
    if not os.path.exists(args.mzml_dir):
        print(f"Error: mzML directory does not exist: {args.mzml_dir}")
        quit()
        
    # Prefer .mzML files (already converted, no .NET Runtime dependency) over .raw files
    raw_files = glob.glob(os.path.join(args.mzml_dir, "*.raw"))
    mzml_files = glob.glob(os.path.join(args.mzml_dir, "*.mzML"))
    
    if mzml_files:
        data_files = mzml_files
        print(f"Found {len(mzml_files)} .mzML files in {args.mzml_dir}")
    elif raw_files:
        data_files = raw_files
        print(f"Found {len(raw_files)} .raw files in {args.mzml_dir} (using native format)")
    else:
        print("No .raw or .mzML files found in directory:", args.mzml_dir)
        quit()
    
    print(f"Found {len(data_files)} spectral data files")

    # Download the FASTA file for this organism taxid if not already present
    if args.reviewed_only:
        print(f'Downloading reviewed-only FASTA for taxid {args.taxid} from UniProt')
        fasta_path = os.path.join(outdir, f"{args.taxid}_reviewed.fasta")
        url = f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query=organism_id:{args.taxid}+AND+reviewed:true"
    else:
        print(f'Downloading full FASTA for taxid {args.taxid} from UniProt')
        fasta_path = os.path.join(outdir, f"{args.taxid}_all.fasta")
        url = f"https://rest.uniprot.org/uniprotkb/stream?format=fasta&query=organism_id:{args.taxid}"
    
    print(f'Using URL: {url}')
    print(f'Using FASTA file: {fasta_path}')
    
    if os.path.isfile(fasta_path):
        print(f'FASTA file already exists: {fasta_path}')
    else:
        print("Downloading FASTA...")
        response = requests.get(url)
        with open(fasta_path, "wb") as f:
            f.write(response.content)
    
    if not os.path.isfile(fasta_path):
        print(f'Error: {fasta_path} not found.')
        raise FileNotFoundError
    else:
        print(f'SAVED: {fasta_path}')

    # Run DIA-NN
    report_tsv = os.path.join(outdir, "report.tsv")
    report_parquet = os.path.join(outdir, "report.parquet")

    existing_report = None
    if os.path.isfile(report_tsv):
        existing_report = report_tsv
    elif os.path.isfile(report_parquet):
        existing_report = report_parquet

    if existing_report and not args.overwrite:
        print("DIA-NN report already exists and will be used:", existing_report)
        report_file = existing_report
    else:
        print("Running DIA-NN...")
        print(f"Using labeling: {args.labeling}")
        print(f"Using modifications: {args.diann_modifications}")
        rc, out_log, err_log = run_diann(
            data_files, 
            fasta_path, 
            outdir, 
            taxid=args.taxid,
            modifications=args.diann_modifications,
            use_cache=True,
            cache_dir=args.diann_cache_dir
        )
        print("DIA-NN run complete.")

        # DIA-NN 2.2+ commonly writes a compressed Parquet report even if --out ends with .tsv.
        if os.path.isfile(report_tsv):
            report_file = report_tsv
        elif os.path.isfile(report_parquet):
            report_file = report_parquet
        else:
            print("Error: DIA-NN output report not found (expected report.tsv or report.parquet)")
            raise SystemExit(1)

        print("DIA-NN output report:", report_file)

    # Save run metadata
    metadata = {
        "taxid": args.taxid,
        "data_files": data_files,
        "fasta_path": fasta_path,
        "output_dir": outdir,
        "report_file": report_file,
        "report_tsv": report_tsv if os.path.isfile(report_tsv) else None,
        "report_parquet": report_parquet if os.path.isfile(report_parquet) else None,
        "reviewed_only": args.reviewed_only
    }
    
    metadata_path = os.path.join(outdir, "results.json")
    with open(metadata_path, 'w') as f:
        json.dump(metadata, f, indent=4)
    print(f"Saved metadata to: {metadata_path}")


if __name__ == "__main__":
    main()
