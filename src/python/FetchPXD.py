import pandas as pd
import sys, os
import glob
import argparse
import requests
import subprocess
import time
import shutil
from typing import List, Any, Dict, Optional
import json
import zipfile
from pathlib import Path

# Add parent directory to path for importing PipelineLogger and pmc_client
sys.path.insert(0, str(Path(__file__).parent))
from PipelineLogger import PipelineLogger
from pmc_client import PMCClient

EXIT_NO_RAW_FILES = 42
###################################################################################################################################################
def fetch_pride_project_and_files(pxd: str, page_size: int = 200, timeout: int = 20, max_pages: Optional[int] = 100, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    """
    Fetch PRIDE project metadata and all file records for a given PXD.

    Returns
    -------
    Dict[str, Any]
        {
          "project": <project metadata JSON>,
          "files": {
             "page": {...},              # pagination summary (if available)
             "files": [ ...file dicts...],
          }
        }
    """
    sess = session or requests.Session()
    headers = {"User-Agent": "PRIDE-fetch/1.0 (+https://github.com/your-org/your-repo)"}

    base = f"https://www.ebi.ac.uk/pride/ws/archive/v3/projects/{pxd}"

    # 1) Project metadata
    proj_resp = sess.get(base, headers=headers, timeout=timeout)
    if not proj_resp.ok:
        raise RuntimeError(
            f"Failed to fetch project {pxd}: {proj_resp.status_code} {proj_resp.text[:300]}"
        )
    project_json = proj_resp.json()

    # 2) Files (paginated)
    files_endpoint = f"{base}/files"
    page_num = 0
    file_data = []

    while True:
        params = {"pageSize": page_size, "page": page_num}
        files_resp = sess.get(files_endpoint, headers=headers, params=params, timeout=timeout)
        if not files_resp.ok:
            raise RuntimeError(
                f"Failed to fetch files page {page_num} for {pxd}: "
                f"{files_resp.status_code} {files_resp.text[:300]}"
            )
        data = files_resp.json()
        # print(data)
        file_data.extend(data)

        if max_pages is not None and page_num + 1 >= max_pages:
            break

        if len(data) == 0:
            break

        page_num += 1

    return {"project": project_json, "files": file_data}
###################################################################################################################################################

###################################################################################################################################################
def download_ftp_file_aria2c(url, outfile, threads=4):
    """
    Download using aria2c with multiple threads for parallel segment downloads.
    Try HTTPS first, then FTP.
    """
    candidates = []
    if url.startswith("ftp://"):
        candidates.append(url.replace("ftp://", "https://", 1))
    candidates.append(url)

    last_err = None
    for candidate in candidates:
        for attempt in range(6):
            try:
                print(f"Downloading (aria2c, {threads} threads, attempt {attempt+1}) {candidate} -> {outfile}")
                result = _aria2c(candidate, outfile, threads)
                print(result.stdout)
                return
            except subprocess.CalledProcessError as e:
                last_err = e
                rc = e.returncode
                # Retry on network/server errors
                if rc in (3, 5, 7, 9):  # aria2c error codes for network issues
                    sleep_s = 5 * (2 ** attempt)
                    print(f"aria2c failed (rc={rc}). Retrying in {sleep_s}s...\nSTDERR:\n{e.stderr}")
                    time.sleep(sleep_s)
                    continue
                else:
                    print(f"aria2c failed (rc={rc}). Not retrying.\nSTDERR:\n{e.stderr}")
                    break

    # If we get here, all retries/candidates failed
    raise last_err

def download_ftp_file_wget(url, outfile):
    """
    Download using wget with retry logic.
    Try HTTPS first (friendlier through firewalls/proxies), then FTP.
    Retry with exponential backoff on network/server errors.
    """
    candidates = []
    if url.startswith("ftp://"):
        candidates.append(url.replace("ftp://", "https://", 1))
    candidates.append(url)

    last_err = None
    for candidate in candidates:
        for attempt in range(6):  # 6 attempts per candidate
            try:
                print(f"Downloading (attempt {attempt+1}) {candidate} -> {outfile}")
                result = _wget(candidate, outfile)
                print(result.stdout)
                return
            except subprocess.CalledProcessError as e:
                last_err = e
                rc = e.returncode
                # 4 = network failure, 8 = server error; retry those
                if rc in (4, 8):
                    sleep_s = 5 * (2 ** attempt)
                    print(f"wget failed (rc={rc}). Retrying in {sleep_s}s...\nSTDERR:\n{e.stderr}")
                    time.sleep(sleep_s)
                    continue
                else:
                    print(f"wget failed (rc={rc}). Not retrying.\nSTDERR:\n{e.stderr}")
                    break

    # If we get here, all retries/candidates failed
    raise last_err
###################################################################################################################################################

###################################################################################################################################################
def _aria2c(url: str, outfile_path: str, threads: int = 4):
    """
    Use aria2c for multi-threaded segment downloads.
    -x: maximum number of connections per server
    -s: number of connections used for download (split into segments)
    -j: max concurrent downloads (we download one file at a time here)
    -c: continue partial downloads
    --file-allocation=none: faster for most cases
    """
    # Get directory and filename
    out_dir = os.path.dirname(outfile_path) or "."
    out_file = os.path.basename(outfile_path)
    
    cmd = [
        "aria2c",
        "-x", str(threads),  # connections per server
        "-s", str(threads),  # split download into segments
        "-j", "1",          # download one file at a time
        "-c",               # continue downloads
        "--file-allocation=none",
        "--max-tries=10",
        "--retry-wait=5",
        "--timeout=600",          # 10 minutes (aria2c max allowed), relies on -c to resume if interrupted
        "-d", out_dir,      # output directory
        "-o", out_file,     # output filename
        url,
    ]
    print("Running command:", " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True, text=True)

def _wget(url: str, outfile_path: str):
    # Quiet-ish but resilient; keeps partials (-c)
    cmd = [
        "wget", "-c",
        "--tries=10",
        "--retry-connrefused",
        "--waitretry=5",
        "--read-timeout=1800",  # 30 minutes read timeout (accommodates slow networks)
        "--timeout=300",       # 5 minutes per connection attempt
        "-O", outfile_path,
        url,
    ]
    print("Running command:", " ".join(cmd))
    return subprocess.run(cmd, check=True, capture_output=True, text=True)
###################################################################################################################################################

###################################################################################################################################################
def find_spectral_files_in_directory(directory: str) -> List[str]:
    """
    Recursively search a directory for spectral data files.
    
    Returns list of absolute paths to .raw and .wiff files (case-insensitive).
    """
    spectral_files = []
    for root, dirs, files in os.walk(directory):
        for file in files:
            file_lower = file.lower()
            if file_lower.endswith('.raw') or file_lower.endswith('.wiff'):
                spectral_files.append(os.path.join(root, file))
    return spectral_files

def extract_zip_file(zip_path: str, extract_to: str) -> bool:
    """
    Extract a ZIP file to the specified directory.
    
    Returns True if successful, False otherwise.
    """
    try:
        print(f"Extracting ZIP file: {zip_path} to {extract_to}")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_to)
        print(f"Successfully extracted {zip_path}")
        return True
    except zipfile.BadZipFile as e:
        print(f"ERROR: {zip_path} is not a valid ZIP file: {e}")
        return False
    except Exception as e:
        print(f"ERROR: Failed to extract {zip_path}: {e}")
        return False

###################################################################################################################################################
def convert_spectral_file_to_mzml(file_path: str, max_retries: int = 3):
    """
    Convert .RAW files to centroided .mzML.
    
    Uses ThermoRawFileParser which is a native .NET tool that reads Thermo RAW files 
    directly without requiring containers or Wine.
    
    Args:
        file_path: Path to .raw file
        max_retries: Number of retries on failure (default 3, exponential backoff)
    
    Returns:
        Path to output .mzML if successful, None otherwise
    """
    filetype = os.path.splitext(file_path)[1]  # Get original extension (preserving case)
    
    # Only .raw files are supported in this container-free version
    if filetype.lower() != '.raw':
        print(f"Skipping conversion for {file_path}: only .raw files are supported in this version")
        return None
    
    outfile = file_path[:-len(filetype)] + '.mzML'  # Replace extension with .mzML
    
    # Check if output already exists
    if os.path.exists(outfile):
        print(f"mzML file already exists: {outfile}")
        return outfile
    
    # Convert .raw to .mzML using ThermoRawFileParser
    return _convert_thermo_raw_to_mzml(file_path, outfile, max_retries)

###################################################################################################################################################
def _convert_thermo_raw_to_mzml(file_path: str, outfile: str, max_retries: int = 3):
    """
    Convert Thermo .RAW files to .mzML using ThermoRawFileParser.
    
    ThermoRawFileParser is a native .NET tool that reads Thermo RAW files directly
    (no Wine/Wine needed). This is more reliable than ProteoWizard's Wine-based approach.
    
    Args:
        file_path: Path to .raw file
        outfile: Path to output .mzML file
        max_retries: Number of retries on failure
    """
    abs_file_path = os.path.abspath(file_path)
    abs_outdir = os.path.dirname(abs_file_path)
    filename_only = os.path.basename(file_path)
    
    # Retry loop with exponential backoff
    for attempt in range(max_retries + 1):
        try:
            print(f"\n{'='*80}")
            print(f"Converting {file_path} --> .mzML via ThermoRawFileParser")
            if attempt > 0:
                print(f"RETRY ATTEMPT {attempt}/{max_retries}")
            print(f"{'='*80}")
            
            # Build ThermoRawFileParser command
            # -i: input file
            # -b: output file path
            # -f: format (2 = indexed mzML)
            # By default: peak picking enabled, zlib compression enabled
            cmd = [
                "ThermoRawFileParser",
                "-i", abs_file_path,
                "-b", outfile,
                "-f", "2"  # 2 = indexed mzML (includes peak picking and zlib by default)
            ]
            
            print(f"\nCommand:")
            print(f"  {' '.join(cmd)}")
            
            print(f"\nInput file:")
            print(f"  {abs_file_path} ({os.path.getsize(abs_file_path)} bytes)")
            print(f"Output directory:")
            print(f"  {abs_outdir}")
            
            print(f"\nRunning ThermoRawFileParser...")
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=6000  # 100 minute timeout
            )
            print(result.stdout)
            if result.stderr:
                print(f"(stderr): {result.stderr}")
            
            # Verify output file was created
            if os.path.exists(outfile):
                print(f"\nSuccess! Finished converting {file_path} --> {outfile}")
                return outfile
            else:
                raise RuntimeError(f"Output file not created: {outfile}")

        except subprocess.TimeoutExpired:
            error_msg = f"TIMEOUT: ThermoRawFileParser conversion exceeded 10 minutes for {file_path}"
            print(f"ERROR: {error_msg}")
            if attempt < max_retries:
                backoff_seconds = 2 ** attempt
                print(f"Retrying in {backoff_seconds} seconds...")
                time.sleep(backoff_seconds)
                continue
            else:
                print(f"Giving up after {max_retries} retries")
                return None
                
        except subprocess.CalledProcessError as e:
            print(f"ERROR: ThermoRawFileParser failed with exit code {e.returncode}")
            print(f"stdout:\n{e.stdout}")
            print(f"stderr:\n{e.stderr}")
            
            if attempt < max_retries:
                backoff_seconds = 2 ** attempt
                print(f"Retrying in {backoff_seconds} seconds...")
                time.sleep(backoff_seconds)
                continue
            else:
                print("Continuing to next file...")
                return None
                
        except Exception as e:
            print(f"ERROR: Unexpected error converting {file_path}: {e}")
            if attempt < max_retries:
                backoff_seconds = 2 ** attempt
                print(f"Retrying in {backoff_seconds} seconds...")
                time.sleep(backoff_seconds)
                continue
            else:
                return None
    
    return None

###################################################################################################################################################
def _convert_wiff_to_mzml(file_path: str, outfile: str, max_retries: int = 3):
    """
    Convert AB Sciex .WIFF files to .mzML using ProteoWizard (via Wine/Singularity).
    
    WIFF files require ProteoWizard's Wine-based conversion because there's no
    native Linux alternative with good coverage of AB Sciex formats.
    
    Args:
        file_path: Path to .wiff file
        outfile: Path to output .mzML file
        max_retries: Number of retries on transient Wine issues
    """
    filetype = os.path.splitext(file_path)[1]
    
    # Verify paired .scan file exists (case-insensitive)
    scan_file = file_path + '.scan'
    if not os.path.exists(scan_file):
        # Try to find it case-insensitively
        base_dir = os.path.dirname(file_path)
        base_file = os.path.basename(file_path)
        scan_candidates = glob.glob(os.path.join(base_dir, base_file + '.scan*'), recursive=False)
        if scan_candidates:
            scan_file = scan_candidates[0]
        else:
            print(f"WARNING: No .wiff.scan sidecar found for {file_path}")
            print(f"Expected: {scan_file}")
            print(f"Skipping WIFF conversion (both .wiff and .wiff.scan are required)")
            return None
    
    # Get paths to ProteoWizard resources
    pwiz_sif = os.environ.get("PROTEOWIZARD_SINGULARITY")
    pwiz_prefix = os.environ.get("PROTEOWIZARD_WINEPREFIX")
    
    # Check if msconvert is available on PATH (for unified container/direct Wine setup)
    msconvert_available = shutil.which("msconvert") is not None
    
    if not pwiz_sif and not msconvert_available:
        print(f"WARNING: ProteoWizard setup incomplete for WIFF conversion")
        print(f"  - $PROTEOWIZARD_SINGULARITY not set (external ProteoWizard container)")
        print(f"  - msconvert not found on PATH (in-container Wine/ProteoWizard setup)")
        print(f"Skipping WIFF conversion for {file_path}")
        print(f"Manual conversion required: use ProteoWizard msconvert or equivalent tool")
        return None
    
    if pwiz_sif and (not pwiz_sif or not os.path.exists(pwiz_sif)):
        print(f"ERROR: ProteoWizard Singularity image not found at: {pwiz_sif}")
        print(f"Set $PROTEOWIZARD_SINGULARITY environment variable or ensure msconvert is on PATH")
        return None
    
    if pwiz_sif and (not pwiz_prefix or not os.path.exists(pwiz_prefix)):
        print(f"ERROR: ProteoWizard wine prefix not found at: {pwiz_prefix}")
        print(f"Set $PROTEOWIZARD_WINEPREFIX environment variable")
        return None
    
    # Get absolute paths
    abs_file_path = os.path.abspath(file_path)
    abs_outdir = os.path.dirname(abs_file_path)
    
    # Determine which path to use: direct msconvert or external Singularity container
    use_direct_msconvert = msconvert_available and not pwiz_sif
    use_singularity = pwiz_sif and pwiz_prefix
    
    # ========== DIRECT MSCONVERT (Unified Container Path) ==========
    if use_direct_msconvert:
        print(f"\n{'='*80}")
        print(f"Converting {file_path} --> .mzML via direct msconvert (unified container)")
        print(f"{'='*80}")
        
        # Set up environment for msconvert to work with Wine/locale
        env = os.environ.copy()
        env['LC_ALL'] = 'C'
        env['LANG'] = 'C'
        env['WINEPREFIX'] = os.environ.get('WINEPREFIX', '/opt/wineprefix')
        
        # Build msconvert command
        cmd = [
            "msconvert",
            abs_file_path,
            "--mzML",         # Output format
            "--zlib",         # Zlib compression
            "--filter", "peakPicking vendor",  # Centroiding via vendor algorithm
            "-o", abs_outdir  # Output directory
        ]
        
        print(f"\nCommand: {' '.join(cmd)}")
        print(f"Environment: LC_ALL=C, LANG=C, WINEPREFIX={env['WINEPREFIX']}")
        
        for attempt in range(max_retries + 1):
            try:
                if attempt > 0:
                    print(f"\nRETRY ATTEMPT {attempt}/{max_retries}")
                
                print(f"\nRunning msconvert...")
                result = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=6000,  # 100 minute timeout
                    env=env
                )
                print(result.stdout)
                
                # Verify output file was created
                if os.path.exists(outfile):
                    print(f"\nSuccess! Created {outfile}")
                    return outfile
                else:
                    # msconvert completed but didn't produce output
                    # Check for WIFF vendor DLL issue
                    if result.stderr and "vendor" in result.stderr.lower():
                        print(f"\nWARNING: ProteoWizard cannot read WIFF files on Linux without Windows vendor DLLs")
                        print(f"The conda msconvert was built without vendor DLL support.")
                        print(f"WIFF files require manual conversion or a Windows ProteoWizard installation.")
                        return None
                    else:
                        print(f"\nERROR: msconvert completed but did not create output file: {outfile}")
                        if result.stderr:
                            print(f"stderr: {result.stderr}")
                        raise RuntimeError("msconvert did not produce output")
                        
            except subprocess.TimeoutExpired:
                error_msg = f"TIMEOUT: msconvert conversion exceeded 100 minutes for {file_path}"
                print(f"ERROR: {error_msg}")
                if attempt < max_retries:
                    backoff_seconds = 2 ** attempt
                    print(f"Retrying in {backoff_seconds} seconds...")
                    time.sleep(backoff_seconds)
                else:
                    raise
                    
            except subprocess.CalledProcessError as e:
                error_msg = f"msconvert failed with exit code {e.returncode}: {e.stderr}"
                print(f"ERROR: {error_msg}")
                
                # Check for WIFF vendor DLL issue
                if e.stderr and ("vendor" in e.stderr.lower() or "scan" in e.stderr.lower()):
                    print(f"\nWARNING: ProteoWizard cannot read WIFF files on Linux without Windows vendor DLLs")
                    return None
                
                if attempt < max_retries:
                    backoff_seconds = 2 ** attempt
                    print(f"Retrying in {backoff_seconds} seconds...")
                    time.sleep(backoff_seconds)
                else:
                    raise
        
        return None
    
    # ========== EXTERNAL SINGULARITY CONTAINER PATH ==========
    if use_singularity:
        abs_pwiz_sif = os.path.abspath(pwiz_sif)
        abs_pwiz_prefix = os.path.abspath(pwiz_prefix)
        filename_only = os.path.basename(file_path)
        
        for attempt in range(max_retries + 1):
            try:
                print(f"\n{'='*80}")
                print(f"Converting {file_path} --> .mzML via ProteoWizard msconvert")
                if attempt > 0:
                    print(f"RETRY ATTEMPT {attempt}/{max_retries}")
                print(f"{'='*80}")
                
                # Build singularity exec command with proper binds
                # Bind: data directory to /data, wine prefix to /wineprefix64
                # CRITICAL: Set WINEPREFIX env var so wine uses the extracted wineprefix64
                cmd = [
                    "singularity", "exec",
                    "--bind", f"{abs_outdir}:/data",
                    "--bind", f"{abs_pwiz_prefix}:/wineprefix64",
                    "--env", "WINEPREFIX=/wineprefix64",
                    abs_pwiz_sif,
                    "wine", "msconvert",
                    "/data/" + filename_only,
                    "--mzML",         # Output format
                    "--zlib",         # Zlib compression
                    "--filter", "peakPicking vendor",  # Centroiding via vendor algorithm
                    "-o", "/data"     # Output directory (inside container)
                ]
                
                print(f"\nSingularity Command:")
                # Print with proper quoting for multi-word arguments
                cmd_for_display = []
                for arg in cmd:
                    if ' ' in arg and not arg.startswith(('-', '/')):  # Quote args with spaces (but not flags/paths)
                        cmd_for_display.append(f'"{arg}"')
                    else:
                        cmd_for_display.append(arg)
                print(f"  {' '.join(cmd_for_display)}")
                
                print(f"\nBound Paths:")
                print(f"  Host {abs_outdir} <--> Container /data")
                print(f"  Host {abs_pwiz_prefix} <--> Container /wineprefix64")
                print(f"  Wine Prefix: /wineprefix64 (WINEPREFIX env var)")
                
                print(f"\nHost-side directory listing ({abs_outdir}):")
                try:
                    for item in sorted(os.listdir(abs_outdir)):
                        item_path = os.path.join(abs_outdir, item)
                        if os.path.isfile(item_path):
                            size = os.path.getsize(item_path)
                            print(f"  FILE: {item} ({size} bytes)")
                        else:
                            print(f"  DIR:  {item}/")
                except Exception as e:
                    print(f"  WARNING: Could not list directory: {e}")
                
                # List container-side directory before conversion
                print(f"\nContainer-side directory listing (before conversion, inside /data):")
                ls_cmd = [
                    "singularity", "exec",
                    "--bind", f"{abs_outdir}:/data",
                    "--bind", f"{abs_pwiz_prefix}:/wineprefix64",
                    "--env", "WINEPREFIX=/wineprefix64",
                    abs_pwiz_sif,
                    "ls", "-lah", "/data"
                ]
                try:
                    ls_result = subprocess.run(ls_cmd, capture_output=True, text=True, timeout=10)
                    print(ls_result.stdout)
                    if ls_result.stderr:
                        print(f"  (stderr): {ls_result.stderr}")
                except Exception as e:
                    print(f"  WARNING: Could not list container /data: {e}")
                
                print(f"\nRunning msconvert...")
                result = subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=6000  # 100 minute timeout
                )
                print(result.stdout)
                print(f"\nSuccess! Finished converting {file_path} --> {outfile}")
                return outfile

            except subprocess.TimeoutExpired:
                error_msg = f"TIMEOUT: msconvert conversion exceeded 10 minutes for {file_path}"
                print(f"ERROR: {error_msg}")
                if attempt < max_retries:
                    backoff_seconds = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                    print(f"Retrying in {backoff_seconds} seconds...")
                    time.sleep(backoff_seconds)
                    continue
                else:
                    print(f"Giving up after {max_retries} retries")
                    return None
                    
            except subprocess.CalledProcessError as e:
                # Check if error is "no files found" - likely transient Wine issue
                error_output = e.stderr + e.stdout
                is_no_files_error = "no files found" in error_output.lower()
                # Also detect vendor filter arg parsing issue
                is_vendor_error = "no files found matching" in error_output.lower() and "vendor" in error_output.lower()
                
                print(f"ERROR: msconvert failed with exit code {e.returncode}")
                print(f"stdout:\n{e.stdout}")
                print(f"stderr:\n{e.stderr}")
                
                if (is_no_files_error or is_vendor_error) and attempt < max_retries:
                    backoff_seconds = 2 ** attempt  # Exponential backoff: 1, 2, 4 seconds
                    print(f"\nDetected transient 'no files found' error (likely Wine/binding issue)")
                    print(f"Retrying in {backoff_seconds} seconds...")
                    time.sleep(backoff_seconds)
                    continue
                else:
                    if is_no_files_error or is_vendor_error:
                        print(f"Gave up after {max_retries} retries of transient 'no files found' error")
                    print("Conversion failed")
                    return None
                    
            except Exception as e:
                print(f"Unexpected error converting {file_path} to .mzML: {e}")
                if attempt < max_retries:
                    backoff_seconds = 2 ** attempt
                    print(f"Retrying in {backoff_seconds} seconds...")
                    time.sleep(backoff_seconds)
                    continue
                else:
                    return None
        
        return None

###################################################################################################################################################
def check_existing_mzml_files(pxd_dir: str) -> tuple:
    """
    Check if mzML files already exist in the given directory.
    
    Returns:
        (exists: bool, mzml_files: List[str])
    """
    mzml_files = glob.glob(os.path.join(pxd_dir, "*.mzML"))
    exists = len(mzml_files) > 0
    return exists, mzml_files


def validate_mzml_file(filepath: str, min_size_mb: int = 1) -> tuple:
    """
    Validate mzML file integrity.
    
    Returns:
        (is_valid: bool, reason: str or None)
    """
    try:
        if not os.path.exists(filepath):
            return False, f"File does not exist: {filepath}"
        
        # Check file size (mzML files should be > min_size_mb)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        if size_mb < min_size_mb:
            return False, f"File too small ({size_mb:.1f}MB < {min_size_mb}MB)"
        
        # Check for mzML markers in file
        with open(filepath, 'rb') as f:
            header = f.read(1024)
            if b'<mzML' not in header and b'<?xml' not in header:
                return False, "File does not contain mzML markers"
        
        return True, None
    except Exception as e:
        return False, f"Validation error: {str(e)}"

###################################################################################################################################################
def run_runAssessor(output_dir="raw_data", central_mzml_dir=None, pxd=None):
    """
    Run runAssessor on the mzML files in output_dir.
    
    If central_mzml_dir is provided, saves results to central storage for persistence.
    Otherwise, saves to output_dir/runAssessor/ (local cache).
    """
    # Figure out where THIS script lives (inside container: /workspace/src/python)
    this_dir = os.path.dirname(os.path.abspath(__file__))
    assessor_path = os.path.join(this_dir, "mzML_assessor.py")

    print(f"\nLaunching Run Assessor")
    
    # Determine where to save results
    if central_mzml_dir and pxd:
        # Save to central storage for reuse across pipeline runs
        runAssessor_output_dir = os.path.join(central_mzml_dir, pxd, "runAssessor")
    else:
        # Fall back to local output_dir
        runAssessor_output_dir = os.path.join(output_dir, "runAssessor")
    
    os.makedirs(runAssessor_output_dir, exist_ok=True)
    runAssessor_outfile = os.path.join(runAssessor_output_dir, "study_metadata.json")

    if os.path.exists(runAssessor_outfile):
        print(f"✓ RunAssessor output already exists: {runAssessor_outfile}")
        return runAssessor_outfile

    cmd = [
        "python",
        assessor_path,
        "--inpath", output_dir,
        "--outpath", runAssessor_output_dir,
    ]

    print("#" * 50)
    print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    # show logs
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"mzML_assessor failed with code {result.returncode}:\n{result.stderr}"
        )

    print(f"✓ RunAssessor results saved to: {runAssessor_outfile}")
    return runAssessor_outfile
###################################################################################################################################################

###################################################################################################################################################
def processes_pxds(pxd_list: List[str], download_dir: str, use_aria2c: bool = False, aria2c_threads: int = 4, max_raw_files: Optional[int] = None, logger: Optional[PipelineLogger] = None):
    for pxd in pxd_list:
        print(f"\nProcessing PXD: {pxd}")
        if logger:
            logger.process_step("fetch", f"Processing {pxd}", {"pxd": pxd})
        print(f"Download method: {'aria2c (' + str(aria2c_threads) + ' threads)' if use_aria2c else 'wget'}")
        if max_raw_files:
            print(f"Max raw files to download: {max_raw_files}")

        # Create directory for this PXD
        pxd_dir = os.path.join(download_dir, pxd)
        os.makedirs(pxd_dir, exist_ok=True)
        
        # CHECK: Skip if mzML files already exist in central repository
        exists, mzml_files = check_existing_mzml_files(pxd_dir)
        if exists:
            print(f"✓ Found {len(mzml_files)} existing mzML file(s) in central repository: {pxd_dir}")
            # Validate existing files
            all_valid = True
            for mzml in mzml_files:
                is_valid, reason = validate_mzml_file(mzml)
                if is_valid:
                    print(f"  ✓ {os.path.basename(mzml)} is valid")
                else:
                    print(f"  ✗ {os.path.basename(mzml)} is corrupted: {reason}")
                    # Delete corrupted file so it can be re-downloaded
                    os.remove(mzml)
                    all_valid = False
            
            if all_valid:
                print(f"✓ All files valid, skipping download for {pxd}")
                # Create symlink in current work directory for Nextflow output
                work_pxd_dir = os.path.join('.', pxd)
                if os.path.islink(work_pxd_dir):
                    os.unlink(work_pxd_dir)
                else:
                    if os.path.isdir(work_pxd_dir):
                        shutil.rmtree(work_pxd_dir)
                os.symlink(pxd_dir, work_pxd_dir)
                print(f"✓ Created symlink: {work_pxd_dir} → {pxd_dir}")
                if logger:
                    logger.process_step("fetch", f"Reusing existing files for {pxd}", {"pxd": pxd, "mzml_count": len(mzml_files)})
                continue
            else:
                print(f"⚠ Some files corrupted, will re-download missing files...")

        print(f"Created directory for PXD {pxd}: {pxd_dir}")

        pride_data = fetch_pride_project_and_files(pxd)
        project_info = pride_data['project']
        files_info = pride_data['files']

        # Save project metadata
        metadata_file = os.path.join(pxd_dir, f"{pxd}_PRIDEmetadata.json")
        with open(metadata_file, 'w') as mf:
            json.dump(pride_data, mf, indent=2)
        print(f"Saved project metadata to {metadata_file}")

        # Fetch PMC publication text if PMID is available
        try:
            pmid = None
            # Extract PMID from PRIDE metadata
            if 'project' in pride_data and 'references' in pride_data['project']:
                references = pride_data['project']['references']
                if references and len(references) > 0:
                    pmid = references[0].get('pubmedID')
            
            if pmid:
                print(f"Found PMID {pmid} for {pxd}, querying PMC...")
                if logger:
                    logger.process_step("fetch", {"action": "pmid_extracted", "pmid": pmid, "pxd": pxd})
                
                # Create pmc_json directory
                pmc_json_dir = os.path.join(pxd_dir, 'pmc_json')
                os.makedirs(pmc_json_dir, exist_ok=True)
                
                # Initialize PMC client and fetch publication text
                pmc_client = PMCClient(timeout=30)
                pmcid = pmc_client.pmid_to_pmcid(str(pmid))
                
                if pmcid:
                    print(f"Converted PMID {pmid} to PMCID {pmcid}")
                    if logger:
                        logger.process_step("fetch", {"action": "pmcid_obtained", "pmid": pmid, "pmcid": pmcid, "pxd": pxd})
                    
                    # Fetch full text in BioC JSON format
                    bioc_data = pmc_client.fetch_full_text(pmcid)
                    
                    if bioc_data:
                        # Save BioC JSON
                        pmc_json_file = os.path.join(pmc_json_dir, f"{pxd}_{pmid}.json")
                        with open(pmc_json_file, 'w') as f:
                            json.dump(bioc_data, f, indent=2)
                        print(f"Saved PMC publication text to {pmc_json_file}")
                        if logger:
                            logger.process_step("fetch", {"action": "pmc_text_saved", "pmid": pmid, "pmcid": pmcid, "file": pmc_json_file, "pxd": pxd})
                    else:
                        print(f"Warning: Could not fetch full text for PMCID {pmcid}")
                        if logger:
                            logger.process_step("fetch", {"action": "pmc_fetch_failed", "pmid": pmid, "pmcid": pmcid, "pxd": pxd})
                else:
                    print(f"Warning: Could not convert PMID {pmid} to PMCID (paper may not be in PMC)")
                    if logger:
                        logger.process_step("fetch", {"action": "pmcid_not_found", "pmid": pmid, "pxd": pxd})
            else:
                print(f"No PubMed ID found in PRIDE metadata for {pxd}")
                if logger:
                    logger.process_step("fetch", {"action": "no_pmid", "pxd": pxd})
        
        except Exception as e:
            print(f"Warning: Error fetching PMC publication text: {e}")
            if logger:
                logger.process_error("fetch", f"PMC fetch error: {str(e)}", is_fatal=False)

        # For each file check its FTP location and download
        num_raw_downloaded = 0
        num_download_failures = 0
        processed_files = set()  # Track processed .raw files to avoid duplicates
        
        # Single pass: ONLY download .raw files (no .wiff, .zip, or other formats)
        for file_record_i, file_record in enumerate(files_info):

            # Check if we've reached the max spectrum files limit BEFORE downloading next file
            if max_raw_files and num_raw_downloaded >= max_raw_files:
                print(f"Reached max spectrum files limit ({max_raw_files}). Stopping download.")
                break

            file_name = file_record.get('fileName')
            file_lower = file_name.lower()
            
            # FILTER: Only download .raw files (no .wiff, .zip, or other formats)
            if not file_lower.endswith('.raw'):
                print(f"Skipping non-.raw file: {file_name}")
                continue
            
            # Skip if we've already processed this file
            if file_name in processed_files:
                print(f"Already processed {file_name}, skipping")
                continue
            processed_files.add(file_name)

            public_locations = file_record.get('publicFileLocations')
            ftp_url = None
            for location in public_locations:
                if location.get('value').startswith('ftp://'):
                    ftp_url = location.get('value')
                    break
            print(f"Found FTP URL: {ftp_url}")

            ## if ftp_url is found, download the file
            if ftp_url and file_name:
                outfile_path = os.path.join(pxd_dir, file_name)
                print(f"Downloading .raw file {file_name} from {ftp_url} to {outfile_path}")
                
                # Try to download the file
                try:
                    if use_aria2c:
                        download_ftp_file_aria2c(ftp_url, outfile_path, aria2c_threads)
                    else:
                        download_ftp_file_wget(ftp_url, outfile_path)
                except Exception as e:
                    error_msg = f"Download failed for {file_name}: {str(e)}"
                    print(f"WARNING: {error_msg}")
                    if logger:
                        logger.process_error("fetch", error_msg, is_fatal=False, details={
                            "pxd": pxd,
                            "file_name": file_name,
                            "ftp_url": ftp_url,
                            "error_type": type(e).__name__
                        })
                    # Skip this file and continue to the next one
                    num_download_failures += 1
                    print(f"Skipping {file_name} and continuing to next file...")
                    continue

                # Count this spectral file BEFORE attempting conversion
                # (regardless of conversion success/failure)
                num_raw_downloaded += 1
                
                # Convert .raw file to mzML via ThermoRawFileParser
                mzml_path = convert_spectral_file_to_mzml(outfile_path)
                if mzml_path and os.path.exists(mzml_path):
                    print(f"Successfully converted {outfile_path} to {mzml_path}")
                else:
                    print(f"WARNING: Conversion may have failed for {outfile_path}")
            else:
                print(f"Failed to extract {zip_path}, skipping")

        # Print download summary
        print(f"\n{'='*80}")
        print(f"Download Summary for {pxd}:")
        print(f"  Successfully downloaded: {num_raw_downloaded} file(s)")
        if num_download_failures > 0:
            print(f"  Failed downloads: {num_download_failures} file(s)")
            if logger:
                logger.process_step("fetch", f"Download complete with failures", {
                    "pxd": pxd,
                    "successful": num_raw_downloaded,
                    "failed": num_download_failures
                })
        print(f"{'='*80}\n")

        # ERROR HANDLING: Check if any spectral files were downloaded
        if num_raw_downloaded == 0:
            warning_msg = f"WARNING: No .raw or .wiff files could be downloaded for {pxd}. This PXD will be skipped."
            print(f"\n{'='*80}")
            print(warning_msg)
            print(f"{'='*80}\n")
            
            # Log to pipeline logger
            if logger:
                logger.process_error("fetch", "No .raw or .wiff files could be downloaded", is_fatal=True, details={"pxd": pxd})
            
            # Log warning to file
            warning_log_file = os.path.join(pxd_dir, f"{pxd}_NO_SPECTRAL_FILES_WARNING.log")
            with open(warning_log_file, 'w') as wf:
                wf.write(warning_msg + "\n")
                wf.write(f"Timestamp: {pd.Timestamp.now()}\n")
                wf.write(f"No .raw or .wiff files were found or downloadable for this PXD.\n")
            
            print(f"Warning logged to: {warning_log_file}")
            # Use a distinct exit code so Nextflow can ignore/skip this PXD without
            # treating it as a transient download failure.
            sys.exit(EXIT_NO_RAW_FILES)

        print(f"\nSuccessfully downloaded and converted {num_raw_downloaded} spectrum file(s) for {pxd}")
        
        # VALIDATION: Verify all mzML files are valid
        exists, mzml_files = check_existing_mzml_files(pxd_dir)
        if exists:
            print(f"\n✓ Validating {len(mzml_files)} mzML file(s)...")
            all_valid = True
            for mzml in mzml_files:
                is_valid, reason = validate_mzml_file(mzml)
                if is_valid:
                    print(f"  ✓ {os.path.basename(mzml)} is valid")
                else:
                    print(f"  ✗ {os.path.basename(mzml)} is corrupted: {reason}")
                    # Delete corrupted file for retry on next run
                    os.remove(mzml)
                    all_valid = False
                    if logger:
                        logger.process_error("fetch", f"Corrupted mzML file deleted: {os.path.basename(mzml)}", is_fatal=False)
            
            if not all_valid:
                print(f"⚠ Some files were corrupted and deleted. They will be re-downloaded on next run.")
        else:
            print(f"⚠ No mzML files found after conversion - download may have failed")

        # Run RunAssessor on the downloaded data
        run_runAssessor(output_dir=pxd_dir, central_mzml_dir=download_dir, pxd=pxd)
        
        # Create symlink in current work directory for Nextflow output
        work_pxd_dir = os.path.join('.', pxd)
        if os.path.islink(work_pxd_dir):
            os.unlink(work_pxd_dir)
        elif os.path.isdir(work_pxd_dir):
            shutil.rmtree(work_pxd_dir)
        os.symlink(pxd_dir, work_pxd_dir)
        print(f"✓ Created symlink: {work_pxd_dir} → {pxd_dir}")
###################################################################################################################################################

###################################################################################################################################################
def main():
    """
    Main function for downloading and converting PRIDE datasets.
    
    File Format Support:
    - .RAW (Thermo): Converted to .mzML via ThermoRawFileParser
      * Lightweight native .NET tool (no containers required)
      * Must be available in PATH or conda environment
    
    Environment Variables (optional):
    - $PROTEOWIZARD_SINGULARITY: Ignored (ThermoRawFileParser is used)
    - $PROTEOWIZARD_WINEPREFIX: Ignored (ThermoRawFileParser is used)
    
    NOTE: This version ONLY downloads .raw files. Other formats (.wiff, .zip) are skipped.
    
    Example:
    python FetchPXD.py --PXD PXD003539 PXD006877 --max_raw_files 5
    """
    parser = argparse.ArgumentParser(description='Download and convert PRIDE spectral data (.RAW → .mzML)')
    parser.add_argument('--central_mzml_dir', default=None, help='Central directory for all mzML files (if not provided, uses current directory)')
    parser.add_argument('--download_dir', default='data/PRIDE_downloads', help='Directory to save downloaded projects (deprecated, use --central_mzml_dir)')
    parser.add_argument('--PXD', nargs='+', help='List of PXD identifiers to download (overrides other selection criteria)')
    parser.add_argument('--use_aria2c', action='store_true', help='Use aria2c for multi-threaded downloads instead of wget')
    parser.add_argument('--aria2c_threads', type=int, default=4, help='Number of threads for aria2c downloads (default: 4)')
    parser.add_argument('--max_raw_files', type=int, default=None, help='Maximum number of spectrum files (.RAW) to download per PXD (default: all files)')
    parser.add_argument('--log_file', default=None, help='Path to JSONL file for pipeline event logging')
    args = parser.parse_args()
    print(f"\nStarting FetchPXD with arguments: {args}")
    
    # Initialize logger if log_file specified
    logger = None
    if args.log_file and args.PXD:
        pxd_id = args.PXD[0] if isinstance(args.PXD, list) else args.PXD
        logger = PipelineLogger(args.log_file, pxd_id)
        logger.process_start("fetch", {"pxd": pxd_id})
    
    # Note: ThermoRawFileParser conversion requires ThermoRawFileParser to be available
    print("INFO: ThermoRawFileParser will be used for .raw → .mzML conversion.")
    print("Ensure ThermoRawFileParser is installed and available in PATH or conda environment.")

    ## Use central_mzml_dir if provided, otherwise use download_dir for backward compatibility
    download_dir = args.central_mzml_dir if args.central_mzml_dir else args.download_dir
    os.makedirs(download_dir, exist_ok=True)
    print(f"Central mzML directory: {download_dir}")

    ## For each PXD query the PRIDE API and download the 
    pxd_list = args.PXD
    if not pxd_list:
        print("No PXD identifiers provided. Exiting.")
        if logger:
            logger.process_error("fetch", "No PXD identifiers provided")
        return
    print(f"Processing PXDs: {pxd_list}")
    processes_pxds(pxd_list, download_dir, args.use_aria2c, args.aria2c_threads, args.max_raw_files, logger=logger)
    
###################################################################################################################################################
if __name__ == "__main__":
    main()
print('NORMAL TERMINATION')