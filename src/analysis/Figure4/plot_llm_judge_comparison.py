#!/usr/bin/env python3
"""Figures for the LLM-as-judge source comparison (human annotation vs. raw HAMLET
agent output vs. harmonized HAMLET SDRF, each judged in strict and inference mode).

Reads compare_sources_results/source_comparison_summary.csv (written by
sdrf_judge.py --compare-sources) and writes one PNG per panel plus a 2x2
composite into the same directory.
"""

from __future__ import annotations

import argparse
import sys
from functools import partial
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plot_style import COLORS, clean_axes, add_suptitle, save_fig  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "input_llm_judge" / "compare_sources_results"
SUMMARY_CSV = RESULTS_DIR / "source_comparison_summary.csv"

# fixed categorical assignment, source = pipeline stage (never re-derived per plot)
SOURCE_ORDER = ["hamlet_raw", "hamlet_harmonized", "human_annotation"]
SOURCE_LABEL = {
    "hamlet_raw": "HAMLET raw\n(pre-harmonization)",
    "hamlet_harmonized": "HAMLET harmonized\n(final SDRF)",
    "human_annotation": "SDRF-Proteomics\n(expert gold standard)",
}
SOURCE_COLOR = {
    "hamlet_raw": COLORS["orange"],
    "hamlet_harmonized": COLORS["green"],
    "human_annotation": COLORS["dark_blue"],
}
MODE_ORDER = ["strict", "inference"]
MODE_LABEL = {"strict": "Strict (explicit extraction only)", "inference": "Inference (expert-inferable allowed)"}


def load_summary() -> pd.DataFrame:
    df = pd.read_csv(SUMMARY_CSV)
    df["source"] = pd.Categorical(df["source"], categories=SOURCE_ORDER, ordered=True)
    df["mode"] = pd.Categorical(df["mode"], categories=MODE_ORDER, ordered=True)
    #judge_accuracy_effective is what "accuracy" should mean for headline plots:
    #for strict-mode rows it's just judge_accuracy (no inference concept exists
    #in strict mode). For inference-mode rows, judge_accuracy itself only counts
    #genuinely EXPLICIT matches (INFERENCE: yes values are a separate, distinct
    #bucket -- see sdrf_judge.py's INFERENCE MODE OUTPUT FIELD), so the number
    #that actually reflects "how well this source does once expert-level
    #inference is allowed" is judge_accuracy_with_inference.
    if "judge_accuracy_with_inference" in df.columns:
        df["judge_accuracy_effective"] = np.where(
            df["mode"] == "inference",
            df["judge_accuracy_with_inference"], df["judge_accuracy"])
    else:
        df["judge_accuracy_effective"] = df["judge_accuracy"]
    return df


# -----------------------------------------------------------------------------
# Panel 1: mean accuracy by source x mode, with per-source n and SD
# -----------------------------------------------------------------------------

def draw_panel_mean_accuracy(ax: plt.Axes, df: pd.DataFrame) -> None:
    grouped = df.groupby(["source", "mode"], observed=True)["judge_accuracy_effective"].agg(["mean", "std", "count"])

    n_sources = len(SOURCE_ORDER)
    bar_w = 0.35
    x = np.arange(n_sources)

    for i, mode in enumerate(MODE_ORDER):
        means, stds, ns = [], [], []
        for source in SOURCE_ORDER:
            row = grouped.loc[(source, mode)]
            means.append(row["mean"])
            stds.append(0 if pd.isna(row["std"]) else row["std"])
            ns.append(int(row["count"]))
        offset = (i - 0.5) * bar_w
        bars = ax.bar(
            x + offset, means, bar_w,
            color=[SOURCE_COLOR[s] for s in SOURCE_ORDER],
            alpha=(0.87 if mode == "strict" else 0.5),
            edgecolor="white", linewidth=0.5,
            hatch=("" if mode == "strict" else "//"),
            yerr=stds, capsize=5, error_kw={"linewidth": 1, "ecolor": "#444444"},
            zorder=3,
        )
        for bar, mean, sd, n in zip(bars, means, stds, ns):
            ax.text(bar.get_x() + bar.get_width() / 2, mean + sd + 0.02,
                    f"{mean:.0%} ± {sd:.0%}\n(n={n})", ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels([SOURCE_LABEL[s] for s in SOURCE_ORDER], fontsize=9.5)
    ax.set_ylabel("Mean judge accuracy", fontsize=10)
    ax.set_ylim(0, 1.2)
    ax.set_title("Extraction accuracy by source and judge mode",
                 fontsize=11, fontstyle="italic", fontweight="normal", pad=7)
    clean_axes(ax)

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor="gray", alpha=0.87, edgecolor="white", label="Strict"),
        plt.Rectangle((0, 0), 1, 1, facecolor="gray", alpha=0.5, hatch="//", edgecolor="white", label="Inference"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", framealpha=0.9, fontsize=9.5)


# -----------------------------------------------------------------------------
# Panel 2: per-PXD improvement from raw -> harmonized (the PXDs where both exist)
# -----------------------------------------------------------------------------

def draw_panel_raw_vs_harmonized(ax: plt.Axes, df: pd.DataFrame) -> None:
    pivot = (
        df[df["source"].isin(["hamlet_raw", "hamlet_harmonized"])]
        .pivot_table(index=["paper_id", "mode"], columns="source", values="judge_accuracy", observed=True)
        .dropna()
        .reset_index()
    )

    if pivot.empty:
        ax.text(0.5, 0.5, "No PXDs with both raw and harmonized SDRF", ha="center", va="center",
                transform=ax.transAxes, fontsize=10, color="#888888")
        ax.set_axis_off()
        return

    papers = sorted(pivot["paper_id"].unique())
    y_positions = {p: i for i, p in enumerate(papers)}
    mode_dy = {"strict": 0.12, "inference": -0.12}
    mode_marker = {"strict": "o", "inference": "^"}

    for _, row in pivot.iterrows():
        y = y_positions[row["paper_id"]] + mode_dy[row["mode"]]
        ax.plot([row["hamlet_raw"], row["hamlet_harmonized"]], [y, y],
                color="#999999", lw=1.4, zorder=1)
        ax.scatter(row["hamlet_raw"], y, color=SOURCE_COLOR["hamlet_raw"],
                   marker=mode_marker[row["mode"]], s=70, zorder=3, edgecolor="white", linewidth=0.6)
        ax.scatter(row["hamlet_harmonized"], y, color=SOURCE_COLOR["hamlet_harmonized"],
                   marker=mode_marker[row["mode"]], s=70, zorder=3, edgecolor="white", linewidth=0.6)
        delta = row["hamlet_harmonized"] - row["hamlet_raw"]
        ax.text(max(row["hamlet_raw"], row["hamlet_harmonized"]) + 0.03, y,
                f"{delta:+.0%}", va="center", fontsize=8,
                color=(COLORS["green"] if delta >= 0 else COLORS["red"]), fontweight="bold")

    ax.set_yticks(list(y_positions.values()))
    ax.set_yticklabels(list(y_positions.keys()), fontsize=9.5)
    ax.set_xlabel("Judge accuracy", fontsize=10)
    ax.set_xlim(0, 1.25)
    ax.set_title("Harmonization improvement, per paper\n(only PXDs with both a raw and harmonized SDRF)",
                 fontsize=11, fontstyle="italic", fontweight="normal", pad=7)
    clean_axes(ax, grid_axis="x")

    legend_handles = [
        plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=SOURCE_COLOR["hamlet_raw"],
                   markersize=9, label="HAMLET raw"),
        plt.Line2D([0], [0], marker="o", color="none", markerfacecolor=SOURCE_COLOR["hamlet_harmonized"],
                   markersize=9, label="HAMLET harmonized"),
        plt.Line2D([0], [0], marker="o", color="gray", markerfacecolor="gray", markersize=7,
                   label="Strict mode", linestyle="none"),
        plt.Line2D([0], [0], marker="^", color="gray", markerfacecolor="gray", markersize=7,
                   label="Inference mode", linestyle="none"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", framealpha=0.9, fontsize=9)


# -----------------------------------------------------------------------------
# Panel 3: strict -> inference headroom per source (paired per PXD)
# -----------------------------------------------------------------------------

def draw_panel_inference_headroom(ax: plt.Axes, df: pd.DataFrame) -> None:
    pivot = df.pivot_table(index=["paper_id", "source"], columns="mode",
                            values="judge_accuracy_effective", observed=True).dropna().reset_index()
    pivot["delta"] = pivot["inference"] - pivot["strict"]

    rng = np.random.default_rng(7)
    for i, source in enumerate(SOURCE_ORDER):
        vals = pivot.loc[pivot["source"] == source, "delta"].values
        if len(vals) == 0:
            continue
        jitter = rng.normal(0, 0.06, size=len(vals))
        ax.scatter(np.full(len(vals), i) + jitter, vals, color=SOURCE_COLOR[source],
                   s=45, alpha=0.85, edgecolor="white", linewidth=0.5, zorder=3)
        mean = vals.mean()
        ax.hlines(mean, i - 0.28, i + 0.28, color="black", lw=2.2, zorder=4)
        ax.text(i, mean + (0.025 if mean >= 0 else -0.06), f"{mean:+.1%}",
                ha="center", fontsize=9, fontweight="bold")

    ax.axhline(0, color="#888888", lw=1, linestyle="--", zorder=1)
    ax.set_xticks(range(len(SOURCE_ORDER)))
    ax.set_xticklabels([SOURCE_LABEL[s] for s in SOURCE_ORDER], fontsize=9.5)
    ax.set_ylabel("Accuracy gain, inference vs. strict mode (pp)", fontsize=10)
    ax.set_title("Headroom unlocked by allowing expert-level inference\n(one point per paper)",
                 fontsize=11, fontstyle="italic", fontweight="normal", pad=7)
    clean_axes(ax)


# -----------------------------------------------------------------------------
# Panel 4 (strict mode) / Panel 6 (inference mode): error composition by source
#
# _classify_row in sdrf_judge.py assigns each extracted value to exactly ONE
# of seven mutually-exclusive categories, in precedence order: technical
# origin (meti_only) is checked *before* hallucination, so
# judge_n_technical_not_in_text and judge_n_hallucinated never overlap --
# judge_n_correct + judge_n_hallucinated + judge_n_mismatch + judge_n_wrong +
# judge_n_incomplete + judge_n_technical_not_in_text + judge_n_inferred sums
# exactly to total_extracted for every row. Stack all seven directly; do not
# subtract one from another. judge_n_inferred (inference mode only) is a
# further distinct category: values the judge accepted (HALLUCINATED: no)
# only via inference mode's relaxed SOURCE CHECK (a confident expert
# inference, not a literal match, and not a hallucination) -- see
# sdrf_judge.py's INFERENCE MODE OUTPUT FIELD. Always 0 in strict mode.
# -----------------------------------------------------------------------------

TECHNICAL_COLOR = "#888888"
INFERRED_COLOR  = COLORS.get("teal", "#3fa7a7")

ERROR_CATEGORIES = [
    ("judge_n_correct", "Correct (explicit)", COLORS["green"]),
    ("judge_n_inferred", "Inferred (expert inference, not a hallucination)", INFERRED_COLOR),
    ("judge_n_hallucinated", "Hallucinated (other)", COLORS["red"]),
    ("judge_n_technical_not_in_text", "Hallucinated (technical origin, not in text)", TECHNICAL_COLOR),
    ("judge_n_mismatch", "Type mismatch", COLORS["purple"]),
    ("judge_n_wrong", "Wrong value", COLORS["orange"]),
    ("judge_n_incomplete", "Incomplete", COLORS["blue"]),
]


def draw_panel_error_composition(ax: plt.Axes, df: pd.DataFrame, mode: str = "strict",
                                  show_title: bool = True, legend: bool = True,
                                  legend_loc: str = "outside") -> None:
    mode_df = df[df["mode"] == mode].copy()
    if "judge_n_inferred" not in mode_df.columns:
        mode_df["judge_n_inferred"] = 0

    totals = mode_df.groupby("source", observed=True)[[c for c, _, _ in ERROR_CATEGORIES]].sum()
    totals = totals.reindex(SOURCE_ORDER)
    row_sums = totals.sum(axis=1)
    fractions = totals.div(row_sums, axis=0)

    x = np.arange(len(SOURCE_ORDER))
    bottom = np.zeros(len(SOURCE_ORDER))
    for col, label, color in ERROR_CATEGORIES:
        vals = fractions[col].values
        if not vals.any():
            continue
        ax.bar(x, vals, 0.55, bottom=bottom, color=color, alpha=0.87, label=label,
               edgecolor="white", linewidth=1.0, zorder=3)
        for xi, (v, b) in enumerate(zip(vals, bottom)):
            if v > 0.04:
                ax.text(xi, b + v / 2, f"{v:.0%}", ha="center", va="center",
                        fontsize=7.5, color="white", fontweight="bold")
        bottom += vals

    for xi, n in enumerate(row_sums.values):
        ax.text(xi, 1.02, f"n={int(n)}\nannotations", ha="center", va="bottom", fontsize=8)

    ax.set_xticks(x)
    ax.set_xticklabels([SOURCE_LABEL[s] for s in SOURCE_ORDER], fontsize=9.5)
    ax.set_ylabel("Share of judged annotations", fontsize=10)
    ax.set_ylim(0, 1.18)
    if show_title:
        ax.set_title(f"Error composition by source ({MODE_LABEL[mode]}, all papers pooled)",
                     fontsize=11, fontstyle="italic", fontweight="normal", pad=7)
    clean_axes(ax)
    if legend:
        if legend_loc == "outside":
            ax.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), framealpha=0.9, fontsize=8.5)
        else:
            ax.legend(loc=legend_loc, framealpha=0.9, fontsize=7.5)


# -----------------------------------------------------------------------------
# Panel 5: raw vs. technical-origin-adjusted accuracy, per source (strict mode)
# -----------------------------------------------------------------------------

def draw_panel_adjusted_accuracy(ax: plt.Axes, df: pd.DataFrame) -> None:
    strict_df = df[df["mode"] == "strict"]
    grouped = strict_df.groupby("source", observed=True)[
        ["judge_accuracy", "judge_accuracy_adjusted"]].mean().reindex(SOURCE_ORDER)

    x = np.arange(len(SOURCE_ORDER))
    bar_w = 0.35
    bars_raw = ax.bar(x - bar_w / 2, grouped["judge_accuracy"], bar_w,
                       color=[SOURCE_COLOR[s] for s in SOURCE_ORDER], alpha=0.87,
                       edgecolor="white", linewidth=0.5, label="Raw (text-only judge)", zorder=3)
    bars_adj = ax.bar(x + bar_w / 2, grouped["judge_accuracy_adjusted"], bar_w,
                       color=[SOURCE_COLOR[s] for s in SOURCE_ORDER], alpha=0.87,
                       edgecolor="white", linewidth=0.5, hatch="..",
                       label="Adjusted (credits technical-origin values)", zorder=3)

    for bar in bars_raw:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.015,
                f"{bar.get_height():.0%}", ha="center", va="bottom", fontsize=8)
    for bar, raw in zip(bars_adj, grouped["judge_accuracy"]):
        gain = bar.get_height() - raw
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.015,
                f"{bar.get_height():.0%}\n(+{gain:.0%})", ha="center", va="bottom",
                fontsize=8, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels([SOURCE_LABEL[s] for s in SOURCE_ORDER], fontsize=9.5)
    ax.set_ylabel("Mean judge accuracy", fontsize=10)
    ax.set_ylim(0, 1.15)
    ax.set_title("Accuracy before/after crediting technical-origin values\n(strict mode)",
                 fontsize=11, fontstyle="italic", fontweight="normal", pad=7)
    clean_axes(ax)

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, facecolor="gray", alpha=0.87, edgecolor="white",
                       label="Raw (text-only judge)"),
        plt.Rectangle((0, 0), 1, 1, facecolor="gray", alpha=0.87, hatch="..", edgecolor="white",
                       label="Adjusted (credits technical-origin values)"),
    ]
    ax.legend(handles=legend_handles, loc="upper left", framealpha=0.9, fontsize=8.5)


def main() -> None:
    global RESULTS_DIR, SUMMARY_CSV
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", default=str(RESULTS_DIR),
                        help="Directory containing source_comparison_summary.csv "
                             "(default: input_llm_judge/compare_sources_results)")
    args = parser.parse_args()
    RESULTS_DIR = Path(args.results_dir)
    SUMMARY_CSV = RESULTS_DIR / "source_comparison_summary.csv"

    df = load_summary()
    n_papers = df["paper_id"].nunique()

    draw_panel_error_composition_strict = partial(draw_panel_error_composition, mode="strict")
    draw_panel_error_composition_inference = partial(draw_panel_error_composition, mode="inference")

    panels = [
        ("panel1_mean_accuracy", draw_panel_mean_accuracy, (7.5, 6)),
        ("panel2_raw_vs_harmonized", draw_panel_raw_vs_harmonized, (8, 4.5)),
        ("panel3_inference_headroom", draw_panel_inference_headroom, (7.5, 6)),
        ("panel4_error_composition", draw_panel_error_composition_strict, (9.5, 6)),
        ("panel5_adjusted_accuracy", draw_panel_adjusted_accuracy, (8, 6)),
        ("panel6_error_composition_inference", draw_panel_error_composition_inference, (9.5, 6)),
    ]

    for name, draw_fn, figsize in panels:
        fig, ax = plt.subplots(figsize=figsize)
        draw_fn(ax, df)
        add_suptitle(fig, "LLM-as-judge: HAMLET extraction quality across sources",
                      f"compare_sources_results (n = {n_papers} papers, Gemma-4-31B judge)")
        save_fig(fig, RESULTS_DIR / f"{name}.png")
        plt.close(fig)

    # 3x2 composite (6 panels, exactly fills the grid)
    fig, axes = plt.subplots(3, 2, figsize=(15, 17))
    draw_panel_mean_accuracy(axes[0, 0], df)
    draw_panel_raw_vs_harmonized(axes[0, 1], df)
    draw_panel_inference_headroom(axes[1, 0], df)
    draw_panel_error_composition_strict(axes[1, 1], df)
    draw_panel_adjusted_accuracy(axes[2, 0], df)
    draw_panel_error_composition_inference(axes[2, 1], df)
    add_suptitle(fig, "LLM-as-judge: HAMLET extraction quality across sources",
                  f"compare_sources_results (n = {n_papers} papers, Gemma-4-31B judge)")
    save_fig(fig, RESULTS_DIR / "composite_llm_judge_comparison.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
