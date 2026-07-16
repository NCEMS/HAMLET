"""Analyze HAMLET LLM judge outputs across all available PXDs.

This script scans ``results/PXD*/`` for the post-judge CSV and matching
final SDRF file, then builds a combined table and publication-style
distribution plots for the judge metrics.

The code is intentionally small and split into a few helpers so that new
analysis steps can be added without disturbing the data loading layer.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


JUDGE_RELATIVE_PATH = Path(
    "agentic_metadata/metadata_extraction_output/post_judge/llm_judge_per_paper.csv"
)
SDRF_RELATIVE_TEMPLATE = "agentic_metadata/{pxd}.sdrf.tsv"
PXD_PATTERN = re.compile(r"^PXD\d{6}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze LLM judge outputs and summarize missing PXDs."
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Root results directory that contains PXD folders.",
    )
    parser.add_argument(
        "--outdir",
        default="results/llm_judge_analysis",
        help="Directory where tables and figures will be written.",
    )
    return parser.parse_args()


def find_pxd_dirs(results_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in results_dir.iterdir()
            if path.is_dir() and PXD_PATTERN.match(path.name)
        ]
    )


def read_judge_file(path: Path, pxd: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "paper_id" not in df.columns:
        raise ValueError(f"{path} is missing the required paper_id column")

    numeric_columns = [column for column in df.columns if column != "paper_id"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df.insert(0, "pxd", pxd)
    return df


def read_sdrf_file(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, sep="\t")


def discover_judge_file(pxd_dir: Path) -> tuple[Path | None, str]:
    exact_path = pxd_dir / JUDGE_RELATIVE_PATH
    if exact_path.exists():
        return exact_path, "exact_post_judge"

    nested_post_judge = sorted(
        pxd_dir.glob("agentic_metadata/**/post_judge/llm_judge_per_paper.csv")
    )
    if nested_post_judge:
        return nested_post_judge[0], "nested_post_judge"

    return None, "missing"


def build_summary_row(
    pxd: str,
    exact_judge_path: Path,
    judge_path: Path | None,
    judge_source: str,
    sdrf_path: Path,
    judge_df: pd.DataFrame | None,
    sdrf_df: pd.DataFrame | None,
) -> dict[str, object]:
    row: dict[str, object] = {
        "pxd": pxd,
        "has_post_judge": exact_judge_path.exists(),
        "judge_source": judge_source,
        "has_any_judge": judge_source != "missing",
        "has_sdrf": sdrf_path.exists(),
        "judge_path": str(judge_path or exact_judge_path),
        "sdrf_path": str(sdrf_path),
        "judge_rows": 0,
        "sdrf_rows": 0,
        "judge_accuracy_mean": pd.NA,
        "judge_accuracy_median": pd.NA,
        "judge_accuracy_min": pd.NA,
        "judge_accuracy_max": pd.NA,
        "fraction_accuracy_1": pd.NA,
        "fraction_no_corrections": pd.NA,
        "fraction_incomplete": pd.NA,
    }

    if judge_df is not None and not judge_df.empty:
        row["judge_rows"] = int(len(judge_df))
        row["judge_accuracy_mean"] = float(judge_df["judge_accuracy"].mean())
        row["judge_accuracy_median"] = float(judge_df["judge_accuracy"].median())
        row["judge_accuracy_min"] = float(judge_df["judge_accuracy"].min())
        row["judge_accuracy_max"] = float(judge_df["judge_accuracy"].max())
        row["fraction_accuracy_1"] = float((judge_df["judge_accuracy"] == 1.0).mean())
        row["fraction_no_corrections"] = float((judge_df["judge_n_corrected"] == 0).mean())
        row["fraction_incomplete"] = float((judge_df["judge_n_incomplete"] > 0).mean())

    if sdrf_df is not None:
        row["sdrf_rows"] = int(len(sdrf_df))

    return row


def summarize_presence(summary_df: pd.DataFrame) -> pd.DataFrame:
    categories = pd.Series(
        [
            "both_present"
            if row.has_post_judge and row.has_sdrf
            else "judge_only"
            if row.has_post_judge
            else "sdrf_only"
            if row.has_sdrf
            else "neither_present"
            for row in summary_df.itertuples(index=False)
        ],
        name="presence_category",
    )
    return categories.value_counts().rename_axis("presence_category").reset_index(name="pxd_count")


def plot_numeric_distributions(df: pd.DataFrame, outpath: Path) -> None:
    numeric_columns = [
        column for column in df.columns if column not in {"pxd", "paper_id"}
    ]
    ncols = 2
    nrows = (len(numeric_columns) + ncols - 1) // ncols

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(14, 4.2 * nrows),
        constrained_layout=True,
    )
    axes = axes.flatten() if len(numeric_columns) > 1 else [axes]

    for ax, column in zip(axes, numeric_columns):
        values = df[column].dropna()
        if values.empty:
            ax.set_visible(False)
            continue

        if column == "judge_accuracy":
            bins = [x / 20 for x in range(0, 21)]
        elif (values.round() == values).all():
            minimum = int(values.min())
            maximum = int(values.max())
            bins = range(minimum, maximum + 2)
        else:
            bins = "auto"

        ax.hist(values, bins=bins, color="#2457A6", edgecolor="white", linewidth=0.8)
        ax.axvline(values.mean(), color="#C43C3C", linestyle="--", linewidth=1.5, label="mean")
        ax.axvline(values.median(), color="#2F7F5E", linestyle=":", linewidth=1.8, label="median")
        ax.set_title(column)
        ax.set_ylabel("count")
        ax.legend(frameon=False, fontsize=9)

        if column == "judge_accuracy":
            ax.set_xlim(0.0, 1.0)

    for ax in axes[len(numeric_columns):]:
        ax.set_visible(False)

    fig.suptitle("LLM judge metric distributions", fontsize=16, fontweight="bold")
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    plt.close(fig)


def plot_presence_summary(summary_df: pd.DataFrame, outpath: Path) -> None:
    presence_df = summarize_presence(summary_df)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(8.5, 4.5), constrained_layout=True)
    ax.bar(
        presence_df["presence_category"],
        presence_df["pxd_count"],
        color="#2457A6",
        edgecolor="white",
        linewidth=0.8,
    )
    ax.set_title("Post-judge and SDRF file availability")
    ax.set_ylabel("PXD count")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=20)
    for label, value in zip(presence_df["presence_category"], presence_df["pxd_count"]):
        ax.text(label, value, str(value), ha="center", va="bottom", fontsize=9)
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    results_dir = Path(args.results_dir).resolve()
    outdir = Path(args.outdir).resolve()
    figures_dir = outdir / "figures"
    tables_dir = outdir / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    pxd_dirs = find_pxd_dirs(results_dir)
    if not pxd_dirs:
        raise SystemExit(f"No PXD directories found in {results_dir}")

    all_judge_rows: list[pd.DataFrame] = []
    summary_rows: list[dict[str, object]] = []

    for pxd_dir in pxd_dirs:
        pxd = pxd_dir.name
        exact_judge_path = pxd_dir / JUDGE_RELATIVE_PATH
        judge_path, judge_source = discover_judge_file(pxd_dir)
        sdrf_path = pxd_dir / SDRF_RELATIVE_TEMPLATE.format(pxd=pxd)

        judge_df = read_judge_file(judge_path, pxd) if judge_path is not None else None
        sdrf_df = read_sdrf_file(sdrf_path)

        if judge_df is not None:
            all_judge_rows.append(judge_df)

        summary_rows.append(
            build_summary_row(
                pxd,
                exact_judge_path,
                judge_path,
                judge_source,
                sdrf_path,
                judge_df,
                sdrf_df,
            )
        )

    summary_df = pd.DataFrame(summary_rows)
    combined_judge_df = (
        pd.concat(all_judge_rows, ignore_index=True) if all_judge_rows else pd.DataFrame()
    )

    summary_df.to_csv(tables_dir / "pxd_summary.csv", index=False)
    summarize_presence(summary_df).to_csv(
        tables_dir / "file_presence_summary.csv", index=False
    )
    if not combined_judge_df.empty:
        combined_judge_df.to_csv(tables_dir / "combined_judge_rows.csv", index=False)

    plot_presence_summary(summary_df, figures_dir / "file_presence_summary.png")

    if not combined_judge_df.empty:
        plot_numeric_distributions(
            combined_judge_df,
            figures_dir / "judge_metric_distributions.png",
        )

    total_pxds = len(summary_df)
    with_judge = int(summary_df["has_post_judge"].sum())
    with_any_judge = int(summary_df["has_any_judge"].sum())
    with_sdrf = int(summary_df["has_sdrf"].sum())
    with_both = int((summary_df["has_post_judge"] & summary_df["has_sdrf"]).sum())
    with_alt_judge = int(((~summary_df["has_post_judge"]) & summary_df["has_any_judge"]).sum())
    missing_judge = total_pxds - with_judge

    print("LLM judge analysis summary")
    print(f"  results dir: {results_dir}")
    print(f"  PXDs scanned: {total_pxds}")
    print(f"  with post_judge CSV: {with_judge}")
    print(f"  with any judge CSV: {with_any_judge}")
    print(f"  with alternate judge CSV only: {with_alt_judge}")
    print(f"  with SDRF TSV: {with_sdrf}")
    print(f"  with both files: {with_both}")
    print(f"  missing post_judge CSV: {missing_judge}")

    if not summary_df.empty and summary_df["judge_rows"].sum() > 0:
        accurate_pxds = int((summary_df["fraction_accuracy_1"] == 1.0).sum())
        all_corrected_zero = int((summary_df["fraction_no_corrections"] == 1.0).sum())
        print(f"  PXDs with all papers at accuracy 1.0: {accurate_pxds}")
        print(f"  PXDs with no corrections needed: {all_corrected_zero}")

    print(f"  tables written to: {tables_dir}")
    print(f"  figures written to: {figures_dir}")


if __name__ == "__main__":
    main()