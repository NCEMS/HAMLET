#!/usr/bin/env python3
"""
Generate SLURM scripts for each PXD in a CSV file.

Takes a template SLURM file and a CSV list of PXDs, generates a unique SLURM
file for each PXD with the PXD number updated throughout.
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def existing_results_root(row, override=None):
    pxd = row["accession"]
    if override:
        root = Path(override).expanduser().resolve()
    else:
        location = row.get("aggregated_results_json_path", "")
        if not location or "::" in location:
            raise ValueError(f"{pxd}: prior results are absent or archived; restore them and use --existing-results-root")
        aggregate = Path(location).resolve()
        parents = [p for p in aggregate.parents if p.name == pxd]
        if not parents:
            raise ValueError(f"{pxd}: cannot identify prior per-PXD directory in {location}")
        root = parents[0].parent
    prior = root / pxd
    aggregate = prior / f"{pxd}_aggregated_results.json"
    if aggregate.is_file():
        with aggregate.open() as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or data.get("pxd_id", pxd) != pxd:
            raise ValueError(f"{pxd}: invalid prior aggregate: {aggregate}")
        return root
    directories = [prior / "search", prior / "llm_results"]
    files = [prior / "taxid_warnings.json", prior / "runAssessor/study_metadata.json"]
    missing = [str(p) for p in directories if not p.is_dir() or not os.access(p, os.R_OK | os.X_OK)]
    missing += [str(p) for p in files if not p.is_file() or not os.access(p, os.R_OK) or not p.stat().st_size]
    if missing:
        raise ValueError(f"{pxd}: missing prior inputs: {', '.join(missing)}")
    return root


def generate_slurm_files(template_path, pxd_csv_path, output_dir,
                         existing_root=None, skip_unavailable=False):
    """
    Generate SLURM files for each PXD listed in a CSV.

    Args:
        template_path: Path to the template SLURM file
        pxd_csv_path: Path to CSV file with PXDs (first column or "PXDs" header)
        output_dir: Output directory for generated SLURM files

    Returns:
        List of generated SLURM file paths, in CSV order.
    """
    template_path = Path(template_path)
    pxd_csv_path = Path(pxd_csv_path)
    output_dir = Path(output_dir)

    # Verify inputs
    if not template_path.exists():
        raise FileNotFoundError(f"Template file not found: {template_path}")
    if not pxd_csv_path.exists():
        raise FileNotFoundError(f"PXD CSV file not found: {pxd_csv_path}")

    # Read template
    template_content = template_path.read_text()

    # Extract template PXD from template content
    template_pxd = None
    match = re.search(r"^PXD=(PXD(?:\d+|#+))$", template_content, re.MULTILINE)
    if match:
        template_pxd = match.group(1)

    if not template_pxd:
        raise ValueError("Could not extract PXD from template file")

    print(f"Template PXD found: {template_pxd}")

    # Read PXDs from CSV
    rows = []
    seen = set()
    with open(pxd_csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        key = next((k for k in ("accession", "PXD", "PXDs") if k in reader.fieldnames), reader.fieldnames[0])
        for row in reader:
            pxd = row[key].strip()
            if not re.fullmatch(r"PXD\d{6,}", pxd):
                raise ValueError(f"Invalid PXD: {pxd!r}")
            if pxd not in seen:
                rows.append(dict(row, accession=pxd))
                seen.add(pxd)

    if not rows:
        raise ValueError("No PXDs found in CSV file")

    planned = []
    for row in rows:
        pxd = row["accession"]
        content = template_content.replace(template_pxd, pxd)
        if "__EXISTING_RESULTS__" in content:
            try:
                prior_root = existing_results_root(row, existing_root)
            except ValueError as error:
                if not skip_unavailable:
                    raise
                print(f"SKIPPED: {error}", file=sys.stderr)
                continue
            content = content.replace("__EXISTING_RESULTS__", str(prior_root))
        target = output_dir / f"{pxd}.slurm"
        if target.exists():
            raise FileExistsError(target)
        planned.append((target, content))
    if not planned:
        raise ValueError("No scripts can be generated with the available inputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate SLURM files
    output_files = []
    for output_file, new_content in planned:
        # Slurm opens its log before the script can create RUN_DIR.
        log = re.search(r"^#SBATCH --output=(.+)$", new_content, re.MULTILINE)
        if log:
            Path(log.group(1)).parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(new_content)
        print(f"Generated: {output_file}")
        output_files.append(output_file)

    print(f"\nGenerated {len(output_files)} scripts; skipped {len(rows) - len(output_files)} PXDs.")

    return output_files


def submit_slurm_files(slurm_files, batch_size, dwell):
    """
    Submit SLURM files with sbatch in batches, sleeping between batches.

    Args:
        slurm_files: List of SLURM file paths to submit, in submission order.
        batch_size: Number of files to submit per batch.
        dwell: Seconds to sleep between batches (skipped after the last batch).
    """
    batches = [
        slurm_files[i:i + batch_size]
        for i in range(0, len(slurm_files), batch_size)
    ]

    for batch_num, batch in enumerate(batches, start=1):
        print(f"\nSubmitting batch {batch_num}/{len(batches)} ({len(batch)} job(s))")
        for slurm_file in batch:
            result = subprocess.run(
                ["sbatch", str(slurm_file)],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to submit {slurm_file}: {result.stderr.strip()}")
            else:
                print(f"  {result.stdout.strip()} ({slurm_file})")

        if batch_num < len(batches) and dwell > 0:
            print(f"Waiting {dwell}s before next batch...")
            time.sleep(dwell)


def main():
    parser = argparse.ArgumentParser(
        description="Generate SLURM scripts for each PXD in a CSV file"
    )
    parser.add_argument(
        "template",
        help="Path to template SLURM file"
    )
    parser.add_argument(
        "pxd_csv",
        help="Path to CSV file with PXD list (first column)"
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output directory for generated SLURM files"
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Submit the generated SLURM files with sbatch after generating them"
    )
    parser.add_argument("--existing-results-root", help="Prior results root containing PXD*/ aggregates or stage outputs (organism-only template)")
    parser.add_argument("--skip-unavailable", action="store_true",
                        help="Explicitly report and skip organism reruns without readable prior inputs")
    parser.add_argument(
        "--batch",
        type=int,
        default=1,
        help="Number of SLURM files to submit per batch (default: 1)"
    )
    parser.add_argument(
        "--dwell",
        type=float,
        default=0,
        help="Seconds to wait between batch submissions (default: 0)"
    )

    args = parser.parse_args()

    if args.batch < 1:
        parser.error("--batch must be >= 1")
    if args.dwell < 0:
        parser.error("--dwell must be >= 0")

    output_files = generate_slurm_files(args.template, args.pxd_csv, args.output,
                                       args.existing_results_root, args.skip_unavailable)

    if args.submit:
        submit_slurm_files(output_files, args.batch, args.dwell)


if __name__ == "__main__":
    main()
