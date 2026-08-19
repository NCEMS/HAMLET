#!/usr/bin/env python3
"""Backfill empty aggregate PRIDE metadata from the local PRIDE cache."""

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
AGGREGATES_DIR = REPO_ROOT / "store" / "aggregated_results_files"
PRIDE_CACHE = REPO_ROOT / "pride_survey" / "pride_cache"


def normalized_pride_metadata(cache_record: dict) -> dict:
    """Match the project/files wrapper used by populated aggregate records."""
    return {
        "project": {key: value for key, value in cache_record.items() if key != "files"},
        "files": cache_record.get("files", []),
    }


def main() -> None:
    with PRIDE_CACHE.open(encoding="utf-8") as handle:
        records = json.load(handle)["response"]
    by_accession = {record["accession"]: record for record in records}

    changed = []
    for path in sorted(AGGREGATES_DIR.glob("*_aggregated_results.json")):
        with path.open(encoding="utf-8") as handle:
            aggregate = json.load(handle)
        if aggregate.get("pride_metadata") != {}:
            continue

        pxd = aggregate["pxd_id"]
        cache_record = by_accession.get(pxd)
        if cache_record is None:
            raise KeyError(f"PRIDE cache has no record for {pxd}")
        aggregate["pride_metadata"] = normalized_pride_metadata(cache_record)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(aggregate, handle, indent=2)
            handle.write("\n")
        changed.append(pxd)

    print(f"Backfilled PRIDE metadata for {len(changed)} aggregate records")


if __name__ == "__main__":
    main()