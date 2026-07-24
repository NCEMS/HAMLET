#!/usr/bin/env python3
"""LLM-as-judge evaluation for the 30-PXD test set.

For each PXD under input_llm_judge/TEXT_SDRF_30PXDs/, judges three extraction
sources against the manuscript text: the human-curated ground truth
("human_annotation"), the raw per-agent HAMLET output ("hamlet_raw", from
HAMLET_30PXDs/{BiologicalAgent,ExperimentalDesignAgent,TechnicalAgent}/), and
the tool-reconciled IntegratedAgent output ("hamlet_harmonized", from
HAMLET_30PXDs/IntegratedAgent/{...}/) -- reusing that existing source label/slot
rather than adding a new category. Each source is judged in "strict" and
"inference" mode, exactly as sdrf_judge.run_compare_sources() does; this script
only supplies new loaders for this dataset's directory layout, which does not
match discover_compare_sources()'s expected GoldenAnnotations/HAMLET_SDRFs tree.

technical_ref IS built for this run, from IntegratedAgent/*/PXD*_gemma.json's
per-field "sources.meti" sub-value: whenever the technical/database pipeline
(PRIDE metadata, PTM-Shepherd, RunAssessor search criteria) contributed a
field's value directly, that value is real even if it is never written in
the manuscript text, so it must not be scored as a fabrication. This applies
to all three sources (hamlet_raw, hamlet_harmonized, human_annotation): a
correct value is correct regardless of who/what produced it.

Requires OPENROUTER_API_KEY in the environment (or HAMLET_SDRF_JUDGE_BACKEND=local
with a local judge server configured, see sdrf_judge.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT / "src" / "python") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

import sdrf_judge  # noqa: E402

INPUT_DIR = Path(__file__).resolve().parent / "input_llm_judge"
TEXT_SDRF_DIR = INPUT_DIR / "TEXT_SDRF_30PXDs"
HAMLET_DIR = INPUT_DIR / "HAMLET_30PXDs"
INTEGRATED_DIR = HAMLET_DIR / "IntegratedAgent"
DEFAULT_OUT_DIR = INPUT_DIR / "compare_sources_results_30pxds"

#agent subfolder name -> file suffix used in its <PXD>_<suffix>_gemma.json files
AGENT_SUFFIXES = {
    "BiologicalAgent": "biological",
    "ExperimentalDesignAgent": "experimental",
    "TechnicalAgent": "technical",
}


def _extract_value(val) -> str | None:
    """pull the extracted value out of one field entry, whichever of the two
    schemas seen in this dataset it uses: a plain [value, quote] pair
    (HAMLET_30PXDs raw agent output) or a {resolved, confidence, status,
    sources} dict (HAMLET_30PXDs/IntegratedAgent, reconciled against meti/tool
    inference)."""
    if isinstance(val, list) and val:
        return str(val[0]).strip()
    if isinstance(val, dict):
        resolved = val.get("resolved")
        return str(resolved).strip() if resolved is not None else None
    return None


def _value_origin(val) -> str:
    """classify which pipeline stage actually produced a field's resolved value:
    'meti' (technical/database pipeline: PRIDE metadata, PTM-Shepherd, RunAssessor
    search criteria -- resolved == sources.meti.value), 'llm' (resolved == the LLM
    agent's own text reading, or a plain [value, quote] pair from the pre-integration
    per-agent output, which has no meti attribution at all), 'agree' (meti and llm
    independently produced the same value), or 'unknown' if neither source matches
    the resolved value. Distinguishing these matters because a WRONG value sourced
    from meti is a technical-pipeline extraction bug, not an LLM hallucination from
    misreading the manuscript text -- the two should not be counted as the same
    error class."""
    if isinstance(val, list):
        return "llm"
    if not isinstance(val, dict):
        return "unknown"
    resolved = val.get("resolved")
    if resolved is None:
        return "unknown"
    resolved_norm = sdrf_judge._norm(str(resolved))
    sources = val.get("sources") or {}
    meti = sources.get("meti")
    llm = sources.get("llm")
    meti_val = meti.get("value") if isinstance(meti, dict) else None
    llm_val = llm.get("value") if isinstance(llm, dict) else None
    meti_match = isinstance(meti_val, str) and sdrf_judge._norm(meti_val) == resolved_norm
    llm_match = isinstance(llm_val, str) and sdrf_judge._norm(llm_val) == resolved_norm
    if meti_match and llm_match:
        return "agree"
    if meti_match:
        return "meti"
    if llm_match:
        return "llm"
    return "unknown"


def merge_agent_jsons(pxd_id: str, agent_root: Path) -> tuple[dict[str, list[str]], dict[tuple[str, str], str]]:
    """merge the three per-agent JSONs for one PXD under agent_root into a single
    {canonical_field: [values]} dict, skipping internal (_-prefixed) keys and
    unresolved ("unknown"/"n/a"/...) values -- mirrors the unresolved-value
    handling in sdrf_judge.load_agent_predictions(). Also returns a parallel
    {(canonical_field, normalised_value): origin} map (see _value_origin) so
    downstream analysis can tell a meti-sourced extraction error apart from an
    LLM hallucination."""
    result: dict[str, list[str]] = {}
    origin: dict[tuple[str, str], str] = {}
    for agent_dir, suffix in AGENT_SUFFIXES.items():
        path = agent_root / agent_dir / f"{pxd_id}_{suffix}_gemma.json"
        if not path.is_file():
            print(f"    WARNING: missing {path}")
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"    WARNING: could not read {path}: {e}")
            continue
        for key, val in data.items():
            if key.startswith("_"):
                continue
            value = _extract_value(val)
            if not value or value.lower() in sdrf_judge._AGENT_UNRESOLVED_VALUES:
                continue
            before = {v for vals in result.values() for v in vals}
            sdrf_judge._add_annotation_value(result, key, value)
            canon = sdrf_judge.ENTITY_FIELD_ALIAS.get(sdrf_judge._camel_to_snake(key), key)
            if canon in result and value in result[canon] and value not in before:
                origin[(canon, sdrf_judge._norm(value))] = _value_origin(val)
    return result, origin


def load_technical_reference_30pxds(pxd_id: str, agent_root: Path) -> dict[str, set[str]]:
    """build the technical/meti-derived reference set for one PXD from this
    dataset's IntegratedAgent JSONs: each field's 'sources.meti.value' was
    contributed by the technical pipeline (PRIDE metadata, PTM-Shepherd,
    RunAssessor search criteria), not read from the paper text by an LLM agent,
    so a value here that the judge later calls HALLUCINATED (absent from the
    manuscript text) is not a fabrication -- just outside the judge's
    text-only view. Mirrors sdrf_judge.load_technical_reference() but reads
    this dataset's flat 'sources': {'meti': ..., 'llm': ...} schema directly
    instead of a separate enriched.json / aggregated_results.json."""
    ref: dict[str, set[str]] = {}
    for agent_dir, suffix in AGENT_SUFFIXES.items():
        path = agent_root / agent_dir / f"{pxd_id}_{suffix}_gemma.json"
        if not path.is_file():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        for key, val in data.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            meti = (val.get("sources") or {}).get("meti")
            meti_value = meti.get("value") if isinstance(meti, dict) else None
            if not isinstance(meti_value, str) or not meti_value.strip():
                continue
            canon = sdrf_judge.ENTITY_FIELD_ALIAS.get(sdrf_judge._camel_to_snake(key))
            if not canon:
                continue
            ref.setdefault(canon, set()).add(sdrf_judge._norm(meti_value))
    return ref


def load_ground_truth(pxd_id: str, pxd_dir: Path) -> dict[str, list[str]]:
    annotation_json = pxd_dir / f"{pxd_id}_annotation.json"
    if annotation_json.is_file():
        return sdrf_judge.load_human_annotation(str(annotation_json))
    sdrf_tsv = pxd_dir / f"{pxd_id}.sdrf.tsv"
    if sdrf_tsv.is_file():
        return sdrf_judge.load_sdrf(str(pxd_dir), pxd_id)
    print(f"    WARNING: no ground truth found for {pxd_id} in {pxd_dir}")
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--modes", default="strict,inference")
    parser.add_argument("--limit", type=int, default=None,
                        help="Evaluate only the first N PXDs (sorted), for a quick smoke test")
    parser.add_argument("--workers", type=int, default=None,
                        help=f"Max parallel LLM calls (default: {sdrf_judge.MAX_WORKERS})")
    args = parser.parse_args()

    if args.workers:
        sdrf_judge.MAX_WORKERS = args.workers

    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    #redirect the judge's disk cache under out_dir and reset the singleton so it
    #picks up the new cache dir on first use (mirrors run_compare_sources())
    sdrf_judge.CACHE_DIR = str(out_dir / f".prompt_cache_{sdrf_judge._CACHE_MODEL_SLUG}")
    sdrf_judge._judge_model = None

    pxd_dirs = sorted(p for p in TEXT_SDRF_DIR.iterdir() if p.is_dir())
    if args.limit:
        pxd_dirs = pxd_dirs[: args.limit]
    print(f"  PXDs to judge: {len(pxd_dirs)}  {[p.name for p in pxd_dirs]}")

    summary_rows: list[dict] = []
    all_review: list[pd.DataFrame] = []

    for pxd_dir in pxd_dirs:
        pxd_id = pxd_dir.name
        text_path = pxd_dir / "manuscript.txt"
        if not text_path.is_file():
            print(f"  SKIP {pxd_id}: no manuscript.txt.")
            continue
        source_text = sdrf_judge._extract_sections_or_full(
            sdrf_judge._read_text_file(str(text_path)), f"Text [{pxd_id}]")
        if not source_text:
            print(f"  SKIP {pxd_id}: manuscript text is empty.")
            continue

        sources: dict[str, dict] = {}
        ground_truth = load_ground_truth(pxd_id, pxd_dir)
        if ground_truth:
            sources["human_annotation"] = ground_truth
        hamlet_raw, _ = merge_agent_jsons(pxd_id, HAMLET_DIR)
        if hamlet_raw:
            sources["hamlet_raw"] = hamlet_raw
        hamlet_harmonized, _ = merge_agent_jsons(pxd_id, INTEGRATED_DIR)
        if hamlet_harmonized:
            sources["hamlet_harmonized"] = hamlet_harmonized

        if not sources:
            print(f"  SKIP {pxd_id}: no extraction source available.")
            continue

        technical_ref = load_technical_reference_30pxds(pxd_id, INTEGRATED_DIR)

        for source_label, predicted in sources.items():
            for mode in modes:
                print(f"  [{pxd_id}] source={source_label}  mode={mode}  "
                      f"({len(predicted)} field(s))")
                df, per_paper_df = sdrf_judge.evaluate_source(
                    pxd_id, predicted, source_text, str(out_dir), source_label,
                    mode=mode, technical_ref=technical_ref)
                if not df.empty:
                    all_review.append(df)
                if not per_paper_df.empty:
                    summary_rows.append(per_paper_df.iloc[0].to_dict())

    if not summary_rows:
        print("ERROR: no comparable data produced.")
        return

    summary_df = pd.DataFrame(summary_rows)
    summary_path = out_dir / "source_comparison_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"\nSource comparison summary written to: {summary_path}")

    if all_review:
        review_df = pd.concat(all_review, ignore_index=True)
        review_path = out_dir / "source_comparison_review.csv"
        review_df.to_csv(review_path, index=False)
        print(f"Source comparison review written to: {review_path}")

    sdrf_judge.plot_source_comparison(summary_df, str(out_dir))

    print("\nMean judge accuracy by source and mode:")
    raw_acc = summary_df.groupby(["source", "mode"])["judge_accuracy"].mean()
    for key in raw_acc.index:
        source, mode = key
        print(f"  {source:<20} {mode:<10} {raw_acc[key]:.1%}")


if __name__ == "__main__":
    main()
