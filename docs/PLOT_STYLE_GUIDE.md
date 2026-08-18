# Benchmark plot style guide

House style for all matplotlib figures in this project (bar, scatter, violin, line, not
bar-specific). Derived from the existing `plot_*.py` scripts in `benchmark_data/` and the
"Output consistency: Master Prompt vs Specialized Agents" figure. Use `plot_style.py`
(same directory) to apply this automatically instead of copy-pasting rcParams.

## Figure setup

- `matplotlib.use("Agg")` before `import matplotlib.pyplot as plt` (headless server, no display).
- `plt.savefig(path, dpi=150, bbox_inches="tight")`. Always print the saved path.
- `plt.tight_layout()` before saving.
- Figsize by plot type (inches): single panel roughly `(7, 6.5)` to `(10, 6)`; two side-by-side
  panels `(14, 6)`; two stacked panels `(17, 10)`; scale width with number of x categories for
  per-PXD bar charts (about 0.4-0.5 in/category).

## Title

- `fig.suptitle(...)`, never per-axes titles for the main title.
- No em dashes anywhere in title or label text. Use a colon, comma, or plain hyphen instead.
- Two lines: line 1 = what's being compared, line 2 = dataset/model/n detail. Join with `\n`.
  Example: `"Output consistency: Master Prompt vs Specialized Agents\n(Llama and GPT, 30-PXD test set, mean ± SD)"`
- `fontsize=13, fontstyle="italic", fontweight="normal"` for the suptitle, not bold.
- Sub-panel titles (when using subplots): `fontsize=11, fontstyle="italic", fontweight="normal", pad=6-8`.
- Group/category labels placed above panels (e.g. "Master Prompt" / "Specialized Agents"):
  italic, colored to match that group's series color, no bold.

## Color palette

Reuse these hex values, don't introduce new colors ad hoc:

| Role | Hex | Usage |
|---|---|---|
| Blue (primary series) | `#5b9bd5` | precision / first series / "master" light |
| Dark blue | `#2166ac` | master prompt series, diagonal-reference plots |
| Green | `#70ad47` | recall / second series |
| Purple | `#9b59b6` | F1 / third metric |
| Orange | `#ed7d31` | third categorical group |
| Red/salmon | `#d6604d` | specialized agents series, "after"/contrast group |
| Light salmon | tint of `#d6604d` at low alpha | second model within same group (e.g. GPT agents vs Llama agents) |

Within one figure: one color per *series* (metric or condition), consistent across all
panels of that figure. Don't reuse a color for two different meanings in the same figure.

## Bars

- `alpha=0.85-0.88`, `edgecolor="white"`, `linewidth=0.4-0.5`.
- Grouped bars: `width=0.22` for 3 metrics side by side, `width=0.35` for 2-way comparisons.
- Center grouped bars on the tick with symmetric offsets: `offset = (i - (n-1)/2) * width`.

## Overlaid raw data points (bar + strip plot)

When a bar shows a mean over multiple underlying observations (e.g. per-PXD counts):
- Draw the bar as the mean first, then scatter the raw points on top, `zorder` above the bar.
- Jitter points horizontally: `x + rng.normal(0, jitter_sd, size=n)` with a **fixed seed**
  (`np.random.default_rng(42)`) so figures are reproducible on re-run.
- Point style: small, semi-transparent, light tint of the bar's own color, white-ish edge.
  Points should read as detail on the bar, never compete with it.
- Draw the SD as a black error bar (`ax.errorbar`, capsize about 4-6) on top of the bar, then a
  text annotation `f"{mean:.0f} ± {sd:.0f}"` just above the error bar cap, centered on the bar.

## Grid, spines, axis

- `ax.spines[["top", "right"]].set_visible(False)`, always.
- Gridlines: y-axis only (or both for scatter plots comparing two measured axes),
  `alpha=0.25-0.3, linestyle="--"`.
- `ax.set_axisbelow(True)` so grid sits behind bars/points.
- When comparing logical groups side by side in one axes (e.g. "Master" vs "Agents"),
  separate them with a vertical divider: `ax.axvline(x, color="gray", ls=":", alpha=0.5)`
  rather than a subplot boundary, when they share one y-axis and one legend.

## Annotations

- Value labels on bars: centered above the bar, `fontsize=7.5-9`.
- Bold the label for the "headline" metric only (e.g. F1, or the mean±SD summary); other
  metric labels stay regular weight. This is how the eye is steered to the main takeaway.
- Stats callouts (r, mean, μ) as a boxed text in-axes:
  `bbox=dict(boxstyle="round,pad=0.4", fc="white", alpha=0.85)`, `fontsize=8.5`, placed in a
  corner via `transform=ax.transAxes`, not at data coordinates.

## Axis labels & ticks

- Axis label fontsize 10-11, plain (not bold).
- Tick label fontsize 8-11 depending on category name length; rotate long/many x-tick labels
  `rotation=45, ha="right"`.
- Shared y-axis across panels (`sharey=True`) whenever panels use the same metric/scale, so
  bar heights are visually comparable.

## Legend

- Only on one panel/location per figure (usually the first/leftmost panel or wherever it
  doesn't overlap data). Don't repeat the same legend on every subplot.
- `fontsize=9-10`, `framealpha=0.9`, placed at whichever corner is empty of data
  (`"upper left"`, `"lower right"`, etc.). Check the actual data range, don't default to a
  fixed corner.

## Checklist for a new plot

1. `Agg` backend, headless.
2. Palette from the table above, pick colors, don't invent new hex values.
3. Suptitle: italic (not bold), two-line, states the comparison plus the dataset/n. No em dashes.
4. Spines top/right off, y-grid dashed, axisbelow.
5. If showing a mean over raw observations: bar + jittered points (fixed seed) + SD error
   bar + `mean ± sd` label.
6. Bold only the headline number; everything else regular weight.
7. One legend, positioned to avoid data.
8. `tight_layout()` then `savefig(dpi=150, bbox_inches="tight")` then print the saved path.
