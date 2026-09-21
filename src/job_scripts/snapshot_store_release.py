#!/usr/bin/env python3
"""Create an immutable per-PXD store release manifest from a Git revision."""

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


FINAL_JUDGE_PATH = "store/agentic_results_files/{pxd}/sdrf_judge/llm_judge_per_paper.csv"
HISTORICAL_FINAL_JUDGE_PATH = "store/agentic_results_files/{pxd}/metadata_extraction_output/post_judge/llm_judge_per_paper.csv"
LEGACY_REFINEMENT_JUDGE_PATH = "store/agentic_results_files/{pxd}/judge_output/llm_judge_per_paper.csv"
SDRF_PATH = "store/hamlet_sdrfs/{pxd}.sdrf.tsv"
REVIEW_FILENAME = "llm_judge_annotation_review.csv"
JUDGE_CATEGORIES = ("Biological", "Technical", "ExperimentalDesign")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-dir", type=Path, default=Path("store"))
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--source-revision", default="HEAD")
    parser.add_argument("--pxd-file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_pxds(path):
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    return [row[0].strip() for row in rows if row and re.fullmatch(r"PXD\d+", row[0].strip())]


def git_bytes(repo_root, revision, relative_path):
    completed = subprocess.run(
        ("git", "-C", str(repo_root), "show", "{}:{}".format(revision, relative_path)),
        capture_output=True,
    )
    return completed.stdout if completed.returncode == 0 else None


def sha256(content):
    return hashlib.sha256(content).hexdigest()


def coerce_metrics(row):
    metrics = {}
    for key, value in row.items():
        if key in {"paper_id", "source", "mode"}:
            metrics[key] = value
        elif key == "total_extracted" or key.startswith("judge_n_"):
            metrics[key] = int(value)
        elif key.startswith("judge_accuracy"):
            metrics[key] = float(value)
    return metrics


def category_metrics(review_content, pxd):
    rows = list(csv.DictReader(io.StringIO(review_content.decode("utf-8"))))
    output = {}
    for category in JUDGE_CATEGORIES:
        category_rows = [row for row in rows if row.get("paper_id") == pxd and row.get("agent") == category]
        if not category_rows:
            continue
        counts = {name: sum(row.get("error_category") == name for row in category_rows) for name in (
            "correct_explicit", "hallucinated", "type_mismatch", "wrong_value", "incomplete", "meti_only", "inferred"
        )}
        total = len(category_rows)
        output[category] = {
            "total_extracted": total,
            "judge_n_correct": counts["correct_explicit"],
            "judge_n_hallucinated": counts["hallucinated"],
            "judge_n_mismatch": counts["type_mismatch"],
            "judge_n_wrong": counts["wrong_value"],
            "judge_n_incomplete": counts["incomplete"],
            "judge_n_technical_not_in_text": counts["meti_only"],
            "judge_n_inferred": counts["inferred"],
            "judge_n_corrected": sum(bool(row.get("corrected_value")) for row in category_rows),
            "judge_accuracy": round(counts["correct_explicit"] / total, 4),
            "judge_accuracy_adjusted": round((counts["correct_explicit"] + counts["meti_only"]) / total, 4),
            "judge_accuracy_with_inference": round((counts["correct_explicit"] + counts["inferred"]) / total, 4),
        }
    return output


def judge_record(repo_root, revision, pxd):
    for relative_path in (
        FINAL_JUDGE_PATH.format(pxd=pxd),
        HISTORICAL_FINAL_JUDGE_PATH.format(pxd=pxd),
        LEGACY_REFINEMENT_JUDGE_PATH.format(pxd=pxd),
    ):
        content = git_bytes(repo_root, revision, relative_path)
        if content is None:
            continue
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
        if len(rows) == 1 and rows[0].get("paper_id") == pxd:
            review_path = relative_path.replace("llm_judge_per_paper.csv", REVIEW_FILENAME)
            review_content = git_bytes(repo_root, revision, review_path)
            return {
                "status": "available",
                "source_path": relative_path,
                "metrics": coerce_metrics(rows[0]),
                "category_metrics": category_metrics(review_content, pxd) if review_content else {},
            }
    return {"status": "missing"}


def build_manifest(repo_root, release_version, source_revision, pxds):
    records = []
    for pxd in pxds:
        sdrf_path = SDRF_PATH.format(pxd=pxd)
        sdrf = git_bytes(repo_root, source_revision, sdrf_path)
        records.append(
            {
                "pxd": pxd,
                "sdrf": {
                    "status": "available" if sdrf is not None else "missing",
                    "source_path": sdrf_path,
                    "sha256": sha256(sdrf) if sdrf is not None else None,
                },
                "judge": judge_record(repo_root, source_revision, pxd),
            }
        )
    return {
        "schema_version": 1,
        "release_version": release_version,
        "source_revision": source_revision,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pxds": records,
    }


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    store_dir = (repo_root / args.store_dir).resolve() if not args.store_dir.is_absolute() else args.store_dir.resolve()
    release_dir = store_dir / "releases" / args.release_version
    revision = subprocess.check_output(
        ("git", "-C", str(repo_root), "rev-parse", args.source_revision), text=True
    ).strip()
    if release_dir.exists() and not args.dry_run:
        raise SystemExit("release is already immutable: {}".format(release_dir))
    manifest = build_manifest(repo_root, args.release_version, revision, read_pxds(args.pxd_file))
    available = sum(record["judge"]["status"] == "available" for record in manifest["pxds"])
    print("Built {} baseline records; {} have judge metrics.".format(len(manifest["pxds"]), available))
    if args.dry_run:
        return 0
    release_dir.mkdir(parents=True)
    (release_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())