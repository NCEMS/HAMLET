#!/usr/bin/env python3
"""Populate master.csv with PRIDE SDRF availability.

Adds/updates a boolean column `existing_PRIDE_SDRF` by querying:
https://www.ebi.ac.uk/pride/ws/archive/v3/files/sdrf/{accession}

An accession is marked True when the endpoint returns a non-empty JSON list.
Results are checkpointed to a cache CSV to support resume.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update master.csv with existing_PRIDE_SDRF column")
    parser.add_argument("--master-csv", default="master.csv", help="Path to master CSV")
    parser.add_argument(
        "--cache-csv",
        default="src/analysis/Figure1/output/all_master_sdrf_presence.csv",
        help="Checkpoint cache CSV path",
    )
    parser.add_argument("--workers", type=int, default=24, help="Concurrent request workers")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-request timeout seconds")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Requery all accessions even when cache values exist",
    )
    return parser.parse_args()


def _to_bool(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def query_sdrf_presence(accession: str, timeout: float) -> bool:
    url = f"https://www.ebi.ac.uk/pride/ws/archive/v3/files/sdrf/{accession}"
    try:
        resp = requests.get(url, timeout=timeout)
        if not resp.ok:
            return False
        data = resp.json()
        return bool(data)
    except Exception:
        return False


def load_cache(cache_csv: Path) -> dict[str, bool]:
    if not cache_csv.exists():
        return {}
    out: dict[str, bool] = {}
    with cache_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            acc = str(row.get("accession", "")).strip()
            val = _to_bool(row.get("existing_PRIDE_SDRF"))
            if acc and val is not None:
                out[acc] = val
    return out


def save_cache(cache_csv: Path, mapping: dict[str, bool]) -> None:
    cache_csv.parent.mkdir(parents=True, exist_ok=True)
    with cache_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["accession", "existing_PRIDE_SDRF"])
        writer.writeheader()
        for accession in sorted(mapping):
            writer.writerow({"accession": accession, "existing_PRIDE_SDRF": mapping[accession]})


def main() -> None:
    args = parse_args()
    master_path = Path(args.master_csv)
    cache_path = Path(args.cache_csv)

    df = pd.read_csv(master_path)
    if "accession" not in df.columns:
        raise SystemExit(f"Missing required accession column in {master_path}")

    if "existing_PRIDE_SDRF" not in df.columns:
        df["existing_PRIDE_SDRF"] = pd.NA

    accessions = df["accession"].astype(str).str.strip().tolist()

    cache = load_cache(cache_path)

    # Seed from existing master column where parseable.
    for acc, val in zip(accessions, df["existing_PRIDE_SDRF"].tolist()):
        parsed = _to_bool(val)
        if parsed is not None:
            cache.setdefault(acc, parsed)

    if args.refresh:
        todo = [acc for acc in accessions if acc]
    else:
        todo = [acc for acc in accessions if acc and acc not in cache]

    print(f"Total accessions: {len(accessions)}")
    print(f"Cached values: {len(cache)}")
    print(f"To query: {len(todo)}")

    if todo:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(query_sdrf_presence, acc, args.timeout): acc for acc in todo}
            completed = 0
            for future in as_completed(futures):
                acc = futures[future]
                try:
                    cache[acc] = bool(future.result())
                except Exception:
                    cache[acc] = False
                completed += 1
                if completed % 250 == 0:
                    print(f"Completed {completed}/{len(todo)}")
                    save_cache(cache_path, cache)

    # Final checkpoint + master update.
    save_cache(cache_path, cache)

    df["existing_PRIDE_SDRF"] = [cache.get(acc, False) for acc in accessions]
    df.to_csv(master_path, index=False)

    print(f"Updated {master_path} with existing_PRIDE_SDRF")
    print(f"True count: {int(df['existing_PRIDE_SDRF'].sum())}")
    print(f"False count: {int((~df['existing_PRIDE_SDRF']).sum())}")
    print(f"Cache written: {cache_path}")


if __name__ == "__main__":
    main()
