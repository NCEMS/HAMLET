"""Merge listed archive JSONs into a ROAR-enriched CSV without extracting files."""

import argparse
import csv
import gzip
import json
import os
import re
import tarfile
import tempfile
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from pathlib import Path


SECTIONS = (
    "runAssessor",
    "organism_identification.results",
    "PTM-shepherd_open_search",
    "modification_site_fractions",
)
PATH_COLUMN = "aggregated_results_json_path"


def member_key(path):
    parts = [part for part in path.split("/") if part not in ("", ".")]
    if ".." in parts:
        raise ValueError("Parent traversal in listed/member path: " + path)
    for index, part in enumerate(parts):
        if part in ("HAMLETruns", "results", "store", "work"):
            return "/".join(parts[index:])
    return "/".join(parts)


def pxd_from_path(path):
    ids = set(re.findall(r"PXD\d+", path))
    if len(ids) != 1:
        raise ValueError("Expected exactly one PXD in " + path)
    return next(iter(ids))


def section_values(data, location, pxd):
    if not isinstance(data, dict):
        raise ValueError("JSON root is not an object: " + location)
    if data.get("pxd_id") not in (None, pxd):
        raise ValueError("PXD mismatch: " + location)
    values = {}
    for section in SECTIONS:
        value = data
        for part in section.split("."):
            if value is None:
                break
            if not isinstance(value, dict):
                raise ValueError("Invalid parent for {} in {}".format(section, location))
            value = value.get(part)
        values[section] = str(bool(value))
    return values


@contextmanager
def open_tar(path):
    with open(path, "rb") as raw:
        if str(path).endswith((".tar.gz", ".tgz")):
            with gzip.GzipFile(fileobj=raw) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as archive:
                    yield archive
        elif str(path).endswith((".tar.zst", ".tzst")):
            try:
                import zstandard
            except ImportError as exc:
                raise RuntimeError(
                    "Zstandard archives require: python3 -m pip install zstandard"
                ) from exc
            with zstandard.ZstdDecompressor().stream_reader(raw) as stream:
                with tarfile.open(fileobj=stream, mode="r|") as archive:
                    yield archive
        elif str(path).endswith(".tar"):
            with tarfile.open(fileobj=raw, mode="r|") as archive:
                yield archive
        else:
            raise ValueError("Unsupported archive extension: " + str(path))


def scan_archive(job):
    archive_path, list_path, accessions, baseline_ranks = job
    expected = {}
    with open(list_path) as handle:
        for line in handle:
            entry = line.strip()
            if entry:
                pxd = pxd_from_path(entry)
                if pxd in accessions:
                    expected[member_key(entry)] = pxd
    print("Scanning {}: {} relevant listed paths".format(
        archive_path, len(expected)), flush=True)
    selected = {}
    matched = set()
    with open_tar(archive_path) as archive:
        for member in archive:
            # Avoid retaining every TarInfo in very large archives.
            archive.members.clear()
            if not member.isfile():
                continue
            key = member_key(member.name)
            if key not in expected:
                continue
            matched.add(key)
            pxd = expected[key]
            location = "{}::{}".format(archive_path, member.name)
            rank = (member.size, int(member.mtime * 1e9), location)
            previous = selected[pxd][0] if pxd in selected else baseline_ranks.get(pxd)
            if previous is not None and rank <= previous:
                continue
            with archive.extractfile(member) as handle:
                data = json.load(handle)
            values = section_values(data, location, pxd)
            selected[pxd] = (rank, dict(values, **{PATH_COLUMN: location}))
    missing = set(expected) - matched
    print("Finished {}: {} listed paths matched, {} unmatched, {} candidate PXDs".format(
        archive_path, len(matched), len(missing), len(selected)), flush=True)
    if missing:
        print("WARNING: unmatched listed paths in {} (first 5): {}".format(
            archive_path, ", ".join(sorted(missing)[:5])), flush=True)
    return selected


def enrich(input_path, output_path, archives, workers):
    input_path, output_path = Path(input_path), Path(output_path)
    if output_path.exists():
        raise FileExistsError("Refusing to overwrite " + str(output_path))
    with input_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        rows = list(reader)
    required = {"accession", PATH_COLUMN}.union(SECTIONS)
    if not columns or not required.issubset(columns):
        raise ValueError("Input CSV must contain accession and the five ROAR columns")
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("Malformed CSV row")
    accessions = {row["accession"] for row in rows}
    jobs = []
    for archive_path, list_path in archives:
        archive_path = str(Path(archive_path).resolve(strict=True))
        list_path = str(Path(list_path).resolve(strict=True))
        with open_tar(archive_path) as archive:
            archive.next()
        jobs.append((archive_path, list_path))
    selected = {}
    for row in rows:
        location = row[PATH_COLUMN]
        if not location:
            continue
        if "::" in location:
            raise ValueError("Input must be the original ROAR-enriched CSV, not archive output")
        stat = Path(location).stat()
        rank = (stat.st_size, stat.st_mtime_ns, location)
        pxd = row["accession"]
        if pxd_from_path(location) != pxd:
            raise ValueError("CSV accession/path mismatch: " + location)
        if pxd not in selected or rank > selected[pxd][0]:
            with open(location) as handle:
                values = section_values(json.load(handle), location, pxd)
            selected[pxd] = (rank, dict(values, **{PATH_COLUMN: location}))
    baseline_ranks = {pxd: entry[0] for pxd, entry in selected.items()}
    jobs = [(archive_path, list_path, accessions, baseline_ranks)
            for archive_path, list_path in jobs]
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
        for candidates in pool.map(scan_archive, jobs):
            for pxd, candidate in candidates.items():
                if pxd not in selected or candidate[0] > selected[pxd][0]:
                    selected[pxd] = candidate
    updated = []
    for row in rows:
        updated.append(dict(row, **selected[row["accession"]][1])
                       if row["accession"] in selected else dict(row))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", newline="", dir=str(output_path.parent),
                prefix=output_path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = handle.name
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(updated)
        with open(temporary, newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns or list(reader) != updated:
                raise ValueError("Output CSV verification failed")
        os.link(temporary, str(output_path))
    finally:
        if temporary is not None:
            os.unlink(temporary)
    print("Wrote {} rows; {} unique PXDs with selected JSONs".format(
        len(updated), len(selected)), flush=True)
    print("Section | Nonempty PXDs | Empty/null/missing PXDs", flush=True)
    for section in SECTIONS:
        count = sum(values[section] == "True" for _, values in selected.values())
        print("{} | {} | {}".format(section, count, len(selected) - count), flush=True)
    print("All four nonempty:", sum(
        all(values[section] == "True" for section in SECTIONS)
        for _, values in selected.values()), flush=True)
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="Original ROAR-enriched CSV")
    parser.add_argument("--output", required=True, help="New CSV; must not exist")
    parser.add_argument("--archive", nargs=2, action="append", required=True,
                        metavar=("TARBALL", "FILE_LIST"))
    parser.add_argument("--workers", type=int, default=3, help="Concurrent archives (default: 3)")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    enrich(args.csv, args.output, args.archive, args.workers)


if __name__ == "__main__":
    main()
