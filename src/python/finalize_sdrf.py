#!/usr/bin/env python3

import argparse
import csv
import json
from pathlib import Path

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


def _raw_files_from_technical_document(document: dict) -> list[str]:
    """Return the upstream canonical RAW manifest for row construction."""
    manifest = document.get("raw_file_manifest")
    records = manifest if isinstance(manifest, list) else []
    raw_files = [
        str(record.get("raw_file") or "").strip()
        for record in records
        if isinstance(record, dict)
    ]
    if not raw_files:
        raise ValueError(
            "TechnicalAgent enriched JSON is missing raw_file_manifest; "
            "finalization cannot reconstruct rows from aggregate data."
        )
    return raw_files


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an SDRF from enriched metadata and llm_judge consensus.")
    parser.add_argument("--pxd", required=True, help="PXD accession")
    parser.add_argument("--input_dir", required=True, type=Path, help="Path to metadata_extraction_output directory")
    parser.add_argument("--judge_dir", type=Path, default=None, help="Optional path to judge_output directory")
    parser.add_argument("--output_dir", type=Path, default=None, help="Directory to receive final .sdrf.tsv and refinement reports")
    args = parser.parse_args()

    input_dir = args.input_dir.resolve()
    output_dir = (args.output_dir or args.input_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    tech_json = _resolve_integrated_json(input_dir, "TechnicalAgent", args.pxd)
    bio_json = _resolve_integrated_json(input_dir, "BiologicalAgent", args.pxd)
    exp_json = _resolve_integrated_json(input_dir, "ExperimentalDesignAgent", args.pxd)
    technical_document = _load_json(tech_json)
    if not isinstance(technical_document, dict):
        raise ValueError(f"TechnicalAgent integrated JSON is not an object: {tech_json}")
    raw_files = _raw_files_from_technical_document(technical_document)

    judge_dir = args.judge_dir.resolve() if args.judge_dir and args.judge_dir.exists() and args.judge_dir.is_dir() else None
    override_doc = _load_override_doc(judge_dir, args.pxd) if judge_dir else None
    judge_stats = _load_judge_stats(judge_dir) if judge_dir else None
    applied_overrides, refinement_metrics = _build_applied_overrides(override_doc)

    sdrf_path = output_dir / f"{args.pxd}.sdrf.tsv"
    confidence_path = output_dir / f"{args.pxd}.confidence.sdrf.tsv"

    def write_sdrf(overrides: dict[str, str]) -> None:
        builder = AgenticToSDRF(
            tech_json=tech_json,
            bio_json=bio_json,
            exp_json=exp_json,
            raw_files=raw_files,
            pxd_id=args.pxd,
            overrides=overrides,
            judge_document=override_doc,
        )
        builder.to_sdrf(sdrf_path)
        builder.to_confidence_sidecar(confidence_path)

    write_sdrf(applied_overrides)

    report = {
        "paper_id": args.pxd,
        "final_sdrf": str(sdrf_path),
        "confidence_sidecar": str(confidence_path),
        "pre_judge_summary": judge_stats,
        "override_document": override_doc,
        "applied_overrides": applied_overrides,
        "refinement_metrics": refinement_metrics,
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