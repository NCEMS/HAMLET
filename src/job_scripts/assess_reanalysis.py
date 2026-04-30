import sys, os
import glob
import json
import shutil
import csv
import argparse
import pandas as pd

def main():
    parser = argparse.ArgumentParser(description="Assess reanalysis status and archive completed results.")
    parser.add_argument("--master_csv", required=True, help="Path to master CSV file with PXDs column")
    parser.add_argument("--results_dir", default="results", help="Path to results directory (default: results)")
    parser.add_argument("--store_dir", default="store", help="Path to store directory (default: store)")
    args = parser.parse_args()

    results_dir = os.path.abspath(args.results_dir)
    store_dir = os.path.abspath(args.store_dir)
    agg_dest = os.path.join(store_dir, "aggregated_results_files")
    inter_dest = os.path.join(store_dir, "intermediate_files")

    os.makedirs(agg_dest, exist_ok=True)
    os.makedirs(inter_dest, exist_ok=True)

    # Read PXDs from CSV
    master = pd.read_csv(args.master_csv)


    total = len(master)
    completed = 0
    missing = 0
    no_agg = 0
    archived = 0
    errors = []

    for rowi, row in master.iterrows():
        print(f"\nProcessing row {rowi+1}/{total} - PXD: {row['accession']}")
        pxd = row["accession"].strip()
        pxd_results = os.path.join(results_dir, pxd)
        print(f"  Checking results directory: {pxd_results}")

        if not os.path.isdir(pxd_results):
            missing += 1
            print(f"  Results directory not found: {pxd_results}")
            continue

        # Look for the aggregated results JSON
        agg_pattern = os.path.join(pxd_results, f"{pxd}_aggregated_results.json")
        agg_files = glob.glob(agg_pattern)

        if not agg_files:
            no_agg += 1
            print(f"  No aggregated results found for PXD: {pxd}")
            continue

        agg_file = agg_files[0]
        print(f"  Found aggregated results: {agg_file}")
        

        # Verify the aggregated file is non-empty and valid JSON
        try:
            with open(agg_file, "r") as f:
                data = json.load(f)
            if not data:
                no_agg += 1
                print(f"  Aggregated results file is empty for PXD: {pxd}") 
                continue
        except (json.JSONDecodeError, IOError):
            no_agg += 1
            print(f"  Error reading aggregated results file for PXD: {pxd}")
            continue

        completed += 1
        print(f"  PXD {pxd} is completed with a valid aggregated results file. Archiving results...")


        try:
            # 1) Copy aggregated results JSON to store/aggregated_results_files/
            agg_dest_file = os.path.join(agg_dest, os.path.basename(agg_file))
            shutil.copy2(agg_file, agg_dest_file)
            print(f"  Copied aggregated results to {agg_dest_file}")

            # 2) Copy remaining non-.raw, non-.mzML files to store/intermediate_files/PXD######/
            pxd_inter = os.path.join(inter_dest, pxd)
            os.makedirs(pxd_inter, exist_ok=True)

            for root, dirs, files in os.walk(pxd_results):
                for fname in files:
                    lower = fname.lower()
                    if lower.endswith(".raw") or lower.endswith(".mzml"):
                        print(f"  Skipping raw/mzML file: {fname}")
                        continue
                    src = os.path.join(root, fname)
                    # Preserve subdirectory structure
                    rel = os.path.relpath(src, pxd_results)
                    dst = os.path.join(pxd_inter, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    print(f"  Copied intermediate file to {dst}")

            # 3) Delete the results/PXD###### directory
            shutil.rmtree(pxd_results)
            archived += 1
            print(f"  Archived and deleted results for PXD: {pxd}")

        except Exception as e:
            errors.append((pxd, str(e)))
            print(f"ERROR archiving {pxd}: {e}")

        
        # if copmpleted and archived then change Reannotated to True in the master CSV
        master.at[rowi, "Reannotated"] = True 
        print(f"  Marked PXD {pxd} as Reannotated in master CSV")

    # Summary
    print(f"\n{'='*50}")
    print(f"Reanalysis Assessment Summary")
    print(f"{'='*50}")
    print(f"Total PXDs in CSV:       {total}")
    print(f"Results dir not found:   {missing}")
    print(f"No aggregated results:   {no_agg}")
    print(f"Completed (agg found):   {completed}")
    print(f"Archived & deleted:      {archived}")
    if errors:
        print(f"Errors during archival:  {len(errors)}")
        for pxd, err in errors:
            print(f"  {pxd}: {err}")
    print(f"{'='*50}")

    # Save the updated master CSV with Reannotated column
    master.to_csv(args.master_csv, index=False)
    print(f"Updated master CSV saved: {args.master_csv}")

if __name__ == "__main__":
    main()
