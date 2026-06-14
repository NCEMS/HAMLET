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

def run_taxid_prediction(store_dir: str, threshold: float | str, outdir: str,
                         email: str | None = None) -> None:
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


def run_modification_frequency(store_dir: str, outdir: str) -> None:
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
        "--email",
        type=str,
        default=None,
        help=("Email address for NCBI Entrez (enables species-level taxid normalisation "
              "so strain IDs match their parent species). Required by NCBI Terms of Service."),
    )
    parser.add_argument(
        "--threshold",
        type=str,
        default="0.5",
        help=("Minimum score for a taxid prediction to count as positive, "
              "or 'best' to select only the top-scoring taxid per raw file. "
              "(default: 0.5)"),
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

    if not args.taxid_prediction and not args.modification_frequency:
        parser.print_help()
        print("\nERROR: specify at least one analysis flag (--taxid_prediction, --modification_frequency)",
              file=sys.stderr)
        sys.exit(1)

    if args.taxid_prediction:
        run_taxid_prediction(store_dir, threshold, outdir, email=args.email)

    if args.modification_frequency:
        run_modification_frequency(store_dir, outdir)


if __name__ == "__main__":
    main()
