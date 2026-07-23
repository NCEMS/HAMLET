#!/usr/bin/env python3
"""Shared matplotlib style helpers for benchmark plots.

See PLOT_STYLE_GUIDE.md for the rationale behind each convention. Import from any
plot_*.py script instead of copy-pasting rcParams / axis-cleanup boilerplate:

    from plot_style import COLORS, clean_axes, add_suptitle, annotate_bar, \
        jittered_points, mean_sd_errorbar, save_fig
"""

import numpy as np

# Palette, reuse these, don't invent new hex values per script
COLORS = {
    "blue": "#5b9bd5",
    "dark_blue": "#2166ac",
    "green": "#70ad47",
    "purple": "#9b59b6",
    "orange": "#ed7d31",
    "red": "#d6604d",
}


def clean_axes(ax, grid_axis="y"):
    """Strip top/right spines, add a dashed grid behind the data."""
    ax.spines[["top", "right"]].set_visible(False)
    if grid_axis in ("y", "both"):
        ax.yaxis.grid(True, alpha=0.3, linestyle="--")
    if grid_axis in ("x", "both"):
        ax.xaxis.grid(True, alpha=0.25, linestyle="--")
    ax.set_axisbelow(True)


def add_suptitle(fig, headline, detail):
    """Two-line italic suptitle: headline claim, then dataset/model/n detail."""
    fig.suptitle(f"{headline}\n{detail}", fontsize=13, fontstyle="italic", fontweight="normal")


def group_divider(ax, x, color="gray"):
    """Vertical dotted separator between logical groups sharing one axes/legend."""
    ax.axvline(x, color=color, ls=":", alpha=0.5)


def group_label(ax, x, text, color):
    """Italic colored label above a group of bars (e.g. 'Master Prompt')."""
    ax.text(x, 1.03, text, transform=ax.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=11, style="italic", color=color)


def annotate_bar(ax, bar, value, fmt="{:.3f}", bold=False, fontsize=8.5):
    """Value label centered above a single bar."""
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01 * max(ax.get_ylim()),
            fmt.format(value), ha="center", va="bottom", fontsize=fontsize,
            fontweight="bold" if bold else "normal")


def jittered_points(x_center, values, jitter_sd=0.06, seed=42):
    """Reproducible horizontal jitter for raw-data points overlaid on a bar (fixed seed)."""
    rng = np.random.default_rng(seed)
    return x_center + rng.normal(0, jitter_sd, size=len(values))


def mean_sd_errorbar(ax, x, values, color, label_fmt="{mean:.0f} ± {sd:.0f}", fontsize=9):
    """Draw a black SD error bar on a bar's mean and label it 'mean ± sd' above the cap."""
    mean, sd = np.mean(values), np.std(values)
    ax.errorbar(x, mean, yerr=sd, color="black", capsize=5, lw=1.3, zorder=3)
    ax.text(x, mean + sd + 0.02 * max(ax.get_ylim()),
            label_fmt.format(mean=mean, sd=sd),
            ha="center", va="bottom", fontsize=fontsize, fontweight="bold", color="black")
    return mean, sd


def save_fig(fig, path, dpi=150):
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    print(f"Saved: {path}")
