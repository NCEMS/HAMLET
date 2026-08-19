#!/usr/bin/env python3
"""Build the static data bundle consumed by the HAMLET Store Explorer."""

import argparse
import json
import re
import shutil
from pathlib import Path


SUPPORTED_SUFFIXES = {".csv", ".json", ".png", ".tsv"}
MAX_PUBLISHED_FILE_BYTES = 1 * 1024 * 1024
RELEASE_VERSION_PATTERN = re.compile(r'"pipeline_version"\s*:\s*"(v\d+\.\d+\.\d+)"')
HAMLET_VERSION_PATTERN = re.compile(r'HAMLET_VERSION\s*=\s*"(v\d+\.\d+\.\d+)"')
HAMLET_VERSION_FILE = Path(__file__).resolve().parents[1] / "python" / "hamlet_version.py"


def canonical_hamlet_version() -> str:
    match = HAMLET_VERSION_PATTERN.search(HAMLET_VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Could not read HAMLET_VERSION from {HAMLET_VERSION_FILE}")
    return match.group(1)


CURRENT_SCHEMA_VERSION = canonical_hamlet_version()
LEGACY_SCHEMA_VERSION = "v2.0.0"


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def release_version(aggregate: Path, agentic_source: Path, pxd: str) -> str | None:
    current_schema = {
        f"{pxd}.sdrf.tsv",
        f"{pxd}.confidence.sdrf.tsv",
        "metadata_extraction_output",
        "judge_output",
    }
    if agentic_source.is_dir() and current_schema <= {path.name for path in agentic_source.iterdir()}:
        return CURRENT_SCHEMA_VERSION
    if not aggregate.is_file():
        return None
    versions = RELEASE_VERSION_PATTERN.findall(aggregate.read_text(encoding="utf-8", errors="replace"))
    return versions[-1] if versions else LEGACY_SCHEMA_VERSION


def read_pxd_file(path: Path) -> list[str]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and line != "PXDs"]


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
    record = {"pxd": pxd, "version": None, "available": False, "aggregated": None, "agentic": []}
    pxd_data_dir = output_data_dir / pxd
    aggregate = store_path / "aggregated_results_files" / f"{pxd}_aggregated_results.json"
    agentic_source = store_path / "agentic_results_files" / pxd
    record["version"] = release_version(aggregate, agentic_source, pxd)
    record["available"] = aggregate.is_file()
    if aggregate.is_file() and aggregate.stat().st_size <= MAX_PUBLISHED_FILE_BYTES:
        relative_path = Path(pxd) / "aggregated_results.json"
        copy_file(aggregate, output_data_dir / relative_path)
        record["aggregated"] = relative_path.as_posix()

    if agentic_source.is_dir():
        record["available"] = True
        for source in sorted(agentic_source.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            relative_source = source.relative_to(agentic_source)
            if source.stat().st_size > MAX_PUBLISHED_FILE_BYTES:
                continue
            if aggregate.is_file() and relative_source == Path("metadata_extraction_output") / f"{pxd}_aggregated_results.json":
                continue
            if relative_source.parts[:1] == ("judge_output",):
                post_judge_copy = agentic_source / "metadata_extraction_output" / "post_judge" / Path(*relative_source.parts[1:])
                if post_judge_copy.is_file():
                    continue
            relative_path = Path(pxd) / "agentic" / relative_source
            copy_file(source, output_data_dir / relative_path)
            record["agentic"].append(relative_path.as_posix())

    if not record["available"]:
        shutil.rmtree(pxd_data_dir, ignore_errors=True)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("store"))
    parser.add_argument("--site-dir", type=Path, default=Path("docs/store-explorer"))
    parser.add_argument("--pxd", action="append", default=[], help="Build only one PXD; repeatable")
    parser.add_argument("--pxd-file", type=Path, help="Build the PXDs listed in a one-column CSV file")
    args = parser.parse_args()

    output_data_dir = args.site_dir / "data"
    shutil.rmtree(output_data_dir, ignore_errors=True)
    output_data_dir.mkdir(parents=True)

    requested_pxds = [*args.pxd, *(read_pxd_file(args.pxd_file) if args.pxd_file else [])]
    records = [build_record(args.store, output_data_dir, pxd) for pxd in collect_pxds(args.store, requested_pxds)]
    records = [record for record in records if record["available"]]
    (output_data_dir / "store-index.json").write_text(
        json.dumps({"pxds": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Built Store Explorer data for {len(records)} PXDs in {output_data_dir}")


if __name__ == "__main__":
    main()