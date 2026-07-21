#!/usr/bin/env python3
"""Build Figure 1 (2x2 layout) for manuscript paneling.

Panel a (upper-left): Availability of PRIDE datasets with linked publication,
open-access/usable BY license, and SDRF metadata (all PXDs in master.csv).
Panel b (upper-right): Existing vs HAMLET field availability (HAMLET PXDs only).
Panel c (lower-left): Annotation availability by metadata class from .ann files.
Panel d (lower-right): Agreement by metadata class.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import pandas as pd
import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Figure 1 2x2 manuscript panel.")
    parser.add_argument(
        "--crosswalk",
        default="src/analysis/Figure1/data/field_crosswalk_table.csv",
        help="Crosswalk CSV with PRIDE + ann mapping.",
    )
    parser.add_argument(
        "--pride-cache",
        default="pride_survey/pride_cache",
        help="Path to local PRIDE cache JSON.",
    )
    parser.add_argument(
        "--results-dir",
        default="results",
        help="Root directory containing PXD result folders with SDRF outputs.",
    )
    parser.add_argument(
        "--hamlet-pxds",
        default="HamletPXDs.csv",
        help="CSV containing Hamlet PXDs (expects PXDs or pxd column).",
    )
    parser.add_argument(
        "--master-csv",
        default="master.csv",
        help="Master CSV for panel a (all PXDs).",
    )
    parser.add_argument(
        "--sdrf-presence-cache",
        default="src/analysis/Figure1/output/all_master_sdrf_presence.csv",
        help="CSV cache for PRIDE SDRF endpoint presence checks.",
    )
    parser.add_argument(
        "--ann-root",
        default="src/analysis/Figure1/data/Select_27_Pubs",
        help="Root containing MultiHuman and SingleHuman .ann files.",
    )
    parser.add_argument(
        "--outdir",
        default="src/analysis/Figure1/output",
        help="Directory for figure and tables.",
    )
    parser.add_argument(
        "--basename",
        default="figure1_composite",
        help="Base filename for output files.",
    )
    parser.add_argument(
        "--refresh-sdrf-cache",
        action="store_true",
        help="Requery PRIDE SDRF endpoint for panel a even if cache file exists.",
    )
    return parser.parse_args()


def configure_font_prefer_arial() -> str:
    available = {f.name for f in fm.fontManager.ttflist}
    if "Arial" in available:
        plt.rcParams["font.family"] = "Arial"
        return "Arial"

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Arial", "Helvetica", "DejaVu Sans"]
    return "sans-serif fallback (Arial not installed)"


# -----------------------------------------------------------------------------
# Panel B helpers (existing logic, kept deterministic)
# -----------------------------------------------------------------------------


def _clean_path_expr(expr: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", str(expr)).strip()


def _split_alternatives(expr: str) -> list[str]:
    expr = _clean_path_expr(expr)
    if not expr:
        return []

    parts = [expr]
    for sep in [" OR ", " / "]:
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(sep))
        parts = next_parts

    return [part.strip() for part in parts if part.strip()]


def _normalize_clause_for_compare(clause: str) -> str:
    token = _clean_path_expr(clause).strip()
    token = re.sub(r"\s+", "", token)
    return token.lower()


def _is_only_sample_processing_protocol(expr: str) -> bool:
    alts = _split_alternatives(expr)
    if not alts:
        return False
    return {_normalize_clause_for_compare(alt) for alt in alts} == {
        "response[].sampleprocessingprotocol"
    }


def _is_only_processing_protocol_paths(expr: str) -> bool:
    alts = _split_alternatives(expr)
    if not alts:
        return False
    normalized = {_normalize_clause_for_compare(alt) for alt in alts}
    allowed = {
        "response[].sampleprocessingprotocol",
        "response[].dataprocessingprotocol",
        "protocols",
    }
    return normalized.issubset(allowed)


def _is_only_experiment_types_or_project_tags(expr: str) -> bool:
    alts = _split_alternatives(expr)
    if not alts:
        return False
    normalized = {_normalize_clause_for_compare(alt) for alt in alts}
    allowed = {
        "response[].experimenttypes",
        "response[].projecttags",
    }
    return normalized.issubset(allowed)


def _is_only_generic_design_paths(expr: str) -> bool:
    alts = _split_alternatives(expr)
    if not alts:
        return False
    normalized = {_normalize_clause_for_compare(alt) for alt in alts}
    allowed = {
        "response[].sampleattributes",
        "response[].projectdescription",
        "response[].sampleprocessingprotocol",
        "response[].sampleattributes/response[].projectdescription",
        "response[].projectdescription/response[].sampleprocessingprotocol",
        "response[].sampleprocessingprotocol/response[].projectdescription",
    }
    return normalized.issubset(allowed)


def _extract_scalar_name(value: object) -> str:
    if isinstance(value, dict):
        if "name" in value and value["name"] is not None:
            return str(value["name"]).strip().lower()
        if "value" in value and value["value"] is not None:
            return str(value["value"]).strip().lower()
    if value is None:
        return ""
    return str(value).strip().lower()


def _has_non_empty(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    if isinstance(value, dict):
        return len(value) > 0
    return True


def _is_annotation_value(value: object) -> bool:
    if value is None:
        return False
    text = str(value).strip().lower()
    if text == "":
        return False
    if text in {"not available", "n/a", "na", "none", "unknown", "nan"}:
        return False
    return True


def _sample_attribute_match(entry: dict, synonyms: list[str]) -> bool:
    attrs = entry.get("sampleAttributes") or []
    synonym_set = {s.strip().lower() for s in synonyms if s.strip()}
    for attr in attrs:
        key_name = ""
        if isinstance(attr, dict):
            key_name = _extract_scalar_name(attr.get("key"))
        if key_name and any(s in key_name for s in synonym_set):
            return True
    return False


def _match_clause(entry: dict, clause: str) -> bool:
    token = clause.strip()
    if not token:
        return False

    if token.lower().startswith("response[]."):
        token = token[len("response[].") :]

    lowered = token.lower().strip()

    if lowered.startswith("sampleattributes["):
        m = re.search(r"key\.name~([^\]]+)", token, flags=re.IGNORECASE)
        if not m:
            return _has_non_empty(entry.get("sampleAttributes"))
        synonyms = [s.strip() for s in m.group(1).split("|")]
        return _sample_attribute_match(entry, synonyms)

    if lowered in {"protocols", "sampleprocessingprotocol", "dataprocessingprotocol"}:
        return _has_non_empty(entry.get("sampleProcessingProtocol")) or _has_non_empty(
            entry.get("dataProcessingProtocol")
        )

    if lowered == "identifiedptmstrings":
        vals = entry.get("identifiedPTMStrings")
        if not _has_non_empty(vals):
            return False
        if not isinstance(vals, list):
            vals = [vals]
        for item in vals:
            name_val = (
                str(item.get("name", "")).strip().lower()
                if isinstance(item, dict)
                else str(item).strip().lower()
            )
            if not name_val:
                continue
            if "no ptms are included in the dataset" in name_val:
                continue
            return True
        return False

    field_name = re.sub(r"\[.*\]", "", token).strip()
    if not field_name:
        return False

    if field_name in entry:
        return _has_non_empty(entry.get(field_name))

    key_map = {str(k).lower(): k for k in entry.keys()}
    k = key_map.get(field_name.lower())
    return _has_non_empty(entry.get(k)) if k else False


def _acquisition_valid_from_experiment_metadata(entry: dict) -> bool:
    valid_terms = {
        "data-dependent acquisition (pride:0000627)",
        "data-independent acquisition (pride:0000450)",
    }

    def _iter_names(values: object) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list):
            values = [values]
        out: list[str] = []
        for item in values:
            if isinstance(item, dict):
                name = str(item.get("name", "")).strip()
                acc = str(item.get("accession", "")).strip()
                if name and acc:
                    out.append(f"{name} ({acc})".lower())
                elif name:
                    out.append(name.lower())
                elif acc:
                    out.append(acc.lower())
            else:
                txt = str(item).strip().lower()
                if txt:
                    out.append(txt)
        return out

    terms = _iter_names(entry.get("experimentTypes")) + _iter_names(entry.get("projectTags"))
    return any(term in valid_terms for term in terms)


def compute_presence_counts(
    crosswalk_df: pd.DataFrame, pxds: list[str], cache_by_pxd: dict[str, dict]
) -> pd.DataFrame:
    pxd_set = set(pxds)
    total = len(pxds)
    rows: list[dict[str, object]] = []

    for row in crosswalk_df.itertuples(index=False):
        expr = str(getattr(row, "pride_cache_field_path", "") or "")
        alternatives = _split_alternatives(expr)
        expr_lower = expr.lower()
        agentic_field = str(getattr(row, "agentic_field", "") or "").strip().lower()

        if agentic_field == "ptm":
            alternatives = [alt for alt in alternatives if "identifiedPTMStrings" in alt]

        if agentic_field == "fragmentation_method" and _is_only_processing_protocol_paths(expr):
            alternatives = []

        if agentic_field == "acquisition_method" and _is_only_experiment_types_or_project_tags(expr):
            alternatives = []

        if agentic_field in {
            "factor_value",
            "number_of_biological_replicates",
            "number_of_technical_replicates",
            "number_of_fractions",
            "biological_replicate",
            "technical_replicate",
        } and _is_only_generic_design_paths(expr):
            alternatives = []

        curated_count_value = getattr(row, "pride_present_in_sampled_n", 0)
        try:
            curated_count = int(curated_count_value)
        except (TypeError, ValueError):
            curated_count = 0

        use_curated = ("free text" in expr_lower) or ("inferred" in expr_lower)
        only_sample_processing = _is_only_sample_processing_protocol(expr)

        count = 0
        if only_sample_processing:
            count = 0
            count_source = "not_available_only_sampleProcessingProtocol"
        elif agentic_field == "fragmentation_method" and _is_only_processing_protocol_paths(expr):
            count = 0
            count_source = "not_available_only_protocol_paths"
        elif agentic_field == "acquisition_method" and _is_only_experiment_types_or_project_tags(expr):
            count = 0
            for pxd in pxd_set:
                entry = cache_by_pxd.get(pxd)
                if entry and _acquisition_valid_from_experiment_metadata(entry):
                    count += 1
            count_source = "restricted_to_DDA_or_DIA"
        elif agentic_field in {
            "factor_value",
            "number_of_biological_replicates",
            "number_of_technical_replicates",
            "number_of_fractions",
            "biological_replicate",
            "technical_replicate",
        } and _is_only_generic_design_paths(expr):
            count = 0
            count_source = "not_available_only_generic_design_paths"
        elif use_curated:
            count = curated_count
            count_source = "crosswalk_curated"
        else:
            count_source = "cache_recomputed"
            for pxd in pxd_set:
                entry = cache_by_pxd.get(pxd)
                if not entry or not alternatives:
                    continue
                if any(_match_clause(entry, alt) for alt in alternatives):
                    count += 1

        out = dict(row._asdict())
        out["pride_present_in_sampled_n_recomputed"] = count
        out["sample_size_recomputed"] = total
        out["pride_present_fraction_recomputed"] = (count / total) if total else 0.0
        out["presence_count_source"] = count_source
        rows.append(out)

    return pd.DataFrame(rows)


def _parse_sdrf_columns(cell: str) -> list[str]:
    text = str(cell or "").strip()
    if not text or text.lower().startswith("(not"):
        return []
    cols: list[str] = []
    for part in text.split(";"):
        cleaned = part.strip().replace("*", "")
        cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned).strip()
        if cleaned:
            cols.append(cleaned)
    return cols


def _find_sdrf_path(results_dir: Path, pxd: str) -> Path | None:
    direct = results_dir / pxd / "agentic_metadata" / f"{pxd}.sdrf.tsv"
    if direct.exists():
        return direct
    nested = sorted((results_dir / pxd).glob("agentic_metadata/**/*.sdrf.tsv"))
    return nested[0] if nested else None


def compute_hamlet_counts(
    filtered_df: pd.DataFrame, pxds: list[str], results_dir: Path
) -> pd.DataFrame:
    field_to_columns = {
        row.agentic_field: _parse_sdrf_columns(row.final_sdrf_columns)
        for row in filtered_df.itertuples(index=False)
    }
    field_to_count = {field: 0 for field in field_to_columns}

    for pxd in pxds:
        sdrf_path = _find_sdrf_path(results_dir, pxd)
        if sdrf_path is None:
            continue
        try:
            sdrf_df = pd.read_csv(sdrf_path, sep="\t")
        except Exception:
            continue

        for field, columns in field_to_columns.items():
            if not columns:
                continue
            present = False
            for col in columns:
                if col in sdrf_df.columns and sdrf_df[col].map(_is_annotation_value).any():
                    present = True
                    break
            if present:
                field_to_count[field] += 1

    return pd.DataFrame(
        {
            "agentic_field": list(field_to_count.keys()),
            "hamlet_present_in_sampled_n": list(field_to_count.values()),
        }
    )


# -----------------------------------------------------------------------------
# Panel A helpers
# -----------------------------------------------------------------------------


def load_or_query_sdrf_presence(accessions: list[str], cache_csv: Path, refresh: bool) -> pd.DataFrame:
    def _normalize_bool_series(series: pd.Series) -> pd.Series:
        lowered = series.astype(str).str.strip().str.lower()
        return lowered.isin({"true", "1", "yes", "y", "t"})

    if cache_csv.exists() and not refresh:
        cached = pd.read_csv(cache_csv)
        if {"accession", "existing_PRIDE_SDRF"}.issubset(cached.columns):
            cached = cached.rename(
                columns={"accession": "pxd", "existing_PRIDE_SDRF": "has_sdrf"}
            )
            cached["has_sdrf"] = _normalize_bool_series(cached["has_sdrf"])

        if {"pxd", "has_sdrf"}.issubset(cached.columns):
            have = set(cached["pxd"].astype(str).str.strip())
            missing = [a for a in accessions if a not in have]
            if not missing:
                return cached[["pxd", "has_sdrf"]]
            accessions = missing
            existing = cached[["pxd", "has_sdrf"]].copy()
        else:
            existing = pd.DataFrame(columns=["pxd", "has_sdrf"])
    else:
        existing = pd.DataFrame(columns=["pxd", "has_sdrf"])

    endpoint = "https://www.ebi.ac.uk/pride/ws/archive/v3/files/sdrf/{}"
    session = requests.Session()
    rows = []
    for idx, pxd in enumerate(accessions, start=1):
        has_sdrf = False
        try:
            resp = session.get(endpoint.format(pxd), timeout=30)
            data = resp.json() if resp.ok else []
            has_sdrf = bool(data)
        except Exception:
            has_sdrf = False
        rows.append({"pxd": pxd, "has_sdrf": has_sdrf})
        if idx % 200 == 0:
            print(f"SDRF query progress: {idx}/{len(accessions)}")

    new_df = pd.DataFrame(rows)
    out = pd.concat([existing, new_df], ignore_index=True).drop_duplicates(subset=["pxd"], keep="last")
    cache_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(cache_csv, index=False)
    return out


def compute_panel_a(master_df: pd.DataFrame, sdrf_df: pd.DataFrame) -> tuple[dict[str, int], pd.DataFrame]:
    all_pxds = master_df["accession"].astype(str).str.strip()
    pmc_mask = master_df["pmc_id"].notna() & master_df["pmc_id"].astype(str).str.strip().ne("")
    lic = master_df["pub_license"].fillna("").astype(str).str.strip()
    by_mask = lic.str.match(r"^CC\s+BY", na=False) | (lic == "CC0")

    sdrf_map = dict(zip(sdrf_df["pxd"].astype(str), sdrf_df["has_sdrf"].astype(bool)))
    sdrf_mask = all_pxds.map(lambda x: bool(sdrf_map.get(x, False)))

    total = len(master_df)
    stats = {
        "PRIDE PXD": total,
        "PMC": int(pmc_mask.sum()),
        "BY": int(by_mask.sum()),
        "SDRF": int(sdrf_mask.sum()),
        "PMC_BY": int((pmc_mask & by_mask).sum()),
        "PMC_BY_SDRF": int((pmc_mask & by_mask & sdrf_mask).sum()),
    }

    membership = pd.DataFrame(
        {
            "accession": all_pxds,
            "has_pmc": pmc_mask,
            "has_by": by_mask,
            "has_sdrf": sdrf_mask,
        }
    )
    return stats, membership


# -----------------------------------------------------------------------------
# Panel C/D helpers (.ann)
# -----------------------------------------------------------------------------


def _parse_ann_entities(ann_path: Path) -> set[str]:
    labels: set[str] = set()
    try:
        txt = ann_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return labels

    for line in txt.splitlines():
        if not line.startswith("T"):
            continue
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue
        span_parts = parts[1].split()
        if not span_parts:
            continue
        labels.add(span_parts[0].strip())
    return labels


def _crosswalk_ann_label_map(crosswalk_df: pd.DataFrame) -> tuple[dict[str, str], dict[str, str]]:
    """Return ann label -> class and ann label -> agentic field representative."""
    ann_to_class: dict[str, str] = {}
    ann_to_field: dict[str, str] = {}

    for row in crosswalk_df.itertuples(index=False):
        cls = str(getattr(row, "category", "") or "").strip().lower()
        field = str(getattr(row, "agentic_field", "") or "").strip()
        labels = str(getattr(row, "ann_metadata_labels", "") or "").strip()
        if not labels:
            continue
        for token in labels.split(";"):
            t = token.strip()
            if not t:
                continue
            ann_to_class[t] = cls
            ann_to_field[t] = field
    return ann_to_class, ann_to_field


def _cohen_kappa_binary(a: list[int], b: list[int]) -> float:
    if len(a) != len(b) or len(a) == 0:
        return float("nan")
    n = len(a)
    p0 = sum(1 for x, y in zip(a, b) if x == y) / n
    pa = sum(a) / n
    pb = sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    if abs(1 - pe) < 1e-12:
        return float("nan")
    return (p0 - pe) / (1 - pe)


def _fleiss_kappa_binary_matrix(matrix: list[list[int]]) -> float:
    """Fleiss kappa for binary categories from n_items x n_raters matrix."""
    if not matrix:
        return float("nan")
    n_items = len(matrix)
    n_raters = len(matrix[0])
    if n_raters < 2:
        return float("nan")

    for row in matrix:
        if len(row) != n_raters:
            return float("nan")

    # Category counts per item (0,1)
    P_i = []
    total_ones = 0
    for row in matrix:
        n1 = sum(row)
        n0 = n_raters - n1
        total_ones += n1
        Pi = ((n0 * n0) + (n1 * n1) - n_raters) / (n_raters * (n_raters - 1))
        P_i.append(Pi)

    P_bar = sum(P_i) / n_items
    p1 = total_ones / (n_items * n_raters)
    p0 = 1.0 - p1
    P_e = p0 * p0 + p1 * p1

    if abs(1 - P_e) < 1e-12:
        return float("nan")
    return (P_bar - P_e) / (1 - P_e)


def _observed_agreement_binary_matrix(matrix: list[list[int]]) -> float:
    """Mean per-item agreement for binary ratings."""
    if not matrix:
        return float("nan")
    n_items = len(matrix)
    n_raters = len(matrix[0])
    if n_raters < 2:
        return float("nan")

    agreements: list[float] = []
    for row in matrix:
        if len(row) != n_raters:
            return float("nan")
        n1 = sum(row)
        n0 = n_raters - n1
        agreements.append(((n0 * n0) + (n1 * n1) - n_raters) / (n_raters * (n_raters - 1)))
    return sum(agreements) / n_items


def _positive_prevalence_binary_matrix(matrix: list[list[int]]) -> float:
    if not matrix:
        return float("nan")
    n_items = len(matrix)
    n_raters = len(matrix[0])
    if n_raters < 1:
        return float("nan")
    total = sum(sum(row) for row in matrix)
    return total / (n_items * n_raters)


def compute_ann_panels(
    ann_root: Path, crosswalk_df: pd.DataFrame, allowed_fields: set[str] | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ann_to_class, ann_to_field = _crosswalk_ann_label_map(crosswalk_df)

    field_category_map = {
        str(row.agentic_field).strip(): str(row.category).strip().lower()
        for row in crosswalk_df.itertuples(index=False)
        if str(getattr(row, "agentic_field", "") or "").strip()
    }

    multi_paths = sorted((ann_root / "MultiHuman").glob("*/*/*.ann"))
    single_paths = sorted((ann_root / "SingleHuman").glob("*.ann"))

    # doc -> annotator -> set(labels)
    multi_doc_ann: dict[str, dict[str, set[str]]] = defaultdict(dict)
    for p in multi_paths:
        annotator = p.parts[-3]
        doc_id = p.stem
        labels = _parse_ann_entities(p)
        multi_doc_ann[doc_id][annotator] = labels

    single_doc_labels: dict[str, set[str]] = {}
    for p in single_paths:
        single_doc_labels[p.stem] = _parse_ann_entities(p)

    fields_in_order = []
    seen_fields = set()
    for row in crosswalk_df.itertuples(index=False):
        field = str(getattr(row, "agentic_field", "") or "").strip()
        ann_labels = str(getattr(row, "ann_metadata_labels", "") or "").strip()
        if allowed_fields is not None and field not in allowed_fields:
            continue
        if field and ann_labels and field not in seen_fields:
            fields_in_order.append(field)
            seen_fields.add(field)

    # Panel C: availability (fraction of docs with >=1 label from mapped field)
    c_rows: list[dict[str, object]] = []
    docs_multi = sorted(multi_doc_ann.keys())
    n_docs = len(docs_multi)

    for field in fields_in_order:
        labels_for_field = {l for l, f in ann_to_field.items() if f == field}
        if not labels_for_field:
            c_rows.append(
                {
                    "category": field_category_map.get(field, "unknown"),
                    "agentic_field": field,
                    "availability_fraction": 0.0,
                    "availability_n": 0,
                    "n_docs": n_docs,
                }
            )
            continue

        present_docs = 0
        for doc in docs_multi:
            merged = set().union(*multi_doc_ann[doc].values()) if multi_doc_ann[doc] else set()
            if any(lbl in labels_for_field for lbl in merged):
                present_docs += 1

        c_rows.append(
            {
                "category": field_category_map.get(field, "unknown"),
                "agentic_field": field,
                "availability_fraction": (present_docs / n_docs) if n_docs else 0.0,
                "availability_n": present_docs,
                "n_docs": n_docs,
            }
        )

    panel_c_df = pd.DataFrame(c_rows)

    # Panel D: agreement
    d_rows: list[dict[str, object]] = []

    for field in fields_in_order:
        labels_for_field = {l for l, f in ann_to_field.items() if f == field}

        # MultiHuman Fleiss: per-doc binary presence per annotator for this field.
        # Use non-Ian raters only and keep a constant rater count subset.
        fleiss_items: list[list[int]] = []
        for doc, ann_map in multi_doc_ann.items():
            ann_names = sorted([a for a in ann_map.keys() if a.lower() != "ian"])
            if len(ann_names) < 2:
                continue
            row = [1 if any(lbl in labels_for_field for lbl in ann_map[a]) else 0 for a in ann_names]
            fleiss_items.append(row)

        # Fleiss requires constant number of raters; use the largest count-consistent subset.
        by_len: dict[int, list[list[int]]] = defaultdict(list)
        for r in fleiss_items:
            by_len[len(r)].append(r)
        if by_len:
            mode_n = max(by_len, key=lambda k: len(by_len[k]))
            mode_matrix = by_len[mode_n]
            fleiss_val = _fleiss_kappa_binary_matrix(mode_matrix)
            fleiss_obs = _observed_agreement_binary_matrix(mode_matrix)
            fleiss_prev = _positive_prevalence_binary_matrix(mode_matrix)
            fleiss_n_items = len(mode_matrix)
            fleiss_n_raters = mode_n
        else:
            fleiss_val = float("nan")
            fleiss_obs = float("nan")
            fleiss_prev = float("nan")
            fleiss_n_items = 0
            fleiss_n_raters = 0

        # SingleHuman vs MultiHuman consensus excluding Ian.
        single_vals: list[int] = []
        consensus_vals: list[int] = []
        for doc, s_labels in single_doc_labels.items():
            if doc not in multi_doc_ann:
                continue
            ann_map = multi_doc_ann[doc]
            non_ian = [a for a in ann_map.keys() if a.lower() != "ian"]
            if len(non_ian) == 0:
                continue

            votes = [1 if any(lbl in labels_for_field for lbl in ann_map[a]) else 0 for a in non_ian]
            consensus = 1 if sum(votes) >= math.ceil(len(votes) / 2) else 0
            single_present = 1 if any(lbl in labels_for_field for lbl in s_labels) else 0
            consensus_vals.append(consensus)
            single_vals.append(single_present)

        cohen_val = _cohen_kappa_binary(consensus_vals, single_vals)

        d_rows.append(
            {
                "category": field_category_map.get(field, "unknown"),
                "agentic_field": field,
                "multihuman_fleiss_kappa": fleiss_val,
                "multihuman_observed_agreement": fleiss_obs,
                "multihuman_positive_prevalence": fleiss_prev,
                "multihuman_items": fleiss_n_items,
                "multihuman_raters": fleiss_n_raters,
                "single_vs_multi_cohen_kappa": cohen_val,
                "single_vs_multi_items": len(single_vals),
            }
        )

    panel_d_df = pd.DataFrame(d_rows)
    return panel_c_df, panel_d_df


# -----------------------------------------------------------------------------
# Drawing
# -----------------------------------------------------------------------------


def draw_panel_a(ax: plt.Axes, panel_a_stats: dict[str, int]) -> None:
    # Dependency-free fallback: set-size bars + overlap annotations.
    labels = ["PRIDE PXD", "PMC", "BY", "SDRF"]
    vals = [panel_a_stats.get(k, 0) for k in labels]
    colors = ["#4c78a8", "#59a14f", "#f28e2b", "#e15759"]

    ax.bar(labels, vals, color=colors, edgecolor="white", linewidth=0.8)
    ax.set_ylabel("Dataset count")
    ax.tick_params(axis="x", rotation=15, labelsize=8)

    ymax = max(vals + [1])
    ax.set_ylim(0, ymax * 1.25)
    for i, v in enumerate(vals):
        ax.text(i, v + ymax * 0.03, str(v), ha="center", va="bottom", fontsize=8)

    ov = (
        f"PMC∩BY: {panel_a_stats.get('PMC_BY', 0)}\n"
        f"PMC∩BY∩SDRF: {panel_a_stats.get('PMC_BY_SDRF', 0)}"
    )
    ax.text(0.98, 0.95, ov, transform=ax.transAxes, ha="right", va="top", fontsize=8)


def _order_by_crosswalk(df: pd.DataFrame, field_order: list[str]) -> pd.DataFrame:
    rank = {field: idx for idx, field in enumerate(field_order)}
    out = df.copy()
    out["_rank"] = out["agentic_field"].astype(str).map(rank)
    out = out.loc[out["_rank"].notna()].sort_values("_rank").drop(columns=["_rank"])
    return out


def _add_category_group_lines(ax: plt.Axes, categories: list[str]) -> None:
    prev = None
    for idx, cat in enumerate(categories):
        if prev is not None and cat != prev:
            ax.axvline(idx - 0.5, color="#bbbbbb", linewidth=0.6, linestyle="--", zorder=0)
        prev = cat


def draw_panel_b(ax: plt.Axes, panel_b_df: pd.DataFrame, field_order: list[str]) -> None:
    g = (
        panel_b_df[["category", "agentic_field", "existing_present_n", "hamlet_present_n"]]
        .drop_duplicates(subset=["agentic_field"], keep="first")
        .pipe(lambda d: _order_by_crosswalk(d, field_order))
        .reset_index(drop=True)
    )

    x = list(range(len(g)))
    w = 0.38
    ax.bar(
        [i - w / 2 for i in x],
        g["existing_present_n"].tolist(),
        width=w,
        color="#457b9d",
        edgecolor="white",
        linewidth=0.6,
        label="Existing",
    )
    ax.bar(
        [i + w / 2 for i in x],
        g["hamlet_present_n"].tolist(),
        width=w,
        color="#e76f51",
        edgecolor="white",
        linewidth=0.6,
        label="HAMLET",
    )

    x_labels = [f.replace("_", " ") for f in g["agentic_field"]]
    ax.set_xticks(x)
    ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=6)
    ax.set_ylabel("Dataset count")
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    xmax = max(g["existing_present_n"].max(), g["hamlet_present_n"].max(), 1)
    ax.set_ylim(0, xmax * 1.08)
    ax.set_xlim(-0.6, len(g) - 0.4)
    ax.grid(False)
    _add_category_group_lines(ax, g["category"].astype(str).tolist())


def draw_panel_c(ax: plt.Axes, panel_c_df: pd.DataFrame, field_order: list[str]) -> None:
    colors = {
        "biological": "#2a9d8f",
        "technical": "#f4a261",
        "experimental_design": "#8ab17d",
    }
    p = _order_by_crosswalk(panel_c_df, field_order).reset_index(drop=True)

    x = list(range(len(p)))
    vals = (100.0 * p["availability_fraction"]).tolist()
    bar_colors = [colors.get(c, "#999999") for c in p["category"]]
    ax.bar(x, vals, color=bar_colors, edgecolor="white", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels([f.replace("_", " ") for f in p["agentic_field"]], rotation=45, ha="right", fontsize=6)
    ax.set_ylim(0, 100)
    ax.set_xlim(-0.6, len(p) - 0.4)
    ax.set_ylabel("Documents with label (%)")
    handles = [
        Patch(facecolor=colors[k], edgecolor="none", label=k.replace("_", " "))
        for k in ["biological", "technical", "experimental_design"]
        if k in set(p["category"].astype(str))
    ]
    if handles:
        ax.legend(handles=handles, frameon=False, fontsize=7, loc="upper right")
    ax.grid(False)
    _add_category_group_lines(ax, p["category"].astype(str).tolist())


def draw_panel_d(ax: plt.Axes, panel_d_df: pd.DataFrame, field_order: list[str]) -> None:
    p = _order_by_crosswalk(panel_d_df, field_order).reset_index(drop=True)

    x = list(range(len(p)))
    fleiss = p["multihuman_fleiss_kappa"].tolist()
    cohen = p["single_vs_multi_cohen_kappa"].tolist()

    ax.scatter(x, fleiss, s=18, color="#264653", label="MultiHuman (Fleiss kappa)", zorder=3)
    ax.scatter(x, cohen, s=18, color="#f4a261", label="Single vs Multi (Cohen kappa)", zorder=3)
    ax.axhline(0.0, color="#999", linewidth=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels([f.replace("_", " ") for f in p["agentic_field"]], rotation=45, ha="right", fontsize=6)
    ax.set_ylabel("Agreement")
    ax.set_ylim(-0.2, 1.0)
    ax.set_xlim(-0.6, len(p) - 0.4)
    ax.legend(frameon=False, fontsize=7, loc="upper right")
    ax.grid(False)
    _add_category_group_lines(ax, p["category"].astype(str).tolist())


def write_standalone_panels(
    panel_b_df: pd.DataFrame,
    panel_c_df: pd.DataFrame,
    panel_d_df: pd.DataFrame,
    field_order: list[str],
    outdir: Path,
    basename: str,
) -> None:
    outputs = [
        ("panel_b", draw_panel_b, panel_b_df, (11.0, 8.5)),
        ("panel_c", draw_panel_c, panel_c_df, (11.0, 8.5)),
        ("panel_d", draw_panel_d, panel_d_df, (11.0, 8.5)),
    ]

    for suffix, draw_fn, data_df, size in outputs:
        fig, ax = plt.subplots(figsize=size)
        draw_fn(ax, data_df, field_order)
        fig.subplots_adjust(left=0.08, right=0.985, top=0.985, bottom=0.30)
        fig.savefig(outdir / f"{basename}_{suffix}.png", dpi=400)
        fig.savefig(outdir / f"{basename}_{suffix}.svg")
        plt.close(fig)


def add_panel_label(fig: plt.Figure, ax: plt.Axes, label: str) -> None:
    bbox = ax.get_position()
    fig.text(
        bbox.x0 - 0.050,
        min(0.995, bbox.y1 + 0.004),
        label,
        fontsize=12,
        fontweight="bold",
        ha="left",
        va="bottom",
    )


def make_figure(
    panel_a_stats: dict[str, int],
    panel_b_df: pd.DataFrame,
    panel_c_df: pd.DataFrame,
    panel_d_df: pd.DataFrame,
    field_order: list[str],
    out_png: Path,
    out_svg: Path,
) -> None:
    # 180 mm x 180 mm -> inches
    fig_w = 180.0 / 25.4
    fig_h = 180.0 / 25.4
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(fig_w, fig_h), constrained_layout=False)

    ax_a = axes[0, 0]
    ax_b = axes[0, 1]
    ax_c = axes[1, 0]
    ax_d = axes[1, 1]

    draw_panel_a(ax_a, panel_a_stats)
    draw_panel_b(ax_b, panel_b_df, field_order)
    draw_panel_c(ax_c, panel_c_df, field_order)
    draw_panel_d(ax_d, panel_d_df, field_order)

    fig.subplots_adjust(left=0.10, right=0.985, top=0.96, bottom=0.14, wspace=0.28, hspace=0.60)

    add_panel_label(fig, ax_a, "a")
    add_panel_label(fig, ax_b, "b")
    add_panel_label(fig, ax_c, "c")
    add_panel_label(fig, ax_d, "d")

    fig.savefig(out_png, dpi=400)
    fig.savefig(out_svg)
    plt.close(fig)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main() -> None:
    args = parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    font_used = configure_font_prefer_arial()

    # Shared inputs
    crosswalk_df = pd.read_csv(Path(args.crosswalk))
    field_order = [
        field
        for field in dict.fromkeys(crosswalk_df["agentic_field"].astype(str).str.strip().tolist())
        if field
    ]

    # Panel b inputs (HAMLET only)
    hamlet_df = pd.read_csv(Path(args.hamlet_pxds))
    if "PXDs" in hamlet_df.columns:
        hamlet_pxds = hamlet_df["PXDs"].astype(str).str.strip().tolist()
    elif "pxd" in hamlet_df.columns:
        hamlet_pxds = hamlet_df["pxd"].astype(str).str.strip().tolist()
    else:
        raise SystemExit("Could not find PXDs/pxd column in Hamlet PXD CSV")

    with Path(args.pride_cache).open("r", encoding="utf-8") as f:
        cache_json = json.load(f)
    cache_by_pxd = {
        str(entry.get("accession", "")).strip(): entry
        for entry in cache_json.get("response", [])
        if str(entry.get("accession", "")).strip()
    }

    filtered_crosswalk_df = crosswalk_df[
        crosswalk_df["used_in_current_sdrf_builder"].astype(str).str.lower().isin(["yes", "conditional"])
    ].copy()

    panel_b_df = compute_presence_counts(filtered_crosswalk_df, hamlet_pxds, cache_by_pxd)
    hamlet_counts = compute_hamlet_counts(panel_b_df, hamlet_pxds, Path(args.results_dir))
    panel_b_df = panel_b_df.merge(hamlet_counts, on="agentic_field", how="left")
    panel_b_df["hamlet_present_n"] = panel_b_df["hamlet_present_in_sampled_n"].fillna(0).astype(int)
    panel_b_df["existing_present_n"] = panel_b_df["pride_present_in_sampled_n_recomputed"].astype(int)

    # Panel a inputs (all master.csv PXDs)
    master_df = pd.read_csv(Path(args.master_csv))
    all_accessions = (
        master_df["accession"].dropna().astype(str).str.strip().loc[lambda s: s.str.startswith("PXD")].tolist()
    )
    sdrf_presence_df = load_or_query_sdrf_presence(
        all_accessions,
        Path(args.sdrf_presence_cache),
        refresh=args.refresh_sdrf_cache,
    )
    panel_a_stats, panel_a_membership = compute_panel_a(master_df, sdrf_presence_df)

    # Panels c/d inputs (.ann): include all fields where used_in_current_sdrf_builder != no.
    used_active_fields = set(
        crosswalk_df.loc[
            crosswalk_df["used_in_current_sdrf_builder"].astype(str).str.lower().ne("no"),
            "agentic_field",
        ]
        .astype(str)
        .str.strip()
        .tolist()
    )
    panel_c_df, panel_d_df = compute_ann_panels(
        Path(args.ann_root),
        crosswalk_df,
        allowed_fields=used_active_fields,
    )

    out_png = outdir / f"{args.basename}.png"
    out_svg = outdir / f"{args.basename}.svg"

    make_figure(panel_a_stats, panel_b_df, panel_c_df, panel_d_df, field_order, out_png, out_svg)
    write_standalone_panels(panel_b_df, panel_c_df, panel_d_df, field_order, outdir, args.basename)

    # Write tables for auditability
    panel_b_df.to_csv(outdir / f"{args.basename}_panel_b_table.csv", index=False)
    panel_a_membership.to_csv(outdir / f"{args.basename}_panel_a_membership.csv", index=False)
    panel_c_df.to_csv(outdir / f"{args.basename}_panel_c_table.csv", index=False)
    panel_d_df.to_csv(outdir / f"{args.basename}_panel_d_table.csv", index=False)

    print(f"Font setting: {font_used}")
    print(f"Wrote: {out_png}")
    print(f"Wrote: {out_svg}")
    print(f"Wrote: {outdir / (args.basename + '_panel_a_membership.csv')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_b_table.csv')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_c_table.csv')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_d_table.csv')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_b.png')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_b.svg')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_c.png')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_c.svg')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_d.png')}")
    print(f"Wrote: {outdir / (args.basename + '_panel_d.svg')}")


if __name__ == "__main__":
    main()
