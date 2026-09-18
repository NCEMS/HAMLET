#!/usr/bin/env python3
"""Run report-only post-store SDRF QC against immutable HAMLET fixtures."""

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


PXD_SDRF_PATH = re.compile(r"^store/hamlet_sdrfs/(PXD\d+)\.sdrf\.tsv$")
JUDGE_METRIC_PATTERN = re.compile(r"^(judge_accuracy|judge_n_)")
JUDGE_CATEGORIES = ("Biological", "Technical", "ExperimentalDesign")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-sha", help="Git revision before the change set")
    parser.add_argument("--after-sha", help="Git revision after the change set")
    parser.add_argument(
        "--pxd",
        action="append",
        default=[],
        help="Explicit changed PXD; can be supplied more than once",
    )
    parser.add_argument(
        "--pxd-file",
        type=Path,
        help="One-column CSV/text file of explicit changed PXDs",
    )
    parser.add_argument(
        "--sdrf-dir", type=Path, default=Path("store/hamlet_sdrfs"),
        help="Directory containing candidate <PXD>.sdrf.tsv files",
    )
    parser.add_argument(
        "--fixture-root", type=Path,
        default=Path("tests/fixtures/sdrf_qc/v2.1.0"),
        help="Immutable HAMLET SDRF fixture root",
    )
    parser.add_argument(
        "--baseline-release-manifest",
        type=Path,
        default=Path("store/releases/v2.1.0/manifest.json"),
        help="Per-PXD judge-metric baseline manifest for release comparison",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--commit",
        help="Commit being evaluated; defaults to the current repository HEAD.",
    )
    parser.add_argument(
        "--pmc-cache", type=Path,
        help="Durable PMC cache used for optional fresh post-judge evaluation",
    )
    parser.add_argument(
        "--skip-judge", action="store_true",
        help="Do not run the external LLM judge",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Return nonzero when a requested comparison or judge command fails",
    )
    return parser.parse_args()


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_fixture_manifest(fixture_root):
    manifest_path = fixture_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid fixture manifest {}: {}".format(manifest_path, exc))
    if manifest.get("fixture_version") != fixture_root.name:
        raise ValueError("fixture version does not match fixture-root directory")
    cohort = manifest.get("cohort")
    if not isinstance(cohort, list) or not cohort:
        raise ValueError("fixture manifest has no cohort records")

    records = {}
    for record in cohort:
        pxd = record.get("pxd")
        if not isinstance(pxd, str) or not re.fullmatch(r"PXD\d+", pxd):
            raise ValueError("fixture manifest contains an invalid PXD")
        if pxd in records:
            raise ValueError("fixture manifest contains duplicate {}".format(pxd))
        for artifact in record.get("artifacts", []):
            relative_path = artifact.get("fixture_path")
            if not isinstance(relative_path, str) or Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
                raise ValueError("fixture manifest contains an unsafe artifact path for {}".format(pxd))
            fixture_path = fixture_root / pxd / relative_path
            if not fixture_path.is_file():
                raise ValueError("missing fixture artifact {}".format(fixture_path))
            if fixture_path.stat().st_size != artifact.get("bytes"):
                raise ValueError("fixture artifact size mismatch: {}".format(fixture_path))
            if _sha256(fixture_path) != artifact.get("sha256"):
                raise ValueError("fixture artifact hash mismatch: {}".format(fixture_path))
        gold_sdrf = fixture_root / pxd / "{}.sdrf.tsv".format(pxd)
        if not gold_sdrf.is_file():
            raise ValueError("missing gold SDRF {}".format(gold_sdrf))
        records[pxd] = record
    return manifest, records


def load_release_baseline(manifest_path):
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("invalid release baseline {}: {}".format(manifest_path, exc))
    if not isinstance(manifest.get("release_version"), str):
        raise ValueError("release baseline has no release_version")
    records = {}
    for record in manifest.get("pxds", []):
        pxd = record.get("pxd")
        if not isinstance(pxd, str) or not re.fullmatch(r"PXD\d+", pxd):
            raise ValueError("release baseline contains an invalid PXD")
        if pxd in records:
            raise ValueError("release baseline contains duplicate {}".format(pxd))
        records[pxd] = record.get("judge", {"status": "missing"})
    if not records:
        raise ValueError("release baseline has no PXD records")
    return manifest, records


def read_judge_metrics(path, pxd):
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise ValueError("could not read post-judge metrics {}: {}".format(path, exc))
    if len(rows) != 1 or rows[0].get("paper_id") != pxd:
        raise ValueError("post-judge metrics have no unambiguous {} row".format(pxd))
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
        raise ValueError("could not read post-judge review {}: {}".format(path, exc))
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


def pxds_from_file(path):
    return sorted(
        {
            value.strip()
            for value in path.read_text(encoding="utf-8").splitlines()
            for cell in [value.split(",", 1)[0]]
            if re.fullmatch(r"PXD\d+", cell.strip())
        }
    )


def changed_pxds_from_paths(paths):
    return sorted(
        {
            match.group(1)
            for path in paths
            for match in [PXD_SDRF_PATH.fullmatch(path.strip())]
            if match is not None
        }
    )


def changed_pxds_from_git(repo_root, before_sha, after_sha):
    command = [
        "git", "-C", str(repo_root), "diff", "--name-only", before_sha, after_sha,
        "--", "store/hamlet_sdrfs",
    ]
    completed = subprocess.run(command, check=True, text=True, capture_output=True)
    return changed_pxds_from_paths(completed.stdout.splitlines())


def _run_command(command, label):
    completed = subprocess.run(command, text=True, capture_output=True)
    return {
        "label": label,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _git_head(repo_root):
    try:
        return subprocess.run(
            ("git", "-C", str(repo_root), "rev-parse", "HEAD"),
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _run_comparison(repo_root, pxd, candidate_sdrf, gold_sdrf, output_dir):
    command = [
        sys.executable,
        str(repo_root / "src/python/conflictAssessment.py"),
        "--pxd", pxd,
        "--assessed-sdrf", str(candidate_sdrf),
        "--gold-sdrf", str(gold_sdrf),
        "--output-dir", str(output_dir),
    ]
    result = _run_command(command, "candidate_vs_hamlet_gold")
    summary_path = output_dir / pxd / "candidate_vs_hamlet_gold" / "conflict_summary.json"
    if result["status"] == "passed" and summary_path.is_file():
        result["summary"] = json.loads(summary_path.read_text(encoding="utf-8"))
        result["report_path"] = str(summary_path.parent)
    elif result["status"] == "passed":
        result["status"] = "failed"
        result["stderr"] += "\nComparison did not write conflict_summary.json"
    return result


def _run_judge(repo_root, pxd, candidate_sdrf, pmc_cache, output_dir):
    judge_dir = output_dir / pxd / "post_judge"
    command = [
        sys.executable,
        str(repo_root / "src/python/sdrf_judge.py"),
        "--pipeline",
        "--pxd", pxd,
        "--sdrf", str(candidate_sdrf),
        "--pmc_cache", str(pmc_cache),
        "--outdir", str(judge_dir),
        "--workers", "1",
    ]
    result = _run_command(command, "post_judge")
    result["report_path"] = str(judge_dir)
    metrics_path = judge_dir / "llm_judge_per_paper.csv"
    review_path = judge_dir / "llm_judge_annotation_review.csv"
    if result["status"] == "passed":
        try:
            result["metrics"] = read_judge_metrics(metrics_path, pxd)
            result["category_metrics"] = read_judge_category_metrics(review_path, pxd)
        except ValueError as exc:
            result["status"] = "failed"
            result["stderr"] += "\n{}".format(exc)
    return result


def main():
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    fixture_root = (repo_root / args.fixture_root).resolve() if not args.fixture_root.is_absolute() else args.fixture_root.resolve()
    baseline_manifest_path = (repo_root / args.baseline_release_manifest).resolve() if not args.baseline_release_manifest.is_absolute() else args.baseline_release_manifest.resolve()
    sdrf_dir = (repo_root / args.sdrf_dir).resolve() if not args.sdrf_dir.is_absolute() else args.sdrf_dir.resolve()
    output_dir = (repo_root / args.output_dir).resolve() if not args.output_dir.is_absolute() else args.output_dir.resolve()
    try:
        manifest, fixture_records = load_fixture_manifest(fixture_root)
        baseline_manifest, baseline_records = load_release_baseline(baseline_manifest_path)
    except ValueError as exc:
        raise SystemExit(str(exc))

    explicit_pxds = [*args.pxd, *(pxds_from_file(args.pxd_file) if args.pxd_file else [])]
    if explicit_pxds:
        changed_pxds = sorted(set(explicit_pxds))
    elif args.before_sha and args.after_sha:
        try:
            changed_pxds = changed_pxds_from_git(repo_root, args.before_sha, args.after_sha)
        except subprocess.CalledProcessError as exc:
            raise SystemExit("could not determine changed SDRFs: {}".format(exc.stderr.strip()))
    elif args.before_sha or args.after_sha:
        raise SystemExit("--before-sha and --after-sha must be supplied together")
    else:
        raise SystemExit("supply one or more --pxd values or a --before-sha/--after-sha range")

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    failures = []
    for pxd in changed_pxds:
        candidate_sdrf = sdrf_dir / "{}.sdrf.tsv".format(pxd)
        result = {
            "pxd": pxd,
            "candidate_sdrf": str(candidate_sdrf),
            "gold_cohort_member": pxd in fixture_records,
        }
        if not candidate_sdrf.is_file():
            result["candidate_status"] = "missing"
            failures.append(pxd)
            results.append(result)
            continue
        result["candidate_status"] = "present"

        if pxd in fixture_records:
            comparison = _run_comparison(
                repo_root,
                pxd,
                candidate_sdrf,
                fixture_root / pxd / "{}.sdrf.tsv".format(pxd),
                output_dir / pxd / "comparison",
            )
            result["comparison"] = comparison
            if comparison["status"] == "failed":
                failures.append(pxd)

        if args.skip_judge:
            result["judge"] = {"status": "skipped", "reason": "--skip-judge"}
        elif args.pmc_cache is None:
            result["judge"] = {"status": "skipped", "reason": "no --pmc-cache"}
        elif not os.environ.get("OPENROUTER_API_KEY"):
            result["judge"] = {"status": "skipped", "reason": "OPENROUTER_API_KEY is unavailable"}
        else:
            pmc_cache = args.pmc_cache.resolve()
            if not pmc_cache.is_dir():
                result["judge"] = {"status": "failed", "reason": "PMC cache directory not found"}
                failures.append(pxd)
            else:
                judge = _run_judge(repo_root, pxd, candidate_sdrf, pmc_cache, output_dir)
                result["judge"] = judge
                if judge["status"] == "failed":
                    failures.append(pxd)
                elif baseline_records.get(pxd, {}).get("status") == "available":
                    result["judge_deltas"] = metric_deltas(
                        baseline_records[pxd]["metrics"], judge["metrics"]
                    )
                    result["judge_category_deltas"] = {
                        category: metric_deltas(
                            baseline_metrics,
                            judge["category_metrics"][category],
                        )
                        for category, baseline_metrics in baseline_records[pxd].get("category_metrics", {}).items()
                        if category in judge["category_metrics"]
                    }
                else:
                    result["judge_delta_status"] = "no_baseline_metrics"
        results.append(result)

    summary = {
        "schema_version": 1,
        "fixture_version": manifest["fixture_version"],
        "fixture_manifest": str(fixture_root / "manifest.json"),
        "baseline_release_version": baseline_manifest["release_version"],
        "baseline_release_manifest": str(baseline_manifest_path),
        "evaluated_commit": args.commit or _git_head(repo_root),
        "changed_pxds": changed_pxds,
        "results": results,
        "report_only": not args.strict,
        "failures": sorted(set(failures)),
    }
    summary_path = output_dir / "qc-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("QC summary: {}".format(summary_path))
    if args.strict and failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())