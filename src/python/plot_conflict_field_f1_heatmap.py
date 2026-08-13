#!/usr/bin/env python3
"""Plot mean per-file conflict metrics by PXD and SDRF field."""

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

from conflictAssessment import REPORT_CATEGORIES, _canonical_field, _field_category


METRICS = (
    ("assessed_entities", "Mean assessed entities", "#5b9bd5"),
    ("gold_entities", "Mean gold entities", "#70ad47"),
    ("matched_entities", "Mean matched entities", "#2166ac"),
    ("assessed_only_entities", "Mean assessed-only entities", "#d6604d"),
    ("gold_only_entities", "Mean gold-only entities", "#ed7d31"),
    ("micro_f1", "Mean micro F1", "#9b59b6"),
)

COMPARISON_LABELS = {
    "store_vs_pride": "Store versus PRIDE",
    "store_vs_user": "Store versus user",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Discover store-versus-PRIDE and store-versus-user metric files and "
            "plot mean conflict metrics across each PXD's raw files."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("reports/conflict_assessment"),
        help="Conflict assessment root (default: reports/conflict_assessment)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/conflict_assessment"),
        help="Directory for heatmaps and matrices (default: reports/conflict_assessment)",
    )
    parser.add_argument(
        "--comparisons",
        nargs="+",
        choices=sorted(COMPARISON_LABELS),
        default=list(COMPARISON_LABELS),
        help="Comparisons to plot (default: both)",
    )
    parser.add_argument(
        "--store-dir",
        type=Path,
        default=Path("store"),
        help="Store root used to define allowed fields (default: store)",
    )
    return parser.parse_args()


def store_fields(store_dir, pxd):
    path = store_dir / "agentic_results_files" / pxd / (pxd + ".sdrf.tsv")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        headers = next(csv.reader(handle, delimiter="\t"))
    return {
        _canonical_field(header)
        for header in headers
        if _field_category(header) in REPORT_CATEGORIES
    }


def collect_values(input_dir, store_dir, comparison):
    values = {
        metric: defaultdict(lambda: defaultdict(list))
        for metric, _, _ in METRICS
    }
    pattern = "PXD*/{}/sample_field_metrics.tsv".format(comparison)
    paths = sorted(input_dir.glob(pattern))
    for path in paths:
        pxd = path.parents[1].name
        allowed_fields = store_fields(store_dir, pxd)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            required = {"pxd", "field"} | {metric for metric, _, _ in METRICS}
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("{} is missing required columns".format(path))
            for row in reader:
                if row["field"] not in allowed_fields:
                    continue
                for metric, _, _ in METRICS:
                    value = row[metric].strip()
                    if value and value.upper() != "NA":
                        values[metric][row["pxd"]][row["field"]].append(float(value))
    return paths, values


def write_matrix(path, pxds, fields, means):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["pxd"] + fields)
        for pxd in pxds:
            writer.writerow(
                [pxd]
                + ["NA" if np.isnan(means[pxd, field]) else "{:.6f}".format(means[pxd, field]) for field in fields]
            )


def metric_output_path(output_dir, comparison, metric):
    return output_dir / "{}_field_{}_heatmap.png".format(comparison, metric)


def plot_heatmaps(paths, values, output_dir, comparison):
    if not paths:
        raise ValueError("no sample_field_metrics.tsv files found")
    f1_values = values["micro_f1"]
    if not f1_values:
        raise ValueError("no numeric micro_f1 values found")

    pxds = sorted(f1_values)
    fields = sorted({field for pxd_values in f1_values.values() for field in pxd_values})
    f1_means = {
        (pxd, field): (
            float(np.mean(f1_values[pxd][field]))
            if f1_values[pxd].get(field)
            else np.nan
        )
        for pxd in pxds
        for field in fields
    }
    fields.sort(
        key=lambda field: (
            np.nanmean([f1_means[pxd, field] for pxd in pxds]),
            field,
        )
    )

    width = min(30.0, max(12.0, 0.4 * len(fields)))
    height = min(40.0, max(7.0, 0.22 * len(pxds)))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = []
    for metric, label, color in METRICS:
        metric_values = values[metric]
        means = {
            (pxd, field): (
                float(np.mean(metric_values[pxd][field]))
                if metric_values[pxd].get(field)
                else np.nan
            )
            for pxd in pxds
            for field in fields
        }
        matrix = np.array(
            [[means[pxd, field] for field in fields] for pxd in pxds], dtype=float
        )
        color_map = LinearSegmentedColormap.from_list(metric, ["#ffffff", color])
        color_map.set_bad("#d9d9d9")

        figure, axis = plt.subplots(figsize=(width, height))
        image_options = {
            "aspect": "auto",
            "interpolation": "nearest",
            "cmap": color_map,
            "vmin": 0.0,
        }
        if metric == "micro_f1":
            image_options["vmax"] = 1.0
        image = axis.imshow(matrix, **image_options)
        axis.set_xticks(range(len(fields)))
        axis.set_xticklabels(fields, rotation=45, ha="right", fontsize=7)
        axis.set_yticks(range(len(pxds)))
        axis.set_yticklabels(pxds, fontsize=7)
        axis.set_xlabel("Metadata field, sorted by ascending mean F1")
        axis.set_ylabel("PXD")
        axis.spines[["top", "right"]].set_visible(False)
        figure.suptitle(
            "{} metadata agreement\n{} across raw files, {} PXDs".format(
                COMPARISON_LABELS[comparison], label, len(pxds)
            ),
            fontsize=13,
            fontstyle="italic",
            fontweight="normal",
        )
        color_bar = figure.colorbar(image, ax=axis, pad=0.01)
        color_bar.set_label(label)
        figure.tight_layout()

        image_path = metric_output_path(output_dir, comparison, metric)
        figure.savefig(str(image_path), dpi=150, bbox_inches="tight")
        plt.close(figure)
        matrix_path = image_path.with_suffix(".tsv")
        write_matrix(matrix_path, pxds, fields, means)
        output_paths.append((image_path, matrix_path))
    return output_paths, len(pxds), len(fields)


def main():
    args = parse_args()
    for comparison in args.comparisons:
        paths, values = collect_values(args.input_dir, args.store_dir, comparison)
        output_paths, pxd_count, field_count = plot_heatmaps(
            paths, values, args.output_dir, comparison
        )
        print("{}: read {} report files".format(comparison, len(paths)))
        print("{}: plotted {} PXDs by {} fields".format(
            comparison, pxd_count, field_count
        ))
        for image_path, matrix_path in output_paths:
            print("Saved heatmap: {}".format(image_path))
            print("Saved matrix: {}".format(matrix_path))


if __name__ == "__main__":
    main()