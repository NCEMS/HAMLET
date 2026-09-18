#!/usr/bin/env python3
"""Promote completed agentic SDRFs into the active HAMLET store by release."""

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path


REQUIRED_RESULT_FILES = (
    "agentic_metadata/{pxd}.sdrf.tsv",
    "agentic_metadata/{pxd}.confidence.sdrf.tsv",
    "judge_output/llm_judge_per_paper.csv",
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_path", type=Path, help="Completed agentic result directory")
    parser.add_argument("store_path", type=Path, help="HAMLET durable store root")
    parser.add_argument("--release-version", required=True, help="Release to promote, for example v2.1.1")
    parser.add_argument("--dry-run", action="store_true", help="Validate without changing the store")
    return parser.parse_args()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_annotation(release_version):
    return "HAMLET-agentic {}".format(release_version)


def versioned_paths(store_path, release_version, pxd):
    return (
        store_path / "hamlet_sdrfs" / release_version / "{}.sdrf.tsv".format(pxd),
        store_path / "agentic_results_files" / release_version / pxd,
    )


def result_artifacts(results_path, pxd):
    result_dir = results_path / pxd
    artifacts = {
        template.format(pxd=pxd): result_dir / template.format(pxd=pxd)
        for template in REQUIRED_RESULT_FILES
    }
    missing = [path for path in artifacts.values() if not path.is_file() or not path.stat().st_size]
    if missing:
        raise ValueError("{} is missing: {}".format(pxd, ", ".join(map(str, missing))))
    return artifacts


def stamp_sdrf_annotation(source_path, destination_path, annotation):
    with source_path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source, delimiter="\t"))
    if len(rows) < 2:
        raise ValueError("SDRF has no data rows: {}".format(source_path))
    if any(len(row) != len(rows[0]) for row in rows[1:]):
        raise ValueError("SDRF has inconsistent columns: {}".format(source_path))
    try:
        annotation_index = rows[0].index("comment[sdrf annotation tool]")
    except ValueError as exc:
        raise ValueError("SDRF has no annotation-tool column: {}".format(source_path)) from exc
    original_annotations = sorted({row[annotation_index] for row in rows[1:]})
    for row in rows[1:]:
        row[annotation_index] = annotation
    with destination_path.open("w", encoding="utf-8", newline="") as destination:
        csv.writer(destination, delimiter="\t", lineterminator="\n").writerows(rows)
    return original_annotations


def promotion_plan(results_path, store_path, release_version):
    if not results_path.is_dir():
        raise ValueError("results path not found: {}".format(results_path))
    if not store_path.is_dir():
        raise ValueError("store path not found: {}".format(store_path))
    release_dir = store_path / "releases" / release_version
    if release_dir.exists():
        raise ValueError("release is already immutable: {}".format(release_dir))
    versioned_sdrfs, versioned_agentic = versioned_paths(store_path, release_version, "PXD000000")
    if versioned_sdrfs.parent.exists() or versioned_agentic.parent.exists():
        raise ValueError("release artifact directories are already immutable: {}, {}".format(
            versioned_sdrfs.parent, versioned_agentic.parent
        ))
    records = []
    for result_dir in sorted(results_path.glob("PXD*")):
        if not result_dir.is_dir():
            continue
        pxd = result_dir.name
        artifacts = result_artifacts(results_path, pxd)
        source_sdrf = artifacts["agentic_metadata/{}.sdrf.tsv".format(pxd)]
        active_sdrf = store_path / "hamlet_sdrfs" / "{}.sdrf.tsv".format(pxd)
        records.append(
            {
                "pxd": pxd,
                "result_dir": result_dir,
                "artifacts": artifacts,
                "source_sdrf_sha256": sha256(source_sdrf),
                "previous_active_sdrf_sha256": sha256(active_sdrf) if active_sdrf.is_file() else None,
            }
        )
    if not records:
        raise ValueError("no PXD result directories found under {}".format(results_path))
    return records


def promote_record(record, store_path, annotation):
    pxd = record["pxd"]
    active_agentic = store_path / "agentic_results_files" / pxd
    active_sdrf = store_path / "hamlet_sdrfs" / "{}.sdrf.tsv".format(pxd)
    release_version = annotation.removeprefix("HAMLET-agentic ")
    release_sdrf, release_agentic = versioned_paths(store_path, release_version, pxd)
    active_agentic.parent.mkdir(parents=True, exist_ok=True)
    active_sdrf.parent.mkdir(parents=True, exist_ok=True)
    release_agentic.parent.mkdir(parents=True, exist_ok=True)
    release_sdrf.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(store_path)) as temporary_directory:
        staging_root = Path(temporary_directory)
        staged_agentic = staging_root / "agentic"
        staged_sdrf = staging_root / active_sdrf.name
        shutil.copytree(record["result_dir"] / "agentic_metadata", staged_agentic)
        shutil.copytree(record["result_dir"] / "judge_output", staged_agentic / "judge_output")
        source_annotations = stamp_sdrf_annotation(
            record["artifacts"]["agentic_metadata/{}.sdrf.tsv".format(pxd)], staged_sdrf, annotation
        )
        shutil.copy2(staged_sdrf, staged_agentic / staged_sdrf.name)
        staged_agentic.rename(release_agentic)
        staged_sdrf.replace(release_sdrf)
        if active_agentic.exists():
            shutil.rmtree(active_agentic)
        shutil.copytree(release_agentic, active_agentic)
        shutil.copy2(release_sdrf, active_sdrf)
    return {
        "pxd": pxd,
        "source_sdrf_sha256": record["source_sdrf_sha256"],
        "active_sdrf_sha256": sha256(active_sdrf),
        "previous_active_sdrf_sha256": record["previous_active_sdrf_sha256"],
        "source_annotation_values": source_annotations,
        "active_annotation_value": annotation,
        "archive": {
            "sdrf_path": str(release_sdrf.relative_to(store_path)),
            "sdrf_sha256": sha256(release_sdrf),
            "agentic_path": str(release_agentic.relative_to(store_path)),
        },
        "artifacts": [
            {
                "source_path": str(path.relative_to(record["result_dir"].parents[1])),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in record["artifacts"].values()
        ],
    }


def write_release_manifest(store_path, results_path, release_version, records):
    releases_dir = store_path / "releases"
    release_dir = releases_dir / release_version
    release_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "release_version": release_version,
        "promoted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "results_path": str(results_path),
        "active_store_paths": {"sdrfs": "hamlet_sdrfs", "agentic_results": "agentic_results_files"},
        "versioned_store_paths": {
            "sdrfs": "hamlet_sdrfs/{}".format(release_version),
            "agentic_results": "agentic_results_files/{}".format(release_version),
        },
        "pxds": records,
    }
    (release_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    active_path = releases_dir / "active.json"
    active = json.loads(active_path.read_text(encoding="utf-8")) if active_path.is_file() else {"schema_version": 1, "pxds": {}}
    active["pxds"].update({record["pxd"]: release_version for record in records})
    active_path.write_text(json.dumps(active, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    try:
        records = promotion_plan(args.results_path.resolve(), args.store_path.resolve(), args.release_version)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print("Validated {} PXD result bundles for {}.".format(len(records), args.release_version))
    if args.dry_run:
        return 0
    promoted = [promote_record(record, args.store_path.resolve(), release_annotation(args.release_version)) for record in records]
    write_release_manifest(args.store_path.resolve(), args.results_path.resolve(), args.release_version, promoted)
    print("Promoted {} PXDs into store release {}.".format(len(promoted), args.release_version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


