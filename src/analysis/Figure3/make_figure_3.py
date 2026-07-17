"""
analyzeMeti.py — Modular analysis of HAMLET aggregated results.

Analyses
--------
taxid_prediction
    Evaluates whether organism_identification predictions recover the
    ground-truth taxids listed in pride_metadata.project.organisms.
    Reports per-PXD recall, precision, F1 and distribution plots.

Usage
-----
python analyzeMeti.py --store /path/to/store [--threshold 0.5] [--outdir ./meti_results]
"""

import argparse
import glob
import json
import math
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_allowed_pxds(pxd_list_path: str | None) -> set[str] | None:
    """Load allowed PXDs from CSV/TXT and return an uppercase accession set.

    Accepted inputs:
    - CSV with a column named PXDs / pxd / accession (case-insensitive)
    - Plain text with one accession per line
    """
    if not pxd_list_path:
        return None

    if not os.path.exists(pxd_list_path):
        raise FileNotFoundError(f"PXD list file not found: {pxd_list_path}")

    allowed: set[str] = set()
    lower_name = os.path.basename(pxd_list_path).lower()

    if lower_name.endswith(".csv"):
        df = pd.read_csv(pxd_list_path)
        if df.empty:
            return set()

        lower_cols = {str(c).strip().lower(): c for c in df.columns}
        pick_col = None
        for candidate in ("pxds", "pxd", "accession"):
            if candidate in lower_cols:
                pick_col = lower_cols[candidate]
                break
        if pick_col is None:
            pick_col = df.columns[0]

        values = df[pick_col].dropna().astype(str).str.strip().tolist()
    else:
        with open(pxd_list_path, "r", encoding="utf-8") as fh:
            values = [line.strip() for line in fh if line.strip()]

    for v in values:
        token = str(v).strip().upper()
        if token.startswith("PXD"):
            allowed.add(token)
    return allowed


def _filter_aggregated_files_by_pxd(files: list[str], allowed_pxds: set[str] | None) -> list[str]:
    """Keep only aggregated files whose PXD is in *allowed_pxds*."""
    if allowed_pxds is None:
        return files

    filtered: list[str] = []
    for fpath in files:
        pxd = os.path.basename(fpath).split("_aggregated")[0].strip().upper()
        if pxd in allowed_pxds:
            filtered.append(fpath)
    return filtered

def _parse_ground_truth_taxids(project: dict) -> set[str]:
    """Return set of string taxids from pride_metadata.project.organisms.

    Organisms carry accessions like 'NEWT:9606' — we strip the prefix.
    """
    taxids = set()
    for org in project.get("organisms", []):
        acc = org.get("accession", "")
        if ":" in acc:
            taxids.add(acc.split(":", 1)[1])
    return taxids


def _parse_llm_taxids(llm_meta: dict) -> set[str]:
    """Return set of taxids from llm_extracted_metadata per-file Characteristics[OrganismTaxid]."""
    taxids: set[str] = set()
    for file_data in llm_meta.values():
        if not isinstance(file_data, dict):
            continue
        for val in file_data.get("Characteristics[OrganismTaxid]", []):
            tid = str(val).strip()
            if tid:
                taxids.add(tid)
    return taxids


def _parse_predicted_taxids(organism_id: dict, threshold: float | str,
                            n_best: int = 1) -> set[str]:
    """Return union of predicted taxids across all raw files.

    threshold : float  — include all taxids with score >= threshold
                'best' — include the top-*n_best* scoring taxids per file,
                         where n_best is the number of ground-truth organisms
    n_best    : int    — used only when threshold='best'
    """
    predicted = set()
    for file_result in organism_id.get("results", []):
        data = file_result.get("data", [])
        if not data:
            continue
        if threshold == "best":
            top = sorted(data, key=lambda e: e.get("score", 0.0), reverse=True)[:n_best]
            for entry in top:
                predicted.add(str(entry["taxon_id"]))
        else:
            for entry in data:
                if entry.get("score", 0.0) >= threshold:
                    predicted.add(str(entry["taxon_id"]))
    return predicted


def _compute_metrics(ground_truth: set[str], predicted: set[str]) -> dict:
    """Compute set-based recall, precision, F1.

    Returns dict with keys: tp, fp, fn, recall, precision, f1.
    If ground_truth is empty, all metrics are NaN (caller should skip).
    """
    if not ground_truth:
        return dict(tp=0, fp=len(predicted), fn=0,
                    recall=float("nan"), precision=float("nan"), f1=float("nan"),
                    balanced_accuracy=float("nan"))

    tp = len(ground_truth & predicted)
    fp = len(predicted - ground_truth)
    fn = len(ground_truth - predicted)

    recall = tp / len(ground_truth)
    precision = tp / len(predicted) if predicted else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) > 0 else 0.0)
    balanced_accuracy = (recall + precision) / 2

    return dict(tp=tp, fp=fp, fn=fn, recall=recall, precision=precision, f1=f1,
                balanced_accuracy=balanced_accuracy)


def _ci95(values: np.ndarray) -> float:
    """Return half-width of 95% confidence interval assuming normality."""
    n = len(values)
    if n < 2:
        return 0.0
    return 1.96 * np.std(values, ddof=1) / math.sqrt(n)


# ---------------------------------------------------------------------------
# Species-level taxonomy helpers (NCBI Entrez)
# ---------------------------------------------------------------------------

_SPECIES_TAXID_CACHE: dict[int, int | None] = {}


def _get_species_taxid(taxid: int, email: str) -> int | None:
    """Return the species-rank ancestor taxid for *taxid* via NCBI Entrez.

    Results are cached in-process.  Respects the NCBI rate limit of
    3 requests / second (no API key).  Returns None if the taxid is not
    found or has no species-rank ancestor (e.g. kingdom-level entries).
    """
    if taxid in _SPECIES_TAXID_CACHE:
        return _SPECIES_TAXID_CACHE[taxid]

    url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
        f"?db=taxonomy&id={int(taxid)}&retmode=xml&email={email}"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            xml_data = resp.read()
    except Exception as exc:
        print(f"[same_species] NCBI fetch failed for taxid {taxid}: {exc}", file=sys.stderr)
        _SPECIES_TAXID_CACHE[taxid] = None
        return None
    finally:
        time.sleep(0.35)  # <= 3 requests/s without API key

    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        print(f"[same_species] XML parse error for taxid {taxid}: {exc}", file=sys.stderr)
        _SPECIES_TAXID_CACHE[taxid] = None
        return None

    taxon = root.find("Taxon")
    if taxon is None:
        _SPECIES_TAXID_CACHE[taxid] = None
        return None

    # If the taxid itself is species-rank, return it directly
    if taxon.findtext("Rank") == "species":
        sp = int(taxon.findtext("TaxId"))
        _SPECIES_TAXID_CACHE[taxid] = sp
        return sp

    # Walk ancestors (LineageEx lists root → direct parent)
    for ancestor in taxon.findall(".//LineageEx/Taxon"):
        if ancestor.findtext("Rank") == "species":
            sp = int(ancestor.findtext("TaxId"))
            _SPECIES_TAXID_CACHE[taxid] = sp
            return sp

    _SPECIES_TAXID_CACHE[taxid] = None
    return None


def same_species(
    taxid1: int,
    taxid2: int,
    email: str,
    return_species_taxids: bool = False,
) -> "bool | tuple[bool, int | None, int | None]":
    """Check whether two NCBI taxids resolve to the same species.

    Walks each taxid's lineage (via NCBI Entrez) to find the species-rank
    ancestor, then compares the two.  Useful for treating strain-level
    predictions (e.g. 208964 = PAO1) as correct when the label is the
    parent species (287 = *P. aeruginosa*).

    Parameters
    ----------
    taxid1, taxid2 :
        NCBI taxonomy IDs to compare (int or string coercible to int).
    email :
        Email forwarded to NCBI Entrez — required by NCBI Terms of Service.
    return_species_taxids :
        If True return ``(same, species_taxid1, species_taxid2)``.

    Returns
    -------
    bool, or tuple[bool, int | None, int | None]

    Examples
    --------
    >>> same, sp1, sp2 = same_species(287, 208964, email="you@example.com",
    ...                               return_species_taxids=True)
    >>> print(same, sp1, sp2)
    True 287 287
    """
    sp1 = _get_species_taxid(int(taxid1), email)
    sp2 = _get_species_taxid(int(taxid2), email)
    same = (sp1 is not None) and (sp2 is not None) and (sp1 == sp2)
    if return_species_taxids:
        return same, sp1, sp2
    return same


def _normalize_to_species(taxids: set[str], email: str) -> set[str]:
    """Map each taxid to its species-rank ancestor (or itself if lookup fails).

    Used to collapse strain/sub-species taxids before computing metrics so
    that e.g. 208964 (PAO1) and 287 (*P. aeruginosa*) are treated as equal.
    Any taxid whose NCBI lookup returns None is kept as-is.
    """
    normalized: set[str] = set()
    for tid_str in taxids:
        try:
            sp = _get_species_taxid(int(tid_str), email)
        except ValueError:
            sp = None
        normalized.add(str(sp) if sp is not None else tid_str)
    return normalized


# ---------------------------------------------------------------------------
# Analysis: taxid_prediction
# ---------------------------------------------------------------------------

def run_taxid_prediction(
    store_dir: str,
    threshold: float | str,
    outdir: str,
    email: str | None = None,
    allowed_pxds: set[str] | None = None,
) -> None:
    """Evaluate organism-identification accuracy against PRIDE ground truth.

    For each PXD in *store_dir*/aggregated_results_files/:
    - Ground truth  = taxids in pride_metadata.project.organisms
    - Predictions   = union of taxids with score >= *threshold* across all
                      raw files in organism_identification.results;
                      or if threshold='best', the single top-scoring taxid per file
    - Metrics       = set-based recall, precision, F1

    If *email* is supplied, both ground-truth and predicted taxids are
    resolved to their species-rank ancestor via NCBI Entrez before scoring,
    so strain-level IDs (e.g. 208964 = PAO1) match their parent species
    (287 = *P. aeruginosa*).

    Outputs
    -------
    <outdir>/taxid_prediction.csv        per-PXD metrics table
    <outdir>/taxid_prediction_plot.png   distribution histograms
    """
    agg_dir = os.path.join(store_dir, "aggregated_results_files")
    pattern = os.path.join(agg_dir, "PXD*_aggregated_results.json")
    files = sorted(glob.glob(pattern))
    files = _filter_aggregated_files_by_pxd(files, allowed_pxds)

    if not files:
        print(f"[taxid_prediction] No aggregated results found in: {agg_dir}", file=sys.stderr)
        return

    print(f"[taxid_prediction] Found {len(files)} aggregated result files.")
    print(f"[taxid_prediction] Score threshold: {threshold}")
    if email:
        print(f"[taxid_prediction] Species normalisation: ON (email={email})")
    else:
        print("[taxid_prediction] Species normalisation: OFF (pass --email to enable)")

    rows = []
    n_no_organism_id = 0
    n_empty_ground_truth = 0

    for fpath in files:
        pxd = os.path.basename(fpath).split("_aggregated")[0]
        with open(fpath, "r") as fh:
            data = json.load(fh)

        # ------------------------------------------------------------------
        # Ground truth
        # ------------------------------------------------------------------
        project = (data.get("pride_metadata") or {}).get("project") or {}
        ground_truth = _parse_ground_truth_taxids(project)

        if not ground_truth:
            n_empty_ground_truth += 1

        # ------------------------------------------------------------------
        # Predictions — union of organism_identification + LLM metadata
        # ------------------------------------------------------------------
        organism_id = data.get("organism_identification")
        llm_meta    = data.get("llm_extracted_metadata") or {}
        llm_taxids  = _parse_llm_taxids(llm_meta)

        has_org_id = bool(organism_id and organism_id.get("results"))
        if not has_org_id:
            n_no_organism_id += 1

        if has_org_id:
            predicted = _parse_predicted_taxids(
                organism_id, threshold, n_best=max(1, len(ground_truth))
            ) | llm_taxids
        else:
            predicted = llm_taxids

        if not predicted:
            rows.append(dict(
                pxd=pxd,
                n_ground_truth=len(ground_truth),
                ground_truth_taxids="; ".join(sorted(ground_truth)),
                n_predicted=0,
                predicted_taxids="",
                tp=0, fp=0, fn=len(ground_truth),
                recall=float("nan"),
                precision=float("nan"),
                f1=float("nan"),
                balanced_accuracy=float("nan"),
                has_organism_id=has_org_id,
                has_llm_taxids=False,
            ))
            continue

        # Species-level normalisation (only when --email is provided)
        if email:
            gt_for_metrics   = _normalize_to_species(ground_truth, email)
            pred_for_metrics = _normalize_to_species(predicted, email)
        else:
            gt_for_metrics   = ground_truth
            pred_for_metrics = predicted

        metrics = _compute_metrics(gt_for_metrics, pred_for_metrics)

        rows.append(dict(
            pxd=pxd,
            n_ground_truth=len(ground_truth),
            ground_truth_taxids="; ".join(sorted(ground_truth)),
            n_predicted=len(predicted),
            predicted_taxids="; ".join(sorted(predicted)),
            tp=metrics["tp"],
            fp=metrics["fp"],
            fn=metrics["fn"],
            recall=metrics["recall"],
            precision=metrics["precision"],
            f1=metrics["f1"],
            balanced_accuracy=metrics["balanced_accuracy"],
            has_organism_id=has_org_id,
            has_llm_taxids=bool(llm_taxids),
        ))

    # ----------------------------------------------------------------------
    # Summary statistics
    # ----------------------------------------------------------------------
    total = len(files)
    n_with_results = total - n_no_organism_id

    print(f"\n[taxid_prediction] Summary")
    print(f"  Total PXDs processed          : {total}")
    print(f"  PXDs WITH organism_id results : {n_with_results}")
    print(f"  PXDs WITHOUT organism_id      : {n_no_organism_id}")
    print(f"  PXDs with empty ground truth  : {n_empty_ground_truth}")

    # ----------------------------------------------------------------------
    # Save CSV
    # ----------------------------------------------------------------------
    os.makedirs(outdir, exist_ok=True)
    df = pd.DataFrame(rows)
    csv_path = os.path.join(outdir, "taxid_prediction.csv")
    df.to_csv(csv_path, index=False)
    print(f"\n[taxid_prediction] Saved metrics to: {csv_path}")

    # ----------------------------------------------------------------------
    # Plot — only evaluable rows (has_organism_id=True, ground_truth != empty)
    # ----------------------------------------------------------------------
    eval_df = df[(df["has_organism_id"] | df["has_llm_taxids"]) & (df["n_ground_truth"] > 0)].copy()
    eval_df = eval_df.dropna(subset=["recall", "precision", "f1", "balanced_accuracy"])

    n_eval = len(eval_df)
    print(f"  PXDs used for metric plots    : {n_eval}")

    if n_eval == 0:
        print("[taxid_prediction] No evaluable PXDs — skipping plot.", file=sys.stderr)
        return

    metrics_cfg = [
        ("recall",            "Recall",             "#4C72B0"),
        ("precision",         "Precision",          "#55A868"),
        ("f1",                "F1 Score",            "#C44E52"),
        ("balanced_accuracy", "Balanced Accuracy",   "#9B59B6"),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(20, 5))
    threshold_label = "best (top-1 per file)" if threshold == "best" else f"threshold={threshold}"
    fig.suptitle(
        f"Taxid Prediction Metrics  (n={n_eval}, {threshold_label})",
        fontsize=13, fontweight="bold",
    )

    for ax, (col, label, color) in zip(axes, metrics_cfg):
        vals = eval_df[col].values.astype(float)
        mean_val = float(np.mean(vals))
        ci = _ci95(vals)

        ax.hist(vals, bins=20, range=(0, 1), color=color, alpha=0.75, edgecolor="white")
        ax.axvline(mean_val, color="black", linewidth=1.5, linestyle="--",
                   label=f"Mean={mean_val:.3f}")
        ax.axvspan(max(0, mean_val - ci), min(1, mean_val + ci),
                   alpha=0.18, color="black", label=f"95% CI ±{ci:.3f}")
        ax.set_xlabel(label, fontsize=11)
        ax.set_ylabel("Number of PXDs", fontsize=10)
        ax.set_xlim(-0.02, 1.02)
        ax.legend(fontsize=9)
        ax.set_title(
            f"{label}\nmean={mean_val:.3f}, 95% CI [{max(0,mean_val-ci):.3f}, {min(1,mean_val+ci):.3f}]",
            fontsize=10,
        )

    plt.tight_layout()
    plot_path = os.path.join(outdir, "taxid_prediction_plot.png")
    fig.savefig(plot_path, dpi=150)
    plt.close(fig)
    print(f"[taxid_prediction] Saved plot to:    {plot_path}")


# ---------------------------------------------------------------------------
# Analysis: modification_frequency
# ---------------------------------------------------------------------------

_SEARCH_TYPE_KEYS = ("dda_closed_search", "dia_search")

# Mapping from unimod key -> group name.
# Keys not listed here fall into "Miscellaneous rare".
_MOD_GROUP_MAP: dict[str, str] = {
    # --- Cys alkylation (all reagents merged) ---
    "unimod:4":    "Cys alkylation",
    "unimod:6":    "Cys alkylation",
    "unimod:24":   "Cys alkylation",
    "unimod:108":  "Cys alkylation",
    "unimod:303":  "Cys alkylation",
    "unimod:320":  "Cys alkylation",
    "unimod:327":  "Cys alkylation",
    "unimod:371":  "Cys alkylation",
    "unimod:472":  "Cys alkylation",
    "unimod:735":  "Cys alkylation",
    "unimod:763":  "Cys alkylation",
    "unimod:773":  "Cys alkylation",
    "unimod:893":  "Cys alkylation",
    "unimod:1033": "Cys alkylation",
    "unimod:1358": "Cys alkylation",
    "unimod:1390": "Cys alkylation",
    # --- Oxidation (Met + Pro + Trp merged) ---
    "unimod:35":   "Oxidation",
    "unimod:342":  "Oxidation",
    "unimod:345":  "Oxidation",
    "unimod:351":  "Oxidation",
    "unimod:359":  "Oxidation",
    "unimod:360":  "Oxidation",
    "unimod:369":  "Oxidation",
    "unimod:425":  "Oxidation",
    "unimod:1922": "Oxidation",
    "unimod:1925": "Oxidation",
    # --- Deamidation ---
    "unimod:7":    "Deamidation",
    # --- Dehydration / Pyro-Glu ---
    "unimod:23":   "Dehydration/Pyro-Glu",
    "unimod:28":   "Dehydration/Pyro-Glu",
    "unimod:1827": "Dehydration/Pyro-Glu",
    # --- Carbamylation ---
    "unimod:5":    "Carbamylation",
    # --- Acetylation / amidation / formylation ---
    "unimod:1":    "Acetylation/amidation",
    "unimod:2":    "Acetylation/amidation",
    "unimod:122":  "Acetylation/amidation",
    "unimod:254":  "Acetylation/amidation",
    "unimod:834":  "Acetylation/amidation",
    "unimod:836":  "Acetylation/amidation",
    # --- Methylation (mono + di/tri merged) ---
    "unimod:34":   "Methylation",
    "unimod:36":   "Methylation",
    "unimod:37":   "Methylation",
    "unimod:329":  "Methylation",
    "unimod:330":  "Methylation",
    "unimod:529":  "Methylation",
    "unimod:1414": "Methylation",
    # --- Phosphorylation ---
    "unimod:21":   "Phosphorylation",
    "unimod:898":  "Phosphorylation",
    # --- Organophosphorus adducts ---
    "unimod:723":  "Organophosphorus adducts",
    "unimod:725":  "Organophosphorus adducts",
    "unimod:728":  "Organophosphorus adducts",
    "unimod:729":  "Organophosphorus adducts",
    "unimod:1255": "Organophosphorus adducts",
    "unimod:1365": "Organophosphorus adducts",
    "unimod:1987": "Organophosphorus adducts",
    # --- Ubiquitination (GlyGly) ---
    "unimod:121":  "Ubiquitination (GlyGly)",
    "unimod:864":  "Ubiquitination (GlyGly)",
    # --- Amino acid substitutions ---
    "unimod:372":  "Amino acid substitutions",
    "unimod:556":  "Amino acid substitutions",
    "unimod:613":  "Amino acid substitutions",
    "unimod:662":  "Amino acid substitutions",
    "unimod:1159": "Amino acid substitutions",
    "unimod:1176": "Amino acid substitutions",
    "unimod:1181": "Amino acid substitutions",
    "unimod:1187": "Amino acid substitutions",
    # --- Lipid adducts (HNE/MDA/acrolein) ---
    "unimod:205":  "Lipid adducts",
    "unimod:207":  "Lipid adducts",
    "unimod:209":  "Lipid adducts",
    "unimod:253":  "Lipid adducts",
    "unimod:318":  "Lipid adducts",
    "unimod:319":  "Lipid adducts",
    "unimod:335":  "Lipid adducts",
    "unimod:1312": "Lipid adducts",
    "unimod:1313": "Lipid adducts",
    "unimod:1800": "Lipid adducts",
    # --- Nitrosylation / sulfonation ---
    "unimod:40":   "Nitrosylation/sulfonation",
    "unimod:275":  "Nitrosylation/sulfonation",
    "unimod:421":  "Nitrosylation/sulfonation",
    "unimod:1327": "Nitrosylation/sulfonation",
    # --- Glycosylation ---
    "unimod:41":   "Glycosylation",
    "unimod:295":  "Glycosylation",
    "unimod:910":  "Glycosylation",
    "unimod:1400": "Glycosylation",
    "unimod:1425": "Glycosylation",
    # --- Metal adducts ---
    "unimod:30":   "Metal adducts",
    "unimod:530":  "Metal adducts",
    "unimod:902":  "Metal adducts",
    "unimod:951":  "Metal adducts",
    "unimod:953":  "Metal adducts",
    "unimod:956":  "Metal adducts",
    "unimod:1870": "Metal adducts",
    "unimod:1910": "Metal adducts",
    # --- Crosslinkers / affinity tags (crosslinkers + biotinylation merged) ---
    "unimod:3":    "Crosslinkers/affinity",
    "unimod:92":   "Crosslinkers/affinity",
    "unimod:126":  "Crosslinkers/affinity",
    "unimod:324":  "Crosslinkers/affinity",
    "unimod:357":  "Crosslinkers/affinity",
    "unimod:824":  "Crosslinkers/affinity",
    "unimod:1020": "Crosslinkers/affinity",
    "unimod:1028": "Crosslinkers/affinity",
    "unimod:1031": "Crosslinkers/affinity",
    "unimod:1037": "Crosslinkers/affinity",
    "unimod:1789": "Crosslinkers/affinity",
    "unimod:1841": "Crosslinkers/affinity",
    "unimod:1878": "Crosslinkers/affinity",
    "unimod:1882": "Crosslinkers/affinity",
    "unimod:1884": "Crosslinkers/affinity",
    "unimod:1887": "Crosslinkers/affinity",
    "unimod:1888": "Crosslinkers/affinity",
    "unimod:1893": "Crosslinkers/affinity",
    "unimod:1895": "Crosslinkers/affinity",
    "unimod:1906": "Crosslinkers/affinity",
    # --- TMT / isobaric labels (TMT + iTRAQ + DiLeu + mTRAQ merged) ---
    "unimod:17":   "TMT/isobaric labels",
    "unimod:214":  "TMT/isobaric labels",
    "unimod:481":  "TMT/isobaric labels",
    "unimod:536":  "TMT/isobaric labels",
    "unimod:730":  "TMT/isobaric labels",
    "unimod:737":  "TMT/isobaric labels",
    "unimod:738":  "TMT/isobaric labels",
    "unimod:739":  "TMT/isobaric labels",
    "unimod:1300": "TMT/isobaric labels",
    "unimod:1302": "TMT/isobaric labels",
    "unimod:1321": "TMT/isobaric labels",
    "unimod:1342": "TMT/isobaric labels",
    "unimod:2016": "TMT/isobaric labels",
    # --- SILAC labels ---
    "unimod:184":  "SILAC labels",
    "unimod:188":  "SILAC labels",
    "unimod:259":  "SILAC labels",
    "unimod:262":  "SILAC labels",
    "unimod:267":  "SILAC labels",
    "unimod:772":  "SILAC labels",
    "unimod:897":  "SILAC labels",
    "unimod:986":  "SILAC labels",
    "unimod:1006": "SILAC labels",
    # --- Other isotope labels (dimethyl + propionate/acetate + ICAT merged) ---
    "unimod:13":   "Other isotope labels",
    "unimod:56":   "Other isotope labels",
    "unimod:58":   "Other isotope labels",
    "unimod:59":   "Other isotope labels",
    "unimod:64":   "Other isotope labels",
    "unimod:105":  "Other isotope labels",
    "unimod:199":  "Other isotope labels",
    "unimod:284":  "Other isotope labels",
    "unimod:298":  "Other isotope labels",
    "unimod:510":  "Other isotope labels",
    "unimod:1291": "Other isotope labels",
    # everything else → Miscellaneous rare (default in code)
}

# The grouped plot is sorted by n_pxds_observed (descending), so this list
# is only used as a fallback tiebreaker / canonical reference.
_GROUP_ORDER = [
    "Cys alkylation",
    "Oxidation",
    "Deamidation",
    "Dehydration/Pyro-Glu",
    "Carbamylation",
    "Acetylation/amidation",
    "Methylation",
    "Phosphorylation",
    "Organophosphorus adducts",
    "Ubiquitination (GlyGly)",
    "Amino acid substitutions",
    "Lipid adducts",
    "Nitrosylation/sulfonation",
    "Glycosylation",
    "Metal adducts",
    "Crosslinkers/affinity",
    "TMT/isobaric labels",
    "SILAC labels",
    "Other isotope labels",
    "Miscellaneous rare",
]


def run_modification_frequency(
    store_dir: str,
    outdir: str,
    allowed_pxds: set[str] | None = None,
) -> None:
    """Plot the frequency of PTMs identified in modification_site_fractions.

    For every PXD that has a non-null modification_site_fractions section,
    iterate all search types (dda_closed_search / dia_search) and all
    per-sample files.  For each modification record collect:
        - n_pxds_observed  : PXDs in which the mod appears at least once
        - mean / median fraction_modified across all sample occurrences
        - total peptides_with_mod

    Outputs
    -------
    <outdir>/modification_frequency.csv   per-modification detail table
    <outdir>/modification_grouped.csv     aggregated per group
    <outdir>/modification_grouped_plot.png  vertical bar chart sorted by PXD count
    """
    from collections import defaultdict

    agg_dir = os.path.join(store_dir, "aggregated_results_files")
    pattern = os.path.join(agg_dir, "PXD*_aggregated_results.json")
    files = sorted(glob.glob(pattern))
    files = _filter_aggregated_files_by_pxd(files, allowed_pxds)

    if not files:
        print(f"[modification_frequency] No aggregated results found in: {agg_dir}",
              file=sys.stderr)
        return

    print(f"[modification_frequency] Found {len(files)} aggregated result files.")

    mod_data: dict[str, dict] = defaultdict(lambda: {
        "mod_name": "",
        "unimod_id": None,
        "mass_shift": None,
        "pxds": set(),
        "fractions": [],
        "peptides_with_mod": 0,
        "modified_sites": 0,
    })
    # True union of PXDs per group (avoids double-counting)
    group_pxds: dict[str, set] = defaultdict(set)

    n_with_msf = 0
    n_without_msf = 0

    for fpath in files:
        pxd = os.path.basename(fpath).split("_aggregated")[0]
        with open(fpath, "r") as fh:
            data = json.load(fh)

        msf = data.get("modification_site_fractions")
        if not msf:
            n_without_msf += 1
            continue

        n_with_msf += 1
        for search_key in _SEARCH_TYPE_KEYS:
            search_block = msf.get(search_key)
            if not search_block:
                continue
            per_sample = search_block.get("per_sample_files", {})
            for _sample, sample_data in per_sample.items():
                for entry in sample_data.get("data", []):
                    mk = entry.get("mod_key", "")
                    if not mk:
                        continue
                    rec = mod_data[mk]
                    rec["mod_name"] = entry.get("mod_name", mk)
                    rec["unimod_id"] = entry.get("unimod_id")
                    rec["mass_shift"] = entry.get("mass_shift")
                    rec["pxds"].add(pxd)
                    group_pxds[_MOD_GROUP_MAP.get(mk, "Miscellaneous rare")].add(pxd)
                    frac = entry.get("fraction_modified")
                    if frac is not None and not (isinstance(frac, float) and math.isnan(frac)):
                        rec["fractions"].append(float(frac))
                    rec["peptides_with_mod"] += int(entry.get("peptides_with_mod") or 0)
                    rec["modified_sites"]    += int(entry.get("modified_sites") or 0)

    print(f"\n[modification_frequency] Summary")
    print(f"  PXDs with modification_site_fractions    : {n_with_msf}")
    print(f"  PXDs without modification_site_fractions : {n_without_msf}")
    print(f"  Unique modification keys found           : {len(mod_data)}")

    # ------------------------------------------------------------------
    # Build per-mod detail dataframe
    # ------------------------------------------------------------------
    rows = []
    for mk, rec in mod_data.items():
        fracs = rec["fractions"]
        group = _MOD_GROUP_MAP.get(mk, "Miscellaneous rare")
        rows.append({
            "mod_key":                  mk,
            "mod_name":                 rec["mod_name"],
            "unimod_id":                rec["unimod_id"],
            "mass_shift":               rec["mass_shift"],
            "group":                    group,
            "n_pxds_observed":          len(rec["pxds"]),
            "n_sample_obs":             len(fracs),
            "mean_fraction_modified":   float(np.mean(fracs))   if fracs else float("nan"),
            "median_fraction_modified": float(np.median(fracs)) if fracs else float("nan"),
            "total_peptides_with_mod":  rec["peptides_with_mod"],
            "total_modified_sites":     rec["modified_sites"],
        })

    df = pd.DataFrame(rows).sort_values("n_pxds_observed", ascending=False).reset_index(drop=True)

    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "modification_frequency.csv")
    df.to_csv(csv_path, index=False)
    print(f"\n[modification_frequency] Saved detail table to: {csv_path}")

    # ------------------------------------------------------------------
    # Build grouped dataframe
    # Weighted mean fraction: weight by n_sample_obs so larger datasets
    # contribute proportionally.
    # ------------------------------------------------------------------
    grp_rows = []
    for grp, sub in df.groupby("group"):
        valid = sub.dropna(subset=["mean_fraction_modified"])
        weights = valid["n_sample_obs"].values.astype(float)
        fracs_w = valid["mean_fraction_modified"].values.astype(float)
        if weights.sum() > 0:
            wmean = float(np.average(fracs_w, weights=weights))
        else:
            wmean = float("nan")
        grp_rows.append({
            "group":                    grp,
            "n_mods_in_group":          len(sub),
            "n_pxds_observed":          int(sub["n_pxds_observed"].sum()),
            "n_pxds_unique":            len(group_pxds[grp]),
            "weighted_mean_fraction":   wmean,
            "total_peptides_with_mod":  int(sub["total_peptides_with_mod"].sum()),
        })

    grp_df = pd.DataFrame(grp_rows)

    # Sort by unique PXD count descending; put Miscellaneous rare last
    grp_df["_misc"] = (grp_df["group"] == "Miscellaneous rare").astype(int)
    grp_df = (
        grp_df.sort_values(["_misc", "n_pxds_unique"], ascending=[True, False])
        .drop(columns="_misc")
        .reset_index(drop=True)
    )

    grp_csv = os.path.join(outdir, "modification_grouped.csv")
    grp_df.to_csv(grp_csv, index=False)
    print(f"[modification_frequency] Saved grouped table to: {grp_csv}")

    # ------------------------------------------------------------------
    # Plot: grouped vertical bar chart sorted by PXD count
    # ------------------------------------------------------------------
    _plot_mod_grouped(grp_df, n_with_msf, outdir)


_PLOT_EXCLUDE_GROUPS = {"Amino acid substitutions", "Miscellaneous rare"}


def _plot_mod_grouped(grp_df: pd.DataFrame, n_with_msf: int, outdir: str) -> None:
    """Vertical dual bar chart of grouped modifications, sorted by PXD count."""
    plot_df = grp_df[~grp_df["group"].isin(_PLOT_EXCLUDE_GROUPS)].copy()
    labels   = plot_df["group"].tolist()
    n_groups = len(labels)
    x_pos    = np.arange(n_groups)

    fig, axes = plt.subplots(2, 1, figsize=(max(10, 0.6 * n_groups), 10))
    fig.suptitle(
        f"Grouped PTM frequency across {n_with_msf} PXDs",
        fontsize=13, fontweight="bold",
    )

    # Top panel: fraction of PXDs that observed each group (true union, no double-count)
    frac_pxd = (plot_df["n_pxds_unique"] / n_with_msf).tolist()
    ax = axes[0]
    ax.bar(x_pos, frac_pxd, color="#4C72B0", edgecolor="white", alpha=0.85)
    ax.set_xticks(x_pos)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_ylabel("Fraction of PXDs observed", fontsize=10)
    ax.set_title("Fraction of PXDs per modification group", fontsize=11)
    ax.set_ylim(0, min(1.05, max(frac_pxd) * 1.15))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.grid(axis="y", linestyle="--", linewidth=0.4, alpha=0.5)

    # Bottom panel: weighted mean fraction modified
    ax2 = axes[1]
    wm = plot_df["weighted_mean_fraction"].fillna(0).tolist()
    ax2.bar(x_pos, wm, color="#C44E52", edgecolor="white", alpha=0.85)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax2.set_ylabel("Weighted mean fraction modified", fontsize=10)
    ax2.set_title("Mean modification occupancy per group", fontsize=11)
    ax2.grid(axis="y", linestyle="--", linewidth=0.4, alpha=0.5)

    plt.tight_layout()
    path = os.path.join(outdir, "modification_grouped_plot.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"[modification_frequency] Saved grouped bar chart to: {path}")


# ---------------------------------------------------------------------------
# Analysis: runassessor_technical_summary
# ---------------------------------------------------------------------------

_RE_MS_LEVEL = re.compile(r"^n_ms(.+)_spectra$")
_RE_CHARGE = re.compile(r"^n_charge_(.+)_precursors$")


def _normalize_category(value: object, unknown: str = "unknown") -> str:
    """Normalize category-like values from JSON to a stable lowercase label."""
    if value is None:
        return unknown
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return unknown
    return text.lower()


def _to_float_or_none(value: object) -> float | None:
    """Return float(value) when possible, else None."""
    try:
        if value is None:
            return None
        num = float(value)
        if math.isnan(num):
            return None
        return num
    except (TypeError, ValueError):
        return None


def _collect_runassessor_stats(files: list[str]) -> dict:
    """Aggregate RunAssessor technical fields across aggregated-result files.

    Shared by the standalone runassessor_technical_summary analysis and the
    Figure 3 composite (panel a) so both draw from identical counts.
    """
    from collections import Counter

    stats: dict = {
        "acquisition_counter": Counter(),
        "fragmentation_counter": Counter(),
        "fragmentation_tag_counter": Counter(),
        "labeling_counter": Counter(),
        "high_acc_precursor_counter": Counter(),
        "water_loss_counter": Counter(),
        "ms_level_counter": Counter(),
        "precursor_charge_counter": Counter(),
        "isolation_width_counter": Counter(),
        "fragment_channel_counter": Counter(),
        "roi_signature_counter": Counter(),
        "precursor_tol_ppm": [],
        "fragment_tol_ppm": [],
        "phospho_water_ratio": [],
        "dynex_decay_constant": [],
        "dynex_pulse_start": [],
        "n_with_runassessor": 0,
        "n_without_runassessor": 0,
        "n_file_level_entries": 0,
    }

    acquisition_counter = stats["acquisition_counter"]
    fragmentation_counter = stats["fragmentation_counter"]
    fragmentation_tag_counter = stats["fragmentation_tag_counter"]
    labeling_counter = stats["labeling_counter"]
    high_acc_precursor_counter = stats["high_acc_precursor_counter"]
    water_loss_counter = stats["water_loss_counter"]
    ms_level_counter = stats["ms_level_counter"]
    precursor_charge_counter = stats["precursor_charge_counter"]
    isolation_width_counter = stats["isolation_width_counter"]
    fragment_channel_counter = stats["fragment_channel_counter"]
    roi_signature_counter = stats["roi_signature_counter"]
    precursor_tol_ppm = stats["precursor_tol_ppm"]
    fragment_tol_ppm = stats["fragment_tol_ppm"]
    phospho_water_ratio = stats["phospho_water_ratio"]
    dynex_decay_constant = stats["dynex_decay_constant"]
    dynex_pulse_start = stats["dynex_pulse_start"]

    for fpath in files:
        with open(fpath, "r") as fh:
            data = json.load(fh)

        run_assessor = data.get("runAssessor")
        if not run_assessor:
            stats["n_without_runassessor"] += 1
            continue
        stats["n_with_runassessor"] += 1

        pxd_roi_types: set[str] = set()
        run_files = run_assessor.get("files") or {}
        if run_files:
            for file_data in run_files.values():
                if not isinstance(file_data, dict):
                    continue

                spectra_stats = file_data.get("spectra_stats") or {}
                if isinstance(spectra_stats, dict) and spectra_stats:
                    stats["n_file_level_entries"] += 1
                    acquisition_counter[_normalize_category(spectra_stats.get("acquisition_type"))] += 1
                    fragmentation_counter[_normalize_category(spectra_stats.get("fragmentation_type"))] += 1
                    fragmentation_tag_counter[_normalize_category(spectra_stats.get("fragmentation_tag"))] += 1
                    high_acc_precursor_counter[_normalize_category(spectra_stats.get("high_accuracy_precursors"))] += 1

                    isolation_windows = spectra_stats.get("isolation_window_full_widths") or {}
                    if isinstance(isolation_windows, dict):
                        for width, count in isolation_windows.items():
                            w = _to_float_or_none(width)
                            c = _to_float_or_none(count)
                            if w is None or c is None:
                                continue
                            isolation_width_counter[f"{w:g}"] += c

                    for key, value in spectra_stats.items():
                        n = _to_float_or_none(value)
                        if n is None:
                            continue

                        ms_match = _RE_MS_LEVEL.match(key)
                        if ms_match:
                            ms_level_counter[f"ms{ms_match.group(1)}"] += n

                        charge_match = _RE_CHARGE.match(key)
                        if charge_match:
                            precursor_charge_counter[charge_match.group(1)] += n

                        key_upper = key.upper()
                        if "HCD" in key_upper:
                            fragment_channel_counter["hcd"] += n
                        if "CID" in key_upper:
                            fragment_channel_counter["cid"] += n
                        if "ETD" in key_upper:
                            fragment_channel_counter["etd"] += n
                        if "QTOF" in key_upper:
                            fragment_channel_counter["qtof"] += n

                summary = file_data.get("summary") or {}
                if isinstance(summary, dict) and summary:
                    combined = summary.get("combined summary") or {}
                    if isinstance(combined, dict):
                        labeling_counter[_normalize_category(combined.get("call"))] += 1
                        water_loss_counter[_normalize_category(combined.get("has water_loss"))] += 1

                        rec_prec = _to_float_or_none(combined.get("recommended precursor tolerance (ppm)"))
                        if rec_prec is not None:
                            precursor_tol_ppm.append(rec_prec)

                        frag_tol_block = combined.get("fragmentation tolerance") or {}
                        if isinstance(frag_tol_block, dict):
                            rec_frag = _to_float_or_none(frag_tol_block.get("recommended fragment tolerance"))
                            if rec_frag is not None:
                                fragment_tol_ppm.append(rec_frag)

                        ratio = _to_float_or_none(
                            combined.get("total z=2 phosphoric_acid to z=2 water_loss intensity ratio")
                        )
                        if ratio is not None:
                            phospho_water_ratio.append(ratio)

                    precursor_stats = summary.get("precursor stats") or {}
                    if isinstance(precursor_stats, dict):
                        dynex = precursor_stats.get("dynamic exclusion window") or {}
                        if isinstance(dynex, dict):
                            fit = dynex.get("fit_pulse_time") or {}
                            if isinstance(fit, dict):
                                decay = _to_float_or_none(fit.get("decay constant"))
                                pulse = _to_float_or_none(fit.get("pulse start"))
                                if decay is not None:
                                    dynex_decay_constant.append(decay)
                                if pulse is not None:
                                    dynex_pulse_start.append(pulse)

            if not isinstance(file_data, dict):
                continue
            rois = file_data.get("ROIs") or {}
            if not isinstance(rois, dict):
                continue
            for roi_name, roi_data in rois.items():
                if not isinstance(roi_data, dict):
                    continue
                found = bool(((roi_data.get("peak") or {}).get("assessment") or {}).get("is_found"))
                if not found:
                    continue
                roi_type = _normalize_category(roi_data.get("type") or roi_name)
                pxd_roi_types.add(roi_type)
        else:
            # Fallback to top-level runAssessor schema when per-file entries are absent.
            search_criteria = run_assessor.get("search_criteria") or {}
            acquisition_counter[_normalize_category(search_criteria.get("acquisition_type"))] += 1
            fragmentation_counter[_normalize_category(search_criteria.get("fragmentation_type"))] += 1
            labeling_counter[_normalize_category(search_criteria.get("labeling"))] += 1
            high_acc_precursor_counter[_normalize_category(search_criteria.get("high_accuracy_precursors"))] += 1

            tolerances = search_criteria.get("tolerances") or {}
            rec_prec = _to_float_or_none(tolerances.get("recommended overall precursor tolerance (ppm)"))
            rec_frag = _to_float_or_none(tolerances.get("recommended overall fragment tolerance (ppm)"))
            if rec_prec is not None:
                precursor_tol_ppm.append(rec_prec)
            if rec_frag is not None:
                fragment_tol_ppm.append(rec_frag)

            spectra_stats = run_assessor.get("spectra_stats") or {}
            for key, value in spectra_stats.items():
                n = _to_float_or_none(value)
                if n is None:
                    continue
                ms_match = _RE_MS_LEVEL.match(key)
                if ms_match:
                    ms_level_counter[f"ms{ms_match.group(1)}"] += n
                charge_match = _RE_CHARGE.match(key)
                if charge_match:
                    precursor_charge_counter[charge_match.group(1)] += n
                key_upper = key.upper()
                if "HCD" in key_upper:
                    fragment_channel_counter["hcd"] += n
                if "CID" in key_upper:
                    fragment_channel_counter["cid"] += n
                if "ETD" in key_upper:
                    fragment_channel_counter["etd"] += n
                if "QTOF" in key_upper:
                    fragment_channel_counter["qtof"] += n

        for roi_type in pxd_roi_types:
            roi_signature_counter[roi_type] += 1

    return stats


def run_runassessor_technical_summary(
    store_dir: str,
    outdir: str,
    allowed_pxds: set[str] | None = None,
) -> None:
    """Summarize runAssessor technical metadata and write plot/CSV outputs.

    Outputs
    -------
    <outdir>/runassessor_technical_summary.csv
    <outdir>/runassessor_technical_summary_plot.png
    """
    from collections import Counter

    agg_dir = os.path.join(store_dir, "aggregated_results_files")
    pattern = os.path.join(agg_dir, "PXD*_aggregated_results.json")
    files = sorted(glob.glob(pattern))
    files = _filter_aggregated_files_by_pxd(files, allowed_pxds)

    if not files:
        print(f"[runassessor_technical_summary] No aggregated results found in: {agg_dir}",
              file=sys.stderr)
        return

    print(f"[runassessor_technical_summary] Found {len(files)} aggregated result files.")

    stats = _collect_runassessor_stats(files)
    n_with_runassessor = stats["n_with_runassessor"]
    n_without_runassessor = stats["n_without_runassessor"]
    n_file_level_entries = stats["n_file_level_entries"]

    print("\n[runassessor_technical_summary] Summary")
    print(f"  PXDs with runAssessor section    : {n_with_runassessor}")
    print(f"  PXDs without runAssessor section : {n_without_runassessor}")
    print(f"  File-level run summaries parsed  : {n_file_level_entries}")

    if n_with_runassessor == 0:
        print("[runassessor_technical_summary] No runAssessor data available.", file=sys.stderr)
        return

    # Build long-form summary table
    summary_rows = []

    def add_counter_rows(domain: str, counter: Counter, denominator: float | None = None) -> None:
        for key, value in counter.items():
            row = {"domain": domain, "category": str(key), "value": float(value)}
            if denominator and denominator > 0:
                row["fraction"] = float(value) / float(denominator)
            else:
                row["fraction"] = float("nan")
            summary_rows.append(row)

    cat_den = n_file_level_entries if n_file_level_entries > 0 else n_with_runassessor
    add_counter_rows("acquisition_type", stats["acquisition_counter"], cat_den)
    add_counter_rows("fragmentation_type", stats["fragmentation_counter"], cat_den)
    add_counter_rows("fragmentation_tag", stats["fragmentation_tag_counter"], cat_den)
    add_counter_rows("labeling", stats["labeling_counter"], cat_den)
    add_counter_rows("high_accuracy_precursors", stats["high_acc_precursor_counter"], cat_den)
    add_counter_rows("has_water_loss", stats["water_loss_counter"], cat_den)
    add_counter_rows("ms_level_spectra", stats["ms_level_counter"], sum(stats["ms_level_counter"].values()))
    add_counter_rows("precursor_charge", stats["precursor_charge_counter"],
                     sum(stats["precursor_charge_counter"].values()))
    add_counter_rows("isolation_window_full_width", stats["isolation_width_counter"],
                     sum(stats["isolation_width_counter"].values()))
    add_counter_rows("fragmentation_channel_spectra", stats["fragment_channel_counter"],
                     sum(stats["fragment_channel_counter"].values()))
    add_counter_rows("roi_quant_signature_pxds", stats["roi_signature_counter"], n_with_runassessor)

    def add_numeric_rows(domain: str, values: list[float]) -> None:
        if not values:
            return
        summary_rows.extend([
            {"domain": domain, "category": "count",  "value": float(len(values)), "fraction": float("nan")},
            {"domain": domain, "category": "mean",   "value": float(np.mean(values)), "fraction": float("nan")},
            {"domain": domain, "category": "median", "value": float(np.median(values)), "fraction": float("nan")},
            {"domain": domain, "category": "p95",    "value": float(np.percentile(values, 95)), "fraction": float("nan")},
        ])

    add_numeric_rows("recommended_precursor_tolerance_ppm", stats["precursor_tol_ppm"])
    add_numeric_rows("recommended_fragment_tolerance_ppm", stats["fragment_tol_ppm"])
    add_numeric_rows("phosphoric_to_water_intensity_ratio", stats["phospho_water_ratio"])
    add_numeric_rows("dynamic_exclusion_decay_constant", stats["dynex_decay_constant"])
    add_numeric_rows("dynamic_exclusion_pulse_start", stats["dynex_pulse_start"])

    os.makedirs(outdir, exist_ok=True)
    summary_df = pd.DataFrame(summary_rows)
    summary_csv = os.path.join(outdir, "runassessor_technical_summary.csv")
    summary_df.to_csv(summary_csv, index=False)
    print(f"[runassessor_technical_summary] Saved summary table to: {summary_csv}")

    _plot_runassessor_technical_summary(stats, outdir)


def _bar_with_aligned_ticks(ax, labels, values, color, alpha=0.9):
    """Draw bars with explicit tick locations to avoid category offset artifacts."""
    x = np.arange(len(labels))
    ax.bar(x, values, color=color, edgecolor="white", alpha=alpha)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right", rotation_mode="anchor")


def _draw_runassessor_panels(
    fig: plt.Figure,
    outer_spec,
    stats: dict,
    title_fs: float,
    label_fs: float,
    tick_fs: float,
) -> None:
    """Draw the 10-panel RunAssessor technical-summary grid into *outer_spec*.

    Shared by the standalone runassessor_technical_summary plot and by
    panel a of the Figure 3 composite, so both stay visually identical.
    """
    inner_gs = outer_spec.subgridspec(2, 5, wspace=0.55, hspace=0.85)
    axes = [[fig.add_subplot(inner_gs[r, c]) for c in range(5)] for r in range(2)]
    for row in axes:
        for ax in row:
            ax.tick_params(axis="both", labelsize=tick_fs)

    acquisition_counter = stats["acquisition_counter"]
    fragmentation_counter = stats["fragmentation_counter"]
    fragmentation_tag_counter = stats["fragmentation_tag_counter"]
    ms_level_counter = stats["ms_level_counter"]
    precursor_charge_counter = stats["precursor_charge_counter"]
    isolation_width_counter = stats["isolation_width_counter"]
    precursor_tol_ppm = stats["precursor_tol_ppm"]
    fragment_tol_ppm = stats["fragment_tol_ppm"]
    fragment_channel_counter = stats["fragment_channel_counter"]
    labeling_counter = stats["labeling_counter"]
    roi_signature_counter = stats["roi_signature_counter"]

    # 1) Acquisition type (DDA/DIA)
    ax = axes[0][0]
    acq_items = sorted(acquisition_counter.items(), key=lambda kv: kv[1], reverse=True)
    _bar_with_aligned_ticks(ax, [k for k, _ in acq_items], [v for _, v in acq_items], "#4C72B0")
    ax.set_title("Acquisition", fontsize=title_fs)
    ax.set_ylabel("Runs", fontsize=label_fs)

    # 2) Fragmentation type
    ax = axes[0][1]
    frag_items = sorted(fragmentation_counter.items(), key=lambda kv: kv[1], reverse=True)[:6]
    _bar_with_aligned_ticks(ax, [k for k, _ in frag_items], [v for _, v in frag_items], "#64B5CD")
    ax.set_title("Fragmentation type", fontsize=title_fs)

    # 3) Fragmentation tag
    ax = axes[0][2]
    tag_items = sorted(fragmentation_tag_counter.items(), key=lambda kv: kv[1], reverse=True)[:5]
    _bar_with_aligned_ticks(ax, [k for k, _ in tag_items], [v for _, v in tag_items], "#4E79A7")
    ax.set_title("Fragmentation tag", fontsize=title_fs)

    # 4) MS-level spectrum distribution
    ax = axes[0][3]
    ms_order = ["ms0", "ms1", "ms2", "ms3", "ms3+"]
    ms_labels = [m for m in ms_order if m in ms_level_counter]
    ms_vals = [ms_level_counter[m] for m in ms_labels]
    if ms_vals:
        total_ms = float(sum(ms_vals))
        ms_frac = [v / total_ms for v in ms_vals]
        _bar_with_aligned_ticks(ax, ms_labels, ms_frac, "#55A868")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
        ax.set_ylim(0, min(1.0, max(ms_frac) * 1.15))
    ax.set_title("MS levels", fontsize=title_fs)
    ax.set_ylabel("Frac", fontsize=label_fs)

    # 5) Precursor charge distribution (top 6 + other)
    ax = axes[0][4]
    charge_items = []
    for k, v in precursor_charge_counter.items():
        try:
            charge_items.append((int(k), v))
        except ValueError:
            continue
    charge_items.sort(key=lambda kv: kv[1], reverse=True)
    top = charge_items[:6]
    other_sum = sum(v for _, v in charge_items[6:])
    charge_labels = [f"z={k}" for k, _ in top]
    charge_vals = [v for _, v in top]
    if other_sum > 0:
        charge_labels.append("other")
        charge_vals.append(other_sum)
    if charge_vals:
        total_charge = float(sum(charge_vals))
        charge_frac = [v / total_charge for v in charge_vals]
        _bar_with_aligned_ticks(ax, charge_labels, charge_frac, "#C44E52")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
        ax.set_ylim(0, min(1.0, max(charge_frac) * 1.15))
    ax.set_title("Precursor charge", fontsize=title_fs)
    ax.set_ylabel("Frac", fontsize=label_fs)

    # 6) Isolation window widths
    ax = axes[1][0]
    iso_items = []
    for k, v in isolation_width_counter.items():
        try:
            iso_items.append((float(k), v))
        except ValueError:
            continue
    iso_items.sort(key=lambda kv: kv[0])
    if iso_items:
        labels = [f"{w:g}" for w, _ in iso_items[:8]]
        vals = [v for _, v in iso_items[:8]]
        total_iso = float(sum(v for _, v in iso_items))
        vals = [v / total_iso for v in vals]
        _bar_with_aligned_ticks(ax, labels, vals, "#F28E2B")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.set_title("Isolation window (m/z)", fontsize=title_fs)
    ax.set_ylabel("Frac", fontsize=label_fs)

    # 7) Fragmentation-channel distribution
    ax = axes[1][1]
    channel_items = sorted(fragment_channel_counter.items(), key=lambda kv: kv[1], reverse=True)
    channel_labels = [k.upper() for k, _ in channel_items]
    channel_vals = [v for _, v in channel_items]
    if channel_vals:
        total_frag = float(sum(channel_vals))
        channel_frac = [v / total_frag for v in channel_vals]
        _bar_with_aligned_ticks(ax, channel_labels, channel_frac, "#B07AA1")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
        ax.set_ylim(0, min(1.0, max(channel_frac) * 1.15))
    ax.set_title("Fragmentation channels", fontsize=title_fs)
    ax.set_ylabel("Frac", fontsize=label_fs)

    # 8) Recommended precursor tolerance — own subplot
    ax = axes[1][2]
    if precursor_tol_ppm:
        ax.hist(precursor_tol_ppm, bins=12, alpha=0.8, color="#8172B2", edgecolor="white")
    ax.set_title("Precursor tolerance", fontsize=title_fs)
    ax.set_xlabel("ppm", fontsize=label_fs)
    ax.set_ylabel("Count", fontsize=label_fs)

    # 9) Recommended fragment tolerance — own subplot
    ax = axes[1][3]
    if fragment_tol_ppm:
        ax.hist(fragment_tol_ppm, bins=12, alpha=0.8, color="#E15759", edgecolor="white")
    ax.set_title("Fragment tolerance", fontsize=title_fs)
    ax.set_xlabel("ppm", fontsize=label_fs)
    ax.set_ylabel("Count", fontsize=label_fs)

    # 10) Labeling calls and ROI quant signatures
    ax = axes[1][4]
    label_items = sorted(labeling_counter.items(), key=lambda kv: kv[1], reverse=True)[:4]
    roi_items = sorted(roi_signature_counter.items(), key=lambda kv: kv[1], reverse=True)[:4]
    names = [f"L:{k}" for k, _ in label_items] + [f"Q:{k}" for k, _ in roi_items]
    vals = [v for _, v in label_items] + [v for _, v in roi_items]
    colors = ["#76B7B2"] * len(label_items) + ["#CCB974"] * len(roi_items)
    if vals:
        _bar_with_aligned_ticks(ax, names, vals, "#76B7B2")
        # Reapply per-bar colors after helper call.
        for patch, color in zip(ax.patches, colors):
            patch.set_facecolor(color)
    ax.set_title("Labeling + quant", fontsize=title_fs)
    ax.set_ylabel("Count", fontsize=label_fs)
    ax.tick_params(axis="x", rotation=45)


def _plot_runassessor_technical_summary(stats: dict, outdir: str) -> None:
    """Create the standalone RunAssessor technical summary at 180 mm x 80 mm."""
    fig_width_in = 180.0 / 25.4
    fig_height_in = 80.0 / 25.4
    fig = plt.figure(figsize=(fig_width_in, fig_height_in))
    outer_spec = fig.add_gridspec(1, 1, left=0.055, right=0.99, top=0.95, bottom=0.16)[0, 0]

    title_fs, label_fs, tick_fs = 7, 6, 5
    _draw_runassessor_panels(fig, outer_spec, stats, title_fs, label_fs, tick_fs)

    plot_path = os.path.join(outdir, "runassessor_technical_summary_plot.png")
    fig.savefig(plot_path, dpi=300)
    plt.close(fig)
    print(f"[runassessor_technical_summary] Saved plot to: {plot_path}")


# ---------------------------------------------------------------------------
# Analysis: figure3_composite
# ---------------------------------------------------------------------------

def _compute_taxid_metrics_for_composite(
    files: list[str],
    threshold: float | str = "best",
    email: str | None = None,
) -> dict[str, list[float]]:
    """Lightweight recomputation of taxid recall/precision/F1/balanced accuracy.

    Mirrors the core scoring logic in run_taxid_prediction (same threshold
    semantics and optional species-level normalisation) but only returns
    the evaluable per-PXD metric lists needed to draw Figure 3 panel b.
    """
    metrics_lists: dict[str, list[float]] = {
        "recall": [], "precision": [], "f1": [], "balanced_accuracy": [],
    }
    for fpath in files:
        with open(fpath, "r") as fh:
            data = json.load(fh)

        project = (data.get("pride_metadata") or {}).get("project") or {}
        ground_truth = _parse_ground_truth_taxids(project)
        if not ground_truth:
            continue

        organism_id = data.get("organism_identification")
        llm_meta = data.get("llm_extracted_metadata") or {}
        llm_taxids = _parse_llm_taxids(llm_meta)
        has_org_id = bool(organism_id and organism_id.get("results"))

        if has_org_id:
            predicted = _parse_predicted_taxids(
                organism_id, threshold, n_best=max(1, len(ground_truth))
            ) | llm_taxids
        else:
            predicted = llm_taxids

        if not predicted:
            continue

        if email:
            gt_for_metrics = _normalize_to_species(ground_truth, email)
            pred_for_metrics = _normalize_to_species(predicted, email)
        else:
            gt_for_metrics = ground_truth
            pred_for_metrics = predicted

        metrics = _compute_metrics(gt_for_metrics, pred_for_metrics)
        for key in metrics_lists:
            value = metrics.get(key)
            if value is not None and not (isinstance(value, float) and math.isnan(value)):
                metrics_lists[key].append(float(value))

    return metrics_lists


def _compute_mod_grouped_for_composite(files: list[str]) -> tuple[pd.DataFrame, int]:
    """Lightweight recomputation of grouped PTM frequency for Figure 3 panel c."""
    from collections import defaultdict

    mod_data: dict[str, dict] = defaultdict(lambda: {"pxds": set(), "fractions": [], "n_sample_obs": 0})
    group_pxds: dict[str, set] = defaultdict(set)
    n_with_msf = 0

    for fpath in files:
        pxd = os.path.basename(fpath).split("_aggregated")[0]
        with open(fpath, "r") as fh:
            data = json.load(fh)

        msf = data.get("modification_site_fractions")
        if not msf:
            continue
        n_with_msf += 1

        for search_key in _SEARCH_TYPE_KEYS:
            search_block = msf.get(search_key)
            if not search_block:
                continue
            per_sample = search_block.get("per_sample_files", {})
            for _sample, sample_data in per_sample.items():
                for entry in sample_data.get("data", []):
                    mk = entry.get("mod_key", "")
                    if not mk:
                        continue
                    rec = mod_data[mk]
                    rec["pxds"].add(pxd)
                    group = _MOD_GROUP_MAP.get(mk, "Miscellaneous rare")
                    group_pxds[group].add(pxd)
                    frac = entry.get("fraction_modified")
                    if frac is not None and not (isinstance(frac, float) and math.isnan(frac)):
                        rec["fractions"].append(float(frac))
                        rec["n_sample_obs"] += 1

    if not mod_data:
        return pd.DataFrame(columns=["group", "n_pxds_unique", "weighted_mean_fraction"]), n_with_msf

    rows = []
    for mk, rec in mod_data.items():
        rows.append({
            "mod_key": mk,
            "group": _MOD_GROUP_MAP.get(mk, "Miscellaneous rare"),
            "n_sample_obs": rec["n_sample_obs"],
            "mean_fraction_modified": float(np.mean(rec["fractions"])) if rec["fractions"] else float("nan"),
        })
    df = pd.DataFrame(rows)

    grp_rows = []
    for grp, sub in df.groupby("group"):
        valid = sub.dropna(subset=["mean_fraction_modified"])
        weights = valid["n_sample_obs"].values.astype(float)
        fracs_w = valid["mean_fraction_modified"].values.astype(float)
        wmean = float(np.average(fracs_w, weights=weights)) if weights.sum() > 0 else float("nan")
        grp_rows.append({
            "group": grp,
            "n_pxds_unique": len(group_pxds[grp]),
            "weighted_mean_fraction": wmean,
        })

    grp_df = pd.DataFrame(grp_rows).sort_values("n_pxds_unique", ascending=False).reset_index(drop=True)
    return grp_df, n_with_msf


def _draw_taxid_metrics_panel(
    fig: plt.Figure,
    outer_spec,
    metrics: dict[str, list[float]],
    title_fs: float,
    label_fs: float,
    tick_fs: float,
) -> None:
    """Draw a compact 2x2 grid of taxid-prediction metric histograms."""
    inner_gs = outer_spec.subgridspec(2, 2, wspace=0.45, hspace=0.65)
    metrics_cfg = [
        ("recall", "Recall", "#4C72B0", 0, 0),
        ("precision", "Precision", "#55A868", 0, 1),
        ("f1", "F1 score", "#C44E52", 1, 0),
        ("balanced_accuracy", "Balanced acc.", "#9B59B6", 1, 1),
    ]
    for key, label, color, r, c in metrics_cfg:
        ax = fig.add_subplot(inner_gs[r, c])
        ax.tick_params(axis="both", labelsize=tick_fs)
        vals = np.asarray(metrics.get(key, []), dtype=float)
        if vals.size:
            mean_val = float(np.mean(vals))
            ax.hist(vals, bins=12, range=(0, 1), color=color, alpha=0.8, edgecolor="white")
            ax.axvline(mean_val, color="black", linewidth=1.0, linestyle="--")
            ax.set_xlim(-0.02, 1.02)
        ax.set_title(label, fontsize=title_fs)
        if c == 0:
            ax.set_ylabel("PXDs", fontsize=label_fs)
        if r == 1:
            ax.set_xlabel("Score", fontsize=label_fs)


def _draw_mod_grouped_panel(
    fig: plt.Figure,
    outer_spec,
    grp_df: pd.DataFrame,
    n_with_msf: int,
    title_fs: float,
    label_fs: float,
    tick_fs: float,
) -> None:
    """Draw grouped-PTM frequency (all groups) as two side-by-side horizontal bars.

    Uses the same full group set (and exclusions) as the standalone
    modification_grouped.csv / modification_grouped_plot.png — no top-N
    truncation — so panel c matches the separate plot exactly.
    """
    inner_gs = outer_spec.subgridspec(1, 2, wspace=0.15)

    plot_df = grp_df[~grp_df["group"].isin(_PLOT_EXCLUDE_GROUPS)].copy()
    plot_df = plot_df.sort_values("n_pxds_unique", ascending=False)
    plot_df = plot_df.iloc[::-1]
    labels = plot_df["group"].tolist()
    y = np.arange(len(labels))
    group_tick_fs = max(3.5, tick_fs - 1.5)

    ax_frac = fig.add_subplot(inner_gs[0, 0])
    ax_frac.tick_params(axis="both", labelsize=tick_fs)
    frac_vals = (plot_df["n_pxds_unique"] / n_with_msf).tolist() if n_with_msf else [0.0] * len(labels)
    ax_frac.barh(y, frac_vals, color="#4C72B0", edgecolor="white", alpha=0.85)
    ax_frac.set_yticks(y)
    ax_frac.set_yticklabels(labels, fontsize=group_tick_fs)
    ax_frac.set_ylim(-0.6, len(labels) - 0.4)
    ax_frac.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax_frac.set_title("Fraction of PXDs", fontsize=title_fs)

    ax_wm = fig.add_subplot(inner_gs[0, 1])
    ax_wm.tick_params(axis="both", labelsize=tick_fs)
    wm_vals = plot_df["weighted_mean_fraction"].fillna(0).tolist()
    ax_wm.barh(y, wm_vals, color="#C44E52", edgecolor="white", alpha=0.85)
    ax_wm.set_yticks(y)
    ax_wm.set_yticklabels([])
    ax_wm.set_ylim(-0.6, len(labels) - 0.4)
    ax_wm.set_title("Mean occupancy", fontsize=title_fs)


def _add_panel_label(fig: plt.Figure, spec, label: str) -> None:
    """Place a bold panel label ('a', 'b', 'c', ...) above the top-left of *spec*."""
    bbox = spec.get_position(fig)
    fig.text(
        max(0.0, bbox.x0 - 0.045),
        min(0.995, bbox.y1 + 0.006),
        label,
        fontsize=12,
        fontweight="bold",
        ha="left",
        va="bottom",
    )


def run_figure3_composite(
    store_dir: str,
    outdir: str,
    allowed_pxds: set[str] | None = None,
    threshold: float | str = "best",
    email: str | None = None,
) -> None:
    """Build the Figure 3 consensus composite (180 mm x 180 mm).

    Panel a : RunAssessor technical summary, spanning the full top half.
    Panel b : taxid-prediction metric distributions (bottom-left).
    Panel c : grouped PTM frequency summary (bottom-right).

    *threshold* and *email* are forwarded to the same taxid-scoring logic
    used by run_taxid_prediction so panel b always matches the standalone
    taxid_prediction_plot.png produced in the same invocation.

    Outputs
    -------
    <outdir>/figure3_composite.png
    <outdir>/figure3_composite.svg
    """
    agg_dir = os.path.join(store_dir, "aggregated_results_files")
    pattern = os.path.join(agg_dir, "PXD*_aggregated_results.json")
    files = sorted(glob.glob(pattern))
    files = _filter_aggregated_files_by_pxd(files, allowed_pxds)

    if not files:
        print(f"[figure3_composite] No aggregated results found in: {agg_dir}", file=sys.stderr)
        return

    print(f"[figure3_composite] Found {len(files)} aggregated result files.")

    stats = _collect_runassessor_stats(files)
    taxid_metrics = _compute_taxid_metrics_for_composite(files, threshold=threshold, email=email)
    grp_df, n_with_msf = _compute_mod_grouped_for_composite(files)

    os.makedirs(outdir, exist_ok=True)

    fig_w = 180.0 / 25.4
    fig_h = 180.0 / 25.4
    fig = plt.figure(figsize=(fig_w, fig_h))

    outer = fig.add_gridspec(
        2, 1, height_ratios=[1.0, 0.82], hspace=0.32,
        left=0.065, right=0.99, top=0.96, bottom=0.07,
    )
    top_spec = outer[0, 0]
    bottom_gs = outer[1, 0].subgridspec(1, 2, wspace=0.55)
    panel_b_spec = bottom_gs[0, 0]
    panel_c_spec = bottom_gs[0, 1]

    title_fs, label_fs, tick_fs = 7, 6, 5

    _draw_runassessor_panels(fig, top_spec, stats, title_fs, label_fs, tick_fs)
    _draw_taxid_metrics_panel(fig, panel_b_spec, taxid_metrics, title_fs, label_fs, tick_fs)
    _draw_mod_grouped_panel(fig, panel_c_spec, grp_df, n_with_msf, title_fs, label_fs, tick_fs)

    _add_panel_label(fig, top_spec, "a")
    _add_panel_label(fig, panel_b_spec, "b")
    _add_panel_label(fig, panel_c_spec, "c")

    png_path = os.path.join(outdir, "figure3_composite.png")
    svg_path = os.path.join(outdir, "figure3_composite.svg")
    fig.savefig(png_path, dpi=400)
    fig.savefig(svg_path)
    plt.close(fig)
    print(f"[figure3_composite] Saved composite figure to: {png_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="analyzeMeti — HAMLET aggregated results analysis suite.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--store",
        required=True,
        help="Path to the HAMLET store directory (contains aggregated_results_files/).",
    )
    parser.add_argument(
        "--outdir",
        default="./meti_results",
        help="Directory to write analysis outputs.",
    )
    parser.add_argument(
        "--pxd_list",
        type=str,
        default=None,
        help=(
            "Optional path to CSV/TXT containing PXDs to include. "
            "When provided, only matching PXD aggregated files are analyzed."
        ),
    )

    # Analysis selection
    parser.add_argument(
        "--taxid_prediction",
        action="store_true",
        default=False,
        help="Run the taxid_prediction analysis.",
    )
    parser.add_argument(
        "--modification_frequency",
        action="store_true",
        default=False,
        help="Plot frequency of PTMs from modification_site_fractions.",
    )
    parser.add_argument(
        "--runassessor_technical_summary",
        action="store_true",
        default=False,
        help=(
            "Generate runAssessor-derived technical summaries (MS levels, precursor "
            "characteristics, DDA/DIA, fragmentation, and labeling/quant signatures)."
        ),
    )
    parser.add_argument(
        "--figure3_composite",
        action="store_true",
        default=False,
        help=(
            "Build the Figure 3 consensus composite (180mm x 180mm): panel a is the "
            "RunAssessor technical summary spanning the top half, panel b is taxid-"
            "prediction metrics, and panel c is grouped PTM frequency (bottom half)."
        ),
    )
    parser.add_argument(
        "--email",
        type=str,
        default=None,
        help=("Email address for NCBI Entrez (enables species-level taxid normalisation "
              "so strain IDs match their parent species). Required by NCBI Terms of Service."),
    )
    parser.add_argument(
        "--threshold",
        type=str,
        default="best",
        help=("Minimum score for a taxid prediction to count as positive, "
              "or 'best' to select only the top-scoring taxid per raw file. "
              "(default: 'best')"),
    )

    args = parser.parse_args()

    # Parse threshold
    raw_threshold = args.threshold.strip()
    if raw_threshold.lower() == "best":
        threshold: float | str = "best"
    else:
        try:
            threshold = float(raw_threshold)
        except ValueError:
            print(f"ERROR: --threshold must be a float or 'best', got: {args.threshold!r}",
                  file=sys.stderr)
            sys.exit(1)

    store_dir = os.path.abspath(args.store)
    if not os.path.isdir(store_dir):
        print(f"ERROR: store directory not found: {store_dir}", file=sys.stderr)
        sys.exit(1)

    outdir = os.path.abspath(args.outdir)
    pxd_list_path = os.path.abspath(args.pxd_list) if args.pxd_list else None

    try:
        allowed_pxds = _load_allowed_pxds(pxd_list_path)
    except Exception as exc:
        print(f"ERROR: failed to load --pxd_list: {exc}", file=sys.stderr)
        sys.exit(1)

    if allowed_pxds is not None:
        print(f"[analyzeMeti] PXD filter active: {len(allowed_pxds)} accessions from {pxd_list_path}")

    if (
        not args.taxid_prediction
        and not args.modification_frequency
        and not args.runassessor_technical_summary
        and not args.figure3_composite
    ):
        parser.print_help()
        print(
            "\nERROR: specify at least one analysis flag "
            "(--taxid_prediction, --modification_frequency, --runassessor_technical_summary, "
            "--figure3_composite)",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.taxid_prediction:
        run_taxid_prediction(
            store_dir,
            threshold,
            outdir,
            email=args.email,
            allowed_pxds=allowed_pxds,
        )

    if args.modification_frequency:
        run_modification_frequency(store_dir, outdir, allowed_pxds=allowed_pxds)

    if args.runassessor_technical_summary:
        run_runassessor_technical_summary(store_dir, outdir, allowed_pxds=allowed_pxds)

    if args.figure3_composite:
        run_figure3_composite(
            store_dir,
            outdir,
            allowed_pxds=allowed_pxds,
            threshold=threshold,
            email=args.email,
        )


if __name__ == "__main__":
    main()
