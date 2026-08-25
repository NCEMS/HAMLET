#!/usr/bin/env python3
"""Build the restyled Figure 3 (individual panels + one composite), following
the layout of make_figure1_v2.py: fully self-contained, restyled to
PLOT_STYLE_GUIDE.md throughout (single blue hue per panel, italic two-line
suptitle, dashed y-grid, spines off), reusing make_figure_3.py's data logic
(taxid scoring, PTM aggregation, RunAssessor stat collection) rather than
duplicating it.

Uniform cohort
--------------
The three panels previously drew from three different, mismatched PXD
populations (QC: any PXD with RunAssessor data; organism: any PXD with an
evaluable taxid prediction; PTM: any PXD with modification_site_fractions).
This script instead computes the INTERSECTION of all three criteria once and
restricts every panel to that single common cohort, so "n = ..." means the
same set of papers in every panel of the figure.

Panels
------
a - RunAssessor technical QC summary (10 subplots: acquisition, fragmentation,
    MS levels, precursor charge, isolation window, fragmentation channels,
    tolerances, labeling/quant).
b - Organism-ID prediction quality (success-rate summary + F1 distribution).
c - PTM group frequency and occupancy (fraction of PXDs / mean occupancy).

Outputs (all under output_v2/)
-------------------------------
qc_organism_ptm_pxd_list.txt        the uniform-cohort PXD accessions
taxid_prediction.csv                 per-raw-file organism-ID metrics (uniform cohort)
modification_frequency.csv           per-modification detail table (uniform cohort)
modification_grouped.csv             per-PTM-group summary (uniform cohort)
runassessor_technical_summary.csv    per-domain/category summary (uniform cohort)
figure3_panel_a_technical_qc.png
figure3_panel_b_organism_id.png
figure3_panel_c_ptm_frequency.png
figure3_composite.png / .svg
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

FIGURE3_DIR = Path(__file__).resolve().parent
REPO_ROOT = FIGURE3_DIR.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src" / "analysis") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src" / "analysis"))
if str(FIGURE3_DIR) not in sys.path:
    sys.path.insert(0, str(FIGURE3_DIR))

from plot_style import COLORS, clean_axes, add_suptitle, save_fig  # noqa: E402

from make_figure_3 import (  # noqa: E402
    _parse_ground_truth_taxids,
    _collect_runassessor_stats,
    _compute_mod_grouped_for_composite,
    run_taxid_prediction,
    run_modification_frequency,
    run_runassessor_technical_summary,
)

BLUE = COLORS["blue"]
PEPTONIZER_THRESHOLD = 0.90


# -----------------------------------------------------------------------------
# Uniform cohort: intersect the QC / organism / PTM criteria in a single pass
# over aggregated_results_files, so every panel draws from the same PXDs.
# -----------------------------------------------------------------------------

def determine_uniform_cohort(store_dir: str) -> tuple[set[str], int]:
    agg_dir = os.path.join(store_dir, "aggregated_results_files")
    files = sorted(glob.glob(os.path.join(agg_dir, "PXD*_aggregated_results.json")))

    qc_pxds, organism_pxds, ptm_pxds = set(), set(), set()
    for fpath in files:
        pxd = os.path.basename(fpath).split("_aggregated")[0]
        try:
            with open(fpath, "r") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        if data.get("runAssessor"):
            qc_pxds.add(pxd)

        if data.get("modification_site_fractions"):
            ptm_pxds.add(pxd)

        project = (data.get("pride_metadata") or {}).get("project") or {}
        ground_truth = _parse_ground_truth_taxids(project)
        has_org_results = bool((data.get("organism_identification") or {}).get("results"))
        if ground_truth and has_org_results:
            organism_pxds.add(pxd)

    cohort = qc_pxds & organism_pxds & ptm_pxds
    print(f"[uniform_cohort] QC (RunAssessor)        : {len(qc_pxds):,} PXDs")
    print(f"[uniform_cohort] Organism (evaluable)     : {len(organism_pxds):,} PXDs")
    print(f"[uniform_cohort] PTM (modification data)  : {len(ptm_pxds):,} PXDs")
    print(f"[uniform_cohort] Intersection (all three) : {len(cohort):,} PXDs")
    return cohort, len(files)


# -----------------------------------------------------------------------------
# Panel a: RunAssessor technical QC (10 subplots)
# -----------------------------------------------------------------------------

def _bar(ax, labels, values, ylabel, title, pct=False):
    x = range(len(labels))
    ax.bar(x, values, color=BLUE, alpha=0.87, edgecolor="white", linewidth=0.5, zorder=3)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=35, ha="right", rotation_mode="anchor", fontsize=7.5)
    ax.set_ylabel(ylabel, fontsize=8.5)
    ax.set_title(title, fontsize=9.5, fontstyle="italic", fontweight="normal")
    if pct:
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    clean_axes(ax, grid_axis="y")


def build_panel_a(fig: plt.Figure, spec, stats: dict) -> None:
    gs = spec.subgridspec(2, 5, wspace=0.55, hspace=0.85)
    axes = [[fig.add_subplot(gs[r, c]) for c in range(5)] for r in range(2)]

    acquisition_counter = stats["acquisition_counter"]
    fragmentation_counter = stats["fragmentation_counter"]
    fragmentation_tag_counter = stats["fragmentation_tag_counter"]
    ms_level_counter = stats["ms_level_counter"]
    precursor_charge_counter = stats["precursor_charge_counter"]
    isolation_width_counter = stats["isolation_width_counter"]
    fragment_channel_counter = stats["fragment_channel_counter"]
    precursor_tol_ppm = stats["precursor_tol_ppm"]
    fragment_tol_ppm = stats["fragment_tol_ppm"]
    labeling_counter = stats["labeling_counter"]
    roi_signature_counter = stats["roi_signature_counter"]

    items = sorted(acquisition_counter.items(), key=lambda kv: kv[1], reverse=True)
    _bar(axes[0][0], [k for k, _ in items], [v for _, v in items], "Runs", "Acquisition")

    items = sorted(fragmentation_counter.items(), key=lambda kv: kv[1], reverse=True)[:6]
    _bar(axes[0][1], [k for k, _ in items], [v for _, v in items], "Runs", "Fragmentation type")

    items = sorted(fragmentation_tag_counter.items(), key=lambda kv: kv[1], reverse=True)[:5]
    _bar(axes[0][2], [k for k, _ in items], [v for _, v in items], "Runs", "Fragmentation tag")

    ms_order = ["ms0", "ms1", "ms2", "ms3", "ms3+"]
    ms_labels = [m for m in ms_order if m in ms_level_counter]
    ms_vals = [ms_level_counter[m] for m in ms_labels]
    ms_frac = [v / sum(ms_vals) for v in ms_vals] if ms_vals else []
    _bar(axes[0][3], ms_labels, [v * 100 for v in ms_frac], "Frac", "MS levels")
    axes[0][3].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    charge_items = []
    for k, v in precursor_charge_counter.items():
        try:
            charge_items.append((int(k), v))
        except ValueError:
            continue
    charge_items.sort(key=lambda kv: kv[1], reverse=True)
    top, other_sum = charge_items[:6], sum(v for _, v in charge_items[6:])
    charge_labels = [f"z={k}" for k, _ in top]
    charge_vals = [v for _, v in top]
    if other_sum > 0:
        charge_labels.append("other")
        charge_vals.append(other_sum)
    total_charge = float(sum(charge_vals))
    _bar(axes[0][4], charge_labels, [100 * v / total_charge for v in charge_vals],
         "Frac", "Precursor charge")
    axes[0][4].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    iso_items = []
    for k, v in isolation_width_counter.items():
        try:
            iso_items.append((float(k), v))
        except ValueError:
            continue
    iso_items.sort(key=lambda kv: kv[0])
    iso_top = iso_items[:8]
    total_iso = float(sum(v for _, v in iso_items))
    _bar(axes[1][0], [f"{w:g}" for w, _ in iso_top], [100 * v / total_iso for _, v in iso_top],
         "Frac", "Isolation window (m/z)")
    axes[1][0].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    items = sorted(fragment_channel_counter.items(), key=lambda kv: kv[1], reverse=True)
    total_frag = float(sum(v for _, v in items)) or 1.0
    _bar(axes[1][1], [k.upper() for k, _ in items], [100 * v / total_frag for _, v in items],
         "Frac", "Fragmentation channels")
    axes[1][1].yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    ax = axes[1][2]
    ax.hist(precursor_tol_ppm, bins=12, color=BLUE, alpha=0.75, edgecolor="white", zorder=3)
    ax.set_title("Precursor tolerance", fontsize=9.5, fontstyle="italic", fontweight="normal")
    ax.set_xlabel("ppm", fontsize=8.5)
    ax.set_ylabel("Count", fontsize=8.5)
    clean_axes(ax, grid_axis="y")

    ax = axes[1][3]
    ax.hist(fragment_tol_ppm, bins=12, color=BLUE, alpha=0.75, edgecolor="white", zorder=3)
    ax.set_title("Fragment tolerance", fontsize=9.5, fontstyle="italic", fontweight="normal")
    ax.set_xlabel("ppm", fontsize=8.5)
    ax.set_ylabel("Count", fontsize=8.5)
    clean_axes(ax, grid_axis="y")

    label_items = sorted(labeling_counter.items(), key=lambda kv: kv[1], reverse=True)[:4]
    roi_items = sorted(roi_signature_counter.items(), key=lambda kv: kv[1], reverse=True)[:4]
    names = [f"L:{k}" for k, _ in label_items] + [f"Q:{k}" for k, _ in roi_items]
    vals = [v for _, v in label_items] + [v for _, v in roi_items]
    _bar(axes[1][4], names, vals, "Count", "Labeling + quant")
    axes[1][4].tick_params(axis="x", rotation=45)


# -----------------------------------------------------------------------------
# Panel b: organism-ID prediction quality
# -----------------------------------------------------------------------------

def _ci95(values: np.ndarray) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    return 1.96 * np.std(values, ddof=1) / math.sqrt(n)


def build_panel_b(fig: plt.Figure, spec, eval_df: pd.DataFrame) -> None:
    metrics = [("recall", "Recall"), ("precision", "Precision"), ("f1", "F1")]
    grid = spec.subgridspec(1, 3, wspace=0.32)
    for index, (metric, label) in enumerate(metrics):
        axis = fig.add_subplot(grid[0, index])
        values = eval_df[metric].values.astype(float)
        mean_value = float(np.mean(values))
        ci = _ci95(values)
        axis.hist(
            values, bins=20, range=(0, 1), color=BLUE, alpha=0.75,
            edgecolor="white", zorder=3,
        )
        axis.axvline(mean_value, color="black", linewidth=1.5, linestyle="--")
        axis.axvspan(
            max(0, mean_value - ci), min(1, mean_value + ci), alpha=0.15, color="black",
        )
        axis.text(
            0.03, 0.95, f"mean = {mean_value:.2f}\n95% CI +/- {ci:.2f}",
            transform=axis.transAxes, ha="left", va="top", fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", alpha=0.85),
        )
        axis.set_xlabel(f"{label} score", fontsize=10)
        axis.set_ylabel("Number of raw files", fontsize=10)
        axis.set_xlim(-0.02, 1.02)
        axis.set_title(f"{label} distribution", fontsize=10.5,
                       fontstyle="italic", fontweight="normal")
        clean_axes(axis, grid_axis="y")


# -----------------------------------------------------------------------------
# Panel c: PTM group frequency and occupancy
# -----------------------------------------------------------------------------

_EXCLUDE_GROUPS = {"Amino acid substitutions", "Miscellaneous rare"}


def build_panel_c(fig: plt.Figure, spec, grp_df: pd.DataFrame, n_with_msf: int) -> None:
    plot_df = grp_df[~grp_df["group"].isin(_EXCLUDE_GROUPS)].copy()
    plot_df = plot_df.sort_values("n_pxds_unique", ascending=True)
    labels = plot_df["group"].tolist()
    y = np.arange(len(labels))

    gs = spec.subgridspec(1, 2, wspace=0.3)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1], sharey=ax1)

    frac_pxd = plot_df["n_pxds_unique"] / n_with_msf
    ax1.barh(y, frac_pxd, color=BLUE, alpha=0.87, edgecolor="white", linewidth=0.5, zorder=3)
    ax1.set_yticks(y)
    ax1.set_yticklabels(labels, fontsize=9)
    ax1.set_xlabel("Fraction of PXDs observed", fontsize=10)
    ax1.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax1.set_title("Fraction of PXDs", fontsize=10.5, fontstyle="italic", fontweight="normal")
    clean_axes(ax1, grid_axis="x")

    wm = plot_df["weighted_mean_fraction"].fillna(0)
    ax2.barh(y, wm, color=BLUE, alpha=0.87, edgecolor="white", linewidth=0.5, zorder=3)
    ax2.set_xlabel("Weighted mean fraction modified", fontsize=10)
    ax2.set_title("Mean occupancy", fontsize=10.5, fontstyle="italic", fontweight="normal")
    clean_axes(ax2, grid_axis="x")
    plt.setp(ax2.get_yticklabels(), visible=False)


# -----------------------------------------------------------------------------
# Standalone panels + composite
# -----------------------------------------------------------------------------

def _add_panel_label(fig: plt.Figure, spec, label: str) -> None:
    bbox = spec.get_position(fig)
    fig.text(bbox.x0 - 0.02, bbox.y1 + 0.01, label, fontsize=16, fontweight="bold", va="bottom")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the restyled, uniform-cohort Figure 3 (panels a/b/c + composite).")
    parser.add_argument("--store", default=str(REPO_ROOT / "store"),
                         help="Path to the HAMLET store directory (contains aggregated_results_files/).")
    parser.add_argument("--outdir", default=str(FIGURE3_DIR / "output_v2"))
    call_rule = parser.add_mutually_exclusive_group()
    call_rule.add_argument(
        "--threshold", type=float, default=None,
        help=("Peptonizer score required for a positive organism call per raw file "
              f"(default: {PEPTONIZER_THRESHOLD:.0%}).".replace("%", "%%")),
    )
    call_rule.add_argument(
        "--topN", type=int, default=None,
        help="Call the N highest-scoring Peptonizer taxa independently for each raw file.",
    )
    parser.add_argument("--email", type=str, default=None,
                         help="Email for NCBI Entrez species-level taxid normalisation (optional).")
    args = parser.parse_args()
    if args.topN is not None and args.topN < 1:
        parser.error("--topN must be at least 1.")
    threshold = PEPTONIZER_THRESHOLD if args.topN is None and args.threshold is None else args.threshold
    selection_label = f"top {args.topN}" if args.topN is not None else f"score >= {threshold:.0%}"

    store_dir = os.path.abspath(args.store)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cohort, n_total_files = determine_uniform_cohort(store_dir)
    if not cohort:
        print("ERROR: uniform cohort is empty -- nothing to plot.", file=sys.stderr)
        sys.exit(1)

    pxd_list_path = outdir / "qc_organism_ptm_pxd_list.txt"
    pxd_list_path.write_text("\n".join(sorted(cohort)) + "\n", encoding="utf-8")
    print(f"[uniform_cohort] PXD list written to: {pxd_list_path}")

    # CSV results (also produces each function's own legacy-styled plot, harmless leftovers)
    eval_df = run_taxid_prediction(
        store_dir, threshold, str(outdir), email=args.email, allowed_pxds=cohort, top_n=args.topN,
    )
    run_modification_frequency(store_dir, str(outdir), allowed_pxds=cohort)
    run_runassessor_technical_summary(store_dir, str(outdir), allowed_pxds=cohort)

    # In-memory calculations for the non-organism panels.
    agg_dir = os.path.join(store_dir, "aggregated_results_files")
    files = sorted(glob.glob(os.path.join(agg_dir, "PXD*_aggregated_results.json")))
    files = [f for f in files if Path(f).name.split("_aggregated")[0] in cohort]

    stats = _collect_runassessor_stats(files)
    grp_df, n_with_msf = _compute_mod_grouped_for_composite(files)

    n_pxds = len(cohort)
    subtitle = (
        f"n = {n_pxds:,} PXDs (uniform cohort: QC ∩ organism-ID ∩ PTM); "
        f"organism metrics: n = {len(eval_df):,} raw files, {selection_label}"
    )

    # --- individual panels ---
    fig = plt.figure(figsize=(16, 7))
    build_panel_a(fig, fig.add_gridspec(1, 1)[0, 0], stats)
    add_suptitle(fig, "RunAssessor technical QC summary", subtitle)
    save_fig(fig, outdir / "figure3_panel_a_technical_qc.png")
    plt.close(fig)

    fig = plt.figure(figsize=(11, 5))
    build_panel_b(fig, fig.add_gridspec(1, 1)[0, 0], eval_df)
    add_suptitle(fig, "Organism-ID prediction quality", subtitle)
    save_fig(fig, outdir / "figure3_panel_b_organism_id.png")
    plt.close(fig)

    fig = plt.figure(figsize=(11, 6.5))
    build_panel_c(fig, fig.add_gridspec(1, 1)[0, 0], grp_df, n_with_msf)
    add_suptitle(fig, "PTM group frequency and occupancy", subtitle)
    save_fig(fig, outdir / "figure3_panel_c_ptm_frequency.png")
    plt.close(fig)

    # --- composite ---
    fig = plt.figure(figsize=(15, 18))
    gs = fig.add_gridspec(3, 1, height_ratios=[1.15, 0.8, 1.0], hspace=0.5)
    build_panel_a(fig, gs[0, 0], stats)
    build_panel_b(fig, gs[1, 0], eval_df)
    build_panel_c(fig, gs[2, 0], grp_df, n_with_msf)
    _add_panel_label(fig, gs[0, 0], "a")
    _add_panel_label(fig, gs[1, 0], "b")
    _add_panel_label(fig, gs[2, 0], "c")
    add_suptitle(fig, "HAMLET technical QC, organism-ID quality, and PTM landscape", subtitle)
    save_fig(fig, outdir / "figure3_composite.png")
    fig.savefig(outdir / "figure3_composite.svg", bbox_inches="tight")
    print(f"Saved: {outdir / 'figure3_composite.svg'}")
    plt.close(fig)


if __name__ == "__main__":
    main()
