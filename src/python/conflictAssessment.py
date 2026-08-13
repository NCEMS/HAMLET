#!/usr/bin/env python3
"""Discover and prepare per-PXD SDRFs for conflict assessment."""

import argparse
import csv
import difflib
import io
import json
import re
import shutil
import time
from collections import Counter, namedtuple
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PRIDE_SDRF_ENDPOINT = "https://www.ebi.ac.uk/pride/ws/archive/v3/files/sdrf/{pxd}"
USER_AGENT = "HAMLET-conflict-assessment/0.1"
PXD_PATTERN = re.compile(r"^PXD\d{6,}$")
MISSING_VALUES = {
    "", "n/a", "na", "none", "not available", "not applicable", "null", "unknown"
}
REPORT_CATEGORIES = ("Biological", "Technical", "ExperimentalDesign")

HARMONIZED_FIELD_ALIASES = {
    "raw data file": "comment[data file]",
    "characteristics[organismpart]": "characteristics[organism part]",
    "characteristics[developmentalstage]": "characteristics[developmental stage]",
    "characteristics[ancestrycategory]": "characteristics[ancestry category]",
    "characteristics[celltype]": "characteristics[cell type]",
    "characteristics[cellline]": "characteristics[cell line]",
    "characteristics[biologicalreplicate]": "characteristics[biological replicate]",
    "characteristics[materialtype]": "material type",
    "characteristics[label]": "comment[label]",
    "characteristics[cleavageagent]": "comment[cleavage agent details]",
    "characteristics[modification]": "comment[modification parameters]",
    "characteristics[alkylationreagent]": "comment[alkylation reagent]",
    "characteristics[reductionreagent]": "comment[reduction reagent]",
    "comment[fractionidentifier]": "comment[fraction identifier]",
    "comment[precursormasstolerance]": "comment[precursor mass tolerance]",
    "comment[fragmentmasstolerance]": "comment[fragment mass tolerance]",
    "comment[acquisitionmethod]": "comment[proteomics data acquisition method]",
    "comment[fragmentationmethod]": "comment[dissociation method]",
    "comment[ms2massanalyzer]": "comment[ms2 mass analyzer]",
}

FIELD_CATEGORIES = {
    "technology type": "Technical",
    "comment[proteomics data acquisition method]": "Technical",
    "comment[label]": "Technical",
    "comment[instrument]": "Technical",
    "comment[cleavage agent details]": "Technical",
    "comment[dissociation method]": "Technical",
    "comment[modification parameters]": "Technical",
    "comment[precursor mass tolerance]": "Technical",
    "comment[fragment mass tolerance]": "Technical",
    "comment[reduction reagent]": "Technical",
    "comment[alkylation reagent]": "Technical",
    "comment[ms2 mass analyzer]": "Technical",
    "comment[fraction identifier]": "ExperimentalDesign",
    "comment[technical replicate]": "ExperimentalDesign",
}

SDRFTable = namedtuple(
    "SDRFTable", "source location headers rows sample_keys categorized_values"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prepare store, user, and PRIDE SDRFs for per-PXD conflict assessment."
    )
    parser.add_argument("store_dir", type=Path, help="HAMLET store root")
    parser.add_argument(
        "--sdrf",
        "--sdrf-dir",
        dest="sdrf_dir",
        type=Path,
        default=None,
        help="Optional user SDRF/CSV file or directory containing per-PXD files",
    )
    parser.add_argument(
        "--pxd",
        help="Process one PXD instead of iterating over all store PXD directories",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of store PXD directories to inspect",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="API timeout seconds")
    parser.add_argument("--retries", type=int, default=3, help="PRIDE request attempts")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports/conflict_assessment"),
        help="Root directory for per-PXD comparison reports",
    )
    parser.add_argument(
        "--fuzzy-threshold",
        type=float,
        default=0.90,
        help="Minimum text similarity for values from the same field (default: 0.90)",
    )
    return parser.parse_args()


def _warn(pxd, message):
    print("WARNING [{}]: {}".format(pxd, message))


def _request_bytes(url, timeout, retries):
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, text/tab-separated-values"})
    for attempt in range(retries):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except (HTTPError, URLError, OSError) as exc:
            if attempt == retries - 1:
                raise RuntimeError("request failed for {}: {}".format(url, exc))
            time.sleep(1.5 ** attempt)
    raise RuntimeError("request failed for {}".format(url))


def _parse_sdrf_text(text, source, location, delimiter="\t"):
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        headers = [header.strip() for header in next(reader)]
    except StopIteration:
        raise ValueError("SDRF is empty")
    if len(headers) < 2:
        raise ValueError("SDRF header has fewer than two tab-separated columns")

    rows = []
    for line_number, row in enumerate(reader, start=2):
        if not row or not any(value.strip() for value in row):
            continue
        if len(row) != len(headers):
            raise ValueError(
                "row {} has {} values but header has {}".format(
                    line_number, len(row), len(headers)
                )
            )
        rows.append([value.strip() for value in row])
    if not rows:
        raise ValueError("SDRF has a header but no data rows")

    sample_keys = _sample_keys(headers, rows)
    categorized_values = _categorize_values(headers, rows)
    return SDRFTable(source, str(location), headers, rows, sample_keys, categorized_values)


def _load_local_sdrf(path, source):
    try:
        text = path.read_text(encoding="utf-8-sig")
        delimiter = "," if path.suffix.casefold() == ".csv" else "\t"
        return _parse_sdrf_text(text, source, path, delimiter=delimiter)
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError("invalid {} SDRF {}: {}".format(source, path, exc))


def _sample_keys(headers, rows):
    normalized = [_canonical_field(header) for header in headers]
    key_indices = []
    for candidate in ("comment[data file]", "source name", "assay name"):
        if candidate in normalized:
            key_indices.append((candidate, normalized.index(candidate)))

    keys = []
    for row_number, row in enumerate(rows, start=1):
        key = None
        for label, index in key_indices:
            value = row[index].strip()
            if not value:
                continue
            normalized_value = re.sub(r"\s+", " ", value).strip().casefold()
            key = "{}:{}".format(label, normalized_value)
            break
        keys.append(key or "row:{}".format(row_number))
    return keys


def _field_category(header):
    normalized = _canonical_field(header)
    if normalized in {"source name", "assay name", "comment[data file]"}:
        return "Identity"
    if normalized.startswith("characteristics["):
        if normalized == "characteristics[biological replicate]":
            return "ExperimentalDesign"
        return "Biological"
    if normalized.startswith("factor value["):
        return "ExperimentalDesign"
    return FIELD_CATEGORIES.get(normalized, "Other")


def _categorize_values(headers, rows):
    output = {}
    for index, header in enumerate(headers):
        category = _field_category(header)
        values = []
        for row in rows:
            value = row[index]
            if value.lower() not in MISSING_VALUES and value not in values:
                values.append(value)
        output.setdefault(category, []).append(
            {"column_index": index, "header": header, "values": values}
        )
    return output


def _normalize_data_file(value):
    value = value.strip().strip("\"'").replace("\\", "/")
    return value.rsplit("/", 1)[-1].casefold()


def _canonical_field(header):
    normalized = re.sub(r"\.\d+$", "", header.strip()).casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return HARMONIZED_FIELD_ALIASES.get(normalized, normalized)


def _normalize_text(value):
    normalized = re.sub(r"[^\w.+%-]+", " ", value.casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_entity_value(value):
    value = value.strip()
    parts = {}
    for part in value.split(";"):
        if "=" in part:
            key, part_value = part.split("=", 1)
            parts[key.strip().casefold()] = part_value.strip()
    if parts.get("ac"):
        accession = "cv:{}".format(parts["ac"].casefold())
        aliases = {accession}
        if parts.get("nt"):
            aliases.add(_normalize_text(parts["nt"]))
        return accession, "cv_accession", aliases

    normalized = _normalize_text(value)
    return normalized, "normalized_text", {normalized}


def _row_entities(table, row):
    entities = {category: [] for category in REPORT_CATEGORIES}
    seen = {category: set() for category in REPORT_CATEGORIES}
    for index, header in enumerate(table.headers):
        category = _field_category(header)
        if category not in entities:
            continue
        raw_value = row[index].strip()
        if raw_value.casefold() in MISSING_VALUES:
            continue
        normalized_value, normalization, aliases = _normalize_entity_value(raw_value)
        entity_key = (_canonical_field(header), normalized_value)
        if entity_key in seen[category]:
            continue
        seen[category].add(entity_key)
        entities[category].append(
            {
                "field": entity_key[0],
                "raw_value": raw_value,
                "normalized_value": normalized_value,
                "normalization": normalization,
                "aliases": aliases,
            }
        )
    return entities


def _rows_entities(table, rows):
    entities = {category: [] for category in REPORT_CATEGORIES}
    indexed = {category: {} for category in REPORT_CATEGORIES}
    for row in rows:
        row_entities = _row_entities(table, row)
        for category, values in row_entities.items():
            for entity in values:
                key = (entity["field"], entity["normalized_value"])
                existing = indexed[category].get(key)
                if existing is None:
                    copied = dict(entity)
                    copied["aliases"] = set(entity["aliases"])
                    indexed[category][key] = copied
                    entities[category].append(copied)
                else:
                    existing["aliases"].update(entity["aliases"])
    return entities


def _table_rows_by_data_file(table):
    normalized_headers = [_canonical_field(header) for header in table.headers]
    if "comment[data file]" not in normalized_headers:
        raise ValueError("{} SDRF has no comment[data file] column".format(table.source))
    data_file_index = normalized_headers.index("comment[data file]")
    indexed = {}
    for row in table.rows:
        raw_data_file = row[data_file_index].strip()
        key = _normalize_data_file(raw_data_file)
        if not key:
            continue
        if key in indexed:
            indexed[key][1].append(row)
        else:
            indexed[key] = (raw_data_file, [row])
    return indexed


def _match_entities(assessed_entities, gold_entities, fuzzy_threshold):
    candidates = []
    for assessed_index, assessed_entity in enumerate(assessed_entities):
        for gold_index, gold_entity in enumerate(gold_entities):
            if assessed_entity["field"] != gold_entity["field"]:
                continue
            shared_aliases = assessed_entity["aliases"] & gold_entity["aliases"]
            if shared_aliases:
                similarity = 1.0
                method = (
                    "cv_accession"
                    if assessed_entity["normalized_value"].startswith("cv:")
                    and assessed_entity["normalized_value"] == gold_entity["normalized_value"]
                    else "exact_normalized"
                )
            else:
                text_pairs = [
                    (assessed_alias, gold_alias)
                    for assessed_alias in assessed_entity["aliases"]
                    for gold_alias in gold_entity["aliases"]
                    if not assessed_alias.startswith("cv:") and not gold_alias.startswith("cv:")
                ]
                similarity = max(
                    [difflib.SequenceMatcher(None, left, right).ratio() for left, right in text_pairs]
                    or [0.0]
                )
                method = "fuzzy"
                if similarity < fuzzy_threshold:
                    continue
            candidates.append((similarity, assessed_index, gold_index, method))

    matched_assessed = set()
    matched_gold = set()
    matches = []
    for similarity, assessed_index, gold_index, method in sorted(candidates, reverse=True):
        if assessed_index in matched_assessed or gold_index in matched_gold:
            continue
        matched_assessed.add(assessed_index)
        matched_gold.add(gold_index)
        matches.append(
            {
                "assessed": assessed_entities[assessed_index],
                "gold": gold_entities[gold_index],
                "method": method,
                "similarity": similarity,
                "status": "matched",
            }
        )

    for index, entity in enumerate(assessed_entities):
        if index not in matched_assessed:
            matches.append(
                {"assessed": entity, "gold": None, "method": "unmatched", "similarity": 0.0, "status": "assessed_only"}
            )
    for index, entity in enumerate(gold_entities):
        if index not in matched_gold:
            matches.append(
                {"assessed": None, "gold": entity, "method": "unmatched", "similarity": 0.0, "status": "gold_only"}
            )
    return matches


def _metrics(matches, assessed_total, gold_total):
    matched = sum(match["status"] == "matched" for match in matches)
    precision, recall, f1 = _scores(matched, assessed_total, gold_total)
    return matched, precision, recall, f1


def _scores(matched, assessed_total, gold_total):
    if not assessed_total and not gold_total:
        return None, None, None
    precision = float(matched) / assessed_total if assessed_total else (1.0 if not gold_total else 0.0)
    recall = float(matched) / gold_total if gold_total else (1.0 if not assessed_total else 0.0)
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def _mean(values):
    evaluated = [value for value in values if value is not None]
    return sum(evaluated) / len(evaluated) if evaluated else None


def _format_metric(value, digits=6):
    return "NA" if value is None else ("{:.%df}" % digits).format(value)


def _parse_metric(value):
    return None if value == "NA" else float(value)


def _markdown_metric(value):
    return "NA" if value is None else "{:.3f}".format(value)


def _write_tsv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_sdrf_snapshot(table, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(table.headers)
        writer.writerows(table.rows)


def _write_field_heatmaps(field_metric_rows, output_dir, pxd, comparison_name):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.colors import LinearSegmentedColormap
    except ImportError as exc:
        print("  WARNING: heatmaps skipped because plotting dependencies are unavailable: {}".format(exc))
        return []

    metrics = (
        ("matched_entities", "Matched entities", "#2166ac"),
        ("assessed_only_entities", "Assessed-only entities", "#d6604d"),
        ("gold_only_entities", "Gold-only entities", "#ed7d31"),
        ("micro_precision", "Per-file precision", "#5b9bd5"),
        ("micro_recall", "Per-file recall", "#70ad47"),
        ("micro_f1", "Per-file F1", "#9b59b6"),
    )
    data_files = sorted({row["data_file"] for row in field_metric_rows})
    fields = sorted({row["field"] for row in field_metric_rows})
    indexed = {(row["data_file"], row["field"]): row for row in field_metric_rows}

    mean_f1 = {}
    for field in fields:
        values = [
            _parse_metric(indexed[(data_file, field)]["micro_f1"])
            for data_file in data_files
        ]
        mean_f1[field] = _mean(values)
    fields.sort(
        key=lambda field: (
            mean_f1[field] is None,
            mean_f1[field] if mean_f1[field] is not None else 0.0,
            field,
        )
    )

    heatmap_dir = output_dir / "heatmaps"
    heatmap_dir.mkdir(parents=True, exist_ok=True)
    _write_tsv(
        heatmap_dir / "field_order.tsv",
        ["order", "field", "mean_per_file_f1"],
        [
            {
                "order": index,
                "field": field,
                "mean_per_file_f1": _format_metric(mean_f1[field]),
            }
            for index, field in enumerate(fields, start=1)
        ],
    )

    width = min(24.0, max(10.0, 0.38 * len(fields)))
    height = min(24.0, max(7.0, 0.18 * len(data_files)))
    y_step = max(1, int(np.ceil(len(data_files) / 40.0)))
    saved_paths = []
    for metric, label, color in metrics:
        matrix = np.full((len(data_files), len(fields)), np.nan, dtype=float)
        for row_index, data_file in enumerate(data_files):
            for column_index, field in enumerate(fields):
                value = indexed[(data_file, field)][metric]
                matrix[row_index, column_index] = (
                    np.nan if value == "NA" else float(value)
                )

        color_map = LinearSegmentedColormap.from_list(
            metric, ["#ffffff", color]
        )
        color_map.set_bad("#d9d9d9")
        figure, axis = plt.subplots(figsize=(width, height))
        if metric.startswith("micro_"):
            image = axis.imshow(
                matrix, aspect="auto", interpolation="nearest",
                cmap=color_map, vmin=0.0, vmax=1.0,
            )
        else:
            image = axis.imshow(
                matrix, aspect="auto", interpolation="nearest",
                cmap=color_map, vmin=0.0,
            )
        axis.set_xticks(range(len(fields)))
        axis.set_xticklabels(fields, rotation=45, ha="right", fontsize=7)
        y_positions = list(range(0, len(data_files), y_step))
        axis.set_yticks(y_positions)
        axis.set_yticklabels([data_files[index] for index in y_positions], fontsize=6)
        axis.set_xlabel("Metadata field, sorted by ascending mean per-file F1")
        axis.set_ylabel("Raw data file")
        figure.suptitle(
            "{} heatmap\n{}: {}, {} matched raw files".format(
                label, pxd, comparison_name, len(data_files)
            ),
            fontsize=13,
            fontstyle="italic",
            fontweight="normal",
        )
        color_bar = figure.colorbar(image, ax=axis, pad=0.01)
        color_bar.set_label(label)
        figure.tight_layout()
        path = heatmap_dir / (metric + ".png")
        figure.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(figure)
        saved_paths.append(path)
    return saved_paths


def _remove_stale_comparison_dirs(output_root, pxd, expected_names):
    pxd_output = output_root / pxd
    known_names = {"store_vs_pride", "user_vs_pride", "store_vs_user"}
    for name in known_names - set(expected_names):
        path = pxd_output / name
        if path.is_dir():
            shutil.rmtree(str(path))


def _comparison_report(
    pxd, assessed_table, gold_table, report_fields, output_root, fuzzy_threshold
):
    assessed_rows = _table_rows_by_data_file(assessed_table)
    gold_rows = _table_rows_by_data_file(gold_table)

    comparison_name = "{}_vs_{}".format(assessed_table.source, gold_table.source)
    output_dir = output_root / pxd / comparison_name
    output_dir.mkdir(parents=True, exist_ok=True)
    category_metric_rows = []
    field_metric_rows = []
    entity_rows = []
    matched_files = sorted(set(assessed_rows) & set(gold_rows))
    missing_files = sorted(set(gold_rows) - set(assessed_rows))
    extra_files = sorted(set(assessed_rows) - set(gold_rows))

    for data_file_key in matched_files:
        _, assessed_group = assessed_rows[data_file_key]
        gold_name, gold_group = gold_rows[data_file_key]
        assessed_by_category = _rows_entities(assessed_table, assessed_group)
        gold_by_category = _rows_entities(gold_table, gold_group)
        for category in REPORT_CATEGORIES:
            category_matched = 0
            category_store_total = 0
            category_pride_total = 0
            category_fields = sorted(
                field for field, field_category in report_fields.items()
                if field_category == category
            )
            for field in category_fields:
                assessed_entities = [
                    entity for entity in assessed_by_category[category]
                    if entity["field"] == field
                ]
                gold_entities = [
                    entity for entity in gold_by_category[category]
                    if entity["field"] == field
                ]
                matches = _match_entities(assessed_entities, gold_entities, fuzzy_threshold)
                matched, precision, recall, f1 = _metrics(
                    matches, len(assessed_entities), len(gold_entities)
                )
                category_matched += matched
                category_store_total += len(assessed_entities)
                category_pride_total += len(gold_entities)
                field_metric_rows.append(
                    {
                        "pxd": pxd,
                        "data_file": gold_name,
                        "category": category,
                        "field": field,
                        "assessed_entities": len(assessed_entities),
                        "gold_entities": len(gold_entities),
                        "matched_entities": matched,
                        "assessed_only_entities": len(assessed_entities) - matched,
                        "gold_only_entities": len(gold_entities) - matched,
                        "micro_precision": _format_metric(precision),
                        "micro_recall": _format_metric(recall),
                        "micro_f1": _format_metric(f1),
                    }
                )
                for match in matches:
                    assessed_entity = match["assessed"] or {}
                    gold_entity = match["gold"] or {}
                    entity_rows.append(
                        {
                            "pxd": pxd,
                            "data_file": gold_name,
                            "category": category,
                            "field": field,
                            "assessed_value": assessed_entity.get("raw_value", ""),
                            "gold_value": gold_entity.get("raw_value", ""),
                            "normalized_assessed_value": assessed_entity.get("normalized_value", ""),
                            "normalized_gold_value": gold_entity.get("normalized_value", ""),
                            "status": match["status"],
                            "match_method": match["method"],
                            "similarity": "{:.6f}".format(match["similarity"]),
                        }
                    )

            precision, recall, f1 = _scores(
                category_matched, category_store_total, category_pride_total
            )
            category_metric_rows.append(
                {
                    "pxd": pxd,
                    "data_file": gold_name,
                    "category": category,
                    "assessed_entities": category_store_total,
                    "gold_entities": category_pride_total,
                    "matched_entities": category_matched,
                    "assessed_only_entities": category_store_total - category_matched,
                    "gold_only_entities": category_pride_total - category_matched,
                    "precision": _format_metric(precision),
                    "recall": _format_metric(recall),
                    "f1": _format_metric(f1),
                }
            )

    category_summary = {}
    for category in REPORT_CATEGORIES:
        rows = [row for row in category_metric_rows if row["category"] == category]
        matched = sum(row["matched_entities"] for row in rows)
        store_total = sum(row["assessed_entities"] for row in rows)
        pride_total = sum(row["gold_entities"] for row in rows)
        micro_precision, micro_recall, micro_f1 = _scores(
            matched, store_total, pride_total
        )
        category_summary[category] = {
            "matched_entities": matched,
            "assessed_entities": store_total,
            "gold_entities": pride_total,
            "macro_precision": _mean([_parse_metric(row["precision"]) for row in rows]),
            "macro_recall": _mean([_parse_metric(row["recall"]) for row in rows]),
            "macro_f1": _mean([_parse_metric(row["f1"]) for row in rows]),
            "micro_precision": micro_precision,
            "micro_recall": micro_recall,
            "micro_f1": micro_f1,
        }

    field_summary = {}
    for field in sorted(report_fields):
        rows = [row for row in field_metric_rows if row["field"] == field]
        matched = sum(row["matched_entities"] for row in rows)
        store_total = sum(row["assessed_entities"] for row in rows)
        pride_total = sum(row["gold_entities"] for row in rows)
        field_summary[field] = {
            "category": report_fields[field],
            "matched_entities": matched,
            "assessed_entities": store_total,
            "gold_entities": pride_total,
            "macro_precision": _mean([_parse_metric(row["micro_precision"]) for row in rows]),
            "macro_recall": _mean([_parse_metric(row["micro_recall"]) for row in rows]),
            "macro_f1": _mean([_parse_metric(row["micro_f1"]) for row in rows]),
        }

    summary = {
        "pxd": pxd,
        "comparison": comparison_name,
        "assessed_source": assessed_table.source,
        "gold_standard": gold_table.source,
        "matching_key": "comment[data file]",
        "file_matching": "normalized exact",
        "entity_matching": {
            "methods": ["exact_normalized", "cv_accession", "fuzzy"],
            "fuzzy_threshold": fuzzy_threshold,
            "constraint": "same canonical SDRF field",
        },
        "files": {
            "gold": len(gold_rows),
            "assessed": len(assessed_rows),
            "matched": len(matched_files),
            "missing_from_assessed": len(missing_files),
            "extra_in_assessed": len(extra_files),
            "coverage": float(len(matched_files)) / len(gold_rows) if gold_rows else 0.0,
        },
        "categories": category_summary,
        "fields": field_summary,
        "missing_assessed_data_files": [gold_rows[key][0] for key in missing_files],
        "extra_assessed_data_files": [assessed_rows[key][0] for key in extra_files],
    }

    _write_tsv(
        output_dir / "sample_category_metrics.tsv",
        [
            "pxd", "data_file", "category", "assessed_entities", "gold_entities",
            "matched_entities", "assessed_only_entities", "gold_only_entities",
            "precision", "recall", "f1",
        ],
        category_metric_rows,
    )
    _write_tsv(
        output_dir / "sample_field_metrics.tsv",
        [
            "pxd", "data_file", "category", "field", "assessed_entities",
            "gold_entities", "matched_entities", "assessed_only_entities",
            "gold_only_entities", "micro_precision", "micro_recall", "micro_f1",
        ],
        field_metric_rows,
    )
    field_summary_rows = []
    for field, values in sorted(
        field_summary.items(), key=lambda item: (item[1]["category"], item[0])
    ):
        field_summary_rows.append(dict({"field": field}, **values))
    _write_tsv(
        output_dir / "field_summary.tsv",
        [
            "field", "category", "assessed_entities", "gold_entities",
            "matched_entities", "macro_precision", "macro_recall", "macro_f1",
        ],
        field_summary_rows,
    )
    _write_tsv(
        output_dir / "entity_matches.tsv",
        [
            "pxd", "data_file", "category", "field", "assessed_value", "gold_value",
            "normalized_assessed_value", "normalized_gold_value", "status",
            "match_method", "similarity",
        ],
        entity_rows,
    )
    # heatmap_paths = _write_field_heatmaps(
    #     field_metric_rows, output_dir, pxd, comparison_name
    # )
    # summary["heatmaps"] = [str(path.relative_to(output_dir)) for path in heatmap_paths]
    (output_dir / "conflict_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    report_lines = [
        "# Conflict assessment: {} ({} vs {})".format(
            pxd, assessed_table.source, gold_table.source
        ),
        "",
        "{} is the gold standard. Rows are aligned by normalized exact `comment[data file]`; metadata entities are matched only within the same canonical field.".format(gold_table.source.upper()),
        "",
        "## File coverage",
        "",
        "| Gold files | Assessed files | Matched | Missing from assessed | Assessed only | Coverage |",
        "|---:|---:|---:|---:|---:|---:|",
        "| {gold} | {assessed} | {matched} | {missing_from_assessed} | {extra_in_assessed} | {coverage:.1%} |".format(**summary["files"]),
        "",
        "## Metadata agreement across matched files",
        "",
        "| Category | Macro precision | Macro recall | Macro F1 | Micro precision | Micro recall | Micro F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for category in REPORT_CATEGORIES:
        values = category_summary[category]
        report_lines.append(
            "| {category} | {macro_precision} | {macro_recall} | {macro_f1} | {micro_precision} | {micro_recall} | {micro_f1} |".format(
                category=category,
                **{key: _markdown_metric(values[key]) for key in (
                    "macro_precision", "macro_recall", "macro_f1",
                    "micro_precision", "micro_recall", "micro_f1"
                )}
            )
        )
    report_lines.extend(
        [
            "",
            "## Metadata type agreement across matched files",
            "",
            "| Metadata type | Category | Mean precision | Mean recall | Mean F1 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for field, values in sorted(
        field_summary.items(), key=lambda item: (item[1]["category"], item[0])
    ):
        report_lines.append(
            "| `{field}` | {category} | {macro_precision} | {macro_recall} | {macro_f1} |".format(
                field=field,
                category=values["category"],
                **{key: _markdown_metric(values[key]) for key in (
                    "macro_precision", "macro_recall", "macro_f1"
                )}
            )
        )
    report_lines.extend(
        [
            "",
            "Metadata averages include only the {} uniquely matched files. Missing files are reported as coverage failures rather than zero-score metadata rows.".format(len(matched_files)),
            "",
            "Detailed results: `sample_field_metrics.tsv`, `field_summary.tsv`, `sample_category_metrics.tsv`, `entity_matches.tsv`, and the `heatmaps/` directory.",
        ]
    )
    (output_dir / "conflict_report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary, output_dir


def _find_user_sdrf(sdrf_dir, pxd):
    if sdrf_dir is None:
        return None
    if sdrf_dir.is_file():
        return sdrf_dir
    candidates = [
        sdrf_dir / (pxd + ".sdrf.tsv"),
        sdrf_dir / pxd / (pxd + ".sdrf.tsv"),
        sdrf_dir / pxd / "sdrf.tsv",
    ]
    matches = []
    for candidate in candidates:
        if candidate.is_file() and candidate not in matches:
            matches.append(candidate)
    if not matches:
        patterns = (
            "**/{}*.sdrf.tsv".format(pxd),
            "**/*{}*.csv".format(pxd),
        )
        for pattern in patterns:
            for match in sorted(sdrf_dir.glob(pattern)):
                if match not in matches:
                    matches.append(match)
    if len(matches) > 1:
        raise ValueError("multiple user SDRFs found: {}".format(", ".join(map(str, matches))))
    return matches[0] if matches else None


def _fetch_pride_sdrf(pxd, timeout, retries):
    endpoint = PRIDE_SDRF_ENDPOINT.format(pxd=pxd)
    payload = _request_bytes(endpoint, timeout, retries)
    try:
        urls = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RuntimeError("invalid PRIDE API response: {}".format(exc))
    if not isinstance(urls, list):
        raise RuntimeError("PRIDE API response is not a URL list")
    if not urls:
        return None
    if len(urls) > 1:
        raise RuntimeError("PRIDE returned multiple SDRFs: {}".format(urls))

    url = str(urls[0])
    download_url = url.replace("ftp://ftp.pride.ebi.ac.uk/", "https://ftp.pride.ebi.ac.uk/", 1)
    text = _request_bytes(download_url, timeout, retries).decode("utf-8-sig")
    try:
        return _parse_sdrf_text(text, "pride", url)
    except ValueError as exc:
        raise RuntimeError("invalid PRIDE SDRF {}: {}".format(url, exc))


def _print_table_summary(table):
    category_counts = Counter()
    for category, columns in table.categorized_values.items():
        category_counts[category] = sum(bool(column["values"]) for column in columns)
    counts = ", ".join(
        "{}={}".format(category, category_counts[category])
        for category in ("Identity", "Biological", "Technical", "ExperimentalDesign", "Other")
    )
    print(
        "  {}: rows={}, columns={}, populated category columns={} ({})".format(
            table.source, len(table.rows), len(table.headers), sum(category_counts.values()), counts
        )
    )
    print("    location: {}".format(table.location))
    print("    first sample key: {}".format(table.sample_keys[0]))


def _pxd_directories(store_dir, selected_pxd):
    root = store_dir / "agentic_results_files"
    if not root.is_dir():
        raise ValueError("agentic_results_files directory not found under {}".format(store_dir))
    if selected_pxd:
        if not PXD_PATTERN.match(selected_pxd):
            raise ValueError("invalid PXD accession: {}".format(selected_pxd))
        return [root / selected_pxd]
    return [path for path in sorted(root.glob("PXD*")) if path.is_dir()]


def main():
    args = parse_args()
    store_dir = args.store_dir.resolve()
    sdrf_dir = args.sdrf_dir.resolve() if args.sdrf_dir else None
    output_root = args.output_dir.resolve()
    if sdrf_dir is not None and not sdrf_dir.exists():
        raise SystemExit("User SDRF file or directory not found: {}".format(sdrf_dir))
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if not 0.0 <= args.fuzzy_threshold <= 1.0:
        raise SystemExit("--fuzzy-threshold must be between 0 and 1")

    selected_pxd = args.pxd
    if sdrf_dir is not None and sdrf_dir.is_file() and selected_pxd is None:
        match = re.search(r"PXD\d{6,}", sdrf_dir.name, flags=re.IGNORECASE)
        if match is None:
            raise SystemExit("--pxd is required when the user SDRF filename has no PXD accession")
        selected_pxd = match.group(0).upper()

    try:
        pxd_directories = _pxd_directories(store_dir, selected_pxd)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if args.limit is not None:
        pxd_directories = pxd_directories[: args.limit]

    inspected = 0
    ready = 0
    skipped = 0
    for pxd_dir in pxd_directories:
        pxd = pxd_dir.name
        inspected += 1
        print("\n[{}]".format(pxd))

        store_path = pxd_dir / (pxd + ".sdrf.tsv")
        if not store_path.is_file():
            _warn(pxd, "no store SDRF; skipping")
            skipped += 1
            continue
        try:
            store_table = _load_local_sdrf(store_path, "store")
        except ValueError as exc:
            _warn(pxd, "{}; skipping".format(exc))
            skipped += 1
            continue

        user_table = None
        if sdrf_dir is not None:
            try:
                user_path = _find_user_sdrf(sdrf_dir, pxd)
                if user_path is None:
                    _warn(pxd, "no user-supplied SDRF found")
                else:
                    user_table = _load_local_sdrf(user_path, "user")
            except ValueError as exc:
                _warn(pxd, str(exc))

        try:
            pride_table = _fetch_pride_sdrf(pxd, args.timeout, args.retries)
        except RuntimeError as exc:
            _warn(pxd, "{}; skipping".format(exc))
            skipped += 1
            continue
        if pride_table is None:
            _warn(pxd, "PRIDE/ProteomeXchange has no SDRF; only store SDRF is available; skipping")
            skipped += 1
            continue
        pride_snapshot = output_root / pxd / "pride.sdrf.tsv"
        _write_sdrf_snapshot(pride_table, pride_snapshot)
        print("  PRIDE snapshot: {}".format(pride_snapshot))

        tables = [store_table]
        if user_table is not None:
            tables.append(user_table)
        tables.append(pride_table)
        print("  comparison-ready sources: {}".format(", ".join(table.source for table in tables)))
        for table in tables:
            _print_table_summary(table)
        report_fields = {}
        for header in store_table.headers:
            category = _field_category(header)
            if category in REPORT_CATEGORIES:
                report_fields[_canonical_field(header)] = category
        comparisons = [(store_table, pride_table)]
        if user_table is not None:
            comparisons.extend(
                [
                    (user_table, pride_table),
                    (store_table, user_table),
                ]
            )
        expected_comparisons = [
            "{}_vs_{}".format(assessed.source, gold.source)
            for assessed, gold in comparisons
        ]
        _remove_stale_comparison_dirs(output_root, pxd, expected_comparisons)
        successful_reports = 0
        for assessed_table, gold_table in comparisons:
            try:
                summary, report_dir = _comparison_report(
                    pxd,
                    assessed_table,
                    gold_table,
                    report_fields,
                    output_root,
                    args.fuzzy_threshold,
                )
            except ValueError as exc:
                _warn(
                    pxd,
                    "{}_vs_{} comparison failed: {}".format(
                        assessed_table.source, gold_table.source, exc
                    ),
                )
                continue
            print(
                "  {} report: {} (matched={matched}, missing={missing_from_assessed}, coverage={coverage:.1%})".format(
                    summary["comparison"], report_dir, **summary["files"]
                )
            )
            successful_reports += 1
        if not successful_reports:
            skipped += 1
            continue
        ready += 1

    print("\nSummary: inspected={}, comparison_ready={}, skipped={}".format(inspected, ready, skipped))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())