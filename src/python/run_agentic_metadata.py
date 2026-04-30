#!/usr/bin/env python3
"""
Standalone script to run agentic metadata extraction on a single
PXD*_aggregated_results.json file.

Usage:
    python src/python/run_agentic_metadata.py \
        --input store/aggregated_results_files/PXD041514_aggregated_results.json \
        --outdir /path/to/output \
        [--pub_text /path/to/PXD041514_PubText.txt]
"""

import argparse
import re
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
import json

ALLOWED_section_types = ['TITLE', 'ABSTRACT', 'INTRO', 'RESULTS', 'DISCUSS', 'FIG', 'METHODS', 'REF', 'SUPPL']
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTIC_MAIN = REPO_ROOT / "src" / "agentic-metadata" / "main.py"
AGENTIC_CONFIG = REPO_ROOT / "src" / "agentic-metadata" / "config.yaml"

# Set in main() so agentic_to_sdrf() can access the aggregated_results.json path.
_last_input_json: Path = Path("")
######################################################################################################

######################################################################################################
def run_agentic_extraction(input_json: Path, outdir: Path, pride_cache: Path, pmc_cache: Path) -> None:

    temperature = "0.0"

    ###-------------------------------------------------------------------------------
    print(f"\nInput JSON: {input_json}")
    print(f"Output directory: {outdir}")
    print(f"PRIDE cache: {pride_cache}")
    print(f"PMC cache: {pmc_cache}")
    pxd_match = re.match(r"(PXD\d+)", input_json.name)
    if not pxd_match:
        sys.exit(f"ERROR: Could not extract PXD ID from filename: {input_json.name}")
    pxd = pxd_match.group(1)
    print(f"Extracted PXD ID: {pxd}")

    ###-------------------------------------------------------------------------------
    pub_text = Path(tempfile.gettempdir()) / f"{pxd}_PubText.txt"
    if not pub_text.exists():
        print(f"Publication text file not found: {pub_text}, Creating...")

        ## Load pride_cache and get pxd metadata
        with open(pride_cache, "rb") as f:
            pride_data = json.load(f)

        pxd_metadata = next((m for m in pride_data['response'] if m['accession'] == pxd), None)
        if pxd_metadata is None:
            sys.exit(f"ERROR: PXD ID {pxd} not found in PRIDE cache")
        print(f"Loaded metadata for {pxd} from PRIDE cache")
        # print(pxd_metadata)

        ## Extract .raw file names from PRIDE metadata
        files = pxd_metadata.get('files', [])
        filenames = [f.get('fileName', '') for f in files if f.get('fileName', '').lower().endswith('.raw')]
        print(f"Extracted .raw filenames from PRIDE metadata: {filenames}")


        ###-------------------------------------------------------------------------------
        # Load pmc_cache and get publication text if available
        pmc_data = None
        with open(pmc_cache, "r") as f:
            pmc_data = json.load(f)

        pmc_metadata = pmc_data.get(pxd, None)
        if pmc_metadata is None:
            sys.exit(f"ERROR: PXD ID {pxd} not found in PMC cache")
        print(f"Loaded publication text metadata for {pxd} from PMC cache")
        # print(pmc_metadata)

        full_text = pmc_metadata.get('full_text', '')
        full_text = full_text + "\nMass spectrometry data files:\n" + "\n".join(filenames)
        # print(full_text)
        # Save full text to a temporary file for agentic input
        pub_text = Path(tempfile.gettempdir()) / f"{pxd}_PubText.txt"
        with open(pub_text, 'w') as f:
            f.write(full_text)
        print(f"Saved publication text to temporary file: {pub_text}")

    ###-------------------------------------------------------------------------------

    ###-------------------------------------------------------------------------------
    TechAgent_outfile = outdir / f"integrated_output/TechnicalAgent/temp_{temperature}/{pxd}_PubText_enriched.json"
    BioAgent_outfile = outdir / f"integrated_output/BiologicalAgent/temp_{temperature}/{pxd}_PubText_enriched.json"
    ExpAgent_outfile = outdir / f"integrated_output/ExperimentalDesignAgent/temp_{temperature}/{pxd}_PubText_enriched.json"
    if TechAgent_outfile.exists() and BioAgent_outfile.exists() and ExpAgent_outfile.exists():
        print(f"Agentic output already exists for {pxd} at {TechAgent_outfile}, {BioAgent_outfile}, and {ExpAgent_outfile}. Skipping extraction.")
        return [TechAgent_outfile, BioAgent_outfile, ExpAgent_outfile]
    
    else:
        with tempfile.TemporaryDirectory(prefix=f"agentic_{pxd}_") as tmpdir:
            docs_dir = Path(tmpdir) / "documents"
            runassessor_dir = Path(tmpdir) / "runassessor_data"
            agentic_output = Path(tmpdir) / "output"
            docs_dir.mkdir()
            runassessor_dir.mkdir()
            agentic_output.mkdir()
            print(f"Created temporary directories: {docs_dir}, {runassessor_dir}, {agentic_output}")

            # Copy publication text if provided
            shutil.copy(pub_text, docs_dir / pub_text.name)
            print(f"Copied publication text to: {docs_dir / pub_text.name}")

            # Stage aggregated results for integration
            shutil.copy(input_json, runassessor_dir / input_json.name)
            print(f"Copied aggregated results to: {runassessor_dir / input_json.name}")

            cmd = [
                sys.executable, str(AGENTIC_MAIN), "all",
                "--config", str(AGENTIC_CONFIG),
                "--input", str(docs_dir),
                "--output", str(agentic_output),
                "--integrate",
                "--runassessor-dir", str(runassessor_dir),
                "--single-temp", temperature,
                "--seed", "42",
            ]
            print(f"Running command: {' '.join(cmd)}")

            print(f"Running agentic metadata extraction for {pxd}...")
            result = subprocess.run(cmd, cwd=REPO_ROOT / "src" / "agentic-metadata")
            if result.returncode != 0:
                print(f"WARNING: Extraction exited with code {result.returncode}")

            # Copy results to output directory
            print(f"Copying agentic output from {agentic_output} to {outdir}...")
            outdir.mkdir(parents=True, exist_ok=True)
            for item in agentic_output.iterdir():
                dest = outdir / item.name
                print(item, dest)
                if item.is_dir():
                    shutil.copytree(item, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest)

            # Build the expected output file paths (same pattern used by fast-path above)
            temperature = "0.0"
            output_files = [
                outdir / f"integrated_output/TechnicalAgent/temp_{temperature}/{pxd}_PubText_enriched.json",
                outdir / f"integrated_output/BiologicalAgent/temp_{temperature}/{pxd}_PubText_enriched.json",
                outdir / f"integrated_output/ExperimentalDesignAgent/temp_{temperature}/{pxd}_PubText_enriched.json",
            ]

        print(f"Done. Results written to: {outdir}")
        print(f"Agentic output files: {output_files}")
        return output_files
######################################################################################################

######################################################################################################
def agentic_to_sdrf(agentic_output: list[Path], sdrf_output: Path) -> None:
    """
    Convert the three agentic enriched JSONs + the aggregated_results.json
    (resolved from the input path stored in run_agentic_extraction) into an
    SDRF-Proteomics v1.1.0 TSV file.

    agentic_output is expected to be the list returned by run_agentic_extraction:
        [TechnicalAgent enriched JSON, BiologicalAgent enriched JSON,
         ExperimentalDesignAgent enriched JSON]

    The aggregated_results.json is resolved from the input argument kept at
    module level as _last_input_json.
    """
    from sdrf_builder import AgenticToSDRF
    print(agentic_output)
    if len(agentic_output) < 3:
        print(f"WARNING: expected 3 agentic output files, got {len(agentic_output)}. Skipping SDRF conversion.")
        return

    tech_json, bio_json, exp_json = agentic_output[0], agentic_output[1], agentic_output[2]

    builder = AgenticToSDRF(
        tech_json=tech_json,
        bio_json=bio_json,
        exp_json=exp_json,
        aggregated_json=_last_input_json,
    )
    builder.to_sdrf(sdrf_output)
######################################################################################################

######################################################################################################
######################################################################################################
def main():
    parser = argparse.ArgumentParser(description="Run agentic metadata extraction on a PXD aggregated results JSON.")
    parser.add_argument("--input", required=True, type=Path, help="Path to PXD*_aggregated_results.json")
    parser.add_argument("--outdir", required=True, type=Path, help="Output directory for extraction results")
    parser.add_argument("--pride_cache", default="pride_survey/pride_cache", type=Path, help="Path to the binary cache of PRIDE metadata")
    parser.add_argument("--pmc_cache", default="pride_survey/pmc_cache", type=Path, help="Optional path to PXD*_PubText.txt for publication text input")
    args = parser.parse_args()

    if not args.input.exists():
        sys.exit(f"ERROR: Input file not found: {args.input}")

    ###-------------------------------------------------------------------------------
    ### Store the input path for use by agentic_to_sdrf()
    global _last_input_json
    _last_input_json = args.input.resolve()
    pxd_match = re.match(r"(PXD\d+)", _last_input_json.name)
    if not pxd_match:
        sys.exit(f"ERROR: Could not extract PXD ID from filename: {_last_input_json.name}")
    pxd = pxd_match.group(1)
    print(f"Extracted PXD ID: {pxd}")

    ### Run the agentic metadata extraction
    output_files = run_agentic_extraction(args.input, args.outdir, args.pride_cache, args.pmc_cache)

    ### Convert agentic output to SDRF format (placeholder)
    agentic_to_sdrf(agentic_output=output_files, sdrf_output=args.outdir / f"{pxd}.sdrf.tsv")

######################################################################################################
######################################################################################################

######################################################################################################
if __name__ == "__main__":
    main()
######################################################################################################
