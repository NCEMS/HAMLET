#!/usr/bin/env python3
"""Build the static data bundle consumed by the HAMLET Store Explorer."""

import argparse
import csv
import json
import math
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path


SUPPORTED_SUFFIXES = {".csv", ".json", ".md", ".png", ".tsv"}
MAX_PUBLISHED_FILE_BYTES = 1 * 1024 * 1024
RELEASE_VERSION_PATTERN = re.compile(r'"pipeline_version"\s*:\s*"(v\d+\.\d+\.\d+)"')
VERSION_DIRECTORY_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
HAMLET_VERSION_PATTERN = re.compile(r'HAMLET_VERSION\s*=\s*"(v\d+\.\d+\.\d+)"')
HAMLET_VERSION_FILE = Path(__file__).resolve().parents[1] / "python" / "hamlet_version.py"
SDRF_TERMS_FILE = Path(__file__).resolve().parents[2] / "assets" / "sdrf-terms.csv"
VERSION_HISTORY_FILE = Path(__file__).resolve().parents[2] / "docs" / "HAMLET_VERSION_HISTORY.md"
SDRF_HEADER_PATTERN = re.compile(r"^(characteristics|comment|factor value)\[(.+)]$")
VERSION_HISTORY_HEADING_PATTERN = re.compile(r"^##[ \t]+(v\d+\.\d+\.\d+)[ \t]+-[ \t]+(.+?)[ \t]*$", re.MULTILINE)

HAMLET_SDRF_HEADER_METADATA = {
    "comment[sdrf version]": ("sdrf version", "REQUIRED", "comment", "HAMLET", "Version of the SDRF structure written by HAMLET."),
    "comment[sdrf annotation tool]": ("sdrf annotation tool", "REQUIRED", "comment", "HAMLET", "Tool and release that generated the SDRF annotation."),
    "comment[ms1 scan range]": ("MS1 scan range", "OPTIONAL", "comment", "MS:1000501", "Lower and upper m/z limits acquired for MS1 scans."),
    "characteristics[treatment]": ("treatment", "OPTIONAL", "characteristics", "EFO:0000727", "Treatment or perturbation applied to the analyzed sample."),
    "factor value[experimental design]": ("experimental design", "OPTIONAL", "factor value", "OBI:0000471", "Experimental variable or study-group label assigned to the sample."),
}


def canonical_hamlet_version() -> str:
    match = HAMLET_VERSION_PATTERN.search(HAMLET_VERSION_FILE.read_text(encoding="utf-8"))
    if not match:
        raise RuntimeError(f"Could not read HAMLET_VERSION from {HAMLET_VERSION_FILE}")
    return match.group(1)


CURRENT_SCHEMA_VERSION = canonical_hamlet_version()
LEGACY_SCHEMA_VERSION = "v2.0.0"
JUDGE_SOURCES = (
    ("sdrf_judge", Path("sdrf_judge") / "llm_judge_per_paper.csv"),
    ("llm_judge", Path("metadata_extraction_output") / "post_judge" / "llm_judge_per_paper.csv"),
    ("llm_judge", Path("judge_output") / "llm_judge_per_paper.csv"),
    ("llm_judge", Path("llm_refinement_judge") / "llm_judge_per_paper.csv"),
)


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def annotated_release_version(agentic_source: Path, pxd: str) -> str | None:
    sdrf_path = agentic_source / f"{pxd}.sdrf.tsv"
    if not sdrf_path.is_file():
        return None
    with sdrf_path.open(encoding="utf-8", newline="") as handle:
        rows = csv.reader(handle, delimiter="\t")
        headers = next(rows, [])
        try:
            annotation_index = headers.index("comment[sdrf annotation tool]")
        except ValueError:
            return None
        annotations = {row[annotation_index] for row in rows if len(row) > annotation_index}
    versions = {
        match.group(1)
        for annotation in annotations
        for match in [re.search(r"HAMLET-agentic\s+(v\d+\.\d+\.\d+)", annotation)]
        if match
    }
    return versions.pop() if len(versions) == 1 else None


def release_version(aggregate: Path, agentic_source: Path, pxd: str) -> str | None:
    current_schema = {
        f"{pxd}.sdrf.tsv",
        f"{pxd}.confidence.sdrf.tsv",
        "metadata_extraction_output",
        "llm_refinement_judge",
        "sdrf_judge",
    }
    annotated_version = annotated_release_version(agentic_source, pxd)
    if annotated_version:
        return annotated_version
    if agentic_source.is_dir() and current_schema <= {path.name for path in agentic_source.iterdir()}:
        return CURRENT_SCHEMA_VERSION
    if not aggregate.is_file():
        return None
    versions = RELEASE_VERSION_PATTERN.findall(aggregate.read_text(encoding="utf-8", errors="replace"))
    return versions[-1] if versions else LEGACY_SCHEMA_VERSION


def read_pxd_file(path: Path) -> list[str]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and line != "PXDs"]


def active_release_versions(store_path: Path) -> dict[str, str]:
    active_path = store_path / "releases" / "active.json"
    if not active_path.is_file():
        return {}
    try:
        active = json.loads(active_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read active release index {active_path}: {exc}") from exc
    pxds = active.get("pxds", {})
    if not isinstance(pxds, dict):
        raise RuntimeError(f"Active release index has no PXD mapping: {active_path}")
    return {
        pxd: version
        for pxd, version in pxds.items()
        if isinstance(pxd, str) and re.fullmatch(r"PXD\d+", pxd)
        and isinstance(version, str) and re.fullmatch(r"v\d+\.\d+\.\d+", version)
    }


def collect_pxds(store_path: Path, requested_pxds: list[str], active_versions: dict[str, str]) -> list[str]:
    if requested_pxds:
        return sorted(set(requested_pxds))
    aggregate_pxds = {
        path.name.removesuffix("_aggregated_results.json")
        for path in (store_path / "aggregated_results_files").glob("PXD*_aggregated_results.json")
    }
    return sorted(aggregate_pxds | set(active_versions))


def build_record(store_path: Path, output_data_dir: Path, pxd: str, active_versions: dict[str, str]) -> dict:
    record = {
        "pxd": pxd,
        "version": None,
        "available": False,
        "aggregated": None,
        "aggregate_omission": None,
        "agentic": [],
        "pride": None,
        "conflict": [],
    }
    pxd_data_dir = output_data_dir / pxd
    aggregate = store_path / "aggregated_results_files" / f"{pxd}_aggregated_results.json"
    record["version"] = active_versions.get(pxd)
    agentic_source = (
        store_path / "agentic_results_files" / record["version"] / pxd
        if record["version"] else store_path / "agentic_results_files" / pxd
    )
    record["version"] = record["version"] or release_version(aggregate, agentic_source, pxd)
    record["available"] = aggregate.is_file()
    if aggregate.is_file() and aggregate.stat().st_size <= MAX_PUBLISHED_FILE_BYTES:
        relative_path = Path(pxd) / "aggregated_results.json"
        copy_file(aggregate, output_data_dir / relative_path)
        record["aggregated"] = relative_path.as_posix()
    elif aggregate.is_file():
        record["aggregate_omission"] = {
            "reason": "file exceeds Explorer publish limit",
            "size_bytes": aggregate.stat().st_size,
            "limit_bytes": MAX_PUBLISHED_FILE_BYTES,
        }

    if agentic_source.is_dir():
        record["available"] = True
        for source in sorted(agentic_source.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            relative_source = source.relative_to(agentic_source)
            if source.stat().st_size > MAX_PUBLISHED_FILE_BYTES:
                continue
            if aggregate.is_file() and relative_source == Path("metadata_extraction_output") / f"{pxd}_aggregated_results.json":
                continue
            if relative_source.parts[:1] == ("judge_output",):
                post_judge_copy = agentic_source / "metadata_extraction_output" / "post_judge" / Path(*relative_source.parts[1:])
                final_judge_copy = agentic_source / "sdrf_judge" / Path(*relative_source.parts[1:])
                if post_judge_copy.is_file() or final_judge_copy.is_file():
                    continue
            relative_path = Path(pxd) / "agentic" / relative_source
            copy_file(source, output_data_dir / relative_path)
            record["agentic"].append(relative_path.as_posix())

    conflict_source = Path("reports") / "conflict_assessment" / pxd
    pride_sdrf = conflict_source / "pride.sdrf.tsv"
    if pride_sdrf.is_file() and pride_sdrf.stat().st_size <= MAX_PUBLISHED_FILE_BYTES:
        relative_path = Path(pxd) / "pride.sdrf.tsv"
        copy_file(pride_sdrf, output_data_dir / relative_path)
        record["pride"] = relative_path.as_posix()

    comparison_source = conflict_source / "store_vs_pride"
    if comparison_source.is_dir():
        for source in sorted(comparison_source.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            if source.stat().st_size > MAX_PUBLISHED_FILE_BYTES:
                continue
            relative_path = Path(pxd) / "conflict" / source.relative_to(comparison_source)
            copy_file(source, output_data_dir / relative_path)
            record["conflict"].append(relative_path.as_posix())

    if not record["available"]:
        shutil.rmtree(pxd_data_dir, ignore_errors=True)
    return record


def final_sdrf_path(record: dict, output_data_dir: Path) -> Path | None:
    suffix = f"/{record['pxd']}.sdrf.tsv"
    path = next((path for path in record["agentic"] if path.endswith(suffix)), None)
    return output_data_dir / path if path else None


def read_judge_metrics(path: Path, pxd: str) -> dict[str, float]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("paper_id") == pxd]
    if len(rows) != 1:
        return {}
    metrics = {}
    for field, raw_value in rows[0].items():
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            metrics[field] = value
    return metrics


def preferred_judge_record(agentic_source: Path, pxd: str) -> tuple[str, dict[str, float]] | None:
    for judge_type, relative_path in JUDGE_SOURCES:
        metrics_path = agentic_source / relative_path
        if not metrics_path.is_file():
            continue
        metrics = read_judge_metrics(metrics_path, pxd)
        if metrics:
            return judge_type, metrics
    return None


def release_pxds(store_path: Path, version: str, manifest: dict) -> list[str]:
    pxds = [
        item["pxd"]
        for item in manifest.get("pxds", [])
        if isinstance(item, dict) and isinstance(item.get("pxd"), str)
        and re.fullmatch(r"PXD\d+", item["pxd"])
    ]
    if pxds:
        return sorted(set(pxds))
    return sorted(
        path.name.removesuffix(".sdrf.tsv")
        for path in (store_path / "hamlet_sdrfs" / version).glob("PXD*.sdrf.tsv")
        if re.fullmatch(r"PXD\d+", path.name.removesuffix(".sdrf.tsv"))
    )


def version_sort_key(version: str) -> tuple[int, int, int]:
    match = VERSION_DIRECTORY_PATTERN.fullmatch(version)
    if not match:
        raise ValueError(f"Invalid release version: {version}")
    return tuple(int(value) for value in match.groups())


def load_version_history(path: Path = VERSION_HISTORY_FILE) -> list[dict]:
    """Read release notes from the canonical Markdown history document."""
    text = path.read_text(encoding="utf-8")
    headings = list(VERSION_HISTORY_HEADING_PATTERN.finditer(text))
    notes = []
    for index, heading in enumerate(headings):
        body_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        notes.append(
            {
                "version": heading.group(1),
                "title": heading.group(2),
                "markdown": text[heading.end():body_end].strip(),
            }
        )
    return notes


def release_judge_metrics(store_path: Path) -> list[dict]:
    releases_dir = store_path / "releases"
    sdrf_dir = store_path / "hamlet_sdrfs"
    manifest_paths = {path.parent.name: path for path in releases_dir.glob("v*/manifest.json")}
    release_versions = set(manifest_paths)
    if sdrf_dir.is_dir():
        release_versions.update(
            path.name for path in sdrf_dir.iterdir()
            if path.is_dir() and VERSION_DIRECTORY_PATTERN.fullmatch(path.name)
        )
    summaries = []
    for version in sorted(release_versions, key=version_sort_key):
        manifest_path = manifest_paths.get(version)
        if manifest_path:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if manifest.get("release_version") != version:
                continue
            release_state = "immutable"
        else:
            manifest = {"release_version": version, "pxds": []}
            release_state = "in_progress"
        pxds = release_pxds(store_path, version, manifest)
        records_by_type = defaultdict(list)
        for pxd in pxds:
            judge = preferred_judge_record(store_path / "agentic_results_files" / version / pxd, pxd)
            if judge:
                judge_type, metrics = judge
                records_by_type[judge_type].append({"pxd": pxd, "metrics": metrics})
        if not records_by_type:
            summaries.append({
                "version": version,
                "release_state": release_state,
                "judge_type": None,
                "release_pxd_count": len(pxds),
                "records": [],
                "available_metrics": [],
            })
            continue
        judge_type = "sdrf_judge" if records_by_type["sdrf_judge"] else "llm_judge"
        records = sorted(records_by_type[judge_type], key=lambda item: item["pxd"])
        summaries.append(
            {
                "version": version,
                "release_state": release_state,
                "judge_type": judge_type,
                "release_pxd_count": len(pxds),
                "records": records,
                "available_metrics": sorted({field for record in records for field in record["metrics"]}),
            }
        )
    return summaries


def load_sdrf_terms() -> dict[tuple[str, str], dict]:
    terms: dict[tuple[str, str], dict] = {}
    with SDRF_TERMS_FILE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            terms[(row["TERM"].lower(), row["TYPE"].lower())] = row
    return terms


def category_metadata(header: str, terms: dict[tuple[str, str], dict]) -> dict:
    if header in HAMLET_SDRF_HEADER_METADATA:
        term, requirement, category_type, accession, description = HAMLET_SDRF_HEADER_METADATA[header]
        return {
            "header": header,
            "term": term,
            "requirement": requirement,
            "type": category_type,
            "ontology_accession": accession,
            "catalog_description": description,
        }
    match = SDRF_HEADER_PATTERN.match(header)
    if match:
        category_type, term = match.groups()
    else:
        category_type, term = "other", header
    term_row = terms.get((term.lower(), category_type))
    if not term_row:
        term_row = terms.get((term.lower(), "other"))
    if not term_row:
        return {
            "header": header,
            "term": term,
            "requirement": "",
            "type": category_type,
            "ontology_accession": "",
            "catalog_description": "HAMLET SDRF field without a matching entry in the bundled SDRF term catalog.",
        }
    return {
        "header": header,
        "term": term_row["TERM"],
        "requirement": term_row["REQUIREMENT"],
        "type": term_row["TYPE"],
        "ontology_accession": term_row["ONTOLOGY ACCESSION"],
        "catalog_description": term_row["DESCRIPTION"],
    }


def histogram(values: list[float]) -> list[dict]:
    if not values:
        return []
    minimum, maximum = min(values), max(values)
    if minimum == maximum:
        return [{"label": f"{minimum:g}", "count": len(values)}]
    bins = 10
    if 0 <= minimum and maximum <= 1:
        minimum, maximum = 0.0, 1.0
    width = (maximum - minimum) / bins
    counts = [0] * bins
    for value in values:
        index = min(int((value - minimum) / width), bins - 1)
        counts[index] += 1
    return [
        {
            "label": f"{minimum + index * width:.2f}-{minimum + (index + 1) * width:.2f}",
            "count": count,
        }
        for index, count in enumerate(counts)
    ]


def build_site_summary(records: list[dict], output_data_dir: Path, store_path: Path) -> dict:
    versions: Counter[str] = Counter()
    headers: Counter[str] = Counter()
    for record in records:
        sdrf_path = final_sdrf_path(record, output_data_dir)
        if sdrf_path:
            versions[record["version"] or "Unknown"] += 1
            with sdrf_path.open(encoding="utf-8", newline="") as handle:
                headers.update(next(csv.reader(handle, delimiter="\t"), []))
    terms = load_sdrf_terms()
    categories = [
        {**category_metadata(header, terms), "pxd_count": count}
        for header, count in sorted(headers.items(), key=lambda item: item[0].lower())
    ]
    version_judges = release_judge_metrics(store_path)
    judge_records_by_type = Counter()
    judge_fields_by_type = {}
    for judge_type in ("llm_judge", "sdrf_judge"):
        values_by_field = defaultdict(list)
        for version_judge in version_judges:
            if version_judge["judge_type"] != judge_type:
                continue
            for judge_record in version_judge["records"]:
                judge_records_by_type[judge_type] += 1
                for field, value in judge_record["metrics"].items():
                    values_by_field[field].append(value)
        judge_fields_by_type[judge_type] = [
            {
                "field": field,
                "count": len(values),
                "minimum": min(values),
                "maximum": max(values),
                "mean": sum(values) / len(values),
                "histogram": histogram(values),
            }
            for field, values in sorted(values_by_field.items())
        ]
    return {
        "total_pxds": len(records),
        "sdrf_versions": [
            {"version": version, "count": count}
            for version, count in sorted(versions.items())
        ],
        "judge_records_by_type": dict(judge_records_by_type),
        "judge_fields_by_type": judge_fields_by_type,
        "version_judges": version_judges,
        "metadata_categories": categories,
    }


def publish_qc_summary(qc_summary: Path, output_data_dir: Path) -> None:
    """Copy an explicitly reviewed QC run into the static Explorer data bundle."""
    try:
        summary = json.loads(qc_summary.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read QC summary {qc_summary}: {exc}") from exc
    if not isinstance(summary, dict):
        raise RuntimeError(f"QC summary {qc_summary} is not a JSON object")

    result_groups = []
    if isinstance(summary.get("results"), list):
        result_groups.append(summary["results"])
    if isinstance(summary.get("comparisons"), list):
        result_groups.extend(
            comparison.get("results", [])
            for comparison in summary["comparisons"]
            if isinstance(comparison, dict) and isinstance(comparison.get("results"), list)
        )
    if not result_groups:
        raise RuntimeError(f"QC summary {qc_summary} has no results list")

    for results in result_groups:
        for result in results:
            pxd = result.get("pxd")
            if not isinstance(pxd, str) or not re.fullmatch(r"PXD\d+", pxd):
                continue
            for report_key in ("comparison", "judge", "baseline_judge", "candidate_judge"):
                report = result.get(report_key)
                if not isinstance(report, dict) or not report.get("report_path"):
                    continue
                source = Path(report["report_path"])
                if not source.is_dir():
                    continue
                relative_destination = Path("qc") / pxd / report_key
                destination = output_data_dir / relative_destination
                for artifact in sorted(source.rglob("*")):
                    if not artifact.is_file() or artifact.suffix.lower() not in SUPPORTED_SUFFIXES:
                        continue
                    if artifact.stat().st_size > MAX_PUBLISHED_FILE_BYTES:
                        continue
                    copy_file(artifact, destination / artifact.relative_to(source))
                report["public_report_path"] = relative_destination.as_posix()

    (output_data_dir / "qc-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=Path("store"))
    parser.add_argument("--site-dir", type=Path, default=Path("docs/store-explorer"))
    parser.add_argument("--pxd", action="append", default=[], help="Build only one PXD; repeatable")
    parser.add_argument("--pxd-file", type=Path, help="Build the PXDs listed in a one-column CSV file")
    parser.add_argument(
        "--qc-summary",
        type=Path,
        help="Reviewed qc-summary.json to publish with its report files",
    )
    args = parser.parse_args()

    output_data_dir = args.site_dir / "data"
    shutil.rmtree(output_data_dir, ignore_errors=True)
    output_data_dir.mkdir(parents=True)

    requested_pxds = [*args.pxd, *(read_pxd_file(args.pxd_file) if args.pxd_file else [])]
    active_versions = active_release_versions(args.store)
    records = [
        build_record(args.store, output_data_dir, pxd, active_versions)
        for pxd in collect_pxds(args.store, requested_pxds, active_versions)
    ]
    records = [record for record in records if record["available"]]
    (output_data_dir / "store-index.json").write_text(
        json.dumps({"pxds": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_data_dir / "site-summary.json").write_text(
        json.dumps(build_site_summary(records, output_data_dir, args.store), indent=2) + "\n",
        encoding="utf-8",
    )
    (output_data_dir / "version-history.json").write_text(
        json.dumps({"notes": load_version_history()}, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.qc_summary:
        publish_qc_summary(args.qc_summary, output_data_dir)
    print(f"Built Store Explorer data for {len(records)} PXDs in {output_data_dir}")


if __name__ == "__main__":
    main()