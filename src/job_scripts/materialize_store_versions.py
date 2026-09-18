#!/usr/bin/env python3
"""Materialize immutable per-release SDRF and agentic store directories."""

import argparse
import csv
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-path", type=Path, default=Path("store"))
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--pxd-file", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--source-revision", help="Git revision containing the historical source files")
    source.add_argument("--from-active", action="store_true", help="Copy the current flat active store records")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_pxds(path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    return sorted({row[0].strip() for row in rows if row and row[0].strip().startswith("PXD") and row[0].strip()[3:].isdigit()})


def target_paths(store_path, release_version):
    return (
        store_path / "hamlet_sdrfs" / release_version,
        store_path / "agentic_results_files" / release_version,
    )


def active_sources(store_path, pxds):
    sdrf_root = store_path / "hamlet_sdrfs"
    agentic_root = store_path / "agentic_results_files"
    missing = [pxd for pxd in pxds if not (sdrf_root / f"{pxd}.sdrf.tsv").is_file() or not (agentic_root / pxd).is_dir()]
    if missing:
        raise ValueError("active store is missing {} PXD records: {}".format(len(missing), ", ".join(missing[:10])))
    return sdrf_root, agentic_root


def revision_paths(repo_root, revision, pxds):
    revision = subprocess.check_output(("git", "-C", str(repo_root), "rev-parse", revision), text=True).strip()
    names = subprocess.check_output(
        ("git", "-C", str(repo_root), "ls-tree", "-r", "--name-only", revision, "--", "store/hamlet_sdrfs", "store/agentic_results_files"),
        text=True,
    ).splitlines()
    pxd_set = set(pxds)
    selected = [
        name for name in names
        if any(
            name == f"store/hamlet_sdrfs/{pxd}.sdrf.tsv" or name.startswith(f"store/agentic_results_files/{pxd}/")
            for pxd in pxd_set
        )
    ]
    available_sdrfs = {Path(name).stem.replace(".sdrf", "") for name in selected if name.startswith("store/hamlet_sdrfs/")}
    available_agentic = {Path(name).parts[2] for name in selected if name.startswith("store/agentic_results_files/")}
    missing = sorted(pxd_set - (available_sdrfs & available_agentic))
    if missing:
        raise ValueError("{} is missing {} historical PXD records: {}".format(revision, len(missing), ", ".join(missing[:10])))
    return revision, selected


def extract_revision(repo_root, revision, paths, destination):
    archive_path = destination / "source.tar"
    with archive_path.open("wb") as handle:
        subprocess.run(
            ("git", "-C", str(repo_root), "archive", "--format=tar", revision, "--", *paths),
            check=True,
            stdout=handle,
        )
    with tarfile.open(archive_path) as archive:
        archive.extractall(destination / "source")
    archive_path.unlink()


def materialize_active(store_path, pxds, staged_sdrfs, staged_agentic):
    sdrf_root, agentic_root = active_sources(store_path, pxds)
    for pxd in pxds:
        shutil.copy2(sdrf_root / f"{pxd}.sdrf.tsv", staged_sdrfs / f"{pxd}.sdrf.tsv")
        shutil.copytree(agentic_root / pxd, staged_agentic / pxd)


def materialize_revision(repo_root, revision, paths, pxds, staged_sdrfs, staged_agentic, temporary_root):
    extract_revision(repo_root, revision, paths, temporary_root)
    source_store = temporary_root / "source" / "store"
    for pxd in pxds:
        shutil.copy2(source_store / "hamlet_sdrfs" / f"{pxd}.sdrf.tsv", staged_sdrfs / f"{pxd}.sdrf.tsv")
        shutil.copytree(source_store / "agentic_results_files" / pxd, staged_agentic / pxd)


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    store_path = (repo_root / args.store_path).resolve() if not args.store_path.is_absolute() else args.store_path.resolve()
    pxds = read_pxds(args.pxd_file)
    sdrf_target, agentic_target = target_paths(store_path, args.release_version)
    if sdrf_target.exists() or agentic_target.exists():
        raise SystemExit("version snapshot already exists and is immutable: {}, {}".format(sdrf_target, agentic_target))
    if args.from_active:
        active_sources(store_path, pxds)
        source_description = "active store"
        revision = None
        paths = None
    else:
        try:
            revision, paths = revision_paths(repo_root, args.source_revision, pxds)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            raise SystemExit(str(exc))
        source_description = "Git revision {}".format(revision)
    print("Validated {} PXD records from {}.".format(len(pxds), source_description))
    if args.dry_run:
        return 0

    with tempfile.TemporaryDirectory(dir=str(store_path)) as temporary_directory:
        temporary_root = Path(temporary_directory)
        staged_sdrfs = temporary_root / "hamlet_sdrfs" / args.release_version
        staged_agentic = temporary_root / "agentic_results_files" / args.release_version
        staged_sdrfs.mkdir(parents=True)
        staged_agentic.mkdir(parents=True)
        if args.from_active:
            materialize_active(store_path, pxds, staged_sdrfs, staged_agentic)
        else:
            materialize_revision(repo_root, revision, paths, pxds, staged_sdrfs, staged_agentic, temporary_root)
        staged_sdrfs.rename(sdrf_target)
        staged_agentic.rename(agentic_target)
    print("Materialized {} version snapshots for {}.".format(len(pxds), args.release_version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())