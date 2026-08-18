#!/usr/bin/env python3
"""Consensus across three independent LLM-as-judge passes over the 30-PXD set.

Each of the three runs (run1/run2/run3, produced by
run_llm_judge_30pxds.py --out-dir compare_sources_results_30pxds_run{N})
judges the same extracted values independently -- same input data, but each
run has its own disk-response cache directory, so the judge model is called
fresh in each run rather than replaying a cached verdict. Reading the three
runs' source_comparison_review.csv files side by side and majority-voting per
(paper_id, source, mode, annotation_type, extracted_value) both (a) reduces
the impact of single-call judge noise on the final verdict and (b) quantifies
how much that noise actually is, via the agreement-rate metrics below.

Writes, under input_llm_judge/compare_sources_results_30pxds_consensus/:
  consensus_review.csv     -- one row per judged value, with each run's verdict/
                               value_correct/hallucination/error_category, the
                               majority vote, and n_agree (how many of the
                               available runs agreed with the majority)
  consensus_summary.csv    -- per (paper_id, source, mode) accuracy computed from
                               the majority verdict, same shape as
                               source_comparison_summary.csv
  accuracy_variability.csv -- per (paper_id, source, mode), each run's own
                               judge_accuracy plus mean/std/range across the 3
  agreement_report.txt     -- overall + per-source/mode unanimous-agreement
                               rates (verdict and error_category) and accuracy
                               spread (std/range in pp)
  variability_by_source_mode.png -- bar chart of judge-noise (std of
                               judge_accuracy across the 3 runs) per source x mode
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src" / "analysis") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src" / "analysis"))

INPUT_DIR = Path(__file__).resolve().parent / "input_llm_judge"
RUN_DIRS = [INPUT_DIR / f"compare_sources_results_30pxds_run{n}" for n in (1, 2, 3)]
OUT_DIR = INPUT_DIR / "compare_sources_results_30pxds_consensus"

KEY_COLS = ["paper_id", "source", "mode", "annotation_type", "extracted_value"]


def _parse_bool(v) -> bool | None:
    if isinstance(v, bool):
        return v
    if pd.isna(v):
        return None
    return str(v).strip().lower() in {"true", "1", "yes"}


def load_run_review(run_dir: Path, run_idx: int) -> pd.DataFrame:
    path = run_dir / "source_comparison_review.csv"
    if not path.is_file():
        raise FileNotFoundError(f"missing {path} -- did run {run_idx} finish?")
    df = pd.read_csv(path)
    for col in ("value_correct", "value_complete", "hallucination"):
        if col in df.columns:
            df[col] = df[col].map(_parse_bool)
    #error_category (correct_explicit/inferred/hallucinated/meti_only/type_mismatch/
    #wrong_value/incomplete) is the single authoritative classification -- see
    #sdrf_judge._classify_row. Older runs predating that field simply won't have
    #the column; fall back to plain None so the merge/majority logic still works.
    if "error_category" not in df.columns:
        df["error_category"] = None
    keep = KEY_COLS + ["verdict", "value_correct", "value_complete", "hallucination",
                       "error_category", "corrected_value"]
    df = df[keep].copy()
    df.columns = [c if c in KEY_COLS else f"{c}_run{run_idx}" for c in df.columns]
    return df


def majority(values: list) -> tuple:
    """return (majority_value, n_agree, n_total) over the non-null values seen"""
    clean = [v for v in values if v is not None and not (isinstance(v, float) and pd.isna(v))]
    if not clean:
        return None, 0, 0
    counts = Counter(clean)
    winner, n_agree = counts.most_common(1)[0]
    return winner, n_agree, len(clean)


def main() -> None:
    for d in RUN_DIRS:
        if not d.is_dir():
            sys.exit(f"ERROR: {d} does not exist -- run all three passes first")

    runs = [load_run_review(d, i + 1) for i, d in enumerate(RUN_DIRS)]

    merged = runs[0]
    for r in runs[1:]:
        merged = merged.merge(r, on=KEY_COLS, how="outer")

    n_rows = len(merged)
    n_all_three = merged[[f"verdict_run{i}" for i in (1, 2, 3)]].notna().all(axis=1).sum()
    print(f"  Merged {n_rows} distinct judged values; {n_all_three} present in all 3 runs "
          f"({n_rows - n_all_three} present in only 1-2 runs -- extraction differed or a run errored on that key)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    consensus_rows = []
    for _, row in merged.iterrows():
        verdicts = [row.get(f"verdict_run{i}") for i in (1, 2, 3)]
        correct_vals = [row.get(f"value_correct_run{i}") for i in (1, 2, 3)]
        halluc_vals = [row.get(f"hallucination_run{i}") for i in (1, 2, 3)]
        categories = [row.get(f"error_category_run{i}") for i in (1, 2, 3)]

        maj_verdict, n_agree_verdict, n_total_verdict = majority(verdicts)
        maj_correct, n_agree_correct, n_total_correct = majority(correct_vals)
        maj_halluc, n_agree_halluc, n_total_halluc = majority(halluc_vals)
        maj_category, n_agree_category, n_total_category = majority(categories)

        out_row = {c: row[c] for c in KEY_COLS}
        for i in (1, 2, 3):
            out_row[f"verdict_run{i}"] = row.get(f"verdict_run{i}")
            out_row[f"value_correct_run{i}"] = row.get(f"value_correct_run{i}")
            out_row[f"hallucination_run{i}"] = row.get(f"hallucination_run{i}")
            out_row[f"error_category_run{i}"] = row.get(f"error_category_run{i}")
        out_row["consensus_verdict"] = maj_verdict
        out_row["consensus_value_correct"] = maj_correct
        out_row["consensus_hallucination"] = maj_halluc
        out_row["consensus_error_category"] = maj_category
        out_row["n_agree_verdict"] = n_agree_verdict
        out_row["n_total_verdict"] = n_total_verdict
        out_row["n_agree_category"] = n_agree_category
        out_row["n_total_category"] = n_total_category
        out_row["unanimous"] = (n_total_verdict > 0 and n_agree_verdict == n_total_verdict)
        out_row["unanimous_category"] = (n_total_category > 0 and n_agree_category == n_total_category)
        consensus_rows.append(out_row)

    consensus_df = pd.DataFrame(consensus_rows)
    consensus_review_path = OUT_DIR / "consensus_review.csv"
    consensus_df.to_csv(consensus_review_path, index=False)
    print(f"  Consensus review written to: {consensus_review_path}")

    # per (paper_id, source, mode) accuracy from the majority-vote correctness,
    # mirroring _compute_single_paper_stats' judge_accuracy definition
    summary_rows = []
    for (paper_id, source, mode), group in consensus_df.groupby(["paper_id", "source", "mode"]):
        judged = group[group["consensus_value_correct"].notna()]
        total = len(judged)
        n_correct = int((judged["consensus_value_correct"] == True).sum())  # noqa: E712
        n_halluc = int((group["consensus_hallucination"] == True).sum())  # noqa: E712
        summary_rows.append({
            "paper_id": paper_id, "source": source, "mode": mode,
            "total_extracted": len(group),
            "judge_n_correct": n_correct,
            "judge_n_hallucinated": n_halluc,
            "judge_accuracy": n_correct / total if total else float("nan"),
            "judge_accuracy_adjusted": n_correct / total if total else float("nan"),
            "mean_unanimous_rate": group["unanimous"].mean(),
            "mean_unanimous_category_rate": group["unanimous_category"].mean(),
        })
    summary_df = pd.DataFrame(summary_rows)
    summary_path = OUT_DIR / "consensus_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"  Consensus summary written to: {summary_path}")

    # -------------------------------------------------------------------
    # Judge-noise variability: how much does each RUN's own reported
    # judge_accuracy (from source_comparison_summary.csv, i.e. the actual
    # headline number each run would produce standalone) fluctuate for the
    # exact same (paper_id, source, mode) across the 3 independent passes?
    # This is a different lens from the per-row agreement above -- it's the
    # spread in the metric that actually gets plotted/reported.
    # -------------------------------------------------------------------
    acc_frames = []
    for i, d in enumerate(RUN_DIRS, start=1):
        acc_path = d / "source_comparison_summary.csv"
        if not acc_path.is_file():
            continue
        acc_df = pd.read_csv(acc_path)[["paper_id", "source", "mode", "judge_accuracy"]]
        acc_df = acc_df.rename(columns={"judge_accuracy": f"judge_accuracy_run{i}"})
        acc_frames.append(acc_df)
    variability_df = None
    if len(acc_frames) == 3:
        variability_df = acc_frames[0]
        for f in acc_frames[1:]:
            variability_df = variability_df.merge(f, on=["paper_id", "source", "mode"], how="outer")
        run_cols = [f"judge_accuracy_run{i}" for i in (1, 2, 3)]
        variability_df["mean_accuracy"] = variability_df[run_cols].mean(axis=1)
        variability_df["std_accuracy"]  = variability_df[run_cols].std(axis=1)
        variability_df["range_accuracy"] = (
            variability_df[run_cols].max(axis=1) - variability_df[run_cols].min(axis=1))
        variability_path = OUT_DIR / "accuracy_variability.csv"
        variability_df.to_csv(variability_path, index=False)
        print(f"  Accuracy variability written to: {variability_path}")

    # agreement report: how often do the 3 independent judge passes actually agree?
    lines = []
    overall_unanimous_rate = consensus_df["unanimous"].mean()
    overall_unanimous_cat_rate = consensus_df["unanimous_category"].mean()
    lines.append(f"Overall unanimous-agreement rate (3/3 runs agree on verdict): {overall_unanimous_rate:.1%}")
    lines.append(f"Overall unanimous-agreement rate (3/3 runs agree on error_category): {overall_unanimous_cat_rate:.1%}")
    lines.append(f"Rows judged in all 3 runs: {n_all_three} / {n_rows}")
    lines.append("")
    lines.append("Unanimous-agreement rate by source x mode (verdict / error_category):")
    by_group = consensus_df.groupby(["source", "mode"])[["unanimous", "unanimous_category"]].mean().sort_index()
    for (source, mode), row in by_group.iterrows():
        lines.append(f"  {source:<20} {mode:<10} verdict={row['unanimous']:.1%}  "
                      f"category={row['unanimous_category']:.1%}")
    if variability_df is not None:
        lines.append("")
        lines.append("Judge_accuracy spread across the 3 runs, by source x mode "
                      "(mean std dev / mean range, in percentage points):")
        by_group2 = variability_df.groupby(["source", "mode"])[["std_accuracy", "range_accuracy"]].mean().sort_index()
        for (source, mode), row in by_group2.iterrows():
            lines.append(f"  {source:<20} {mode:<10} std={row['std_accuracy']*100:.1f}pp  "
                          f"range={row['range_accuracy']*100:.1f}pp")
    report_path = OUT_DIR / "agreement_report.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Agreement report written to: {report_path}")
    print()
    print("\n".join(lines))

    if variability_df is not None:
        plot_variability(variability_df, OUT_DIR)


def draw_variability_panel(ax, variability_df: pd.DataFrame, show_title: bool = True,
                            legend: bool = True) -> None:
    """bar chart of judge-noise (std of judge_accuracy across the 3 runs) per
    source x mode -- how much does the headline accuracy number move around
    just from re-running the same judge on the same data three times? Drawn
    onto an existing axes so it can be reused standalone or inside a
    composite figure."""
    import matplotlib.pyplot as plt
    from plot_style import COLORS, clean_axes

    source_order = ["hamlet_raw", "hamlet_harmonized", "human_annotation"]
    source_color = {"hamlet_raw": COLORS["orange"], "hamlet_harmonized": COLORS["green"],
                     "human_annotation": COLORS["dark_blue"]}
    mode_order = ["strict", "inference"]

    grouped = variability_df.groupby(["source", "mode"])["std_accuracy"].mean()

    x = np.arange(len(source_order))
    bar_w = 0.35
    for i, mode in enumerate(mode_order):
        vals = [grouped.get((s, mode), np.nan) * 100 for s in source_order]
        offset = (i - 0.5) * bar_w
        bars = ax.bar(x + offset, vals, bar_w,
                       color=[source_color[s] for s in source_order],
                       alpha=(0.87 if mode == "strict" else 0.5),
                       edgecolor="white", linewidth=0.5,
                       hatch=("" if mode == "strict" else "//"), zorder=3)
        for bar, v in zip(bars, vals):
            if not np.isnan(v):
                ax.text(bar.get_x() + bar.get_width() / 2, v + 0.1, f"{v:.1f}pp",
                        ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels(["HAMLET raw", "HAMLET harmonized", "SDRF-Proteomics"], fontsize=9.5)
    ax.set_ylabel("Std. dev. of judge_accuracy across 3 independent runs (pp)", fontsize=10)
    if show_title:
        ax.set_title("Judge noise: how much does accuracy move run-to-run\non identical input data?",
                      fontsize=11, fontstyle="italic", fontweight="normal", pad=7)
    clean_axes(ax)
    if legend:
        legend_handles = [
            plt.Rectangle((0, 0), 1, 1, facecolor="gray", alpha=0.87, edgecolor="white", label="Strict"),
            plt.Rectangle((0, 0), 1, 1, facecolor="gray", alpha=0.5, hatch="//", edgecolor="white", label="Inference"),
        ]
        ax.legend(handles=legend_handles, loc="upper left", framealpha=0.9, fontsize=9.5)


def plot_variability(variability_df: pd.DataFrame, out_dir: Path) -> None:
    import matplotlib.pyplot as plt
    from plot_style import add_suptitle, save_fig

    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    draw_variability_panel(ax, variability_df)
    add_suptitle(fig, "LLM-as-judge reproducibility: 3 independent passes, same input",
                  "compare_sources_results_30pxds_run{1,2,3} (Gemma-4-31B judge)")
    save_fig(fig, out_dir / "variability_by_source_mode.png")
    plt.close(fig)
    print(f"  Variability plot written to: {out_dir / 'variability_by_source_mode.png'}")


if __name__ == "__main__":
    main()
