#!/usr/bin/env python3

import argparse
import csv
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Optional, Sequence, Tuple


PXD_RE = re.compile(r"PXD\d+")


def _guess_repo_root(start: Optional[Path] = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "main.nf").exists() and (parent / "work").exists():
            return parent
    return Path.cwd().resolve()


def _extract_process_names(main_nf: Path) -> List[str]:
    text = main_nf.read_text(errors="ignore")
    procs = re.findall(r"(?m)^\s*process\s+([A-Za-z0-9_]+)\s*\{", text)
    # Preserve first-seen order, but de-dup
    seen = set()
    ordered = []
    for p in procs:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


# Nextflow log line example:
# Feb-28 00:42:55.063 [Task submitter] INFO  nextflow.Session - [9c/8ce128] Submitted process > llm_extraction (llm-PXD003539)
_NXF_TASK_RE = re.compile(
    r"\[(?P<prefix>[0-9a-f]{2})/(?P<short>[0-9a-f]{6})\]\s+"
    r"(?:(?:Submitted|Cached|Reusing cached)\s+process\s+>\s+)"
    r"(?P<proc>[A-Za-z0-9_]+)\s+\((?P<tag>[^)]+)\)"
)


def _parse_nextflow_log(nextflow_log: Path) -> DefaultDict[str, DefaultDict[str, List[Tuple[str, str, str]]]]:
    """Return mapping: pxd -> process -> list[(prefix, short_hash, tag)]."""
    mapping: DefaultDict[str, DefaultDict[str, List[Tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(list))

    if not nextflow_log.exists():
        return mapping

    with nextflow_log.open("r", errors="ignore") as f:
        for line in f:
            m = _NXF_TASK_RE.search(line)
            if not m:
                continue
            tag = m.group("tag")
            pxd_m = PXD_RE.search(tag)
            if not pxd_m:
                continue
            pxd = pxd_m.group(0)
            proc = m.group("proc")
            mapping[pxd][proc].append((m.group("prefix"), m.group("short"), tag))

    return mapping


def _resolve_work_dirs(work_root: Path, prefix: str, short_hash: str) -> List[Path]:
    # Nextflow prints a shortened hash (first 6 chars). Actual directory is longer.
    prefix_dir = work_root / prefix
    if not prefix_dir.exists():
        return []

    candidates = sorted(prefix_dir.glob(short_hash + "*"))
    return [c for c in candidates if c.is_dir()]


def _task_exitcode(work_dir: Path) -> Optional[int]:
    exitcode_path = work_dir / ".exitcode"
    if not exitcode_path.exists():
        return None
    try:
        raw = exitcode_path.read_text(errors="ignore").strip()
        if raw == "":
            return None
        return int(raw)
    except Exception:
        return None


def _list_spectral_files(downloads_root: Path, pxd: str) -> List[str]:
    """Return basenames of .raw/.wiff files under downloads_root/pxd (recursive)."""
    start = downloads_root / pxd
    if not start.exists():
        return []

    out: List[str] = []
    for root, _dirs, files in os.walk(start):
        for name in files:
            lower = name.lower()
            if lower.endswith(".raw") or lower.endswith(".wiff"):
                out.append(name)
    out.sort()
    return out


def _discover_pxds(results_dir: Path, nextflow_log_map: Dict[str, Dict[str, object]]) -> List[str]:
    pxds = set()

    if results_dir.exists():
        for child in results_dir.iterdir():
            if child.is_dir() and PXD_RE.fullmatch(child.name):
                pxds.add(child.name)

    # Fallback to whatever was seen in the Nextflow log
    pxds.update(nextflow_log_map.keys())

    return sorted(pxds)


def _to_rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except Exception:
        return str(path)


def build_rows(
    repo_root: Path,
    pxds: Sequence[str],
    processes: Sequence[str],
    nxf_map: DefaultDict[str, DefaultDict[str, List[Tuple[str, str, str]]]],
    work_root: Path,
    downloads_root: Path,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []

    for pxd in pxds:
        spectral_files = _list_spectral_files(downloads_root, pxd)
        # Spec asks for "Sample File"; when multiple, store as ';'-joined.
        sample_field = ";".join(spectral_files)

        row: Dict[str, str] = {
            "PXD": pxd,
            "Sample File": sample_field,
        }

        for proc in processes:
            instances = nxf_map.get(pxd, {}).get(proc, [])

            resolved_dirs: List[Path] = []
            exitcodes: List[Optional[int]] = []

            for prefix, short, _tag in instances:
                dirs = _resolve_work_dirs(work_root, prefix, short)
                if not dirs:
                    continue
                for d in dirs:
                    resolved_dirs.append(d)
                    exitcodes.append(_task_exitcode(d))

            # Determine completion:
            # - If we have at least one resolved workdir and any exitcode==0 => completed
            # - If all exitcodes are present and all == 0 => completed
            completed = "False"
            if resolved_dirs:
                if any(ec == 0 for ec in exitcodes if ec is not None):
                    completed = "True"
                else:
                    # if no exitcode files but dirs exist, treat as not completed
                    completed = "False"
            else:
                completed = "False"

            workdirs_str = ";".join(_to_rel(d, repo_root) for d in sorted(set(resolved_dirs)))

            row[f"{proc}_completed"] = completed
            row[f"{proc}_workdir"] = workdirs_str

        rows.append(row)

    return rows


def write_csv(out_csv: Path, rows: Sequence[Dict[str, str]], fieldnames: Sequence[str]) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def main() -> None:
    repo_root = _guess_repo_root()

    parser = argparse.ArgumentParser(
        description=(
            "Summarize pipeline results into a CSV (per PXD: sample files, per-process completion, work hash dirs)."
        )
    )
    parser.add_argument(
        "--repo_root",
        default=str(repo_root),
        help="Repo root (defaults to auto-detected root containing main.nf and work/).",
    )
    parser.add_argument(
        "--results_dir",
        default="results",
        help="Results directory containing PXD* folders (default: results).",
    )
    parser.add_argument(
        "--work_dir",
        default="work",
        help="Nextflow work directory (default: work).",
    )
    parser.add_argument(
        "--downloads_dir",
        default="work/downloads",
        help="Where fetch_pxd stores downloaded spectral files (default: work/downloads).",
    )
    parser.add_argument(
        "--nextflow_log",
        default=".nextflow.log",
        help="Nextflow log path used to map process -> work hash (default: .nextflow.log).",
    )
    parser.add_argument(
        "--main_nf",
        default="main.nf",
        help="Nextflow script to parse for process names (default: main.nf).",
    )
    parser.add_argument(
        "--out_csv",
        default="ResultsSummary.csv",
        help="Output CSV path (default: ResultsSummary.csv).",
    )
    parser.add_argument(
        "--pxd",
        nargs="*",
        default=None,
        help="Optional list of PXDs to include (default: auto-discover).",
    )

    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    results_dir = (repo_root / args.results_dir).resolve()
    work_root = (repo_root / args.work_dir).resolve()
    downloads_root = (repo_root / args.downloads_dir).resolve()
    nextflow_log = (repo_root / args.nextflow_log).resolve()
    main_nf = (repo_root / args.main_nf).resolve()
    out_csv = Path(args.out_csv)
    # Don't resolve relative paths - they will use the current working directory
    # (which is the Nextflow task work dir when called from a process)

    if not main_nf.exists():
        raise SystemExit(f"ERROR: main.nf not found at: {main_nf}")

    processes = _extract_process_names(main_nf)
    nxf_map = _parse_nextflow_log(nextflow_log)

    if args.pxd and len(args.pxd) > 0:
        pxds = sorted(args.pxd)
    else:
        pxds = _discover_pxds(results_dir, nxf_map)

    if not pxds:
        raise SystemExit("ERROR: No PXDs found (no results/PXD* dirs and none parsed from .nextflow.log)")

    rows = build_rows(
        repo_root=repo_root,
        pxds=pxds,
        processes=processes,
        nxf_map=nxf_map,
        work_root=work_root,
        downloads_root=downloads_root,
    )

    fieldnames: List[str] = ["PXD", "Sample File"]
    for proc in processes:
        fieldnames.append(f"{proc}_completed")
        fieldnames.append(f"{proc}_workdir")

    write_csv(out_csv, rows, fieldnames)

    print(f"Wrote: {out_csv}")
    print(f"PXDs: {len(pxds)}")
    print(f"Processes: {len(processes)} ({', '.join(processes)})")


if __name__ == "__main__":
    main()
