#!/usr/bin/env python3
"""Freeze the approved HAMLET v2.1.0 SDRF QC cohort as versioned fixtures."""

import argparse
import csv
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


COHORT = (
    ("PXD003544", "None found"),
    ("PXD034594", "None found"),
    ("PXD005048", "None found"),
    ("PXD032144", "None found"),
    ("PXD044188", "Acquisition-method hallucination"),
    ("PXD033196", "None found"),
    ("PXD073162", "Modification hallucination"),
    ("PXD024054", "None found"),
    ("PXD072078", "Modification hallucination"),
    ("PXD001454", "Modification hallucination"),
    ("PXD030978", "None found"),
    ("PXD015445", "Modification hallucination"),
    ("PXD001805", "Modification type mismatch"),
    ("PXD038818", "Modification hallucination and type mismatch"),
    ("PXD036708", "Modification hallucination"),
    ("PXD008215", "Modification hallucination"),
    ("PXD014472", "Acquisition-method and modification hallucinations"),
    ("PXD032738", "Modification hallucination and type mismatch"),
    ("PXD020418", "None found"),
    ("PXD015800", "None found"),
    ("PXD025590", "Modification hallucination and type mismatch"),
    ("PXD004802", "Modification hallucination"),
    ("PXD009266", "Modification hallucination"),
    ("PXD030847", "Modification hallucination"),
    ("PXD011237", "None found"),
    ("PXD037474", "None found"),
    ("PXD004997", "Modification hallucination"),
    ("PXD037990", "Modification hallucination"),
    ("PXD059345", "Modification hallucination"),
    ("PXD018851", "Modification hallucination and type mismatch"),
)

FIXTURE_VERSION = "v2.1.0"
JUDGE_ARTIFACTS = (
    "llm_judge_per_paper.csv",
    "llm_judge_annotation_review.csv",
    "json_outputs/{pxd}.json",
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-dir", type=Path, default=Path("store"))
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("tests/fixtures/sdrf_qc") / FIXTURE_VERSION,
    )
    parser.add_argument(
        "--fixture-date",
        required=True,
        help="Approved fixture date in YYYY-MM-DD form; required for reproducible manifests.",
    )
    parser.add_argument(
        "--parent-commit",
        default=None,
        help="Parent repository commit recorded as fixture-creation context.",
    )
    parser.add_argument(
        "--source-revision",
        default="HEAD",
        help="Git revision containing the approved source artifacts (default: HEAD).",
    )
    parser.add_argument(
        "--agentic-metadata-gitlink",
        default=None,
        help="Tracked agentic-metadata Gitlink recorded as fixture-creation context.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the approved source artifacts without writing fixtures.",
    )
    return parser.parse_args()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(repo_root, *arguments):
    try:
        return subprocess.check_output(
            ("git", "-C", str(repo_root), *arguments), text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _read_source_artifact(repo_root, source_path, source_revision):
    source_relative = source_path.relative_to(repo_root).as_posix()
    completed = subprocess.run(
        ("git", "-C", str(repo_root), "show", "{}:{}".format(source_revision, source_relative)),
        capture_output=True,
    )
    if completed.returncode:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            "{} is unavailable at {}: {}".format(
                source_relative, source_revision, message
            )
        )
    return completed.stdout


def _source_artifacts(repo_root, store_dir, pxd, source_revision):
    result_root = store_dir / "agentic_results_files" / pxd
    post_judge = result_root / "metadata_extraction_output" / "post_judge"
    paths = {
        "{}.sdrf.tsv".format(pxd): store_dir / "hamlet_sdrfs" / "{}.sdrf.tsv".format(pxd),
        "{}.confidence.sdrf.tsv".format(pxd): result_root / "{}.confidence.sdrf.tsv".format(pxd),
    }
    for template in JUDGE_ARTIFACTS:
        relative_path = template.format(pxd=pxd)
        paths["post_judge/{}".format(relative_path)] = post_judge / relative_path

    for path in paths.values():
        _read_source_artifact(repo_root, path, source_revision)
    return paths


def _baseline_metrics(per_paper_path, pxd):
    with per_paper_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1 or rows[0].get("paper_id") != pxd:
        raise ValueError("{} has no unambiguous final post-judge metric row".format(pxd))

    metrics = {}
    for key, value in rows[0].items():
        if key in {"paper_id", "source", "mode"}:
            metrics[key] = value
        elif key == "total_extracted" or key.startswith("judge_n_"):
            metrics[key] = int(value)
        elif key.startswith("judge_accuracy"):
            metrics[key] = float(value)
        else:
            metrics[key] = value
    return metrics


def _baseline_metrics_from_bytes(content, pxd):
    with io.StringIO(content.decode("utf-8"), newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1 or rows[0].get("paper_id") != pxd:
        raise ValueError("{} has no unambiguous final post-judge metric row".format(pxd))
    return _baseline_metrics_from_row(rows[0])


def _baseline_metrics_from_row(row):
    metrics = {}
    for key, value in row.items():
        if key in {"paper_id", "source", "mode"}:
            metrics[key] = value
        elif key == "total_extracted" or key.startswith("judge_n_"):
            metrics[key] = int(value)
        elif key.startswith("judge_accuracy"):
            metrics[key] = float(value)
        else:
            metrics[key] = value
    return metrics


def _manifest_artifacts(repo_root, source_artifacts, fixture_dir):
    artifacts = []
    combined = hashlib.sha256()
    for relative_path in sorted(source_artifacts):
        source_path = source_artifacts[relative_path]
        fixture_path = fixture_dir / relative_path
        digest = _sha256(fixture_path)
        byte_count = fixture_path.stat().st_size
        combined.update(relative_path.encode("utf-8"))
        combined.update(b"\0")
        combined.update(digest.encode("ascii"))
        combined.update(b"\n")
        artifacts.append(
            {
                "fixture_path": relative_path,
                "source_path": str(source_path.relative_to(repo_root)),
                "bytes": byte_count,
                "sha256": digest,
            }
        )
    return artifacts, combined.hexdigest()


def _copy_fixture(repo_root, source_artifacts, source_revision, target_dir):
    for relative_path, source_path in source_artifacts.items():
        target_path = target_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(
            _read_source_artifact(repo_root, source_path, source_revision)
        )


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    store_dir = (repo_root / args.store_dir).resolve() if not args.store_dir.is_absolute() else args.store_dir.resolve()
    output_root = (repo_root / args.output_root).resolve() if not args.output_root.is_absolute() else args.output_root.resolve()
    if not args.fixture_date or len(args.fixture_date) != 10:
        raise SystemExit("--fixture-date must use YYYY-MM-DD form")
    if output_root.exists() and not args.dry_run:
        raise SystemExit("fixture output already exists and is immutable: {}".format(output_root))

    parent_commit = args.parent_commit or _git_output(repo_root, "rev-parse", "HEAD")
    source_revision = _git_output(repo_root, "rev-parse", args.source_revision)
    agentic_metadata_gitlink = args.agentic_metadata_gitlink or _git_output(
        repo_root, "rev-parse", "HEAD:src/agentic-metadata"
    )
    if not parent_commit or not source_revision or not agentic_metadata_gitlink:
        raise SystemExit("could not determine fixture-creation Git provenance")

    source_by_pxd = {}
    metrics_by_pxd = {}
    for pxd, _ in COHORT:
        source_artifacts = _source_artifacts(
            repo_root, store_dir, pxd, source_revision
        )
        source_by_pxd[pxd] = source_artifacts
        metrics_by_pxd[pxd] = _baseline_metrics_from_bytes(
            _read_source_artifact(
                repo_root,
                source_artifacts["post_judge/llm_judge_per_paper.csv"],
                source_revision,
            ),
            pxd,
        )

    if args.dry_run:
        print("Validated {} approved {} source bundles.".format(len(COHORT), FIXTURE_VERSION))
        return 0

    output_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(output_root.parent)) as temporary_directory:
        temporary_root = Path(temporary_directory) / output_root.name
        cohort_manifest = []
        for rank, (pxd, caveat) in enumerate(COHORT, start=1):
            fixture_dir = temporary_root / pxd
            _copy_fixture(
                repo_root, source_by_pxd[pxd], source_revision, fixture_dir
            )
            metrics_path = fixture_dir / "baseline_metrics.json"
            metrics_path.write_text(
                json.dumps(metrics_by_pxd[pxd], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            artifacts, combined_digest = _manifest_artifacts(
                repo_root, source_by_pxd[pxd], fixture_dir
            )
            cohort_manifest.append(
                {
                    "rank": rank,
                    "pxd": pxd,
                    "known_baseline_caveat": caveat,
                    "baseline_metrics": metrics_by_pxd[pxd],
                    "artifacts": artifacts,
                    "artifact_bundle_sha256": combined_digest,
                }
            )

        manifest = {
            "fixture_version": FIXTURE_VERSION,
            "fixture_date": args.fixture_date,
            "source_snapshot": "approved HAMLET v2.1.0 artifacts from Git revision",
            "source_revision": source_revision,
            "fixture_created_from_parent_commit": parent_commit,
            "agentic_metadata_gitlink": agentic_metadata_gitlink,
            "selection_rationale": (
                "Approved score-ranked 30-PXD cohort with complete final post-judge "
                "and aggregate-stage evidence; documented caveats are retained."
            ),
            "cohort": cohort_manifest,
        }
        (temporary_root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        with (temporary_root / "qc_pxds.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "rank",
                    "pxd",
                    "judge_accuracy",
                    "total_extracted",
                    "judge_n_hallucinated",
                    "judge_n_mismatch",
                    "known_baseline_caveat",
                ),
            )
            writer.writeheader()
            for record in cohort_manifest:
                metrics = record["baseline_metrics"]
                writer.writerow(
                    {
                        "rank": record["rank"],
                        "pxd": record["pxd"],
                        "judge_accuracy": metrics["judge_accuracy"],
                        "total_extracted": metrics["total_extracted"],
                        "judge_n_hallucinated": metrics["judge_n_hallucinated"],
                        "judge_n_mismatch": metrics["judge_n_mismatch"],
                        "known_baseline_caveat": record["known_baseline_caveat"],
                    }
                )
        temporary_root.rename(output_root)

    print("Froze {} approved {} fixture bundles in {}".format(len(COHORT), FIXTURE_VERSION, output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())