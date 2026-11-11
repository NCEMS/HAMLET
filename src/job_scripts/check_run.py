#!/usr/bin/env python3
"""Mark verified HAMLET key outputs for one PXD in a tracker CSV."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(REPO_ROOT / "src" / "python"))
from hamlet_version import HAMLET_VERSION  # noqa: E402

STORE_ROOT = REPO_ROOT / "store"

# Files/folders skipped when sweeping the remaining PXD outputs into intermediate_files.
EXCLUDED_SUFFIXES = {".raw", ".mzml"}

# Each column counts as complete once at least one discovered sample has produced it.
SAMPLE_COLUMNS = (
    "casanovo_mztab",
    "filtered_peptides",
    "peptonizer_result",
)

# A run is a complete, successful Reannotation once every key file except these is present.
NOT_REQUIRED_FOR_REANNOTATION = {"casanovo_mztab", "filtered_peptides"}


@dataclass
class CheckResult:
    column: str
    label: str
    exists: bool
    path: Path | None


def nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def first_match(paths: list[Path]) -> Path | None:
    for path in paths:
        if nonempty_file(path):
            return path
    return None


def infer_run_dir(results_pxd_dir: Path) -> tuple[Path, str]:
    # Accept "results" plus --update_from_existing variants like "results_updated".
    if not results_pxd_dir.parent.name.startswith("results"):
        raise ValueError("results_pxd_dir must be a PXD directory directly under a results directory")
    pxd = results_pxd_dir.name
    if not pxd.startswith("PXD"):
        raise ValueError("results_pxd_dir name must be a PXD accession, for example PXD013468")
    return results_pxd_dir.parent.parent, pxd


def candidate_pxd_dirs(results_pxd_dir: Path) -> list[Path]:
    """Return the selected PXD dir plus matching sibling results* variants.

    Update runs can split outputs between results/ and results_updated/. The selected
    directory remains first so it wins when the same output exists in multiple variants.
    """
    candidates = [results_pxd_dir]
    run_dir = results_pxd_dir.parent.parent
    for results_dir in sorted(run_dir.glob("results*")):
        candidate = results_dir / results_pxd_dir.name
        if candidate.is_dir() and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def first_match_across(pxd_dirs: list[Path], relative: str | tuple[str, ...]) -> Path | None:
    relative_paths = (relative,) if isinstance(relative, str) else relative
    for pxd_dir in pxd_dirs:
        for relative_path in relative_paths:
            candidate = pxd_dir / relative_path
            if nonempty_file(candidate):
                return candidate
    return None


def sample_dirs_across(pxd_dirs: list[Path], pxd: str) -> dict[str, list[Path]]:
    """Map sample name -> its CasanovoSequence dir in each candidate pxd dir where it exists."""
    samples: dict[str, list[Path]] = {}
    for pxd_dir in pxd_dirs:
        for path in sample_dirs(pxd_dir, pxd):
            samples.setdefault(path.name, []).append(path)
    return samples


def find_pubmed_id(tracker_row: dict[str, str], pride_metadata: Path) -> str | None:
    value = tracker_row.get("pubmed_id", "").strip()
    if value and value.lower() not in {"nan", "none"}:
        return value.split(".", maxsplit=1)[0]

    if not nonempty_file(pride_metadata):
        return None
    try:
        metadata = json.loads(pride_metadata.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    references = metadata.get("references", [])
    if not references:
        return None
    pubmed_id = references[0].get("pubmedID") or references[0].get("pubmed_id")
    return str(pubmed_id) if pubmed_id else None


def sample_dirs(results_pxd_dir: Path, pxd: str) -> list[Path]:
    casanovo_dir = results_pxd_dir / "organism_results" / "CasanovoSequence"
    return sorted(
        path
        for path in casanovo_dir.glob(f"{pxd}_*")
        if path.is_dir()
    )


def archive_slurm_script(pxd: str) -> Path | None:
    """Move a not-yet-archived slurm/{pxd}*.slurm script into slurm/completed/."""
    slurm_dir = REPO_ROOT / "slurm"
    completed_dir = slurm_dir / "completed"
    matches = sorted(path for path in slurm_dir.glob(f"{pxd}*.slurm") if path.is_file())
    if not matches:
        return None
    completed_dir.mkdir(parents=True, exist_ok=True)
    destination = completed_dir / matches[0].name
    matches[0].replace(destination)
    return destination


def move_remaining_to_intermediate(results_pxd_dir: Path, intermediate_dir: Path) -> list[Path]:
    """Move every remaining file under results_pxd_dir into intermediate_dir, preserving
    the relative layout, except .raw/.mzML files, which are left in place. Skips any file
    whose destination is already populated (e.g. swept there from another candidate dir)."""
    moved: list[Path] = []
    for path in sorted(results_pxd_dir.rglob("*")):
        if path.is_dir() or path.suffix.lower() in EXCLUDED_SUFFIXES:
            continue
        relative = path.relative_to(results_pxd_dir)
        destination = intermediate_dir / relative
        if destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        moved.append(destination)

    ## Prune directories left empty by the move, deepest first, so that any directory
    ## still holding a retained .raw/.mzML file is left alone.
    for directory in sorted(
        (path for path in results_pxd_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass

    return moved


def archive_to_store(
    pxd_dirs: list[Path], pxd: str, store_root: Path, store_version: str
) -> list[str]:
    """Promote the key outputs of a completed PXD into the versioned store, pulling each
    file from whichever candidate results dir (results_updated/, results/, ...) has it,
    then sweep everything else remaining in every candidate dir (minus .raw/.mzML) into
    intermediate_files."""
    actions: list[str] = []

    ## The aggregated results JSON only lives in one place, so it is moved outright.
    aggregated_source = first_match([pxd_dir / f"{pxd}_aggregated_results.json" for pxd_dir in pxd_dirs])
    aggregated_dest = store_root / "aggregated_results_files" / store_version / f"{pxd}_aggregated_results.json"
    if aggregated_source and not aggregated_dest.exists():
        aggregated_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(aggregated_source), str(aggregated_dest))
        actions.append(f"moved {aggregated_source.name} -> {aggregated_dest}")

    ## The generated SDRF is copied out to hamlet_sdrfs (the original stays inside
    ## agentic_metadata, which is moved wholesale to agentic_results_files below).
    sdrf_source = first_match([pxd_dir / "agentic_metadata" / f"{pxd}.sdrf.tsv" for pxd_dir in pxd_dirs])
    sdrf_dest = store_root / "hamlet_sdrfs" / store_version / f"{pxd}.sdrf.tsv"
    if sdrf_source and not sdrf_dest.exists():
        sdrf_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sdrf_source, sdrf_dest)
        actions.append(f"copied {sdrf_source.name} -> {sdrf_dest}")

    ## The whole agentic_metadata bundle is moved to agentic_results_files, from whichever
    ## candidate dir has it first.
    agentic_dest = store_root / "agentic_results_files" / store_version / pxd
    if not agentic_dest.exists():
        for pxd_dir in pxd_dirs:
            agentic_metadata_dir = pxd_dir / "agentic_metadata"
            if agentic_metadata_dir.is_dir():
                agentic_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(agentic_metadata_dir), str(agentic_dest))
                actions.append(f"moved agentic_metadata -> {agentic_dest}")
                break

    ## Everything else left in each candidate dir (minus .raw/.mzML) is intermediate output.
    intermediate_dest = store_root / "intermediate_files" / store_version / pxd
    for pxd_dir in pxd_dirs:
        moved_files = move_remaining_to_intermediate(pxd_dir, intermediate_dest)
        if moved_files:
            actions.append(f"moved {len(moved_files)} remaining file(s) from {pxd_dir} -> {intermediate_dest}")

    return actions


def sample_output_path(sample_dir: Path, column: str) -> Path | None:
    sample_name = sample_dir.name
    filtered_dir = sample_dir / "Peptonizer2000_data"
    if column == "casanovo_mztab":
        candidate = sample_dir / f"{sample_name}.mztab"
        return candidate if nonempty_file(candidate) else None
    if column == "filtered_peptides":
        return first_match(list(sample_dir.glob(f"{sample_name}_filtered*pct.tsv")))
    return first_match(list(filtered_dir.glob("**/peptonizer_result.csv")))


STORE_VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
STORE_CATEGORIES = ("aggregated_results_files", "hamlet_sdrfs", "agentic_results_files", "intermediate_files")


def version_sort_key(version: str) -> tuple[int, int, int]:
    major, minor, patch = version.lstrip("v").split(".")
    return int(major), int(minor), int(patch)


def version_has_pxd(pxd: str, store_root: Path, version: str) -> bool:
    return (
        nonempty_file(store_root / "aggregated_results_files" / version / f"{pxd}_aggregated_results.json")
        or nonempty_file(store_root / "hamlet_sdrfs" / version / f"{pxd}.sdrf.tsv")
        or (store_root / "agentic_results_files" / version / pxd).is_dir()
        or (store_root / "intermediate_files" / version / pxd).is_dir()
    )


def discover_latest_pxd_version(pxd: str, store_root: Path) -> str | None:
    """Return the newest store version folder that already holds any promoted data for this PXD."""
    versions = {
        path.name
        for category in STORE_CATEGORIES
        if (store_root / category).is_dir()
        for path in (store_root / category).iterdir()
        if path.is_dir() and STORE_VERSION_PATTERN.match(path.name)
    }
    for version in sorted(versions, key=version_sort_key, reverse=True):
        if version_has_pxd(pxd, store_root, version):
            return version
    return None



def store_key_output_statuses(store_root: Path, pxd: str, version: str) -> list[CheckResult]:
    """Check where each key file currently lives once promoted into the versioned store.

    Only checks paths under store_root; files that check_run.py never archives (run/slurm
    logs, stage manifest, pride/publication metadata) are reported by key_output_statuses
    instead and are intentionally omitted here."""
    agentic_prefix = store_root / "agentic_results_files" / version / pxd
    intermediate_prefix = store_root / "intermediate_files" / version / pxd

    single_file_columns: dict[str, Path | list[Path]] = {
        "aggregated_results": store_root / "aggregated_results_files" / version / f"{pxd}_aggregated_results.json",
        "generated_sdrf": store_root / "hamlet_sdrfs" / version / f"{pxd}.sdrf.tsv",
        "biological_metadata": agentic_prefix / "metadata_extraction_output/integrated_output/BiologicalAgent/temp_0.0" / f"{pxd}_PubText_enriched.json",
        "experimental_design_metadata": agentic_prefix / "metadata_extraction_output/integrated_output/ExperimentalDesignAgent/temp_0.0" / f"{pxd}_PubText_enriched.json",
        "technical_metadata": agentic_prefix / "metadata_extraction_output/integrated_output/TechnicalAgent/temp_0.0" / f"{pxd}_PubText_enriched.json",
        "pipeline_summary": intermediate_prefix / f"{pxd}_pipeline.json",
        "runassessor_metadata": intermediate_prefix / "runAssessor/study_metadata.json",
        "sdrf_judge_result": intermediate_prefix / "sdrf_judge/json_outputs" / f"{pxd}.json",
        "sdrf_judge_accuracy_plot": intermediate_prefix / "sdrf_judge/llm_judge_accuracy.png",
        "sdrf_judge_per_paper": intermediate_prefix / "sdrf_judge/llm_judge_per_paper.csv",
        "sage_open_search_psms": [
            intermediate_prefix / "search/dda_search/Open/search_results.tsv",
            intermediate_prefix / "search/dda_search/Open/results.sage.tsv",
            intermediate_prefix / "search/dda_search/results.open.sage.tsv",
        ],
    }

    records: list[CheckResult] = []
    for column, paths in single_file_columns.items():
        candidates = paths if isinstance(paths, list) else [paths]
        path = first_match(candidates)
        records.append(CheckResult(column, column, path is not None, path))

    for column in SAMPLE_COLUMNS:
        for sample in sample_dirs(intermediate_prefix, pxd):
            path = sample_output_path(sample, column)
            records.append(CheckResult(column, f"{column} ({sample.name})", path is not None, path))

    return records


def key_output_statuses(
    results_pxd_dir: Path, pxd: str, tracker_row: dict[str, str]
) -> tuple[dict[str, bool], list[CheckResult]]:
    run_dir, _ = infer_run_dir(results_pxd_dir)
    pxd_dirs = candidate_pxd_dirs(results_pxd_dir)
    spectral_dir = run_dir / "spectral_files" / pxd
    pride_metadata = spectral_dir / f"{pxd}_PRIDEmetadata.json"
    pubmed_id = find_pubmed_id(tracker_row, pride_metadata)

    single_file_columns = {
        "nextflow_log": run_dir / "nextflow.log",
        "stage_manifest": run_dir / "results/pipeline_stage_manifest.json",
        "pride_metadata": pride_metadata,
    }

    # Checked against each candidate pxd dir in turn (results_updated/ first, then results/),
    # since --update_from_existing reruns only refresh the toggled-on stages in the new dir.
    relative_single_file_columns = {
        "aggregated_results": f"{pxd}_aggregated_results.json",
        "pipeline_summary": f"{pxd}_pipeline.json",
        "generated_sdrf": f"agentic_metadata/{pxd}.sdrf.tsv",
        "biological_metadata": f"agentic_metadata/metadata_extraction_output/integrated_output/BiologicalAgent/temp_0.0/{pxd}_PubText_enriched.json",
        "experimental_design_metadata": f"agentic_metadata/metadata_extraction_output/integrated_output/ExperimentalDesignAgent/temp_0.0/{pxd}_PubText_enriched.json",
        "technical_metadata": f"agentic_metadata/metadata_extraction_output/integrated_output/TechnicalAgent/temp_0.0/{pxd}_PubText_enriched.json",
        "runassessor_metadata": "runAssessor/study_metadata.json",
        "sdrf_judge_result": f"sdrf_judge/json_outputs/{pxd}.json",
        "sdrf_judge_accuracy_plot": "sdrf_judge/llm_judge_accuracy.png",
        "sdrf_judge_per_paper": "sdrf_judge/llm_judge_per_paper.csv",
        "sage_open_search_psms": (
            "search/dda_search/Open/search_results.tsv",
            "search/dda_search/Open/results.sage.tsv",
            "search/dda_search/results.open.sage.tsv",
        ),
    }

    statuses: dict[str, bool] = {}
    records: list[CheckResult] = []
    for column, path in single_file_columns.items():
        exists = nonempty_file(path)
        statuses[column] = exists
        records.append(CheckResult(column, column, exists, path if exists else None))

    for column, relative in relative_single_file_columns.items():
        path = first_match_across(pxd_dirs, relative)
        statuses[column] = path is not None
        records.append(CheckResult(column, column, path is not None, path))

    slurm_log_path = first_match(sorted(run_dir.glob("slurm_*.log")))
    statuses["slurm_log"] = slurm_log_path is not None
    records.append(CheckResult("slurm_log", "slurm_log", slurm_log_path is not None, slurm_log_path))

    publication_path = (
        first_match(list((spectral_dir / "pmc_json").glob(f"{pxd}_{pubmed_id}*.json")))
        if pubmed_id
        else None
    )
    statuses["publication_metadata"] = publication_path is not None
    records.append(CheckResult("publication_metadata", "publication_metadata", publication_path is not None, publication_path))

    samples = sample_dirs_across(pxd_dirs, pxd)
    for column in SAMPLE_COLUMNS:
        sample_paths: dict[str, Path | None] = {}
        for sample_name, sample_dir_candidates in samples.items():
            path = None
            for sample_dir in sample_dir_candidates:
                path = sample_output_path(sample_dir, column)
                if path is not None:
                    break
            sample_paths[sample_name] = path
        # Some samples legitimately produce no output (e.g. filtered out upstream), so a
        # column counts as verified once at least one sample has completed it.
        statuses[column] = any(path is not None for path in sample_paths.values())
        for sample_name, path in sample_paths.items():
            records.append(CheckResult(column, f"{column} ({sample_name})", path is not None, path))

    return statuses, records


def update_tracker(
    tracker_path: Path,
    results_pxd_dir: Path,
    store_root: Path = STORE_ROOT,
    store_version: str = HAMLET_VERSION,
) -> tuple[str, list[str], list[CheckResult], Path | None, list[str], list[str]]:

    ## Infer the run directory and PXD identifier from the results directory
    run_dir, pxd = infer_run_dir(results_pxd_dir)
    del run_dir

    ## Read the tracker CSV into memory
    with tracker_path.open(newline="") as tracker_file:
        reader = csv.DictReader(tracker_file)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if not fieldnames or "accession" not in fieldnames:
        raise ValueError("tracker must contain an accession column")

    ## Ensure the tracker contains the required accession column
    matching_rows = [row for row in rows if row.get("accession") == pxd]
    if len(matching_rows) != 1:
        raise ValueError(f"expected exactly one tracker row for {pxd}, found {len(matching_rows)}")
    tracker_row = matching_rows[0]
    reannotated_status = tracker_row.get("Reannotated")
    print(f"Prior to run_check update, Reannotated status for {pxd}: {reannotated_status}")

    ## Determine the current status of key output files across all candidate results dirs
    ## (results/, and results_updated/ etc. for --update_from_existing reruns).
    statuses, records = key_output_statuses(results_pxd_dir, pxd, tracker_row)
    results_statuses = dict(statuses)

    ## Fold in anything already promoted to the store, so a column already archived still
    ## counts even if its results-dir copy has since been swept away by archive_to_store.
    latest_pxd_version = discover_latest_pxd_version(pxd, store_root) or store_version
    store_statuses: dict[str, bool] = {}
    for record in store_key_output_statuses(store_root, pxd, latest_pxd_version):
        store_statuses[record.column] = store_statuses.get(record.column, False) or record.exists
    for column, exists in store_statuses.items():
        if exists:
            statuses[column] = True
    satisfied_via_store = sorted(
        column for column, exists in statuses.items()
        if exists and not results_statuses.get(column, False)
    )

    updated_columns = []
    for column, exists in statuses.items():
        if exists and column in fieldnames and tracker_row.get(column) != "O":
            tracker_row[column] = "O"
            updated_columns.append(column)

    ## A successful Reannotation only requires the casanovo_mztab/filtered_peptides
    ## intermediates to be missing, not the final peptonizer_result and other key files.
    ## A column counts as satisfied if it is present in results/, results_updated/, or store/.
    reannotation_success = all(
        exists for column, exists in statuses.items() if column not in NOT_REQUIRED_FOR_REANNOTATION
    )
    if reannotation_success and "Reannotated" in fieldnames and tracker_row.get("Reannotated") != "True":
        tracker_row["Reannotated"] = "True"
        updated_columns.append("Reannotated")
        print(f"Reannotated {pxd}")
    reannotated_status = tracker_row.get("Reannotated")
    print(f"Post run_check update, Reannotated status for {pxd}: {reannotated_status}")

    ## Write the updated tracker back to disk using a temporary file
    temporary_path = tracker_path.with_suffix(tracker_path.suffix + ".tmp")
    with temporary_path.open("w", newline="") as tracker_file:
        writer = csv.DictWriter(tracker_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(tracker_path)

    ## Once Reannotated, its slurm submission script should be archived as completed,
    ## and its key outputs promoted into the versioned store.
    is_reannotated = tracker_row.get("Reannotated") == "True"
    archived_slurm_script = archive_slurm_script(pxd) if is_reannotated else None
    store_actions = (
        archive_to_store(candidate_pxd_dirs(results_pxd_dir), pxd, store_root, store_version)
        if is_reannotated
        else []
    )

    return pxd, updated_columns, records, archived_slurm_script, store_actions, satisfied_via_store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tracker", type=Path, help="CSV tracker to update")
    parser.add_argument("results_pxd_dir", type=Path, help="Path to RUN_DIR/results/PXDnnnnnn")
    parser.add_argument("--store-root", type=Path, default=STORE_ROOT, help="HAMLET durable store root")
    parser.add_argument(
        "--store-version",
        default=HAMLET_VERSION,
        help=f"Store version folder to archive into (default: {HAMLET_VERSION})",
    )
    arguments = parser.parse_args()

    ## Update the tracker with the current status of sample outputs
    try:
        pxd, updated_columns, records, archived_slurm_script, store_actions, satisfied_via_store = update_tracker(
            arguments.tracker.resolve(),
            arguments.results_pxd_dir.resolve(),
            arguments.store_root.resolve(),
            arguments.store_version,
        )
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    ## Print the check status and absolute path for every key file inspected
    print(f"Key file check for {pxd}:")
    for record in records:
        marker = "FOUND" if record.exists else "MISSING"
        detail = str(record.path.resolve()) if record.path else ""
        print(f"  [{marker}] {record.label}: {detail}")

    ## Print a summary of the updates made to the tracker
    if updated_columns:
        print(f"Updated {pxd}: {', '.join(updated_columns)}")
    else:
        print(f"No new verified outputs for {pxd}.")

    if satisfied_via_store:
        print(f"Satisfied via store only (missing from results dirs): {', '.join(satisfied_via_store)}")

    if archived_slurm_script:
        print(f"Archived slurm script to {archived_slurm_script}")

    for action in store_actions:
        print(f"Store: {action}")

    ## Report where each key file currently lives in the store, regardless of whether
    ## the results folder has already been swept away by archive_to_store above.
    store_root = arguments.store_root.resolve()
    latest_pxd_version = discover_latest_pxd_version(pxd, store_root) or arguments.store_version
    store_records = store_key_output_statuses(store_root, pxd, latest_pxd_version)
    print(f"Store check for {pxd} (version {latest_pxd_version}):")
    for record in store_records:
        marker = "FOUND" if record.exists else "MISSING"
        detail = str(record.path.resolve()) if record.path else ""
        print(f"  [{marker}] {record.label}: {detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())