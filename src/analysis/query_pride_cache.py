#!/usr/bin/env python3
"""Query the local PRIDE cache for a given PXD accession and print its metadata."""

import json
import sys
from pathlib import Path
import argparse
import pandas as pd

CACHE = Path(__file__).parent.parent.parent / "pride_survey" / "pride_cache"
MASTER = Path(__file__).parent.parent.parent / "master.csv"
def main():
    parser = argparse.ArgumentParser(description="Query the local PRIDE cache for a given PXD accession.")
    parser.add_argument("accession", nargs="?", help="PRIDE project accession (e.g., PXD000189)")
    parser.add_argument("--cache", default=CACHE, help="Path to the local PRIDE cache JSON file")
    parser.add_argument("--spectral_file_type_stats", action="store_true", help="Print spectral file type statistics instead of metadata")
    parser.add_argument("--update_master_w_spec_filetype", action="store_true", help="Update the master cache with spectral file type statistics (not implemented yet)")
    parser.add_argument("--master", default=MASTER, help="Path to the master cache CSV file for updates (not implemented yet)")
    args = parser.parse_args()

    ## Load the cache and search for the accession
    with open(CACHE) as f:
        data = json.load(f)


    #############################################################################################################
    ## If accession was provided, search for it in the cache and print its metadata
    if args.accession:
        accession = args.accession.strip().upper()

        for entry in data["response"]:
            if entry.get("accession", "").upper() == accession:
                print(json.dumps(entry, indent=2))
                sys.exit(0)

        print(f"'{accession}' not found in cache.", file=sys.stderr)
        sys.exit(1)

    #############################################################################################################
    ## If spectral file type statistics were requested, calculate and print them
    # Spectral files have fileCategory.value == "RAW" or "PEAK".
    # File type is derived from the extension of fileName.
    SPECTRAL_CATEGORIES = {"RAW", "PEAK"}
    if args.spectral_file_type_stats:
        file_type_counts = {}
        for entry in data["response"]:
            for file in entry.get("files", []):
                cat = file.get("fileCategory", {}).get("value", "")
                if cat not in SPECTRAL_CATEGORIES:
                    continue
                name = file.get("fileName", "")
                ext = name.rsplit(".", 1)[-1].upper() if "." in name else "UNKNOWN"
                file_type_counts[ext] = file_type_counts.get(ext, 0) + 1

        print("Spectral File Type Statistics (RAW + PEAK categories):")
        for ext, count in sorted(file_type_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {ext}: {count}")
        sys.exit(0)


    #############################################################################################################
    ## Update the master with the set of unique spectral file types found in each PXD ";" separated, in a new column "spectral_file_types". This is for future filtering of the master cache by spectral file type.
    if args.update_master_w_spec_filetype:
        SPECTRAL_CATEGORIES = {"RAW", "PEAK"}

        # Build a lookup: accession -> sorted ";"-separated unique extensions
        print("Building spectral file type lookup from cache...", file=sys.stderr)
        pxd_ext_map = {}
        for entry in data["response"]:
            acc = entry.get("accession", "")
            if not acc:
                continue
            exts = set()
            for file in entry.get("files", []):
                cat = file.get("fileCategory", {}).get("value", "")
                if cat not in SPECTRAL_CATEGORIES:
                    continue
                name = file.get("fileName", "")
                ext = name.rsplit(".", 1)[-1].upper() if "." in name else "UNKNOWN"
                exts.add(ext)
            if exts:
                pxd_ext_map[acc] = ";".join(sorted(exts))

        master_path = Path(args.master)
        df = pd.read_csv(master_path)

        df["spectral_file_types"] = df["accession"].map(pxd_ext_map).fillna("")

        df.to_csv(master_path, index=False)
        matched = df["spectral_file_types"].ne("").sum()
        print(f"Updated {master_path}: {matched}/{len(df)} rows matched in cache.")
        sys.exit(0)

if __name__ == "__main__":
    main()