#!/usr/bin/env python3

import argparse
import csv
import json
import shutil
import tempfile
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


# Maps builder override field names back to the integrated JSON field keys
_BUILDER_FIELD_TO_INTEGRATED = {
    "organism":             ("BiologicalAgent", "species"),
    "organism_part":        ("BiologicalAgent", "tissue"),
    "disease":              ("BiologicalAgent", "disease_state"),
    "cell_type":            ("BiologicalAgent", "cell_type"),
    "cell_line":            ("BiologicalAgent", "cell_line"),
    "sex":                  ("BiologicalAgent", "sex"),
    "age":                  ("BiologicalAgent", "age"),
    "sample_source":        ("BiologicalAgent", "sample_source"),
    "biological_replicate": ("ExperimentalDesignAgent", "number_of_biological_replicates"),
    "technical_replicate":  ("ExperimentalDesignAgent", "number_of_technical_replicates"),
    "fraction_identifier":  ("ExperimentalDesignAgent", "number_of_fractions"),
    "factor_value":         ("ExperimentalDesignAgent", "factor_value"),
    "instrument":           ("TechnicalAgent", "instrument"),
    "label":                ("TechnicalAgent", "labeling"),
}


def _resolve_integrated_json(input_dir: Path, agent: str, pxd: str) -> Path:
    path = input_dir / "integrated_output" / agent / "temp_0.0" / f"{pxd}_PubText_enriched.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing integrated JSON for {agent}: {path}")
    return path


def _copy_judge_as_post_judge(judge_dir: Path, output_dir: Path) -> dict | None:
    """Copy the first-pass judge outputs into output_dir/post_judge/ verbatim.

    Used when no SDRF overrides were applied: the integrated JSONs going into
    the final SDRF are unchanged from what the first-pass judge already
    evaluated, so re-running the (expensive) judge would just reproduce the
    same result. We still need a post_judge/llm_judge_per_paper.csv on disk
    for downstream analysis, so copy the existing judge outputs instead.
    """
    post_judge_out = output_dir / "post_judge"
    post_judge_out.mkdir(parents=True, exist_ok=True)

    for name in (
        "llm_judge_per_paper.csv",
        "llm_judge_annotation_review.csv",
        "llm_judge_coverage.csv",
        "llm_judge_accuracy.png",
        "llm_judge_aggregate.png",
        "llm_judge_annotation_quality_counts.png",
    ):
        src = judge_dir / name
        if src.exists():
            shutil.copy2(src, post_judge_out / name)

    json_src = judge_dir / "json_outputs"
    if json_src.exists():
        shutil.copytree(json_src, post_judge_out / "json_outputs", dirs_exist_ok=True)

    stats_path = post_judge_out / "llm_judge_per_paper.csv"
    if not stats_path.exists():
        return None
    with open(stats_path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            return dict(row)
    return None


def _run_post_judge_evaluation(
    pxd: str,
    input_dir: Path,
    applied_overrides: dict,
    pmc_cache: Path,
    output_dir: Path,
) -> dict | None:
    """Run a second judge pass over patched integrated JSONs to produce a post-refinement score.

    Patches each applied override back into a temporary copy of the integrated JSON so the
    judge sees the same values that ended up in the final SDRF. Writes outputs under
    output_dir/post_judge/ and returns the per-paper stats dict.
    """
    # Import judge at call time to avoid circular issues and heavy import at module load
    REPO_ROOT = Path(__file__).resolve().parent.parent.parent
    if str(REPO_ROOT / "src" / "python") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "src" / "python"))
    try:
        import importlib
        judge_mod = importlib.import_module("LLm_as_judge")
    except ImportError as exc:
        print(f"WARNING: could not import LLm_as_judge for post-judge evaluation: {exc}")
        return None

    agents = ["BiologicalAgent", "TechnicalAgent", "ExperimentalDesignAgent"]

    with tempfile.TemporaryDirectory(prefix=f"post_judge_{pxd}_") as tmpdir:
        patched_dir = Path(tmpdir) / "metadata_extraction_output"

        # Copy entire integrated_output tree into temp dir
        src_integrated = input_dir / "integrated_output"
        dst_integrated = patched_dir / "integrated_output"
        shutil.copytree(src_integrated, dst_integrated)

        # Apply overrides into relevant agent JSONs
        for builder_field, override_value in applied_overrides.items():
            if builder_field not in _BUILDER_FIELD_TO_INTEGRATED:
                continue
            agent, json_field = _BUILDER_FIELD_TO_INTEGRATED[builder_field]
            json_path = dst_integrated / agent / "temp_0.0" / f"{pxd}_PubText_enriched.json"
            if not json_path.exists():
                continue
            with open(json_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # Patch: set resolved to override value and mark status
            entry = data.get(json_field)
            if isinstance(entry, dict):
                entry["resolved"] = override_value
                entry["status"] = "JUDGE_OVERRIDE"
            else:
                data[json_field] = {"resolved": override_value, "status": "JUDGE_OVERRIDE", "confidence": 1.0}
            with open(json_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)

        post_judge_out = output_dir / "post_judge"
        post_judge_out.mkdir(parents=True, exist_ok=True)

        judge_mod.run_pipeline_evaluation(
            pxd_id=pxd,
            input_dir=str(patched_dir),
            pmc_cache_path=str(pmc_cache),
            out_dir=str(post_judge_out),
        )

    # Read back per-paper stats
    stats_path = post_judge_out / "llm_judge_per_paper.csv"
    if not stats_path.exists():
        return None
    with open(stats_path, "r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            return dict(row)
    return None


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

    # Run post-judge evaluation against the overridden integrated JSONs.
    # When no overrides were applied, the post-refinement state is identical
    # to what the first-pass judge already evaluated, so copy those results
    # instead of re-running the judge for nothing.
    post_judge_stats = None
    if applied_overrides and args.pmc_cache and args.pmc_cache.exists():
        print("Running post-judge evaluation against refined integrated outputs...")
        try:
            post_judge_stats = _run_post_judge_evaluation(
                pxd=args.pxd,
                input_dir=input_dir,
                applied_overrides=applied_overrides,
                pmc_cache=args.pmc_cache.resolve(),
                output_dir=output_dir,
            )
            if post_judge_stats:
                print(f"Post-judge accuracy: {float(post_judge_stats.get('judge_accuracy', 0)):.0%}")
        except Exception as exc:
            print(f"WARNING: post-judge evaluation failed: {exc}")
    elif judge_dir is not None:
        print("No overrides applied; copying first-pass judge results as post_judge "
              "(nothing changed to re-evaluate).")
        post_judge_stats = _copy_judge_as_post_judge(judge_dir, output_dir)
        if post_judge_stats:
            print(f"Post-judge accuracy (unchanged from first pass): "
                  f"{float(post_judge_stats.get('judge_accuracy', 0)):.0%}")
    else:
        print("Skipping post-judge evaluation: no judge_dir available.")

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