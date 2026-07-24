#!/usr/bin/env python3
"""Composite of the LLM-as-judge results figures referenced in
results_sdrf_judge.md: strict/inference error composition, judge-noise
variability by source x mode, and the per-source class-level error/variance
breakdown -- as one 2x3 grid.

Every panel is redrawn natively onto the composite's own axes (not stitched
from pre-rendered PNGs), so the SVG output stays true vector, and the caller
adds their own panel labels/subtitles downstream -- no titles, suptitle, or
A/B/C lettering are drawn here. The error-composition legend (row 1, shared
by both composition panels) and the class-driver legend (row 2, shared by
all three source panels) are each drawn once, in a wide left margin left
free of any plot axes, so they never overlap plot content.

Row 1: error composition (strict) | error composition (inference) | judge
       reproducibility (3-run std)          -- with a shared legend at far left
Row 2: class-level errors + variance, one column per source (HAMLET raw,
       HAMLET harmonized, SDRF-Proteomics)  -- with a shared legend at far left

Writes compare_sources_results_30pxds_consensus/sdrf_judge_results_composite.{png,svg}.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import plot_llm_judge_comparison as pljc          # noqa: E402
import compute_judge_consensus as cjc             # noqa: E402
import plot_error_class_variance as pecv          # noqa: E402

BASE_DIR = Path(__file__).resolve().parent / "input_llm_judge"
RUN1_DIR = BASE_DIR / "compare_sources_results_30pxds_run1"
CONSENSUS_DIR = BASE_DIR / "compare_sources_results_30pxds_consensus"
OUT_STEM = CONSENSUS_DIR / "sdrf_judge_results_composite"

CLASS_PANEL_TOP_N = 8  # fewer rows than the standalone figures (TOP_N=10), to stay legible at 1/3 width
FIGSIZE = (28, 11.5)
CM_IN_INCHES = 1 / 2.54
LEFT_MARGIN_FRAC = 0.235         # reserved whitespace band for both legends, plus the row-1 y-axis
                                  # label and the row-2 y-tick class-name labels, both of which are
                                  # drawn outside their axes' own bounding box, further left
BLANK_GAP_FRAC = CM_IN_INCHES / FIGSIZE[0]  # a true 1 cm blank gap before the legend itself


def main() -> None:
    pljc.SUMMARY_CSV = RUN1_DIR / "source_comparison_summary.csv"
    df = pljc.load_summary()
    variability_df = pd.read_csv(CONSENSUS_DIR / "accuracy_variability.csv")
    class_summary = pecv.load_rates_and_agreement()

    fig, axes = plt.subplots(2, 3, figsize=FIGSIZE)

    #row 1: draw both composition panels, pull legend handles off the
    #inference panel (superset of categories -- e.g. it's the only one with
    #"Inferred"), then strip its inline legend and place one shared copy in
    #the left-margin whitespace
    pljc.draw_panel_error_composition(axes[0, 0], df, mode="strict", show_title=False, legend=False)
    pljc.draw_panel_error_composition(axes[0, 1], df, mode="inference", show_title=False, legend=True)
    comp_handles, comp_labels = axes[0, 1].get_legend_handles_labels()
    axes[0, 1].get_legend().remove()

    cjc.draw_variability_panel(axes[0, 2], variability_df, show_title=False)

    #row 2: all three source panels share identical categories/colors, so draw
    #without any inline legend and place one shared copy of proxy handles
    for ax, source in zip(axes[1], pecv.SOURCE_ORDER):
        pecv.draw_source_panel(ax, class_summary, source, top_n=CLASS_PANEL_TOP_N,
                                label_fontsize=8.5, value_fontsize=8, legend=False)
    class_handles = [plt.Rectangle((0, 0), 1, 1, facecolor=color, alpha=0.9, edgecolor="white", label=label)
                     for _, label, color in pecv.METRICS]
    class_labels = [label for _, label, _ in pecv.METRICS]

    fig.tight_layout()
    #push every column of axes right, opening up a wide left-margin band
    #(blank 1 cm gap from the figure edge, then the legend itself) that is
    #free of any plot axes, so the legends can never overlap plot content
    fig.subplots_adjust(left=LEFT_MARGIN_FRAC)

    legend_x = BLANK_GAP_FRAC
    fig.legend(comp_handles, comp_labels, loc="center left", bbox_to_anchor=(legend_x, 0.76),
               bbox_transform=fig.transFigure, fontsize=10, framealpha=0.9)
    fig.legend(class_handles, class_labels, loc="center left", bbox_to_anchor=(legend_x, 0.25),
               bbox_transform=fig.transFigure, fontsize=10.5, framealpha=0.9)

    for ext in ("png", "svg"):
        out_path = OUT_STEM.with_suffix(f".{ext}")
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        print(f"Saved: {out_path}")
    plt.close(fig)


if __name__ == "__main__":
    main()
