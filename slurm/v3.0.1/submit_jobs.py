"""Submit the generated manifest in tracker order with per-PXD afterok dependencies."""

import argparse
import csv
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def submit_jobs(rows, receipt):
    submitted = {}
    with receipt.open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("script", "job_id", "depends_on_job_id"))
        writer.writeheader()
        handle.flush()
        for row in rows:
            predecessor = row["depends_on"]
            if predecessor and predecessor not in submitted:
                raise ValueError(f"Predecessor must be submitted first: {predecessor}")
            dependency = submitted[predecessor] if predecessor else ""
            command = ["sbatch", "--parsable"]
            if dependency:
                command.append(f"--dependency=afterok:{dependency}")
            command.append(str(ROOT / row["script"]))
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            job_id = result.stdout.strip().split(";", 1)[0]
            if not re.fullmatch(r"\d+", job_id):
                raise ValueError(f"Unexpected sbatch job ID: {result.stdout!r}")
            submitted[row["script"]] = job_id
            writer.writerow({"script": row["script"], "job_id": job_id,
                             "depends_on_job_id": dependency})
            handle.flush()
            print(f"{job_id}: {row['script']}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submit", action="store_true", help="Actually call sbatch; otherwise show counts only")
    parser.add_argument("--limit", type=int, help="First N jobs in manifest order")
    parser.add_argument("--receipt", type=Path, default=ROOT / "submitted_jobs.csv",
                        help="New receipt path; existing receipts are never overwritten")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    with (ROOT / "jobs.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if args.limit is not None:
        rows = rows[:args.limit]
    scripts = {row["script"] for row in rows}
    for row in rows:
        if not (ROOT / row["script"]).is_file():
            raise FileNotFoundError(ROOT / row["script"])
        if row["depends_on"] and row["depends_on"] not in scripts:
            raise ValueError(f"Missing dependency for {row['script']}")
    print(f"{len(rows)} jobs, {sum(bool(row['depends_on']) for row in rows)} afterok dependencies")
    if not args.submit:
        print("No jobs submitted. Add --submit only when ready.")
        return
    if any(row["mode"] == "full" for row in rows) and not os.environ.get("OPENROUTER_API_KEY"):
        parser.error("Export OPENROUTER_API_KEY before submitting full-pipeline jobs")
    submit_jobs(rows, args.receipt)


if __name__ == "__main__":
    main()
