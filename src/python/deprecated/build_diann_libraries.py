#!/usr/bin/env python3
"""
Build DIA-NN spectral libraries for the top 20 organisms.
Run this script once to pre-cache libraries, then update as needed for new organisms.

Usage:
    python build_diann_libraries.py [--cache-dir <path>] [--threads <N>]

Output:
    Cached libraries stored in: workspace/assets/diann_libraries/{taxid}.tsv
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Top 20 organisms by PRIDE/ProteomeXchange frequency
# Format: (taxid, common_name)
TOP_ORGANISMS = [
    ("9606", "Homo sapiens (Human)"),
    ("10090", "Mus musculus (Mouse)"),
    ("10116", "Rattus norvegicus (Rat)"),
    ("6239", "Caenorhabditis elegans"),
    ("7227", "Drosophila melanogaster (Fruit fly)"),
    ("559292", "Saccharomyces cerevisiae (Baker's yeast)"),
    ("284812", "Schizosaccharomyces pombe"),
    ("3702", "Arabidopsis thaliana"),
    ("7955", "Danio rerio (Zebrafish)"),
    ("8355", "Xenopus laevis (African clawed frog)"),
    ("9913", "Bos taurus (Cattle)"),
    ("9615", "Canis lupus familiaris (Dog)"),
    ("9826", "Sus scrofa (Pig)"),
    ("6945", "Gallus gallus (Chicken)"),
    ("511145", "Escherichia coli"),
    ("562", "Escherichia coli (generic)"),
    ("694009", "Bacillus subtilis"),
    ("1280", "Staphylococcus aureus"),
    ("2157", "Archaea (domain)"),
    ("2759", "Eukaryota (domain)"),
]


def get_diann_executable() -> str:
    """Find DIA-NN executable in search environment"""
    search_env = os.environ.get('SEARCH_ENV_PATH', '/home/ians/miniconda3/envs/search_env')
    tools_root = os.path.join(search_env, 'opt', 'search_tools', 'diann')
    
    diann_bin = os.path.join(tools_root, 'diann-1.9.1.8')
    if os.path.exists(diann_bin):
        return diann_bin
    
    diann_bin = os.path.join(tools_root, 'diann')
    if os.path.exists(diann_bin):
        return diann_bin
    
    raise FileNotFoundError(f"DIA-NN executable not found in {tools_root}. Install it or set SEARCH_ENV_PATH.")


def download_fasta(taxid: str, cache_dir: Path) -> Path:
    """Download UniProt FASTA for organism"""
    fasta_path = cache_dir / f"fasta_{taxid}.fasta"
    
    if fasta_path.exists():
        print(f"✓ FASTA already cached: {fasta_path}")
        return fasta_path
    
    print(f"Downloading FASTA for taxid {taxid}...")
    url = f"https://www.uniprot.org/uniprot/?query=organism:{taxid}&format=fasta&compress=no"
    
    try:
        cmd = ['wget', '-q', '-O', str(fasta_path), url]
        result = subprocess.run(cmd, timeout=300, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"  WARNING: wget failed for {taxid}: {result.stderr}")
            return None
        
        if fasta_path.stat().st_size < 1000:
            print(f"  WARNING: FASTA file too small for {taxid}, may be invalid")
            fasta_path.unlink()
            return None
        
        print(f"  ✓ Downloaded {fasta_path.stat().st_size / 1e6:.1f} MB")
        return fasta_path
        
    except subprocess.TimeoutExpired:
        print(f"  ERROR: Download timeout for taxid {taxid}")
        return None
    except Exception as e:
        print(f"  ERROR downloading FASTA: {e}")
        return None


def build_library(
    taxid: str,
    fasta_path: Path,
    output_library: Path,
    threads: int = 8
) -> bool:
    """Build spectral library using DIA-NN"""
    
    temp_dir = output_library.parent / f"temp_{taxid}"
    temp_dir.mkdir(exist_ok=True)
    
    try:
        diann_bin = get_diann_executable()
        
        print(f"Building library for {taxid}...")
        print(f"  Input FASTA: {fasta_path}")
        print(f"  Output library: {output_library}")
        
        cmd = [
            diann_bin,
            "--fasta", str(fasta_path),
            "--fasta-search",              # library-free mode
            "--cut", "K*,R*",              # trypsin
            "--missed-cleavages", "1",
            "--met-excision",
            "--gen-spec-lib",              # generate library
            "--predictor",
            "--min-fr-mz", "200",
            "--max-fr-mz", "1800",
            "--out-lib", str(output_library),
            "--temp", str(temp_dir),
            "--threads", str(threads),
            "--verbose", "0",
        ]
        
        print(f"  Command: {' '.join(cmd[:5])} ...")
        result = subprocess.run(cmd, timeout=3600, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"  ERROR: DIA-NN failed with exit code {result.returncode}")
            print(f"  STDERR: {result.stderr[:500]}")
            return False
        
        if not output_library.exists():
            print(f"  ERROR: Library file not created")
            return False
        
        lib_size = output_library.stat().st_size / 1e6
        print(f"  ✓ Library built successfully ({lib_size:.1f} MB)")
        return True
        
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        return False
    except subprocess.TimeoutExpired:
        print(f"  ERROR: DIA-NN build timeout")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False
    finally:
        # Clean up temp directory
        import shutil
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
        description='Pre-build DIA-NN spectral libraries for common organisms'
    )
    parser.add_argument(
        '--cache-dir',
        type=Path,
        default=Path(__file__).parent.parent.parent / 'assets' / 'diann_libraries',
        help='Cache directory for libraries (default: workspace/assets/diann_libraries)'
    )
    parser.add_argument(
        '--threads',
        type=int,
        default=8,
        help='Threads for DIA-NN (default: 8)'
    )
    parser.add_argument(
        '--organisms',
        type=str,
        help='Comma-separated taxids to build (default: top 20)'
    )
    parser.add_argument(
        '--skip-download',
        action='store_true',
        help='Skip FASTA download, use cached files only'
    )
    
    args = parser.parse_args()
    
    # Create cache directory
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"Cache directory: {args.cache_dir}\n")
    
    # Determine organisms to build
    if args.organisms:
        organisms = [(tid.strip(), f"Custom {tid}") for tid in args.organisms.split(',')]
    else:
        organisms = TOP_ORGANISMS
    
    print(f"Building libraries for {len(organisms)} organisms...\n")
    
    results = {'success': [], 'skipped': [], 'failed': []}
    
    for taxid, name in organisms:
        print(f"\n{'='*70}")
        print(f"Organism: {name} (taxid: {taxid})")
        print(f"{'='*70}")
        
        lib_path = args.cache_dir / f"{taxid}.tsv"
        
        # Check if library already cached
        if lib_path.exists():
            lib_size = lib_path.stat().st_size / 1e6
            print(f"✓ Library already cached ({lib_size:.1f} MB)")
            results['skipped'].append(taxid)
            continue
        
        # Download FASTA
        if args.skip_download:
            fasta_path = args.cache_dir / f"fasta_{taxid}.fasta"
            if not fasta_path.exists():
                print(f"Skipping (FASTA not cached): {fasta_path}")
                results['skipped'].append(taxid)
                continue
        else:
            fasta_path = download_fasta(taxid, args.cache_dir)
            if not fasta_path:
                results['failed'].append(taxid)
                continue
        
        # Build library
        success = build_library(taxid, fasta_path, lib_path, args.threads)
        if success:
            results['success'].append(taxid)
        else:
            results['failed'].append(taxid)
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"Built: {len(results['success'])}")
    if results['success']:
        print(f"  {', '.join(results['success'])}")
    print(f"Skipped: {len(results['skipped'])}")
    if results['skipped']:
        print(f"  {', '.join(results['skipped'][:5])}")
    print(f"Failed: {len(results['failed'])}")
    if results['failed']:
        print(f"  {', '.join(results['failed'])}")
    
    return 0 if not results['failed'] else 1


if __name__ == '__main__':
    sys.exit(main())
