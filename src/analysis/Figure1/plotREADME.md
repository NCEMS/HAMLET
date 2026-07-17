# Figure 1 — Plotting Guide

Instructions for regenerating Figure 1 (2x2 manuscript panel) after cloning the
HAMLET repo.

## What Figure 1 shows

- **Panel a** (upper-left): Availability of PRIDE datasets with a linked
  publication, an open-access/usable `CC BY`-style license, and SDRF metadata
  (all PXDs in `master.csv`).
- **Panel b** (upper-right): Existing PRIDE field availability vs. HAMLET field
  availability (HAMLET PXDs only).
- **Panel c** (lower-left): Annotation availability by metadata class, derived
  from `.ann` files.
- **Panel d** (lower-right): Inter-annotator agreement by metadata class.

## 1. Clone the repo

```bash
git clone git@github.com:NCEMS/HAMLET.git
cd HAMLET
```

`src/analysis/Figure1/data/` (crosswalk table, `GoldenAnnotations`,
`Select_27_Pubs`) and `store/hamlet_sdrfs/*.sdrf.tsv` are already tracked in
git, so no extra setup is needed for those.

## 2. Get `pride_survey`

The PRIDE cache used by this script (`pride_survey/pride_cache`) is too large
to track in git and ships separately as `pride_survey.tar.xz`. Place the
archive at the repo root and untar it:

```bash
tar -xJf pride_survey.tar.xz
```

This should create a `pride_survey/` directory at the repo root containing
`pride_cache` (and other survey files). The script expects this at
`pride_survey/pride_cache` by default — pass `--pride-cache` if you put it
somewhere else.

## 3. Set up the Python environment

The script needs `pandas`, `matplotlib`, and `requests`. The repo's conda
environment already includes these:

```bash
conda env create -f data/environment.yml
conda activate <env-name-from-yml>
```

Or, in an existing environment:

```bash
pip install pandas matplotlib
```

## 4. Run the script

From the repo root:

```bash
python src/analysis/Figure1/make_figure1.py
```

All arguments have sensible defaults that assume you're running from the repo
root:

| Argument | Default | Description |
|---|---|---|
| `--crosswalk` | `src/analysis/Figure1/data/field_crosswalk_table.csv` | Crosswalk CSV mapping PRIDE fields to `.ann` labels |
| `--pride-cache` | `pride_survey/pride_cache` | Local PRIDE cache JSON (from the untarred `pride_survey.tar.xz`) |
| `--store-dir` | `store/hamlet_sdrfs` | Directory of HAMLET SDRF outputs, named `{PXD}.sdrf.tsv` |
| `--hamlet-pxds` | `HamletPXDs.csv` | CSV of HAMLET PXDs |
| `--master-csv` | `master.csv` | Master CSV of all PXDs (panel a); its `existing_PRIDE_SDRF` column is used directly for SDRF presence |
| `--ann-root` | `src/analysis/Figure1/data/Select_27_Pubs` | Root containing `MultiHuman`/`SingleHuman` `.ann` files |
| `--outdir` | `src/analysis/Figure1/output` | Output directory for figures and tables |
| `--basename` | `figure1_composite` | Base filename for outputs |

## 5. Outputs

Written to `--outdir` (default `src/analysis/Figure1/output/`):

- `figure1_composite.png` / `.svg` — the full 2x2 composite figure
- `figure1_composite_panel_{b,c,d}.png` / `.svg` — standalone panels
- `figure1_composite_panel_{a,b,c,d}_table.csv` — underlying data tables for
  auditability
