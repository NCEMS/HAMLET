#!/usr/bin/env python3
"""Build the restyled Figure 1 (individual panels + one 2x2 composite).

Consolidates the six exploratory scripts under newfigs_test/ into one script,
following the layout of make_figure1.py: it reads the tables that
make_figure1.py already computes (panel a membership, panel b existing/HAMLET
counts, panel c text-mention fractions) plus the Select_27_Pubs .ann files
directly for inter-annotator agreement, and draws the restyled panel designs
picked from the newfigs_test/ drafts.

Main figure panels:
  a - PRIDE dataset availability (bar chart; panel_a_bars.py)
  b - Inter-annotator agreement, pairwise Cohen's kappa (heatmap;
      annotator_agreement.py, heatmap half only)
  c - HAMLET vs. existing PRIDE metadata availability (dumbbell;
      panelb_improvement.py)
  d - Coverage vs. improvement per field (scatter; coverage_vs_improvement.py)

Supplementary panels (not in the composite):
  - Per-entity pairwise agreement (violin; annotator_agreement.py)
  - Field mentions in publication text (lollipop; panel_c_lollipop.py)

Every panel also gets its own standalone PNG and its own output CSV.
"""

from __future__ import annotations

import argparse
import itertools
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

try:
    from adjustText import adjust_text
except ImportError:
    adjust_text = None

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src" / "analysis") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src" / "analysis"))

from plot_style import COLORS, clean_axes, add_suptitle, save_fig  # noqa: E402

FIGURE1_DIR = Path(__file__).resolve().parent

# -----------------------------------------------------------------------------
# Semantic color roles, decided once here and reused by every panel + the
# shared composite legend.
# -----------------------------------------------------------------------------

EXISTING_COLOR = COLORS["dark_blue"]
HAMLET_COLOR = COLORS["red"]

FIELD_CATEGORY_COLORS = {
    "biological": COLORS["blue"],
    "technical": COLORS["orange"],
    "experimental_design": COLORS["green"],
}
FIELD_CATEGORY_ORDER = ["biological", "technical", "experimental_design"]

CAT_SINGLE = "Single human vs. MultiHuman annotator"
CAT_MULTI = "MultiHuman annotator vs. MultiHuman annotator"
CAT_HARM = "HarmonizedHuman vs. Single/MultiHuman annotator"
CAT_GPT = "GPT vs. any human annotator"
PAIR_CATEGORY_COLORS = {
    CAT_SINGLE: COLORS["blue"],
    CAT_MULTI: COLORS["green"],
    CAT_HARM: COLORS["purple"],
    CAT_GPT: COLORS["red"],
}
PAIR_CATEGORY_ORDER = [CAT_SINGLE, CAT_MULTI, CAT_HARM, CAT_GPT]

DIVERGING_LOW = COLORS["red"]
DIVERGING_MID = "#f5f5f5"
DIVERGING_HIGH = COLORS["dark_blue"]

CONNECTOR_COLOR = "#bbbbbb"

MIN_SHARED_DOCS = 1  # floor for a pairwise kappa to be computable at all


def color_yticklabels_by_category(ax, categories: list[str], color_map: dict[str, str]) -> None:
    for label, cat in zip(ax.get_yticklabels(), categories):
        label.set_color(color_map.get(cat, "#333333"))


def add_category_group_lines(ax: plt.Axes, categories: list[str], axis: str = "x") -> None:
    prev = None
    for i, cat in enumerate(categories):
        if prev is not None and cat != prev:
            if axis == "x":
                ax.axvline(i - 0.5, color=CONNECTOR_COLOR, linewidth=0.6, linestyle="--", zorder=0)
            else:
                ax.axhline(i - 0.5, color=CONNECTOR_COLOR, linewidth=0.6, linestyle="--", zorder=0)
        prev = cat


# -----------------------------------------------------------------------------
# Panel a: PRIDE dataset availability (bars)
# -----------------------------------------------------------------------------


def compute_panel_a_stats(membership_csv: Path) -> dict:
    df = pd.read_csv(membership_csv)
    return {
        "PRIDE PXD": len(df),
        "PMC": int(df["has_pmc"].sum()),
        "BY": int(df["has_by"].sum()),
        "SDRF": int(df["has_sdrf"].sum()),
        "PMC_BY": int((df["has_pmc"] & df["has_by"]).sum()),
        "PMC_BY_SDRF": int((df["has_pmc"] & df["has_by"] & df["has_sdrf"]).sum()),
    }


def draw_panel_a(ax: plt.Axes, stats: dict, standalone: bool = False) -> None:
    labels = ["PRIDE PXD", "PMC", "BY", "SDRF"]
    vals = [stats[k] for k in labels]
    bar_colors = [COLORS["blue"], COLORS["green"], COLORS["orange"], COLORS["red"]]

    bars = ax.bar(labels, vals, color=bar_colors, alpha=0.87, edgecolor="white", linewidth=0.5)
    ax.set_ylabel("Dataset count", fontsize=10.5 if standalone else 9)
    ax.tick_params(axis="x", rotation=15, labelsize=10 if standalone else 8)

    ymax = max(vals + [1])
    ax.set_ylim(0, ymax * 1.25)
    for bar, v in zip(bars, vals):
        ax.text(
            bar.get_x() + bar.get_width() / 2, v + ymax * 0.02, f"{v:,}",
            ha="center", va="bottom", fontsize=9 if standalone else 7.5,
        )

    ov = f"PMC ∩ BY: {stats['PMC_BY']:,}\nPMC ∩ BY ∩ SDRF: {stats['PMC_BY_SDRF']:,}"
    ax.text(
        0.97, 0.93, ov, transform=ax.transAxes, ha="right", va="top",
        fontsize=8.5 if standalone else 7,
        bbox=dict(boxstyle="round,pad=0.4", fc="white", alpha=0.85),
    )
    clean_axes(ax, grid_axis="y")


# -----------------------------------------------------------------------------
# Panel b: inter-annotator agreement (heatmap), computed from raw .ann files
# -----------------------------------------------------------------------------


def parse_brat_ann(path: Path) -> set[str]:
    labels: set[str] = set()
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return labels
    for line in txt.splitlines():
        if not line.startswith("T"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        span_parts = parts[1].split()
        if span_parts:
            labels.add(span_parts[0].strip())
    return labels


def parse_flat_ann(path: Path) -> set[str]:
    labels: set[str] = set()
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return labels
    for line in txt.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        label = line.split(":", 1)[0].strip()
        if label:
            labels.add(label)
    return labels


def load_annotators(ann_root: Path) -> dict[str, dict[str, set[str]]]:
    """{annotator_name: {doc_id: {raw_label, ...}}}. 'Ian' is dropped: identical
    to SingleHuman, would duplicate a rater."""
    data: dict[str, dict[str, set[str]]] = defaultdict(dict)

    for p in sorted((ann_root / "SingleHuman").glob("*.ann")):
        data["SingleHuman"][p.stem] = parse_brat_ann(p)
    for p in sorted((ann_root / "GPT").glob("*.ann")):
        data["GPT"][p.stem] = parse_flat_ann(p)
    for p in sorted((ann_root / "HarmonizedHuman").glob("*.ann")):
        doc_id = p.stem.removesuffix("_harmonized")
        data["HarmonizedHuman"][doc_id] = parse_flat_ann(p)
    for p in sorted((ann_root / "MultiHuman").glob("*/*/*.ann")):
        annotator = p.parts[-3]
        if annotator.lower() == "ian":
            continue
        data[annotator][p.stem] = parse_brat_ann(p)
    return data


def anonymize_multihuman(
    annotator_docs: dict[str, dict[str, set[str]]]
) -> tuple[dict[str, dict[str, set[str]]], dict[str, str]]:
    special = {"SingleHuman", "GPT", "HarmonizedHuman"}
    real_names = sorted(name for name in annotator_docs if name not in special)
    id_by_real = {real: f"Annotator{i + 1}" for i, real in enumerate(real_names)}

    renamed = {id_by_real.get(name, name): docs for name, docs in annotator_docs.items()}
    mapping = {anon: real for real, anon in id_by_real.items()}
    return renamed, mapping


def annotator_category(name: str, multihuman_names: set[str]) -> str:
    if name == "GPT":
        return "GPT"
    if name == "HarmonizedHuman":
        return "HarmonizedHuman"
    if name == "SingleHuman":
        return "Single human"
    if name in multihuman_names:
        return "MultiHuman annotators"
    raise ValueError(f"Unrecognised annotator: {name}")


def pair_category(name_a: str, name_b: str, multihuman_names: set[str]) -> str:
    cats = {
        annotator_category(name_a, multihuman_names),
        annotator_category(name_b, multihuman_names),
    }
    if "GPT" in cats:
        return CAT_GPT
    if "HarmonizedHuman" in cats:
        return CAT_HARM
    if "Single human" in cats:
        return CAT_SINGLE
    return CAT_MULTI


def load_field_map(crosswalk_path: Path) -> tuple[dict[str, set[str]], dict[str, str], list[str]]:
    df = pd.read_csv(crosswalk_path)
    field_labels: dict[str, set[str]] = {}
    field_category: dict[str, str] = {}
    fields_in_order: list[str] = []

    for row in df.itertuples(index=False):
        field = str(getattr(row, "agentic_field", "") or "").strip()
        labels_raw = str(getattr(row, "ann_metadata_labels", "") or "").strip()
        category = str(getattr(row, "category", "") or "").strip().lower()
        if not field or not labels_raw:
            continue
        labels = {tok.strip() for tok in labels_raw.split(";") if tok.strip()}
        if not labels:
            continue
        field_labels[field] = labels
        field_category[field] = category
        if field not in fields_in_order:
            fields_in_order.append(field)

    return field_labels, field_category, fields_in_order


def build_presence(
    annotator_docs: dict[str, dict[str, set[str]]], field_labels: dict[str, set[str]]
) -> dict[str, dict[str, dict[str, int]]]:
    presence: dict[str, dict[str, dict[str, int]]] = {}
    for annotator, docs in annotator_docs.items():
        presence[annotator] = {
            doc_id: {field: int(bool(raw_labels & labels)) for field, labels in field_labels.items()}
            for doc_id, raw_labels in docs.items()
        }
    return presence


def cohen_kappa_binary(a: list[int], b: list[int]) -> float:
    if len(a) != len(b) or len(a) == 0:
        return float("nan")
    n = len(a)
    p0 = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if abs(1 - pe) < 1e-12:
        return float("nan")
    return (p0 - pe) / (1 - pe)


def shared_docs(presence: dict, name_a: str, name_b: str) -> list[str]:
    return sorted(set(presence[name_a]) & set(presence[name_b]))


def pooled_pairwise_kappa(presence: dict, name_a: str, name_b: str, fields: list[str]) -> tuple[float, int]:
    docs = shared_docs(presence, name_a, name_b)
    a_vec, b_vec = [], []
    for doc in docs:
        for field in fields:
            a_vec.append(presence[name_a][doc][field])
            b_vec.append(presence[name_b][doc][field])
    return cohen_kappa_binary(a_vec, b_vec), len(docs)


def per_field_pairwise_kappa(presence: dict, name_a: str, name_b: str, field: str) -> tuple[float, int]:
    docs = shared_docs(presence, name_a, name_b)
    a_vec = [presence[name_a][doc][field] for doc in docs]
    b_vec = [presence[name_b][doc][field] for doc in docs]
    return cohen_kappa_binary(a_vec, b_vec), len(docs)


def compute_annotator_agreement(
    ann_root: Path, crosswalk_csv: Path
) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, str], dict[str, str]]:
    """Returns (overall_pairwise_df, per_field_pairwise_df, annotators, name_mapping, field_category)."""
    annotator_docs = load_annotators(ann_root)
    annotator_docs, name_mapping = anonymize_multihuman(annotator_docs)
    multihuman_names = set(annotator_docs) - {"SingleHuman", "GPT", "HarmonizedHuman"}
    annotators = ["SingleHuman", "GPT", "HarmonizedHuman"] + sorted(
        multihuman_names, key=lambda n: int(n.removeprefix("Annotator"))
    )

    field_labels, field_category, fields_in_order = load_field_map(crosswalk_csv)
    presence = build_presence(annotator_docs, field_labels)

    overall_rows = []
    for name_a, name_b in itertools.combinations(annotators, 2):
        docs = shared_docs(presence, name_a, name_b)
        if len(docs) < MIN_SHARED_DOCS:
            continue
        kappa, n_docs = pooled_pairwise_kappa(presence, name_a, name_b, fields_in_order)
        overall_rows.append(
            {
                "annotator_a": name_a,
                "annotator_b": name_b,
                "pair_category": pair_category(name_a, name_b, multihuman_names),
                "n_shared_docs": n_docs,
                "kappa": kappa,
            }
        )
    overall_df = pd.DataFrame(overall_rows).sort_values(["annotator_a", "annotator_b"])

    per_field_rows = []
    for name_a, name_b in itertools.combinations(annotators, 2):
        docs = shared_docs(presence, name_a, name_b)
        if len(docs) < MIN_SHARED_DOCS:
            continue
        cat = pair_category(name_a, name_b, multihuman_names)
        for field in fields_in_order:
            kappa, n_docs = per_field_pairwise_kappa(presence, name_a, name_b, field)
            per_field_rows.append(
                {
                    "field": field,
                    "category": field_category.get(field, "unknown"),
                    "annotator_a": name_a,
                    "annotator_b": name_b,
                    "pair_category": cat,
                    "n_shared_docs": n_docs,
                    "kappa": kappa,
                }
            )
    per_field_df = pd.DataFrame(per_field_rows)

    return overall_df, per_field_df, annotators, name_mapping, field_category


def diverging_kappa_cmap() -> LinearSegmentedColormap:
    return LinearSegmentedColormap.from_list(
        "kappa_diverging", [DIVERGING_LOW, DIVERGING_MID, DIVERGING_HIGH], N=256
    )


def draw_panel_b_heatmap(
    ax: plt.Axes, overall_df: pd.DataFrame, annotators: list[str], fig: plt.Figure | None = None,
    standalone: bool = False,
) -> None:
    n = len(annotators)
    mat = np.full((n, n), np.nan)
    idx = {name: i for i, name in enumerate(annotators)}
    for row in overall_df.itertuples(index=False):
        i, j = idx[row.annotator_a], idx[row.annotator_b]
        mat[i, j] = row.kappa
        mat[j, i] = row.kappa
    np.fill_diagonal(mat, 1.0)

    display_mat = mat.copy()
    upper_tri = np.triu_indices(n, k=1)
    display_mat[upper_tri] = np.nan

    cmap = diverging_kappa_cmap()
    cmap.set_bad("#dddddd")
    im = ax.imshow(display_mat, cmap=cmap, vmin=-1, vmax=1)

    for i, j in zip(*upper_tri):
        ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, facecolor="white", edgecolor="none", zorder=2))

    fontsize = 8 if standalone else 6
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(annotators, rotation=45, ha="right", fontsize=fontsize)
    ax.set_yticklabels(annotators, fontsize=fontsize)

    for i in range(n):
        for j in range(i + 1):
            val = mat[i, j]
            if np.isnan(val):
                continue
            text_color = "white" if abs(val) > 0.55 or i == j else "#111111"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                     fontsize=7 if standalone else 5, color=text_color, zorder=3)

    if fig is not None:
        cbar = fig.colorbar(im, ax=ax, shrink=0.7, ticks=[-1, 0, 1], aspect=25)
        cbar.set_label("Cohen's kappa", fontsize=9.5 if standalone else 7.5)
        cbar.ax.tick_params(labelsize=8 if standalone else 6.5)
    ax.grid(False)


# -----------------------------------------------------------------------------
# Panel c: HAMLET vs. existing PRIDE metadata availability (dumbbell)
# -----------------------------------------------------------------------------


def load_panel_c_data(panel_b_table_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(panel_b_table_csv)
    df["existing_pct"] = 100.0 * df["existing_present_n"] / df["sample_size_recomputed"]
    df["hamlet_pct"] = 100.0 * df["hamlet_present_n"] / df["sample_size_recomputed"]
    df["delta_pp"] = df["hamlet_pct"] - df["existing_pct"]
    df = df[df["category"].isin(FIELD_CATEGORY_ORDER)].copy()
    df["_cat_rank"] = df["category"].map({c: i for i, c in enumerate(FIELD_CATEGORY_ORDER)})
    return df.sort_values(["_cat_rank", "delta_pp"], ascending=[True, False]).reset_index(drop=True)


def draw_panel_c_dumbbell(ax: plt.Axes, df: pd.DataFrame, standalone: bool = False, narrow: bool = False) -> None:
    n = len(df)
    y = list(range(n))[::-1]
    if narrow:
        fontsize, label_fontsize, marker_size, line_width = 6.5, 6, 16, 1.1
    elif standalone:
        fontsize, label_fontsize, marker_size, line_width = 8, 7.5, 55, 2
    else:
        fontsize, label_fontsize, marker_size, line_width = 5.5, 5.5, 22, 1.3

    for yi, row in zip(y, df.itertuples(index=False)):
        ax.plot([row.existing_pct, row.hamlet_pct], [yi, yi], color=CONNECTOR_COLOR, linewidth=line_width, zorder=1)
        ax.scatter([row.existing_pct], [yi], s=marker_size, color=EXISTING_COLOR, zorder=3)
        ax.scatter([row.hamlet_pct], [yi], s=marker_size, color=HAMLET_COLOR, zorder=3)
        rightmost = max(row.existing_pct, row.hamlet_pct)
        sign = "+" if row.delta_pp >= 0 else ""
        ax.text(rightmost + 4, yi, f"{sign}{row.delta_pp:.0f} pp", va="center", ha="left",
                 fontsize=label_fontsize, color="#333333", zorder=4)

    ax.set_yticks(y)
    ax.set_yticklabels([f.replace("_", " ") for f in df["agentic_field"]], fontsize=fontsize)
    color_yticklabels_by_category(ax, df["category"].tolist(), FIELD_CATEGORY_COLORS)
    ax.set_xlim(0, 116)
    ax.set_ylim(-0.7, n + (1.3 if standalone else 0.4))
    ax.set_xlabel("% of datasets with this field present", fontsize=9 if narrow else (10.5 if standalone else 8))

    clean_axes(ax, grid_axis="x")

    prev_cat = None
    for yi, cat in zip(y, df["category"]):
        if prev_cat is not None and cat != prev_cat:
            ax.axhline(yi + 0.5, color="gray", linewidth=0.7, linestyle=":", alpha=0.5, zorder=0)
        prev_cat = cat


# -----------------------------------------------------------------------------
# Panel d: coverage vs. improvement per field (scatter)
# -----------------------------------------------------------------------------


def load_panel_d_data(panel_b_table_csv: Path, panel_c_table_csv: Path) -> pd.DataFrame:
    b = pd.read_csv(panel_b_table_csv)
    c = pd.read_csv(panel_c_table_csv)[["agentic_field", "availability_fraction"]]
    df = b.merge(c, on="agentic_field", how="inner")
    df["delta_pp"] = 100.0 * (df["hamlet_present_n"] - df["existing_present_n"]) / df["sample_size_recomputed"]
    df["ceiling_pct"] = 100.0 * df["availability_fraction"]
    return df


def draw_panel_d_scatter(ax: plt.Axes, df: pd.DataFrame, standalone: bool = False) -> None:
    for cat in FIELD_CATEGORY_ORDER:
        sub = df[df["category"] == cat]
        ax.scatter(
            sub["ceiling_pct"], sub["delta_pp"], s=70 if standalone else 30,
            color=FIELD_CATEGORY_COLORS[cat], edgecolor="white", linewidth=0.6, zorder=3,
        )

    ax.axhline(0, color="gray", linewidth=0.8, zorder=1)
    lo, hi = 0, 108
    ax.plot([lo, hi], [lo, hi], linestyle=":", color="gray", alpha=0.6, linewidth=1.3, zorder=1)

    if standalone and adjust_text is not None:
        texts = [
            ax.text(row.ceiling_pct, row.delta_pp, row.agentic_field.replace("_", " "),
                     fontsize=7, color="#333333")
            for row in df.itertuples(index=False)
        ]
        adjust_text(texts, ax=ax, arrowprops=dict(arrowstyle="-", color="#aaaaaa", lw=0.6),
                    expand=(1.3, 1.6), force_text=(0.3, 0.4))

    ax.set_xlim(0, 108)
    ax.set_ylim(-10, 112)
    ax.set_xlabel("% of gold-annotated papers mentioning field in text (ceiling)",
                   fontsize=10.5 if standalone else 7.5)
    ax.set_ylabel("HAMLET improvement over existing PRIDE metadata (pp)",
                   fontsize=10.5 if standalone else 7.5)
    clean_axes(ax, grid_axis="both")


# -----------------------------------------------------------------------------
# Supplementary: per-entity pairwise agreement (violin)
# -----------------------------------------------------------------------------


def draw_violin(
    per_field_df: pd.DataFrame, field_category: dict[str, str], fields_in_order: list[str], outpath: Path,
) -> None:
    rng = np.random.default_rng(0)
    fields = [f for f in fields_in_order if f in set(per_field_df["field"])]
    field_vals = {f: per_field_df.loc[per_field_df["field"] == f, "kappa"].dropna().tolist() for f in fields}

    fig, ax = plt.subplots(figsize=(24, 8))

    violin_positions = [i for i, f in enumerate(fields) if len(field_vals[f]) >= 2]
    violin_data = [field_vals[fields[i]] for i in violin_positions]
    if violin_data:
        vp = ax.violinplot(violin_data, positions=violin_positions, widths=0.7, showmedians=True, showextrema=True)
        for body in vp["bodies"]:
            body.set_facecolor("#f2f2f0")
            body.set_edgecolor("#888888")
            body.set_alpha(0.9)
            body.set_linewidth(0.8)
        for part in ("cmedians", "cmins", "cmaxes", "cbars"):
            vp[part].set_edgecolor("#555555")
            vp[part].set_linewidth(0.9)

    for i, field in enumerate(fields):
        sub = per_field_df.loc[per_field_df["field"] == field].dropna(subset=["kappa"])
        for cat in PAIR_CATEGORY_ORDER:
            vals = sub.loc[sub["pair_category"] == cat, "kappa"].tolist()
            if not vals:
                continue
            jitter = rng.uniform(-0.14, 0.14, size=len(vals))
            ax.scatter(np.full(len(vals), i) + jitter, vals, s=16, color=PAIR_CATEGORY_COLORS[cat],
                        alpha=0.8, edgecolor="white", linewidth=0.3, zorder=3)

    ax.axhline(0.0, color="#999999", linewidth=0.7, zorder=1)
    ax.set_xticks(range(len(fields)))
    ax.set_xticklabels([f.replace("_", " ") for f in fields], rotation=45, ha="right", fontsize=10)
    ax.tick_params(axis="y", labelsize=9)
    ax.set_ylim(-1.12, 1.12)
    ax.set_ylabel("Pairwise Cohen's kappa", fontsize=11)
    ax.set_xlim(-0.6, len(fields) - 0.4)

    clean_axes(ax, grid_axis="y")
    add_suptitle(fig, "Per-entity pairwise agreement (supplementary)", "Select_27_Pubs, one point per annotator pair")

    categories = [field_category.get(f, "unknown") for f in fields]
    add_category_group_lines(ax, categories, axis="x")

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=PAIR_CATEGORY_COLORS[cat],
                markersize=8, label=cat)
        for cat in PAIR_CATEGORY_ORDER
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.9)
    save_fig(fig, outpath)
    plt.close(fig)


# -----------------------------------------------------------------------------
# Supplementary: field mentions in publication text (lollipop)
# -----------------------------------------------------------------------------


def load_lollipop_data(panel_c_table_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(panel_c_table_csv)
    df["pct"] = 100.0 * df["availability_fraction"]
    df["_cat_rank"] = df["category"].map({c: i for i, c in enumerate(FIELD_CATEGORY_ORDER)})
    return df.sort_values(["_cat_rank", "agentic_field"]).reset_index(drop=True)


def draw_lollipop(df: pd.DataFrame, n_docs: int, outpath: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 5.5))
    x = list(range(len(df)))

    for xi, row in zip(x, df.itertuples(index=False)):
        color = FIELD_CATEGORY_COLORS.get(row.category, "#999999")
        ax.plot([xi, xi], [0, row.pct], color=CONNECTOR_COLOR, linewidth=1.6, zorder=1)
        ax.scatter([xi], [row.pct], s=60, color=color, zorder=2, edgecolor="white", linewidth=0.6)

    ax.set_xticks(x)
    ax.set_xticklabels([f.replace("_", " ") for f in df["agentic_field"]], rotation=45, ha="right", fontsize=8.5)
    ax.set_ylim(0, 108)
    ax.set_xlim(-0.6, len(df) - 0.4)
    ax.set_ylabel("% of gold-annotated papers\nmentioning this field in text", fontsize=10.5)

    clean_axes(ax, grid_axis="y")
    add_suptitle(fig, "Field mentions in publication text (supplementary)", f"Select_27_Pubs, n = {n_docs} gold-annotated papers")
    add_category_group_lines(ax, df["category"].tolist(), axis="x")
    save_fig(fig, outpath)
    plt.close(fig)


# -----------------------------------------------------------------------------
# Composite legend
#
# Panels c and d share the biological/technical/experimental_design field
# category colors; panel c additionally contrasts Existing PRIDE metadata vs.
# HAMLET. Panel b's Cohen's kappa scale is self-contained in its own colorbar,
# so it is left out of the shared legend below the grid.
# -----------------------------------------------------------------------------


def composite_legend_handles() -> list:
    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=EXISTING_COLOR, markersize=9,
                label="Existing PRIDE metadata"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=HAMLET_COLOR, markersize=9,
                label="HAMLET"),
    ]
    handles += [
        Patch(facecolor=FIELD_CATEGORY_COLORS[cat], edgecolor="none", label=cat.replace("_", " "))
        for cat in FIELD_CATEGORY_ORDER
    ]
    return handles


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restyled Figure 1: individual panels + composite.")
    parser.add_argument("--membership-csv", default=str(FIGURE1_DIR / "output" / "figure1_composite_panel_a_membership.csv"))
    parser.add_argument("--panel-b-table", default=str(FIGURE1_DIR / "output" / "figure1_composite_panel_b_table.csv"))
    parser.add_argument("--panel-c-table", default=str(FIGURE1_DIR / "output" / "figure1_composite_panel_c_table.csv"))
    parser.add_argument("--ann-root", default=str(FIGURE1_DIR / "data" / "Select_27_Pubs"))
    parser.add_argument("--crosswalk", default=str(FIGURE1_DIR / "data" / "field_crosswalk_table.csv"))
    parser.add_argument("--outdir", default=str(FIGURE1_DIR / "output_v2"))
    parser.add_argument("--supp-outdir", default=str(FIGURE1_DIR / "output_v2" / "supplementary"))
    parser.add_argument("--basename", default="figure1")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    supp_outdir = Path(args.supp_outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    supp_outdir.mkdir(parents=True, exist_ok=True)

    # --- Load / compute data for every panel ---
    panel_a_stats = compute_panel_a_stats(Path(args.membership_csv))

    overall_kappa_df, per_field_kappa_df, annotators, name_mapping, field_category = compute_annotator_agreement(
        Path(args.ann_root), Path(args.crosswalk)
    )

    panel_c_df = load_panel_c_data(Path(args.panel_b_table))
    n_pxds = int(panel_c_df["sample_size_recomputed"].iloc[0])

    panel_d_df = load_panel_d_data(Path(args.panel_b_table), Path(args.panel_c_table))

    # --- CSV outputs, one per panel, for auditability ---
    pd.DataFrame([panel_a_stats]).to_csv(outdir / f"{args.basename}_panel_a_table.csv", index=False)
    overall_kappa_df.to_csv(outdir / f"{args.basename}_panel_b_table.csv", index=False)
    panel_c_df.to_csv(outdir / f"{args.basename}_panel_c_table.csv", index=False)
    panel_d_df.to_csv(outdir / f"{args.basename}_panel_d_table.csv", index=False)
    pd.DataFrame(
        [{"anonymized_id": anon, "real_name": real} for anon, real in name_mapping.items()]
    ).to_csv(outdir / f"{args.basename}_annotator_name_mapping.csv", index=False)

    # --- Individual standalone panels ---
    fig, ax = plt.subplots(figsize=(7, 6.5))
    draw_panel_a(ax, panel_a_stats, standalone=True)
    add_suptitle(fig, "PRIDE dataset availability", f"n = {panel_a_stats['PRIDE PXD']:,} PRIDE PXD accessions")
    save_fig(fig, outdir / f"{args.basename}_panel_a_availability.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 7.5))
    draw_panel_b_heatmap(ax, overall_kappa_df, annotators, fig=fig, standalone=True)
    add_suptitle(fig, "Pairwise inter-annotator agreement", f"Select_27_Pubs, {len(annotators)} annotators")
    save_fig(fig, outdir / f"{args.basename}_panel_b_heatmap.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(6.5, 0.34 * len(panel_c_df) + 2.5))
    draw_panel_c_dumbbell(ax, panel_c_df, standalone=True)
    ax.legend(handles=composite_legend_handles()[:2], loc="upper right", fontsize=9.5, framealpha=0.9)
    add_suptitle(fig, "HAMLET vs. existing PRIDE metadata availability", f"HamletPXDs.csv, n = {n_pxds:,} datasets")
    save_fig(fig, outdir / f"{args.basename}_panel_c_dumbbell.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 7.5))
    draw_panel_d_scatter(ax, panel_d_df, standalone=True)
    ax.legend(handles=composite_legend_handles()[2:], loc="center left", fontsize=9.5, framealpha=0.9)
    add_suptitle(fig, "Coverage vs. improvement, per field", f"HamletPXDs.csv (n = {n_pxds:,}) vs. Select_27_Pubs text-mention rate")
    save_fig(fig, outdir / f"{args.basename}_panel_d_scatter.png")
    plt.close(fig)

    # --- Composite: left column stacks a/b/d, right column is panel c spanning
    # the full height (tall and narrow suits its 23-row dumbbell better than a
    # quadrant), plus a reserved legend row at the bottom. ---
    fig = plt.figure(figsize=(180.0 / 25.4 * 1.5, 180.0 / 25.4 * 2.1))
    gs = fig.add_gridspec(4, 2, height_ratios=[1, 1, 1, 0.14], hspace=0.55, wspace=0.45)

    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[2, 0])
    ax_c = fig.add_subplot(gs[0:3, 1])
    ax_legend = fig.add_subplot(gs[3, :])
    ax_legend.axis("off")

    draw_panel_a(ax_a, panel_a_stats)
    draw_panel_b_heatmap(ax_b, overall_kappa_df, annotators, fig=fig)
    draw_panel_c_dumbbell(ax_c, panel_c_df, narrow=True)
    draw_panel_d_scatter(ax_d, panel_d_df)

    for ax, label in [(ax_a, "a"), (ax_b, "b"), (ax_c, "c"), (ax_d, "d")]:
        bbox = ax.get_position()
        fig.text(bbox.x0 - 0.03, min(0.995, bbox.y1 + 0.01), label, fontsize=13, fontweight="bold",
                  ha="left", va="bottom")

    ax_legend.legend(
        handles=composite_legend_handles(), loc="center", ncol=5, fontsize=9, frameon=False,
    )

    out_png = outdir / f"{args.basename}_composite.png"
    out_svg = outdir / f"{args.basename}_composite.svg"
    fig.savefig(out_png, dpi=400, bbox_inches="tight")
    fig.savefig(out_svg, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_png}")
    print(f"Saved: {out_svg}")

    # --- Supplementary panels ---
    draw_violin(per_field_kappa_df, field_category, list(field_category.keys()), supp_outdir / "annotator_agreement_per_entity_violin.png")
    per_field_kappa_df.to_csv(supp_outdir / "per_field_pairwise_kappa.csv", index=False)

    lollipop_df = load_lollipop_data(Path(args.panel_c_table))
    n_docs = int(lollipop_df["n_docs"].iloc[0])
    draw_lollipop(lollipop_df, n_docs, supp_outdir / "field_mentions_lollipop.png")
    lollipop_df.to_csv(supp_outdir / "field_mentions_lollipop_table.csv", index=False)

    print(f"Done. Individual panels + composite in {outdir}, supplementary in {supp_outdir}")


if __name__ == "__main__":
    main()
