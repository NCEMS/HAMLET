#!/usr/bin/env python3

import argparse
import csv
import json
import importlib
from pathlib import Path
import sys

from sdrf_builder import AgenticToSDRF


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_judge_stats(judge_dir: Path) -> dict | None:
    stats_path = judge_dir / "llm_judge_per_paper.csv"
    if not stats_path.exists():
        return None
    with open(stats_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            return row
    return None


def _load_override_doc(judge_dir: Path, pxd: str) -> dict | None:
    override_path = judge_dir / "json_outputs" / f"{pxd}_sdrf_overrides.json"
    return _load_json(override_path)


def _build_applied_overrides(override_doc: dict | None) -> tuple[dict, dict]:
    if not override_doc:
        return {}, {
            "safe_fields_considered": 0,
            "safe_fields_with_selection": 0,
            "overrides_applied": 0,
            "fields_improved": 0,
            "fields_unchanged": 0,
        }

    field_overrides = override_doc.get("field_overrides", {})
    applied = {}
    with_selection = 0
    unchanged = 0

    for field_name, info in field_overrides.items():
        selected_value = info.get("selected_value")
        if selected_value:
            with_selection += 1
        if info.get("apply_override") and selected_value:
            applied[str(info.get("builder_field"))] = str(selected_value)
        else:
            unchanged += 1

    metrics = {
        "safe_fields_considered": len(field_overrides),
        "safe_fields_with_selection": with_selection,
        "overrides_applied": len(applied),
        "fields_improved": len(applied),
        "fields_unchanged": unchanged,
    }
    return applied, metrics


def _resolve_integrated_json(input_dir: Path, agent: str, pxd: str) -> Path:
    path = input_dir / "integrated_output" / agent / "temp_0.0" / f"{pxd}_PubText_enriched.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing integrated JSON for {agent}: {path}")
    return path


def _run_post_judge_evaluation(
    pxd: str,
    sdrf_path: Path,
    pmc_cache: Path,
    output_dir: Path,
) -> dict | None:
    """Run a post-finalization judge pass against the finalized SDRF.

    Uses sdrf_judge.py in single-PXD mode and writes outputs under output_dir/post_judge.
    """
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(REPO_ROOT / "src" / "python") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src" / "python"))
    try:
        judge_mod = importlib.import_module("sdrf_judge")
    except ImportError as exc:
        print(f"WARNING: could not import sdrf_judge for post-judge evaluation: {exc}")
        return None

    post_judge_out = output_dir / "post_judge"
    post_judge_out.mkdir(parents=True, exist_ok=True)

    stats = judge_mod.run_single_sdrf_evaluation(
        pxd_id=pxd,
        sdrf_path=str(sdrf_path),
        pmc_cache_path=str(pmc_cache),
        out_dir=str(post_judge_out),
    )
    return dict(stats) if stats else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Finalize SDRF generation using integrated metadata and optional llm_judge overrides.")
    parser.add_argument("--pxd", required=True, help="PXD accession")
    parser.add_argument("--input_dir", required=True, type=Path, help="Path to metadata_extraction_output directory")
    parser.add_argument("--aggregated_json", required=True, type=Path, help="Path to PXD aggregated results JSON")
    parser.add_argument("--judge_dir", type=Path, default=None, help="Optional path to judge_output directory")
    parser.add_argument("--pmc_cache", type=Path, default=None, help="Optional path to PMC cache for post-judge evaluation pass")
    parser.add_argument("--output_dir", type=Path, default=None, help="Directory to receive final .sdrf.tsv and refinement reports")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = (args.output_dir or args.input_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    tech_json = _resolve_integrated_json(input_dir, "TechnicalAgent", args.pxd)
    bio_json = _resolve_integrated_json(input_dir, "BiologicalAgent", args.pxd)
    exp_json = _resolve_integrated_json(input_dir, "ExperimentalDesignAgent", args.pxd)

    judge_dir = args.judge_dir.resolve() if args.judge_dir and args.judge_dir.exists() and args.judge_dir.is_dir() else None
    override_doc = _load_override_doc(judge_dir, args.pxd) if judge_dir else None
    judge_stats = _load_judge_stats(judge_dir) if judge_dir else None
    applied_overrides, refinement_metrics = _build_applied_overrides(override_doc)

    builder = AgenticToSDRF(
        tech_json=tech_json,
        bio_json=bio_json,
        exp_json=exp_json,
        aggregated_json=args.aggregated_json.resolve(),
        overrides=applied_overrides,
    )

    sdrf_path = output_dir / f"{args.pxd}.sdrf.tsv"
    builder.to_sdrf(sdrf_path)

    # Run post-judge evaluation against the finalized SDRF.
    # This always runs (even when no overrides were applied) so post_judge reflects
    # the exact final artifact that will be consumed downstream.
    post_judge_stats = None
    if args.pmc_cache and args.pmc_cache.exists():
        print("Running post-judge evaluation against finalized SDRF...")
        try:
            post_judge_stats = _run_post_judge_evaluation(
                pxd=args.pxd,
                sdrf_path=sdrf_path,
                pmc_cache=args.pmc_cache.resolve(),
                output_dir=output_dir,
            )
            if post_judge_stats:
                print(f"Post-judge accuracy: {float(post_judge_stats.get('judge_accuracy', 0)):.0%}")
        except Exception as exc:
            print(f"WARNING: post-judge evaluation failed: {exc}")
    else:
        print("Skipping post-judge evaluation: pmc_cache path missing or does not exist.")

    report = {
        "paper_id": args.pxd,
        "final_sdrf": str(sdrf_path),
        "pre_judge_summary": judge_stats,
        "override_document": override_doc,
        "applied_overrides": applied_overrides,
        "post_refinement_metrics": refinement_metrics,
        "post_judge_summary": post_judge_stats,
    }
    report_path = output_dir / f"{args.pxd}.sdrf_refinement_report.json"
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)

    metrics_path = output_dir / f"{args.pxd}.sdrf_refinement_metrics.json"
    with open(metrics_path, "w", encoding="utf-8") as handle:
        json.dump(refinement_metrics, handle, indent=2, ensure_ascii=False)

    print(f"Final SDRF written to: {sdrf_path}")
    print(f"Refinement report written to: {report_path}")
    print(f"Refinement metrics written to: {metrics_path}")


if __name__ == "__main__":
    main()