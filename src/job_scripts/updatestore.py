#!/usr/bin/env python3
"""Promote completed agentic result bundles into the versioned HAMLET store."""

import argparse
import csv
import hashlib
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path


REQUIRED_RESULT_FILES = (
    "agentic_metadata/{pxd}.sdrf.tsv",
    "agentic_metadata/{pxd}.confidence.sdrf.tsv",
)
OPTIONAL_RESULT_FILES = (
    "llm_refinement_judge/llm_judge_per_paper.csv",
    "sdrf_judge/llm_judge_per_paper.csv",
)
RELEASE_VERSION_PATTERN = re.compile(r"v\d+\.\d+\.\d+$")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_path", type=Path, help="Completed agentic result directory")
    parser.add_argument("store_path", type=Path, help="HAMLET durable store root")
    parser.add_argument("--release-version", required=True, help="Release to promote, for example v2.1.1")
    promotion_mode = parser.add_mutually_exclusive_group()
    promotion_mode.add_argument(
        "--in-progress",
        action="store_true",
        help="Promote only complete PXD bundles into a mutable version snapshot without creating a release manifest",
    )
    promotion_mode.add_argument(
        "--finalize-in-progress",
        action="store_true",
        help="Seal a complete mutable version snapshot into an immutable release manifest",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate without changing the store")
    return parser.parse_args()


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remove_existing_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def release_annotation(release_version):
    return "HAMLET-agentic {}".format(release_version)


def versioned_paths(store_path, release_version, pxd):
    return (
        store_path / "hamlet_sdrfs" / release_version / "{}.sdrf.tsv".format(pxd),
        store_path / "agentic_results_files" / release_version / pxd,
        store_path / "aggregated_results_files" / release_version / "{}_aggregated_results.json".format(pxd),
    )


def result_artifacts(results_path, pxd, require_final_judge=False):
    result_dir = results_path / pxd
    artifacts = {
        template.format(pxd=pxd): result_dir / template.format(pxd=pxd)
        for template in REQUIRED_RESULT_FILES
    }
    missing = [path for path in artifacts.values() if not path.is_file() or not path.stat().st_size]
    if missing:
        raise ValueError("{} is missing: {}".format(pxd, ", ".join(map(str, missing))))
    artifacts.update(
        {
            template.format(pxd=pxd): result_dir / template.format(pxd=pxd)
            for template in OPTIONAL_RESULT_FILES
            if (result_dir / template.format(pxd=pxd)).is_file()
            and (result_dir / template.format(pxd=pxd)).stat().st_size
        }
    )
    final_judge = "sdrf_judge/llm_judge_per_paper.csv"
    if require_final_judge and final_judge not in artifacts:
        raise ValueError("{} is missing: {}".format(pxd, result_dir / final_judge))
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


def promotion_plan(
    results_path,
    store_path,
    release_version,
    allow_incomplete=False,
    allow_existing=False,
    require_final_judge=False,
):
    if not results_path.is_dir():
        raise ValueError("results path not found: {}".format(results_path))
    if not store_path.is_dir():
        raise ValueError("store path not found: {}".format(store_path))
    if not RELEASE_VERSION_PATTERN.fullmatch(release_version):
        raise ValueError("release version must use v<major>.<minor>.<patch>: {}".format(release_version))
    release_dir = store_path / "releases" / release_version
    if release_dir.exists() and not allow_incomplete:
        raise ValueError("release is already immutable: {}".format(release_dir))
    versioned_sdrfs, versioned_agentic, versioned_aggregates = versioned_paths(store_path, release_version, "PXD000000")
    versioned_directories = (versioned_sdrfs.parent, versioned_agentic.parent, versioned_aggregates.parent)
    if not allow_existing and any(path.exists() for path in versioned_directories):
        raise ValueError("release artifact directories are already immutable: {}".format(
            ", ".join(map(str, versioned_directories))
        ))
    records = []
    incomplete = []
    for result_dir in sorted(results_path.glob("PXD*")):
        if not result_dir.is_dir():
            continue
        pxd = result_dir.name
        try:
            artifacts = result_artifacts(results_path, pxd, require_final_judge=require_final_judge)
        except ValueError:
            if allow_incomplete:
                incomplete.append(pxd)
                continue
            raise
        source_sdrf = artifacts["agentic_metadata/{}.sdrf.tsv".format(pxd)]
        source_aggregate = store_path / "aggregated_results_files" / "{}_aggregated_results.json".format(pxd)
        if not source_aggregate.is_file() or not source_aggregate.stat().st_size:
            raise ValueError("{} is missing aggregate source: {}".format(pxd, source_aggregate))
        release_sdrf, release_agentic, release_aggregate = versioned_paths(store_path, release_version, pxd)
        existing = (release_sdrf.exists(), release_agentic.exists(), release_aggregate.exists())
        if any(existing):
            if not allow_existing or not all(existing):
                raise ValueError("{} has a partial or immutable release snapshot".format(pxd))
        records.append(
            {
                "pxd": pxd,
                "result_dir": result_dir,
                "artifacts": artifacts,
                "aggregate_source": source_aggregate,
                "source_sdrf_sha256": sha256(source_sdrf),
                "source_aggregate_sha256": sha256(source_aggregate),
                "existing_snapshot": all(existing),
            }
        )
    if not records:
        if allow_incomplete:
            raise ValueError("no new complete PXD bundles found under {}".format(results_path))
        raise ValueError("no PXD result directories found under {}".format(results_path))
    return records, incomplete


def promote_record(record, store_path, annotation):
    pxd = record["pxd"]
    release_version = annotation.removeprefix("HAMLET-agentic ")
    release_sdrf, release_agentic, release_aggregate = versioned_paths(store_path, release_version, pxd)
    release_agentic.parent.mkdir(parents=True, exist_ok=True)
    release_sdrf.parent.mkdir(parents=True, exist_ok=True)
    release_aggregate.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(store_path)) as temporary_directory:
        staging_root = Path(temporary_directory)
        staged_agentic = staging_root / "agentic"
        staged_sdrf = staging_root / release_sdrf.name
        staged_aggregate = staging_root / release_aggregate.name
        shutil.copytree(record["result_dir"] / "agentic_metadata", staged_agentic)
        for judge_directory in ("llm_refinement_judge", "sdrf_judge"):
            if "{}/llm_judge_per_paper.csv".format(judge_directory) in record["artifacts"]:
                shutil.copytree(record["result_dir"] / judge_directory, staged_agentic / judge_directory)
        source_annotations = stamp_sdrf_annotation(
            record["artifacts"]["agentic_metadata/{}.sdrf.tsv".format(pxd)], staged_sdrf, annotation
        )
        shutil.copy2(staged_sdrf, staged_agentic / staged_sdrf.name)
        shutil.copy2(record["aggregate_source"], staged_aggregate)
        staged_agentic.rename(release_agentic)
        staged_sdrf.replace(release_sdrf)
        staged_aggregate.replace(release_aggregate)
    return release_record(record, store_path, annotation)


def release_record(record, store_path, annotation):
    pxd = record["pxd"]
    release_version = annotation.removeprefix("HAMLET-agentic ")
    release_sdrf, release_agentic, release_aggregate = versioned_paths(store_path, release_version, pxd)
    if not release_sdrf.is_file() or not release_agentic.is_dir() or not release_aggregate.is_file():
        raise ValueError("{} has an incomplete release snapshot".format(pxd))
    with record["artifacts"]["agentic_metadata/{}.sdrf.tsv".format(pxd)].open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.reader(source, delimiter="\t"))
    annotation_index = rows[0].index("comment[sdrf annotation tool]")
    source_annotations = sorted({row[annotation_index] for row in rows[1:]})
    return {
        "pxd": pxd,
        "source_sdrf_sha256": record["source_sdrf_sha256"],
        "source_aggregate_sha256": record["source_aggregate_sha256"],
        "source_annotation_values": source_annotations,
        "release_annotation_value": annotation,
        "archive": {
            "sdrf_path": str(release_sdrf.relative_to(store_path)),
            "sdrf_sha256": sha256(release_sdrf),
            "agentic_path": str(release_agentic.relative_to(store_path)),
            "aggregate_path": str(release_aggregate.relative_to(store_path)),
            "aggregate_sha256": sha256(release_aggregate),
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
        "versioned_store_paths": {
            "sdrfs": "hamlet_sdrfs/{}".format(release_version),
            "agentic_results": "agentic_results_files/{}".format(release_version),
            "aggregated_results": "aggregated_results_files/{}".format(release_version),
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
        records, incomplete = promotion_plan(
            args.results_path.resolve(),
            args.store_path.resolve(),
            args.release_version,
            allow_incomplete=args.in_progress,
            allow_existing=args.in_progress or args.finalize_in_progress,
            require_final_judge=args.in_progress or args.finalize_in_progress,
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    mode = "complete" if not args.in_progress else "complete"
    print("Validated {} {} PXD result bundles for {}.".format(len(records), mode, args.release_version))
    if incomplete:
        print("Skipped {} incomplete PXD bundles.".format(len(incomplete)))
    if args.dry_run:
        return 0
    store_path = args.store_path.resolve()
    promoted = {
        record["pxd"]: promote_record(record, store_path, release_annotation(args.release_version))
        for record in records
        if not record["existing_snapshot"]
    }
    if args.in_progress:
        print("Promoted {} PXD bundles into mutable store snapshot {}.".format(len(promoted), args.release_version))
        return 0
    manifest_records = [
        promoted.get(record["pxd"], release_record(record, store_path, release_annotation(args.release_version)))
        for record in records
    ]
    write_release_manifest(store_path, args.results_path.resolve(), args.release_version, manifest_records)
    print("Promoted {} new PXDs into store release {}.".format(len(promoted), args.release_version))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


