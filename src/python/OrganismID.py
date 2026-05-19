import argparse
import json
import os
import pandas as pd
import re
import subprocess
import shutil
import glob
import sys
from pathlib import Path
from pyteomics import fasta, parser
from collections import defaultdict

# Add parent directory to path for importing PipelineLogger
sys.path.insert(0, str(Path(__file__).parent))
from PipelineLogger import PipelineLogger
###############################################

def _conda_wrap(cmd, *, conda_exe=None, env_path=None):
    """Optionally prefix a command with `conda run -p <env_path>`.

    If `env_path` is falsy, returns `cmd` unchanged.
    """
    if not env_path:
        return cmd
    conda_exe = conda_exe or os.environ.get("CONDA_EXE") or "conda"
    return [conda_exe, "run", "-p", env_path, "--no-capture-output", *cmd]


def _ensure_writable_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _default_cache_home() -> str:
    # In Nextflow tasks, CWD is the work dir and should be writable.
    return os.environ.get("XDG_CACHE_HOME") or os.path.join(os.getcwd(), ".cache")


def _prepend_env_lib_to_ld_library_path(env: dict, env_prefix: str | None) -> dict:
    """Return a copy of env with <env_prefix>/lib prepended to LD_LIBRARY_PATH.

    This avoids accidental linkage against system libstdc++/libgcc when running
    conda-installed binaries under a scheduler/module environment.
    """
    if not env_prefix:
        return env
    libdir = os.path.join(env_prefix, "lib")
    if not os.path.isdir(libdir):
        return env
    env2 = dict(env)
    old = env2.get("LD_LIBRARY_PATH", "")
    env2["LD_LIBRARY_PATH"] = f"{libdir}:{old}" if old else libdir
    return env2

###############################################
def convert_ssl_to_mztab(ssl_file, mztab_file):
    """
    Convert Cascadia .ssl output to .mztab format for compatibility with downstream processing.
    
    Cascadia SSL columns: file, scan, charge, sequence, score, retention-time
    We need to map these to the expected mztab columns used in the pipeline:
    - stripped_sequence (from sequence) 
    - search_engine_score[1] (from score)
    - Plus dummy values for other expected columns
    """
    try:
        import pandas as pd
        
        # Read the SSL file
        df_ssl = pd.read_csv(ssl_file, sep='\t')
        
        # Create mztab format dataframe
        df_mztab = pd.DataFrame()
        
        # Map columns from SSL to mztab format
        df_mztab['stripped_sequence'] = df_ssl['sequence']
        df_mztab['search_engine_score[1]'] = df_ssl['score']
        df_mztab['sequence'] = df_ssl['sequence']  # Keep full sequence for compatibility
        df_mztab['charge'] = df_ssl['charge']
        df_mztab['retention_time'] = df_ssl['retention-time'] 
        df_mztab['spectrum_reference'] = df_ssl['scan']
        
        # Add dummy columns that might be expected by downstream processing
        df_mztab['opt_ms_run[1]_aa_scores'] = '0.8,0.8,0.8,0.8,0.8'  # Dummy AA scores
        df_mztab['exp_mass_to_charge'] = 0.0  # Will be calculated if needed
        df_mztab['calc_mass_to_charge'] = 0.0  # Will be calculated if needed
        
        # Save as tab-delimited file (mztab format)
        df_mztab.to_csv(mztab_file, sep='\t', index=False)
        print(f"Successfully converted {ssl_file} to {mztab_file}")
        print(f"Converted {len(df_mztab)} peptide identifications")
        
    except Exception as e:
        print(f"Error converting SSL to mztab: {e}")
        # Create an empty mztab file to avoid downstream errors
        with open(mztab_file, 'w') as f:
            f.write("stripped_sequence\tsearch_engine_score[1]\tsequence\tcharge\tretention_time\tspectrum_reference\topt_ms_run[1]_aa_scores\texp_mass_to_charge\tcalc_mass_to_charge\n")

###############################################

###############################################
def add_aa_scores_average(df):
    col = 'opt_ms_run[1]_aa_scores'
    if col in df.columns:
        def avg_scores(val):
            try:
                floats = [float(x) for x in str(val).split(',') if x]
                return sum(floats) / len(floats) if floats else pd.NA
            except Exception:
                return pd.NA
        df[col + '_avg'] = df[col].apply(avg_scores)
    return df
###############################################

###############################################
def filter_peptides(df, min_length=10, min_score=0.7, outfile='filtered_peptides.tsv', contaminants_fasta:str='data/FASTA/UniversalContaminats.fasta'):
    """
    Filter peptides based on specific criteria.
    1. longer than 10 residues. 
    2. have an average aa_score >= 0.7
    """
 
    # Required columns for filtering + output
    required_cols = {'stripped_sequence', 'search_engine_score[1]'}
    missing = required_cols.difference(set(df.columns))
    if missing:
        print(f"Required columns not found ({sorted(missing)}); skipping filtering for {outfile}")
        # Keep behavior predictable for callers
        return df, []

    def extract_modification_tags(seq):
        # Extract modification tags from the sequence
        return [tag for tag in seq.split('-') if '[' in tag and ']' in tag]

    seq_len = df['stripped_sequence'].fillna('').astype(str).str.len()
    score = pd.to_numeric(df['search_engine_score[1]'], errors='coerce')

    filtered_df = df[(seq_len > min_length) & (score >= float(min_score))].copy()
    print(f"Filtered peptides: {len(filtered_df)} out of {len(df)}")

    filtered_df.rename(columns={'stripped_sequence': 'peptide','search_engine_score[1]': 'score'}, inplace=True)

    # Remove contaminants
    filtered_df = remove_contaminants(filtered_df, contaminants_fasta=contaminants_fasta)
    print(f'Filtered peptides {min_score}:\n{filtered_df}')
    
    # Save the parsed Casanovo PSMs to a TSV file
    filtered_df.to_csv(outfile, sep='\t', index=False)
    print(f'Saved: {outfile}')

    # Save a slim version with just the peptide and score columns
    slim_outfile = outfile.replace('.tsv', '_slim.tsv')
    filtered_df[['peptide', 'score']].to_csv(slim_outfile, sep='\t', index=False)
    print(f'Saved: {slim_outfile}')
    outfile_list = [outfile, slim_outfile]
    return filtered_df, outfile_list
###############################################

###############################################
def remove_contaminants(df, contaminants_fasta:str='data/FASTA/UniversalContaminats.fasta'):

    # --- inputs ---
    enzyme = "trypsin"                          # trypsin, no-P rule
    missed_cleavages = 2
    min_len, max_len = 6, 50
    treat_I_L_as_same = True

    # --- digest contaminant FASTA ---
    cont_pep_to_accessions = defaultdict(set)
    cont_accession_to_desc = {}

    for header, seq in fasta.read(contaminants_fasta):
        # store accession and description
        acc = header.split()[0]
        cont_accession_to_desc[acc] = header

        # digest
        peps = parser.cleave(seq, parser.expasy_rules[enzyme], missed_cleavages=missed_cleavages, min_length=min_len, max_length=max_len)
        for p in peps:
            cont_pep_to_accessions[p].add(acc)

    # --- match peptides to contaminant peptides ---
    # Only process contaminants if there are peptides to check
    if len(df) > 0:
        df['contam_accessions'] = df['peptide'].map(lambda p: sorted(cont_pep_to_accessions.get(p, [])))
        df['is_contaminant_exact'] = df['contam_accessions'].map(lambda s: len(s) > 0)
        print(f'Contaminant peptides found: {df["is_contaminant_exact"].sum()} out of {len(df)}')
        
        # Only try to display contaminant peptides if there are any
        if df['is_contaminant_exact'].sum() > 0:
            contaminant_df = df[df['is_contaminant_exact']][['peptide', 'score', 'contam_accessions']]
            print(f'Contaminant peptides:\n{contaminant_df.to_string(index=False)}')
        
        df = df[~df['is_contaminant_exact']].copy()
        df = df.drop(columns=['contam_accessions', 'is_contaminant_exact'])
    else:
        print(f'Contaminant peptides found: 0 out of 0 (no peptides after filtering)')

    return df
###############################################

###############################################
def _load_denovo_table(path: str) -> pd.DataFrame | None:
    """Load either (a) a real mzTab containing PSH/PSM lines or (b) a plain TSV.
    
    For mzTab files:
    - PSH lines define the column header
    - PSM lines contain the actual data
    - MTD and other lines are skipped
    """
    psm_lines: list[str] = []
    header = None
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if line.startswith('PSM\t'):  # PSM data line (starts with PSM followed by tab)
                psm_lines.append(line)
            elif line.startswith('PSH\t'):  # PSH header line
                header = line.split('\t')

    # If we found PSH header and PSM data lines, parse as mzTab
    if header and psm_lines:
        try:
            # PSM lines include "PSM" as first column, so include it in data
            data = [l.split('\t') for l in psm_lines]
            df = pd.DataFrame(data, columns=header)
            df = df.replace('null', pd.NA)
            df = df.dropna(axis=1, how='all')
            print(f"Successfully parsed mzTab format: {len(df)} PSM lines with {len(header)} columns")
            return df
        except Exception as e:
            print(f"Failed to parse mzTab PSM/PSH lines: {e}")
            return None

    # Fallback: Try reading as plain TSV, skipping known header lines
    try:
        # Read the file and skip lines that start with MTD, PRH, etc. (mzTab metadata)
        with open(path, 'r') as f:
            content = [line.strip() for line in f if not line.startswith(('MTD', 'PRH', 'COM'))]
        
        if content:
            import io
            tsv_content = '\n'.join(content)
            df = pd.read_csv(io.StringIO(tsv_content), sep='\t')
            print(f"Successfully parsed as TSV (skipping MTD lines): {len(df)} rows")
            return df
        else:
            print(f"No parseable data found in {path}")
            return None
    except Exception as e:
        print(f"Could not parse {path} as mzTab or TSV; skipping. Reason: {e}")
        return None


def _normalize_denovo_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize disparate tool outputs to a common schema used by filtering."""
    df = df.copy()

    # score column
    if 'search_engine_score[1]' not in df.columns:
        if 'score' in df.columns:
            df['search_engine_score[1]'] = df['score']
    df['search_engine_score[1]'] = pd.to_numeric(df.get('search_engine_score[1]'), errors='coerce')

    # stripped sequence
    if 'stripped_sequence' not in df.columns:
        df = add_stripped_sequence_column(df)

    # aa scores average (optional; used only if present downstream)
    if 'opt_ms_run[1]_aa_scores' in df.columns and 'opt_ms_run[1]_aa_scores_avg' not in df.columns:
        df = add_aa_scores_average(df)

    return df


def process_denovo_files(denovo_files, *, contaminants_fasta: str, denovo_threshold_pct: int):
    """Process de novo outputs (Casanovo mzTab or Cascadia TSV) into filtered peptide TSVs."""
    outfiles: list[str] = []
    min_score = float(denovo_threshold_pct) / 100.0

    for path in denovo_files:
        print(f'\nProcessing: {path}')
        df = _load_denovo_table(path)
        if df is None or df.empty:
            continue
        df = _normalize_denovo_df(df)

        tsv_path = os.path.splitext(path)[0] + '_processed.tsv'
        df.to_csv(tsv_path, sep='\t', index=False)
        print(f'Saved: {tsv_path}')

        filtered_outfile = tsv_path.replace('_processed.tsv', f'_filtered{denovo_threshold_pct}pct.tsv')
        _, outfile_list = filter_peptides(
            df,
            min_score=min_score,
            outfile=filtered_outfile,
            contaminants_fasta=contaminants_fasta,
        )
        outfiles.extend(outfile_list)

    return outfiles
###############################################

###############################################
def strip_modifications(seq):
    # Remove N-terminal modifications like [Acetyl]-
    seq = re.sub(r'^\[.*?\]-', '', seq)
    # Remove all [Modification] tags
    seq = re.sub(r'\[.*?\]', '', seq)
    # Remove any leading/trailing whitespace
    return seq.strip()

def add_stripped_sequence_column(df):
    if 'sequence' in df.columns:
        df['stripped_sequence'] = df['sequence'].apply(strip_modifications)
    return df
###############################################

###############################################
def make_config(input_file, data_dir, log_dir, config_path, taxid_list_str):
    # prefer env var from container; fallback to where you had it on the host
    script_dir = os.environ.get(
        "PEPTONIZER2000_HOME",
        "/workspace/src/Peptonizer2000"
    )
    script_dir = os.path.join(script_dir, "snakemake", "workflow", "scripts")

    config_text = f"""
# ** Input / output settings **

input_file: {input_file}
data_dir: {data_dir}
log_dir: {log_dir}
benchmark_dir: '../benchmarks'

# ** Analysis specific parameters**
taxa_in_graph: 10000
taxa_in_plot: 10000
alpha: [0.7, 0.8, 0.9, 0.99]
beta: [0.6, 0.7, 0.8, 0.9]
prior: [0.1, 0.3, 0.5]
regularized: True
taxon_rank: species
taxon_query: '{taxid_list_str}'

profile: False

script_dir: {script_dir}
"""
    with open(config_path, "w") as f:
        f.write(config_text)
    print(f"Config written: {config_path}")
###############################################

###############################################
def generate_snakemake_commands(filtered_files, taxid_list_str, min_peptides=100, *, conda_exe=None, snakemake_env_path=None, peptonizer_container=None):
    """
    For each filtered CASANOVO output, build a Peptonizer2000 config and run
    the bundled Snakemake workflow from a writable CWD, with absolute paths.
    
    If peptonizer_container is set, run Snakemake via singularity container.
    Otherwise, run via conda env (or system Python if snakemake_env_path is None).
    """
    peptonizer_result_files = []

    pep_home = os.environ.get("PEPTONIZER2000_HOME", "/opt/Peptonizer2000")
    snakefile = os.path.join(pep_home, "snakemake", "workflow", "Snakefile")

    # NEW: keep CWD = Nextflow task dir and make sure ./scripts exists here
    workdir = os.getcwd()
    scripts_src = os.path.join(pep_home, "snakemake", "workflow", "scripts")
    scripts_dst = os.path.join(workdir, "scripts")
    if not os.path.exists(scripts_dst):
        try:
            os.symlink(scripts_src, scripts_dst)
        except OSError:
            shutil.copytree(scripts_src, scripts_dst)

    # env: make sure python can import peptonizer modules
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{pep_home}:{env.get('PYTHONPATH', '')}"

    for file in filtered_files:
        root = os.path.dirname(file)  # writable
        basename = os.path.basename(file).replace(".tsv", "")
        # NEW: use ABSOLUTE paths
        infile = os.path.abspath(os.path.join(root, os.path.basename(file)))

        df = pd.read_csv(infile, sep="\t")
        if len(df) < min_peptides:
            print(f"Skipping {file} as it has less than {min_peptides} peptides ({len(df)})")
            continue

        # NEW: ABSOLUTE dirs
        data_dir = os.path.abspath(os.path.join(root, "Peptonizer2000_data", basename))
        log_dir  = os.path.abspath(os.path.join(root, "Peptonizer2000_logs", basename))
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(log_dir,  exist_ok=True)

        config_path = os.path.abspath(os.path.join(data_dir, f"{basename}_config.yaml"))
        outfile = os.path.join(data_dir, "peptonizer_result.csv")
        peptonizer_result_files.append(outfile)

        if os.path.exists(outfile):
            print(f"Output already exists for {file}, skipping Peptonizer2000.")
            continue

        make_config(infile, data_dir, log_dir, config_path, taxid_list_str)

        # NEW: run snakemake from task dir (so ./scripts resolves)
        cmd = [
            "snakemake",
            "-s", snakefile,
            "--cores", "10",
            "--configfile", config_path,
            "--printshellcmds",
            "--directory", workdir,   # was: root
        ]

        # If peptonizer_container is set, wrap the command with singularity exec
        if peptonizer_container:
            print(f"Using peptonizer_container: {peptonizer_container}")
            if not os.path.exists(peptonizer_container):
                raise FileNotFoundError(f"Peptonizer2000 container not found: {peptonizer_container}")
            
            # Validate that pep_home exists (important when binding to singularity)
            if not os.path.exists(pep_home):
                raise FileNotFoundError(
                    f"PEPTONIZER2000_HOME path does not exist: {pep_home}\n"
                    f"Please set PEPTONIZER2000_HOME environment variable to the host path of Peptonizer2000\n"
                    f"(e.g., PEPTONIZER2000_HOME=/mnt/storage_2/Production/src/Peptonizer2000)"
                )
            
            # Wrap snakemake command with singularity exec
            # Bind necessary directories: home, /tmp, work directory, Peptonizer2000 path
            sing_opts = [
                "singularity", "exec",
                "--bind", f"{os.environ.get('HOME', '/root')}:{os.environ.get('HOME', '/root')}",
                "--bind", "/tmp:/tmp",
                "--bind", f"{workdir}:{workdir}",
                "--bind", f"{pep_home}:/opt/Peptonizer2000",
                "--bind", "/mnt:/mnt",  # For any mounted data
                peptonizer_container
            ]
            cmd = sing_opts + cmd
            print(f"Wrapped Snakemake command with singularity: {' '.join(cmd[:6])} ...")
        else:
            # Use conda wrapping if snakemake_env_path is set
            cmd = _conda_wrap(cmd, conda_exe=conda_exe, env_path=snakemake_env_path)

        print(f"Running Peptonizer2000 snakemake for {file}: {' '.join(cmd)}")
        run_env = _prepend_env_lib_to_ld_library_path(env, snakemake_env_path)
        result = subprocess.run(cmd, capture_output=True, text=True, env=run_env)
        print(result.stdout)
        
        # Check if Snakemake failed and if it's due to empty Unipept results or taxa weighting issues
        if result.returncode != 0:
            # Combine stdout and stderr for better error detection
            error_output = result.stdout + result.stderr
            
            # Check if this is the "All objects have zero weight" error (Peptonizer2000 taxa weighting failure)
            if "All objects have zero weight" in error_output or "WeightTaxa" in error_output or "weighted_random_sample" in error_output:
                peptide_taxa_path = os.path.join(data_dir, basename, "peptide_taxa.json")
                print(f"WARNING: Peptonizer2000 taxa weighting failed for {basename}")
                print(f"  This typically means the de novo peptides do not match any organisms in the taxonomy database.")
                print(f"  The sample will be skipped and marked as organism undetermined.")
                print(f"  Error: All objects have zero weight in taxa sampling - peptides may not be in Unipept database.")
                print(f"Skipping {file} due to Peptonizer2000 taxa weighting failure")
                
                # Log the failure to a dedicated error log file
                error_log_path = os.path.join(log_dir, "peptonizer_error.log")
                os.makedirs(log_dir, exist_ok=True)
                try:
                    with open(error_log_path, 'w') as f:
                        f.write(f"Peptonizer2000 WeightTaxa failed for {basename}\n")
                        f.write(f"Error: All objects have zero weight in taxa sampling\n\n")
                        f.write("STDOUT:\n")
                        f.write(error_output)
                except Exception as log_err:
                    print(f"Could not write error log: {log_err}")
                
                # Skip this file as it cannot be processed further
                continue
            
            # If it's not a known taxa weighting failure, raise the error
            print("ERROR: Snakemake failed with unknown error:")
            print(error_output)
            raise SyntaxError(f"Error running Snakemake for {file}:\n{error_output}")

        # CHECK: Validate that peptide_taxa.json exists and is not empty (defensive check for success case)
        peptide_taxa_path = os.path.join(data_dir, basename, "peptide_taxa.json")
        if os.path.exists(peptide_taxa_path):
            try:
                with open(peptide_taxa_path, 'r') as f:
                    taxa_data = json.load(f)
                if not taxa_data or len(taxa_data) == 0:
                    print(f"WARNING: Unipept lookup returned no taxonomic assignments for {basename}")
                    print(f"  The sample will be skipped and marked as organism undetermined.")
                    print(f"Skipping {file} due to Unipept lookup failure")
                    continue
            except json.JSONDecodeError:
                print(f"WARNING: Could not parse peptide_taxa.json at {peptide_taxa_path}")
                print(f"  The sample will be skipped and marked as organism undetermined.")
                continue
        else:
            # This can happen if Peptonizer2000 failed during GetTaxonomyFromUnipept rule
            print(f"WARNING: peptide_taxa.json not found at {peptide_taxa_path}")
            print(f"  Peptonizer2000 may have failed during taxonomy lookup.")
            print(f"  The sample will be skipped and marked as organism undetermined.")
            continue

        print(f"Finished running Peptonizer2000 for {file} -> {outfile}")

    return peptonizer_result_files
###############################################

####################################################
def run_de_novo_sequencing(input_dir, output_dir, *, conda_exe=None, casanovo_env_path=None, cascadia_env_path=None, cascadia_model_path=None, denovo_threshold_pct: int = 80):
    """
    Run de novo sequencing (Casanovo or Cascadia) on all .mzML files under input_dir.
    If no .mzML files are found, attempt to convert .raw files to .mzML.
    Use hardware acceleration for optimal performance (GPU-accelerated by default).
    Return a list of successfully created .mztab files.
    """
    # Check if we should use Cascadia instead of Casanovo
    use_cascadia = os.environ.get('CASCADIA_HOME') is not None
    
    # 1) find mzMLs
    mzml_files = []
    for root, _, files in os.walk(input_dir):
        for f in files:
            if f.lower().endswith(".mzml"):
                mzml_files.append(os.path.join(root, f))

    # 2) If no mzML files found, try to find and convert .raw files
    if not mzml_files:
        print("No .mzML files found. Looking for .raw files to convert...")
        raw_files = []
        for root, _, files in os.walk(input_dir):
            for f in files:
                if f.lower().endswith(".raw"):
                    raw_files.append(os.path.join(root, f))
        
        if raw_files:
            print(f"Found {len(raw_files)} .raw file(s). Attempting to convert to .mzML...")
            # Try to import and use the conversion function from FetchPXD if available
            try:
                from sys import path as sys_path
                base_dir = os.path.dirname(os.path.abspath(__file__))
                if base_dir not in sys_path:
                    sys_path.insert(0, base_dir)
                from FetchPXD import convert_spectral_file_to_mzml
                
                for raw_file in raw_files:
                    try:
                        mzml_path = convert_spectral_file_to_mzml(raw_file)
                        if mzml_path and os.path.exists(mzml_path):
                            mzml_files.append(mzml_path)
                            print(f"Successfully converted: {raw_file} -> {mzml_path}")
                        else:
                            print(f"WARNING: Conversion may have failed for {raw_file}")
                    except Exception as e:
                        print(f"Error converting {raw_file}: {e}")
            except ImportError:
                print("WARNING: Could not import convert_spectral_file_to_mzml from FetchPXD.py")
                print("Ensure ProteoWizard is configured (PROTEOWIZARD_SINGULARITY and PROTEOWIZARD_WINEPREFIX)")

    tool_name = "Cascadia" if use_cascadia else "Casanovo"
    print(f"Found {len(mzml_files)} .mzML files to process with {tool_name}.")

    casanovo_outputs = []

    for mzml_path in mzml_files:
        base = os.path.splitext(os.path.basename(mzml_path))[0]

        # e.g. PXD023343_Soybean_LPBiomaker_LP3
        pxd_name = os.path.basename(input_dir.rstrip("/"))
        out_root = f"{pxd_name}_{base}"
        
        if use_cascadia:
            # e.g. organism_results/CascadiaSequence
            out_dir = os.path.join(output_dir, "CascadiaSequence", out_root)
            os.makedirs(out_dir, exist_ok=True)
            out_file = os.path.join(out_dir, f"{out_root}.mztab")  # We'll convert .ssl to .mztab
            # Cascadia's CLI appends ".ssl" to the provided output root.
            # If we pass a path ending in ".ssl", it will produce ".ssl.ssl".
            # Therefore we pass an output *root* without the suffix.
            ssl_root = os.path.join(out_dir, f"{out_root}")
            ssl_file = f"{ssl_root}.ssl"
            log_file = os.path.join(out_dir, f"{out_root}.log")
        else:
            # e.g. organism_results/CasanovoSequence
            out_dir = os.path.join(output_dir, "CasanovoSequence", out_root)
            out_file = os.path.join(out_dir, f"{out_root}.mztab")
            # Use .casanovo.log suffix to avoid conflicting with casanovo's own
            # *.log existence check (casanovo raises FileExistsError if .log is present)
            log_file = os.path.join(out_dir, f"{out_root}.casanovo.log")

        # Fast-path: if output already exists, reuse it.
        # - Cascadia: prefer existing .mztab; else convert existing .ssl; else run prediction.
        # - Casanovo: if .mztab exists and is non-empty, skip rerun.
        if use_cascadia:
            if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
                print(f"Found existing Cascadia mztab, skipping prediction: {out_file}")
                casanovo_outputs.append(out_file)
                continue

            # Be defensive in case older runs produced ".ssl.ssl"
            ssl_candidates = [ssl_file, f"{ssl_file}.ssl"]
            existing_ssl = next((p for p in ssl_candidates if os.path.exists(p) and os.path.getsize(p) > 0), None)
            if existing_ssl:
                print(f"Found existing Cascadia SSL, converting to mztab (no rerun): {existing_ssl}")
                convert_ssl_to_mztab(existing_ssl, out_file)
                if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
                    casanovo_outputs.append(out_file)
                continue
        else:
            if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
                print(f"Found existing Casanovo mztab, skipping prediction: {out_file}")
                casanovo_outputs.append(out_file)
                continue
            # Clean up stale output directory before running (may contain .log files
            # from a failed previous run that would trigger casanovo's FileExistsError)
            if os.path.exists(out_dir):
                print(f"Removing existing Casanovo output directory: {out_dir}")
                shutil.rmtree(out_dir)
            os.makedirs(out_dir, exist_ok=True)

        print("#" * 50)
        print(f"Running {tool_name} on: {mzml_path}")
        print(f"Output file path: {out_file}")

        if use_cascadia:
            # Cascadia command
            # cascadia is in the PATH inside the organism container
            model_path = cascadia_model_path or os.environ.get('CASCADIA_MODEL', '/opt/cascadia/models/cascadia.ckpt')
            if not os.path.exists(model_path):
                print(f"ERROR: Cascadia model not found at {model_path}")
                print("Please download cascadia.ckpt from https://drive.google.com/drive/folders/1UTrZIrCdUqYqscbqga_KdX8kc8ZjMMfr")
                print(f"and place it at {model_path}")
                continue
                
            # Cascadia auto-detects CUDA and uses GPU if available
            # It also respects CUDA_VISIBLE_DEVICES if set
            cascadia_t = str(float(denovo_threshold_pct) / 100.0)
            
            # Use wrapper script that monkeypatches pyteomics to use local Unimod
            wrapper_script = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'cascadia_wrapper.py'
            )
            base_cmd = [
                "python", wrapper_script, "sequence", mzml_path, model_path,
                "-o", ssl_root,
                "-t", cascadia_t
            ]
            base_cmd = _conda_wrap(base_cmd, conda_exe=conda_exe, env_path=cascadia_env_path)
        else:
            # Casanovo 5.1.2+ command - uses subcommand-based CLI
            # casanovo sequence PEAK_PATH [--output_dir DIR] [--output_root ROOT]
            base_cmd = [
                "casanovo", "sequence",
                mzml_path,
                "--output_dir", out_dir,
                "--output_root", out_root
            ]
            base_cmd = _conda_wrap(base_cmd, conda_exe=conda_exe, env_path=casanovo_env_path)

        # --- Run Casanovo/Cascadia on GPU ---
        print(f"Running {tool_name} (GPU mode):", " ".join(base_cmd))
        try:
            # Run with GPU enabled (no CUDA_VISIBLE_DEVICES restriction)
            env = os.environ.copy()
            
            # For Cascadia: ensure a writable cache directory for the wrapper script
            if use_cascadia:
                cache_home = _ensure_writable_dir(_default_cache_home())
                env['XDG_CACHE_HOME'] = cache_home

            # Prefer conda env shared libs over system libs (important on older glibc/libstdc++ hosts)
            if use_cascadia:
                env = _prepend_env_lib_to_ld_library_path(env, cascadia_env_path)
            else:
                env = _prepend_env_lib_to_ld_library_path(env, casanovo_env_path)

            # Stream output directly to log files to avoid deadlock with large outputs
            # (capture_output=True can cause subprocess to hang when output buffer fills)
            stderr_log_file = f"{log_file}.stderr"
            with open(log_file, "w") as log_out, open(stderr_log_file, "w") as log_err:
                res = subprocess.run(
                    base_cmd,
                    stdout=log_out,
                    stderr=log_err,
                    text=True,
                    check=True,
                    env=env,
                    timeout=7200,  # 2-hour per-file safety timeout
                )
            print(f"{tool_name} (GPU) succeeded.")
            
            # Check and convert output if using Cascadia
            if use_cascadia:
                # Be defensive in case older runs produced ".ssl.ssl"
                if (not os.path.exists(ssl_file)) and os.path.exists(f"{ssl_file}.ssl"):
                    ssl_file = f"{ssl_file}.ssl"

                if os.path.exists(ssl_file) and os.path.getsize(ssl_file) > 0:
                    print(f"SSL file created successfully ({os.path.getsize(ssl_file)} bytes)")
                    # Convert SSL to mztab format
                    convert_ssl_to_mztab(ssl_file, out_file)
                else:
                    print(f"WARNING: Expected SSL file {ssl_file} not found or empty")
                    print(f"Directory contents: {os.listdir(out_dir)}")
            else:
                # Casanovo should have completed successfully - check for output file
                print(f"Checking for output file: {out_file}")
                if os.path.exists(out_file) and os.path.getsize(out_file) > 0:
                    print(f"Output file created successfully ({os.path.getsize(out_file)} bytes)")
                else:
                    print(f"WARNING: Expected output file {out_file} not found or empty")
                    print(f"Directory contents: {os.listdir(out_dir)}")
                    
        except subprocess.CalledProcessError as e:
            print(f"{tool_name} (GPU mode) exited with code {e.returncode}")
            
            # Read stderr from log file (since we streamed it there)
            stderr_content = "N/A"
            stderr_log_file = f"{log_file}.stderr"
            if os.path.exists(stderr_log_file):
                with open(stderr_log_file, "r") as f:
                    stderr_content = f.read()
            print(f"STDERR excerpt: {stderr_content[:500] if stderr_content != 'N/A' else 'N/A'}")
            
            # CRITICAL: Check if output was created despite the error
            # This can happen with CUDA device capability check failures that occur AFTER prediction completes
            output_exists = False
            if use_cascadia:
                output_exists = os.path.exists(ssl_file) and os.path.getsize(ssl_file) > 0
            else:
                output_exists = os.path.exists(out_file) and os.path.getsize(out_file) > 0
            
            if output_exists:
                print(f"✓ {tool_name} output files exist despite exit error (prediction likely completed)")
                # Convert SSL to mztab if needed
                if use_cascadia:
                    convert_ssl_to_mztab(ssl_file, out_file)
                print(f"{tool_name} output verified successfully, treating as success.")
                # Append error info to log but don't treat as failure
                with open(log_file, "a") as lf:
                    lf.write(f"\n---- STDERR (post-prediction error but output verified) ----\n")
                    lf.write(stderr_content)
            else:
                # No output generated - this is a real failure
                print(f"✗ {tool_name} (GPU mode) failed, no output generated")
                error_msg = f"\n{'='*70}\nERROR: {tool_name} (GPU) failed for {mzml_path}\n{'='*70}\n"
                error_msg += f"Exit Code: {e.returncode}\n"
                error_msg += f"Error Output:\n{stderr_content}\n\n"
                error_msg += f"{tool_name} processing failed on GPU.\n"
                error_msg += f"{'='*70}\n"
                print(error_msg)
                with open(log_file, "w") as lf:
                    lf.write(error_msg)
                    lf.write(f"\nFull STDERR:\n{stderr_content}\n")
                # Continue to next file instead of crashing entire pipeline
                continue

        except subprocess.TimeoutExpired:
            print(f"\u2717 {tool_name} timed out (>2h) for {mzml_path}, skipping file")
            with open(log_file, "w") as lf:
                lf.write(f"ERROR: {tool_name} timed out after 7200s for {mzml_path}\n")
            continue

        # only count it if the .mztab is actually there
        if os.path.exists(out_file):
            casanovo_outputs.append(out_file)
        else:
            print(f"WARNING: Casanovo finished but {out_file} not found.")

    return casanovo_outputs
####################################################

def check_cached_organism_results(pxd, input_dir, results_base_dir, denovo_threshold_pct):
    """
    Check if organism_id results already exist in results/{PXD}/organism_results/.
    
    For each .mzML file in input_dir, checks if the corresponding peptonizer_result.csv exists:
    - {results_base_dir}/{pxd}/organism_results/CascadiaSequence/{pxd}_{mzml_basename}/Peptonizer2000_data/{pxd}_{mzml_basename}_filtered{threshold}pct_slim/peptonizer_result.csv
    - OR CasanovoSequence variant
    
    Returns:
        (bool, str, list): (cache_hit, mode, cached_files)
            - cache_hit: True if all expected files exist
            - mode: 'DIA' or 'DDA' based on which subdirectory exists
            - cached_files: list of paths to peptonizer_result.csv files
    """
    print(f"\n{'='*70}")
    print(f"Checking for cached organism_id results in {results_base_dir}/{pxd}/organism_results/")
    print(f"{'='*70}")
    
    # Find all mzML files in input directory
    mzml_files = sorted(glob.glob(os.path.join(input_dir, '*.mzML')))
    if not mzml_files:
        print(f"No .mzML files found in {input_dir}")
        return False, None, []
    
    print(f"Found {len(mzml_files)} .mzML files to check for cached results")
    
    # Try both DIA (Cascadia) and DDA (Casanovo) modes
    for mode_name, mode_dir in [('DIA', 'CascadiaSequence'), ('DDA', 'CasanovoSequence')]:
        mode_base = os.path.join(results_base_dir, pxd, 'organism_results', mode_dir)
        
        if not os.path.exists(mode_base):
            continue
            
        print(f"\nChecking {mode_name} mode ({mode_dir})...")
        all_found = True
        cached_files = []
        
        for mzml_path in mzml_files:
            base = os.path.splitext(os.path.basename(mzml_path))[0]
            out_root = f"{pxd}_{base}"
            
            # Construct expected path with threshold validation built-in
            expected_path = os.path.join(
                mode_base,
                out_root,
                'Peptonizer2000_data',
                f"{out_root}_filtered{denovo_threshold_pct}pct_slim",
                'peptonizer_result.csv'
            )
            
            if os.path.exists(expected_path) and os.path.getsize(expected_path) > 0:
                file_size = os.path.getsize(expected_path)
                print(f"  ✓ {base}: found cached result ({file_size} bytes)")
                cached_files.append(expected_path)
            else:
                print(f"  ✗ {base}: not found or empty")
                print(f"    Expected: {expected_path}")
                all_found = False
                break
        
        if all_found:
            print(f"\n{'='*70}")
            print(f"✓ Cache HIT: All {len(cached_files)} organism results found in {mode_name} mode")
            print(f"{'='*70}")
            return True, mode_name, cached_files
    
    print(f"\n{'='*70}")
    print(f"✗ Cache MISS: Will run organism_id pipeline")
    print(f"{'='*70}")
    return False, None, []

###############################################
def main():

    ## Get the user arguments
    parser = argparse.ArgumentParser(description='Process Casanovo .mztab files to extract PSM lines and save as .tsv.')
    parser.add_argument('--input_dir', help='Directory to scan for .mzML files')
    parser.add_argument('--output_dir', default='OrganismID', help='Directory to save the output .tsv files')
    parser.add_argument('--contaminants_fasta', default='data/FASTA/UniversalContaminats.fasta', help='Path to contaminants FASTA file')
    parser.add_argument('--taxid_list_file', default='data/taxid_lists/CommonPRIDEtaxids.txt', help='Path to file containing list of taxids')
    parser.add_argument('--denovo_threshold', type=int, default=80, help='De novo confidence threshold (percent). Used for both Casanovo and Cascadia peptides passed to Peptonizer2000.')
    # Backwards-compat alias (will be removed): accept the old name if provided.
    parser.add_argument('--casanovo_thresholds', default=None, help=argparse.SUPPRESS)
    parser.add_argument('--min_peptides_for_peptonizer', type=int, default=100, help='Minimum number of high-quality peptides required to run Peptonizer2000')
    parser.add_argument('--conda_exe', default=None, help='Path to conda executable (for conda run -p ...)')
    parser.add_argument('--casanovo_env_path', default=None, help='Conda env prefix path containing casanovo')
    parser.add_argument('--cascadia_env_path', default=None, help='Conda env prefix path containing cascadia')
    parser.add_argument('--snakemake_env_path', default=None, help='Conda env prefix path containing snakemake (defaults to current env)')
    parser.add_argument('--cascadia_model_path', default=None, help='Path to cascadia.ckpt')
    parser.add_argument('--peptonizer_container', default=None, help='Path to peptonizer2000.sif container (if set, Peptonizer2000 runs via singularity instead of conda)')
    parser.add_argument('--log_file', default=None, help='Path to JSONL file for pipeline event logging')
    parser.add_argument('--results_base_dir', default='results', help='Base directory where completed results are stored (for caching)')
    parser.add_argument('--pxd', default=None, help='PXD accession (auto-detected from input_dir if not provided)')
    args = parser.parse_args()

    # Initialize logger if log_file specified
    logger = None
    if args.log_file:
        pxd_id = os.path.basename(os.path.normpath(args.input_dir)) if args.input_dir else "unknown"
        logger = PipelineLogger(args.log_file, pxd_id)
        logger.process_start("organism", {"pxd": pxd_id})

    # Determine the denovo threshold (percent)
    denovo_threshold_pct = args.denovo_threshold
    if args.casanovo_thresholds:
        try:
            denovo_threshold_pct = int(str(args.casanovo_thresholds).split(',')[0].strip())
        except Exception:
            pass

    print(f'De novo threshold (percent): {denovo_threshold_pct}')
    print(f'Minimum peptides for Peptonizer2000: {args.min_peptides_for_peptonizer}')
    
    # Determine PXD accession (for caching)
    pxd = args.pxd or os.path.basename(os.path.normpath(args.input_dir))
    print(f'PXD: {pxd}')
    
    # Check for cached organism_id results
    cache_hit, cached_mode, cached_files = check_cached_organism_results(
        pxd=pxd,
        input_dir=args.input_dir,
        results_base_dir=args.results_base_dir,
        denovo_threshold_pct=denovo_threshold_pct
    )
    
    if cache_hit:
        print(f"\nReusing cached organism_id results from {args.results_base_dir}/{pxd}/organism_results/")
        
        # Copy cached results to output directory
        cached_organism_results = os.path.join(args.results_base_dir, pxd, 'organism_results')
        
        if os.path.exists(args.output_dir):
            shutil.rmtree(args.output_dir)
        
        shutil.copytree(cached_organism_results, args.output_dir)
        print(f"✓ Copied cached results to {args.output_dir}")
        
        # Log completion
        if logger:
            logger.process_complete("organism", "success", {"cached": True, "mode": cached_mode, "num_files": len(cached_files)})
        
        return
    
    # No cache hit - proceed with normal workflow
    print(f"\nNo cached results found, running organism_id pipeline...")

    # Parse the taxid list file
    if os.path.exists(args.taxid_list_file):
        taxid_list = open(args.taxid_list_file, 'r').read().strip().splitlines()
        assert len(taxid_list) == 1, f"Expected a single line of comma-separated taxids in {args.taxid_list_file}, but found {len(taxid_list)} lines."
        taxid_list = taxid_list[0]
        print(f'taxid_list: {taxid_list}')
        print(f"Loaded {len(taxid_list.split(','))} taxids from {args.taxid_list_file}")


    # Run de novo sequencing (Casanovo or Cascadia depending on mode)
    denovo_files = run_de_novo_sequencing(
        args.input_dir,
        args.output_dir,
        conda_exe=args.conda_exe,
        casanovo_env_path=args.casanovo_env_path,
        cascadia_env_path=args.cascadia_env_path,
        cascadia_model_path=args.cascadia_model_path,
        denovo_threshold_pct=denovo_threshold_pct,
    )
    print(f"Finished running de novo sequencing on input directory: {args.input_dir}")
    print(f"Generated de novo sequencing output files: {denovo_files}")

    
    # Process the input directory to find relevant files and filter them for quality predictions
    filtered_files = process_denovo_files(
        denovo_files,
        contaminants_fasta=args.contaminants_fasta,
        denovo_threshold_pct=denovo_threshold_pct,
    )
    print(f"Filtered files: {filtered_files}")
    slim_files = [f for f in filtered_files if f.endswith('_slim.tsv')]
    print(f"Slim files: {slim_files}")

    # Generate Snakemake commands to use Peptonizer2000 workflow
    peptonizer_result_files = generate_snakemake_commands(
        slim_files,
        taxid_list,
        min_peptides=args.min_peptides_for_peptonizer,
        conda_exe=args.conda_exe,
        snakemake_env_path=args.snakemake_env_path,
        peptonizer_container=args.peptonizer_container,
    )
    print(f"Generated Peptonizer2000 output files: {peptonizer_result_files} {len(peptonizer_result_files)}")

    # Log completion
    if logger:
        logger.process_complete("organism", "success")

    

if __name__ == '__main__':
    main()
