#!/usr/bin/env python3
"""Build static SDRF QC comparisons between versioned HAMLET store releases."""

import argparse
import csv
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path


JUDGE_METRIC_PATTERN = re.compile(r"^(total_extracted|judge_accuracy|judge_n_)")
JUDGE_CATEGORIES = ("Biological", "Technical", "ExperimentalDesign")
LEGACY_AGENT_MAP = {
    "BiologicalAgent": "Biological",
    "TechnicalAgent": "Technical",
    "ExperimentalDesignAgent": "ExperimentalDesign",
}
VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
POST_JUDGE_FILE = "metadata_extraction_output/post_judge/llm_judge_per_paper.csv"
POST_JUDGE_REVIEW_FILE = "metadata_extraction_output/post_judge/llm_judge_annotation_review.csv"
LEGACY_JUDGE_FILE = "judge_output/llm_judge_per_paper.csv"
LEGACY_JUDGE_REVIEW_FILE = "judge_output/llm_judge_annotation_review.csv"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, default=Path("store"))
    parser.add_argument("--baseline-version", help="Baseline release version, for example v2.1.0")
    parser.add_argument("--candidate-version", help="Candidate release version, for example v2.1.1")
    parser.add_argument(
        "--compare",
        action="append",
        default=[],
        help="Explicit comparison pair as baseline:candidate; repeatable",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def version_key(version):
    match = VERSION_PATTERN.fullmatch(version)
    if not match:
        raise ValueError("invalid release version: {}".format(version))
    return tuple(int(value) for value in match.groups())


def comparison_id(baseline_version, candidate_version):
    return "{}__vs__{}".format(baseline_version, candidate_version)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def truthy(value):
    return str(value).strip().lower() in {"true", "1", "yes"}


def review_error_category(row):
    if row.get("error_category"):
        return row["error_category"]
    if truthy(row.get("technical_origin")):
        return "meti_only"
    if truthy(row.get("inference")):
        return "inferred"
    if truthy(row.get("type_mismatch")):
        return "type_mismatch"
    if truthy(row.get("hallucination")):
        return "hallucinated"
    if str(row.get("value_correct", "")).strip().lower() == "false":
        return "wrong_value"
    if str(row.get("value_complete", "")).strip().lower() == "false":
        return "incomplete"
    return "correct_explicit"


def read_judge_metrics(path, pxd):
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise ValueError("could not read judge metrics {}: {}".format(path, exc)) from exc
    if len(rows) != 1 or rows[0].get("paper_id") != pxd:
        raise ValueError("judge metrics have no unambiguous {} row".format(pxd))
    metrics = {}
    for key, value in rows[0].items():
        if not JUDGE_METRIC_PATTERN.match(key):
            continue
        try:
            metrics[key] = float(value) if key.startswith("judge_accuracy") else int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid {} metric {} for {}".format(key, value, pxd)) from exc
    return metrics


def read_judge_category_metrics(path, pxd):
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise ValueError("could not read judge review {}: {}".format(path, exc)) from exc
    output = {}
    for category in JUDGE_CATEGORIES:
        category_rows = [
            row for row in rows
            if row.get("paper_id") == pxd and LEGACY_AGENT_MAP.get(row.get("agent"), row.get("agent")) == category
        ]
        if not category_rows:
            continue
        counts = {name: sum(review_error_category(row) == name for row in category_rows) for name in (
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


def metric_deltas(baseline, candidate):
    output = {}
    for metric in sorted(set(baseline) & set(candidate)):
        baseline_value = baseline[metric]
        candidate_value = candidate[metric]
        absolute_delta = candidate_value - baseline_value
        output[metric] = {
            "baseline": baseline_value,
            "candidate": candidate_value,
            "absolute_delta": absolute_delta,
            "relative_delta": absolute_delta / baseline_value if baseline_value else None,
        }
    return output


def manifest_path(store_root, version):
    return store_root / "releases" / version / "manifest.json"


def versioned_sdrf_path(store_root, version, pxd):
    return store_root / "hamlet_sdrfs" / version / f"{pxd}.sdrf.tsv"


def versioned_agentic_path(store_root, version, pxd):
    return store_root / "agentic_results_files" / version / pxd


def load_release_manifest(path):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid release manifest {}: {}".format(path, exc)) from exc
    version = manifest.get("release_version")
    if not isinstance(version, str):
        raise ValueError("release manifest has no release_version: {}".format(path))
    records = {}
    for record in manifest.get("pxds", []):
        pxd = record.get("pxd")
        if not isinstance(pxd, str) or not re.fullmatch(r"PXD\d+", pxd):
            raise ValueError("release manifest contains an invalid PXD: {}".format(path))
        records[pxd] = record
    if not records:
        raise ValueError("release manifest has no PXD records: {}".format(path))
    return manifest, records


def load_judge_record(store_root, version, pxd):
    base = versioned_agentic_path(store_root, version, pxd)
    candidates = (
        (base / POST_JUDGE_FILE, base / POST_JUDGE_REVIEW_FILE),
        (base / LEGACY_JUDGE_FILE, base / LEGACY_JUDGE_REVIEW_FILE),
    )
    for metrics_path, review_path in candidates:
        if not metrics_path.is_file():
            continue
        record = {
            "status": "available",
            "metrics_path": str(metrics_path.relative_to(store_root)),
            "metrics": read_judge_metrics(metrics_path, pxd),
        }
        if review_path.is_file():
            record["review_path"] = str(review_path.relative_to(store_root))
            record["category_metrics"] = read_judge_category_metrics(review_path, pxd)
        else:
            record["category_metrics"] = {}
        return record
    return {"status": "missing"}


def compare_pair(store_root, baseline_version, candidate_version):
    _, baseline_records = load_release_manifest(manifest_path(store_root, baseline_version))
    _, candidate_records = load_release_manifest(manifest_path(store_root, candidate_version))
    baseline_pxds = set(baseline_records)
    candidate_pxds = set(candidate_records)
    shared_pxds = sorted(baseline_pxds & candidate_pxds)
    baseline_only = sorted(baseline_pxds - candidate_pxds)
    candidate_only = sorted(candidate_pxds - baseline_pxds)
    results = []
    changed_sdrfs = 0
    judge_pairs = 0
    for pxd in shared_pxds:
        baseline_sdrf = versioned_sdrf_path(store_root, baseline_version, pxd)
        candidate_sdrf = versioned_sdrf_path(store_root, candidate_version, pxd)
        baseline_judge = load_judge_record(store_root, baseline_version, pxd)
        candidate_judge = load_judge_record(store_root, candidate_version, pxd)
        result = {
            "pxd": pxd,
            "baseline_sdrf_path": str(baseline_sdrf.relative_to(store_root)),
            "candidate_sdrf_path": str(candidate_sdrf.relative_to(store_root)),
            "baseline_sdrf_sha256": _sha256(baseline_sdrf) if baseline_sdrf.is_file() else None,
            "candidate_sdrf_sha256": _sha256(candidate_sdrf) if candidate_sdrf.is_file() else None,
            "sdrf_status": "available" if baseline_sdrf.is_file() and candidate_sdrf.is_file() else "missing",
            "baseline_judge": baseline_judge,
            "candidate_judge": candidate_judge,
        }
        result["sdrf_changed"] = result["baseline_sdrf_sha256"] != result["candidate_sdrf_sha256"]
        if result["sdrf_changed"]:
            changed_sdrfs += 1
        if baseline_judge["status"] == "available" and candidate_judge["status"] == "available":
            judge_pairs += 1
            result["judge_delta_status"] = "available"
            result["judge_deltas"] = metric_deltas(baseline_judge["metrics"], candidate_judge["metrics"])
            result["judge_category_deltas"] = {
                category: metric_deltas(
                    baseline_judge["category_metrics"][category],
                    candidate_judge["category_metrics"][category],
                )
                for category in sorted(set(baseline_judge["category_metrics"]) & set(candidate_judge["category_metrics"]))
            }
        elif baseline_judge["status"] != "available" and candidate_judge["status"] != "available":
            result["judge_delta_status"] = "missing_both_judges"
        elif baseline_judge["status"] != "available":
            result["judge_delta_status"] = "missing_baseline_judge"
        else:
            result["judge_delta_status"] = "missing_candidate_judge"
        results.append(result)
    return {
        "comparison_id": comparison_id(baseline_version, candidate_version),
        "baseline_version": baseline_version,
        "candidate_version": candidate_version,
        "baseline_release_manifest": str(manifest_path(store_root, baseline_version).relative_to(store_root)),
        "candidate_release_manifest": str(manifest_path(store_root, candidate_version).relative_to(store_root)),
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "pxd_counts": {
            "baseline": len(baseline_pxds),
            "candidate": len(candidate_pxds),
            "shared": len(shared_pxds),
            "baseline_only": len(baseline_only),
            "candidate_only": len(candidate_only),
        },
        "baseline_only_pxds": baseline_only,
        "candidate_only_pxds": candidate_only,
        "summary": {
            "shared_pxds": len(shared_pxds),
            "changed_sdrfs": changed_sdrfs,
            "unchanged_sdrfs": len(shared_pxds) - changed_sdrfs,
            "judge_pairs_available": judge_pairs,
        },
        "results": results,
    }


def available_versions(store_root):
    releases_dir = store_root / "releases"
    versions = [path.name for path in releases_dir.iterdir() if path.is_dir() and VERSION_PATTERN.fullmatch(path.name)]
    return sorted(versions, key=version_key)


def requested_comparisons(args, versions):
    pairs = []
    if args.compare:
        for value in args.compare:
            baseline_version, separator, candidate_version = value.partition(":")
            if separator != ":":
                raise ValueError("invalid comparison {}; use baseline:candidate".format(value))
            pairs.append((baseline_version, candidate_version))
    elif args.baseline_version and args.candidate_version:
        pairs.append((args.baseline_version, args.candidate_version))
    elif args.baseline_version or args.candidate_version:
        raise ValueError("--baseline-version and --candidate-version must be supplied together")
    else:
        pairs = [
            (versions[index], versions[next_index])
            for index in range(len(versions))
            for next_index in range(index + 1, len(versions))
        ]
    if not pairs:
        raise ValueError("no release comparisons requested")
    output = []
    seen = set()
    known_versions = set(versions)
    for baseline_version, candidate_version in pairs:
        if baseline_version == candidate_version:
            raise ValueError("baseline and candidate versions must differ")
        version_key(baseline_version)
        version_key(candidate_version)
        if baseline_version not in known_versions:
            raise ValueError("unknown baseline version: {}".format(baseline_version))
        if candidate_version not in known_versions:
            raise ValueError("unknown candidate version: {}".format(candidate_version))
        pair = (baseline_version, candidate_version)
        if pair in seen:
            continue
        seen.add(pair)
        output.append(pair)
    return output


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    store_root = (repo_root / args.store_root).resolve() if not args.store_root.is_absolute() else args.store_root.resolve()
    output_dir = (repo_root / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    try:
        versions = available_versions(store_root)
        pairs = requested_comparisons(args, versions)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc))
    comparisons = [compare_pair(store_root, baseline_version, candidate_version) for baseline_version, candidate_version in pairs]
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": 2,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "store_root": str(store_root),
        "available_versions": versions,
        "default_comparison_id": comparisons[0]["comparison_id"],
        "comparisons": comparisons,
    }
    summary_path = output_dir / "qc-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("QC summary: {}".format(summary_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
