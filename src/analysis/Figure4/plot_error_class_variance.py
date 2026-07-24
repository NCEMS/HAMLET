#!/usr/bin/env python3
"""Which SDRF fields drive hallucination / type-mismatch / wrong-value errors,
per source, and how much does the judge's verdict on that field move across
independent runs?

For each of the 3 sources (HAMLET raw, HAMLET harmonized, SDRF-Proteomics)
this draws one standalone figure of grouped horizontal bars: per
annotation_type, four bars side by side -- hallucination rate, type-mismatch
rate, wrong-value rate (inference mode, averaged over the 3 reproducibility
runs), and run-to-run disagreement rate (share of rows where the 3 runs did
NOT unanimously agree on error_category), from the same 3 runs. Each source
panel is sorted and filtered independently, since which fields dominate
differs a lot by source (e.g. harmonization only rewrites a couple of
fields; most pass through unchanged from raw). All three figures share the
same x-axis (0-1) so error/variance magnitudes are directly comparable
across sources.

Reads compare_sources_results_30pxds_run{1,2,3}/source_comparison_review.csv
and writes one PNG per source into compare_sources_results_30pxds_consensus/.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plot_style import COLORS, clean_axes, add_suptitle, save_fig  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent / "input_llm_judge"
RUN_DIRS = [BASE_DIR / f"compare_sources_results_30pxds_run{r}" for r in (1, 2, 3)]
OUT_DIR = BASE_DIR / "compare_sources_results_30pxds_consensus"

MIN_N = 10   # drop annotation_types too rare, per source, to trust a rate estimate
TOP_N = 10   # classes shown per source figure
X_MAX = 1.0  # fixed x-axis, shared across all 3 source figures

SOURCE_ORDER = ["hamlet_raw", "hamlet_harmonized", "human_annotation"]
SOURCE_LABEL = {
    "hamlet_raw": "HAMLET raw (pre-harmonization)",
    "hamlet_harmonized": "HAMLET harmonized (final SDRF)",
    "human_annotation": "SDRF-Proteomics (expert gold standard)",
}
SOURCE_FILENAME = {
    "hamlet_raw": "error_class_variance_hamlet_raw.png",
    "hamlet_harmonized": "error_class_variance_hamlet_harmonized.png",
    "human_annotation": "error_class_variance_sdrf_proteomics.png",
}

METRICS = [
    ("halluc_rate", "Hallucinated", COLORS["red"]),
    ("mismatch_rate", "Type mismatch", COLORS["purple"]),
    ("wrong_rate", "Wrong value", COLORS["orange"]),
    ("disagreement", "Run-to-run disagreement (judge variance)", COLORS["blue"]),
]


def load_rates_and_agreement() -> pd.DataFrame:
    run_dfs = [pd.read_csv(d / "source_comparison_review.csv") for d in RUN_DIRS]

    #per-run, per-(source, annotation_type) error rates, inference mode
    rate_rows = []
    for run_idx, df in enumerate(run_dfs, start=1):
        inf = df[df["mode"] == "inference"]
        g = inf.groupby(["source", "annotation_type"])["error_category"].agg(
            n="count",
            halluc=lambda s: (s == "hallucinated").sum(),
            mismatch=lambda s: (s == "type_mismatch").sum(),
            wrong=lambda s: (s == "wrong_value").sum(),
        )
        g["run"] = run_idx
        rate_rows.append(g.reset_index())
    allr = pd.concat(rate_rows)
    for col in ("halluc", "mismatch", "wrong"):
        allr[f"{col}_rate"] = allr[col] / allr["n"]
    rates = allr.groupby(["source", "annotation_type"]).agg(
        n=("n", "mean"), halluc_rate=("halluc_rate", "mean"),
        mismatch_rate=("mismatch_rate", "mean"), wrong_rate=("wrong_rate", "mean"))
    rates["combined_error_rate"] = rates["halluc_rate"] + rates["mismatch_rate"] + rates["wrong_rate"]

    #run-to-run unanimity on error_category, inference mode -- rows are in
    #identical (paper_id, source, mode, agent, annotation_type) order across
    #the 3 run CSVs (same deterministic extraction pipeline, only the judge
    #varies), so a positional compare is valid.
    key_cols = ["paper_id", "source", "mode", "agent", "annotation_type"]
    base = run_dfs[0][key_cols].copy()
    for run_idx, df in enumerate(run_dfs, start=1):
        base[f"cat{run_idx}"] = df["error_category"]
    base = base[base["mode"] == "inference"]
    base["unanimous"] = (base["cat1"] == base["cat2"]) & (base["cat2"] == base["cat3"])
    agreement = base.groupby(["source", "annotation_type"])["unanimous"].mean().rename("agreement")

    summary = rates.join(agreement)
    summary["disagreement"] = 1 - summary["agreement"]
    return summary[summary["n"] >= MIN_N]


def draw_source_panel(ax: plt.Axes, summary: pd.DataFrame, source: str, top_n: int = TOP_N,
                       label_fontsize: float = 9.5, value_fontsize: float = 9.5,
                       legend: bool = True) -> None:
    """draw the grouped-bar class-driver panel for one source onto an existing axes
    (shared by the standalone per-source figures and any composite that reuses them)"""
    sub = summary.xs(source, level="source").sort_values("combined_error_rate", ascending=False).head(top_n)
    sub = sub.iloc[::-1]  # biggest driver at the top

    n_classes = len(sub)
    n_metrics = len(METRICS)

    #zebra striping behind each class group, for readability at this width
    for i in range(n_classes):
        if i % 2 == 1:
            ax.axhspan(i - 0.5, i + 0.5, color="#f2f2f2", zorder=0)

    bar_h = 0.85 / n_metrics
    y = np.arange(n_classes)
    for i, (col, label, color) in enumerate(METRICS):
        offset = (i - (n_metrics - 1) / 2) * bar_h
        bars = ax.barh(y + offset, sub[col], height=bar_h * 0.88, color=color, alpha=0.9,
                        edgecolor="white", linewidth=0.6, label=label, zorder=3)
        for bar, v in zip(bars, sub[col]):
            if v > 0.015:
                ax.text(bar.get_width() + 0.012, bar.get_y() + bar.get_height() / 2,
                        f"{v:.0%}", va="center", ha="left", fontsize=value_fontsize,
                        color="#333333", zorder=4)

    ax.set_yticks(y)
    ax.set_yticklabels([f"{t}  (n={int(n)})" for t, n in zip(sub.index, sub["n"])], fontsize=label_fontsize)
    ax.set_xlabel("Rate (inference mode, mean over 3 judge runs)", fontsize=label_fontsize + 1.5)
    ax.set_ylim(-0.5, n_classes - 0.5)
    ax.set_xlim(0, X_MAX)
    ax.set_xticks(np.arange(0, X_MAX + 0.01, 0.1))
    clean_axes(ax, grid_axis="x")
    if legend:
        ax.legend(loc="lower right", framealpha=0.92, fontsize=label_fontsize + 0.5)


def draw_source_figure(summary: pd.DataFrame, source: str, n_papers: int) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(15, 1.0 * min(TOP_N, len(summary.xs(source, level="source"))) + 1.8))
    draw_source_panel(ax, summary, source, top_n=TOP_N, label_fontsize=11, value_fontsize=9.5)

    add_suptitle(fig, f"Error class drivers and judge reproducibility -- {SOURCE_LABEL[source]}",
                 f"compare_sources_results_30pxds_run{{1,2,3}} (inference mode, top {TOP_N} classes "
                 f"with n >= {MIN_N} judged rows/field, n = {n_papers} papers, Gemma-4-31B judge)")
    return fig


def main() -> None:
    summary = load_rates_and_agreement()
    review = pd.read_csv(RUN_DIRS[0] / "source_comparison_review.csv")
    n_papers = review["paper_id"].nunique()

    for source in SOURCE_ORDER:
        fig = draw_source_figure(summary, source, n_papers)
        save_fig(fig, OUT_DIR / SOURCE_FILENAME[source])
        plt.close(fig)


if __name__ == "__main__":
    main()
