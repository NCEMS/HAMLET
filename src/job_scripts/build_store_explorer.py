#!/usr/bin/env python3
"""Build the static data bundle consumed by the HAMLET Store Explorer."""

import argparse
import json
import shutil
from pathlib import Path


SUPPORTED_SUFFIXES = {".csv", ".json", ".png", ".tsv"}
MAX_PUBLISHED_FILE_BYTES = 1 * 1024 * 1024


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def collect_pxds(store_path: Path, requested_pxds: list[str]) -> list[str]:
    if requested_pxds:
        return sorted(set(requested_pxds))
    aggregate_pxds = {
        path.name.removesuffix("_aggregated_results.json")
        for path in (store_path / "aggregated_results_files").glob("PXD*_aggregated_results.json")
    }
    agentic_dir = store_path / "agentic_results_files"
    agentic_pxds = {path.name for path in agentic_dir.glob("PXD*") if path.is_dir()}
    return sorted(aggregate_pxds | agentic_pxds)


def build_record(store_path: Path, output_data_dir: Path, pxd: str) -> dict:
    record = {"pxd": pxd, "aggregated": None, "agentic": []}
    pxd_data_dir = output_data_dir / pxd
    aggregate = store_path / "aggregated_results_files" / f"{pxd}_aggregated_results.json"
    if aggregate.is_file() and aggregate.stat().st_size <= MAX_PUBLISHED_FILE_BYTES:
        relative_path = Path(pxd) / "aggregated_results.json"
        copy_file(aggregate, output_data_dir / relative_path)
        record["aggregated"] = relative_path.as_posix()

    agentic_source = store_path / "agentic_results_files" / pxd
    if agentic_source.is_dir():
        for source in sorted(agentic_source.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            relative_source = source.relative_to(agentic_source)
            if source.stat().st_size > MAX_PUBLISHED_FILE_BYTES:
                continue
            if aggregate.is_file() and relative_source == Path("metadata_extraction_output") / f"{pxd}_aggregated_results.json":
                continue
            if relative_source.parts[:2] == ("metadata_extraction_output", "post_judge"):
                judge_copy = agentic_source / "judge_output" / Path(*relative_source.parts[2:])
                if judge_copy.is_file():
                    continue
            relative_path = Path(pxd) / "agentic" / relative_source
            copy_file(source, output_data_dir / relative_path)
            record["agentic"].append(relative_path.as_posix())

    if not record["aggregated"] and not record["agentic"]:
        shutil.rmtree(pxd_data_dir, ignore_errors=True)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("store"))
    parser.add_argument("--site-dir", type=Path, default=Path("docs/store-explorer"))
    parser.add_argument("--pxd", action="append", default=[], help="Build only one PXD; repeatable")
    args = parser.parse_args()

    output_data_dir = args.site_dir / "data"
    shutil.rmtree(output_data_dir, ignore_errors=True)
    output_data_dir.mkdir(parents=True)

    records = [build_record(args.store, output_data_dir, pxd) for pxd in collect_pxds(args.store, args.pxd)]
    records = [record for record in records if record["aggregated"] or record["agentic"]]
    (output_data_dir / "store-index.json").write_text(
        json.dumps({"pxds": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built Store Explorer data for {len(records)} PXDs in {output_data_dir}")


if __name__ == "__main__":
    main()