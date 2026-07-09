#!/usr/bin/env python3
import argparse
import fcntl
import glob
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List

STAGES = [
    "fetch",
    "run_assessor",
    "determine_acquisition_params",
    "organism_id",
    "determine_taxids",
    "search",
    "aggregate_results",
    "agentic_metadata_extraction",
    "llm_judge",
    "finalize_sdrf",
]


def _bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _default_availability(stage: str, args) -> bool:
    # Manifest-driven pipeline: new stages default to available.
    # User edits in pipeline_stage_manifest.json control run/skip behavior.
    return True


def _default_key_outputs(stage: str, pxd: str) -> List[str]:
    if stage == "fetch":
        return [f"spectral_files/{pxd}/*.mzML"]
    if stage == "run_assessor":
        return [f"spectral_files/{pxd}/runAssessor/study_metadata.json"]
    if stage == "determine_acquisition_params":
        return [f"spectral_files/{pxd}/detected_params.json"]
    if stage == "organism_id":
        return [
            f"results/{pxd}/organism_results/CasanovoSequence/**/peptonizer_result.csv",
            f"results/{pxd}/organism_results/CascadiaSequence/**/peptonizer_result.csv",
            f"results/{pxd}/organism_results/CasanovoSequence/{pxd}/Peptonizer2000_data/{pxd}_filtered70pct_slim/peptonizer_result.csv",
            f"results/{pxd}/organism_results/CascadiaSequence/{pxd}/Peptonizer2000_data/{pxd}_filtered70pct_slim/peptonizer_result.csv",
        ]
    if stage == "determine_taxids":
        return [
            f"results/{pxd}/taxid_mapping.json",
            f"results/{pxd}/taxid_warnings.json",
        ]
    if stage == "search":
        return [
            f"results/{pxd}/search/dda_search/search_results.tsv",
            f"results/{pxd}/search/dia_search/search_results.tsv",
        ]
    if stage == "aggregate_results":
        return [f"results/{pxd}/{pxd}_aggregated_results.json"]
    if stage == "agentic_metadata_extraction":
        return [
            f"results/{pxd}/agentic_metadata/metadata_extraction_output/integrated_output/TechnicalAgent/temp_0.0/{pxd}_PubText_enriched.json",
            f"results/{pxd}/agentic_metadata/metadata_extraction_output/integrated_output/BiologicalAgent/temp_0.0/{pxd}_PubText_enriched.json",
            f"results/{pxd}/agentic_metadata/metadata_extraction_output/integrated_output/ExperimentalDesignAgent/temp_0.0/{pxd}_PubText_enriched.json",
        ]
    if stage == "llm_judge":
        return [
            f"results/{pxd}/judge_output/llm_judge_per_paper.csv",
            f"results/{pxd}/judge_output/judge_output/llm_judge_per_paper.csv",
        ]
    if stage == "finalize_sdrf":
        return [f"results/{pxd}/agentic_metadata/{pxd}.sdrf.tsv"]
    return []


def _expand(base_dir: Path, pattern: str) -> List[str]:
    return glob.glob(str(base_dir / pattern), recursive=True)


def _stage_complete(base_dir: Path, stage: str, key_outputs: List[str]) -> bool:
    if stage in {"fetch", "organism_id", "search", "llm_judge"}:
        # Any valid output is enough for these stage families.
        return any(_expand(base_dir, p) for p in key_outputs)
    return all(_expand(base_dir, p) for p in key_outputs)


def _load_manifest(path: Path) -> Dict:
    if not path.exists():
        return {"version": 1, "pxds": {}}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write(path: Path, data: Dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(path.parent), encoding="utf-8") as tf:
        json.dump(data, tf, indent=2)
        tmp = tf.name
    os.replace(tmp, path)


def _with_lock(manifest_path: Path):
    lock_path = manifest_path.with_suffix(manifest_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("w", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    return fh


def _with_shared_lock(manifest_path: Path):
    """Shared (read) lock — multiple holders allowed concurrently."""
    lock_path = manifest_path.with_suffix(manifest_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a", encoding="utf-8")
    fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
    return fh


def _ensure_skeleton(manifest: Dict, pxd: str, args):
    pxds = manifest.setdefault("pxds", {})
    rec = pxds.setdefault(pxd, {})
    stages = rec.setdefault("stages", {})
    for s in STAGES:
        st = stages.setdefault(s, {})
        st.setdefault("availability", _default_availability(s, args))
        st.setdefault("complete", False)
        st.setdefault("key_outputs", _default_key_outputs(s, pxd))

        # Migrate legacy checkpoint patterns written by earlier manifest versions.
        if s == "agentic_metadata_extraction":
            legacy_prefix = f"results/{pxd}/agentic_metadata/integrated_output/"
            keys = st.get("key_outputs", [])
            if isinstance(keys, list) and any(isinstance(k, str) and k.startswith(legacy_prefix) for k in keys):
                st["key_outputs"] = _default_key_outputs(s, pxd)
        elif s == "organism_id":
            keys = st.get("key_outputs", [])
            if not isinstance(keys, list):
                st["key_outputs"] = _default_key_outputs(s, pxd)
            else:
                desired = _default_key_outputs(s, pxd)
                # Keep any custom patterns but ensure canonical defaults are present.
                seen = {k for k in keys if isinstance(k, str)}
                for k in desired:
                    if k not in seen:
                        keys.append(k)
                st["key_outputs"] = keys
        elif s == "llm_judge":
            keys = st.get("key_outputs", [])
            if not isinstance(keys, list):
                st["key_outputs"] = _default_key_outputs(s, pxd)
            else:
                desired = _default_key_outputs(s, pxd)
                seen = {k for k in keys if isinstance(k, str)}
                for k in desired:
                    if k not in seen:
                        keys.append(k)
                st["key_outputs"] = keys


def cmd_init(args):
    manifest_path = Path(args.manifest)
    base_dir = Path(args.base_dir)
    lock_fh = _with_lock(manifest_path)
    try:
        manifest = _load_manifest(manifest_path)
        pxds = [p.strip() for p in args.pxds.split(",") if p.strip()]
        for pxd in pxds:
            _ensure_skeleton(manifest, pxd, args)
            for s in STAGES:
                st = manifest["pxds"][pxd]["stages"][s]
                st["complete"] = _stage_complete(base_dir, s, st["key_outputs"])
        _atomic_write(manifest_path, manifest)
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()
    print(f"Initialized/reconciled manifest: {manifest_path}")


def _prepare_materialize(args, complete: bool, availability: bool):
    pxd = args.pxd
    stage = args.stage
    outdir = Path(args.outdir)
    central = Path(args.central_dir)

    # Disabled but incomplete: emit placeholders where needed so pipeline can continue.
    if not availability and not complete:
        if stage == "organism_id":
            os.makedirs("organism_results", exist_ok=True)
            Path("organism_results/empty.json").write_text("{}\n", encoding="utf-8")
        elif stage == "determine_taxids":
            Path("taxid_mapping.json").write_text('{"mappings": {}}\n', encoding="utf-8")
            Path("taxid_warnings.json").write_text('{"warnings": []}\n', encoding="utf-8")
        elif stage == "run_assessor":
            os.makedirs("runAssessor", exist_ok=True)
            Path("runAssessor/study_metadata.json").write_text('{"files": {}, "problems": {"errors": {"count": 0, "list": [], "codes": {}}, "warnings": {"count": 0, "list": [], "codes": {}}}, "state": {"status": "WARNING", "code": "SkippedByManifest", "message": "Stage disabled by manifest"}}\n', encoding="utf-8")
        elif stage == "search":
            os.makedirs("search", exist_ok=True)
            Path("search/skipped.txt").write_text("Stage disabled by manifest\n", encoding="utf-8")
        elif stage == "llm_judge":
            os.makedirs("judge_stage_output", exist_ok=True)
            Path("judge_stage_output/skipped.json").write_text('{"skipped": true, "reason": "disabled by manifest"}\n', encoding="utf-8")
        elif stage == "finalize_sdrf":
            os.makedirs("finalize_stage_output", exist_ok=True)
        return

    # Reuse completed stage outputs by linking/copying into task workdir expected outputs.
    if complete:
        if stage == "fetch":
            target = central / pxd
            if os.path.islink(pxd) or os.path.exists(pxd):
                if os.path.islink(pxd):
                    os.unlink(pxd)
            os.symlink(str(target), pxd)
        elif stage == "run_assessor":
            src = central / pxd / "runAssessor" / "study_metadata.json"
            os.makedirs("runAssessor", exist_ok=True)
            if src.exists():
                Path("runAssessor/study_metadata.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        elif stage == "determine_acquisition_params":
            src = central / pxd / "detected_params.json"
            Path("detected_params.json").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        elif stage == "organism_id":
            src = outdir / pxd / "organism_results"
            if os.path.islink("organism_results"):
                os.unlink("organism_results")
            elif os.path.isdir("organism_results"):
                pass
            os.symlink(str(src), "organism_results")
        elif stage == "determine_taxids":
            Path("taxid_mapping.json").write_text((outdir / pxd / "taxid_mapping.json").read_text(encoding="utf-8"), encoding="utf-8")
            Path("taxid_warnings.json").write_text((outdir / pxd / "taxid_warnings.json").read_text(encoding="utf-8"), encoding="utf-8")
        elif stage == "search":
            src = outdir / pxd / "search"
            if os.path.islink("search"):
                os.unlink("search")
            os.symlink(str(src), "search")
        elif stage == "aggregate_results":
            for name in [f"{pxd}_aggregated_results.json", f"{pxd}_pipeline.json", f"{pxd}_pipeline_summary.md"]:
                src = outdir / pxd / name
                if src.exists():
                    Path(name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        elif stage == "agentic_metadata_extraction":
            src = outdir / pxd / "agentic_metadata" / "metadata_extraction_output"
            if os.path.islink("agentic_stage_output") or os.path.isfile("agentic_stage_output"):
                os.unlink("agentic_stage_output")
            elif os.path.isdir("agentic_stage_output"):
                shutil.rmtree("agentic_stage_output")
            if src.exists():
                shutil.copytree(src, "agentic_stage_output", dirs_exist_ok=True)
            else:
                os.makedirs("agentic_stage_output", exist_ok=True)
        elif stage == "llm_judge":
            src = outdir / pxd / "judge_output"
            if os.path.islink("judge_stage_output") or os.path.isfile("judge_stage_output"):
                os.unlink("judge_stage_output")
            elif os.path.isdir("judge_stage_output"):
                shutil.rmtree("judge_stage_output")
            if src.exists():
                shutil.copytree(src, "judge_stage_output", dirs_exist_ok=True)
            else:
                os.makedirs("judge_stage_output", exist_ok=True)
        elif stage == "finalize_sdrf":
            src = outdir / pxd / "agentic_metadata" / "metadata_extraction_output"
            sdrf = outdir / pxd / "agentic_metadata" / f"{pxd}.sdrf.tsv"

            if os.path.islink("agentic_stage_output") or os.path.isfile("agentic_stage_output"):
                os.unlink("agentic_stage_output")
            elif os.path.isdir("agentic_stage_output"):
                shutil.rmtree("agentic_stage_output")
            if src.exists():
                shutil.copytree(src, "agentic_stage_output", dirs_exist_ok=True)
            else:
                os.makedirs("agentic_stage_output", exist_ok=True)

            if os.path.islink("finalize_stage_output") or os.path.isfile("finalize_stage_output"):
                os.unlink("finalize_stage_output")
            elif os.path.isdir("finalize_stage_output"):
                shutil.rmtree("finalize_stage_output")
            os.makedirs("finalize_stage_output", exist_ok=True)

            if sdrf.exists():
                shutil.copy2(sdrf, f"finalize_stage_output/{pxd}.sdrf.tsv")
                shutil.copy2(sdrf, f"{pxd}.sdrf.tsv")


def cmd_prepare(args):
    manifest_path = Path(args.manifest)
    base_dir = Path(args.base_dir)

    # Use a shared (read) lock so hundreds of concurrent prepares don't
    # serialize on a single exclusive lock.  We only read the manifest here;
    # mark-complete is the authoritative writer.
    lock_fh = _with_shared_lock(manifest_path)
    try:
        manifest = _load_manifest(manifest_path)
        # _ensure_skeleton may need to add new PXD entries; if the PXD is
        # genuinely new we fall back to an exclusive lock.
        pxd_exists = args.pxd in manifest.get("pxds", {})
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()

    if not pxd_exists:
        # New PXD: need to write skeleton under exclusive lock.
        lock_fh = _with_lock(manifest_path)
        try:
            manifest = _load_manifest(manifest_path)
            _ensure_skeleton(manifest, args.pxd, args)
            _atomic_write(manifest_path, manifest)
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            lock_fh.close()
        # Re-read after write.
        lock_fh = _with_shared_lock(manifest_path)
        try:
            manifest = _load_manifest(manifest_path)
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
            lock_fh.close()

    stage_rec = manifest["pxds"][args.pxd]["stages"].get(args.stage, {})

    availability = bool(stage_rec.get("availability", True))
    complete = bool(stage_rec.get("complete", False))

    # Honor explicit manifest completion for organism_id.
    if not (args.stage == "organism_id" and availability and complete):
        complete = _stage_complete(base_dir, args.stage, stage_rec.get("key_outputs", []))
    # Note: we intentionally do NOT write complete back to the manifest here.
    # mark-complete is the authoritative update path.  This removes the
    # LOCK_EX serialisation bottleneck when hundreds of tasks run concurrently.

    if complete or not availability:
        _prepare_materialize(args, complete=complete, availability=availability)
        print(f"Manifest skip for {args.pxd}:{args.stage} (availability={availability}, complete={complete})")
        return 0

    print(f"Manifest run for {args.pxd}:{args.stage}")
    return 3


def cmd_mark_complete(args):
    manifest_path = Path(args.manifest)
    base_dir = Path(args.base_dir)

    lock_fh = _with_lock(manifest_path)
    try:
        manifest = _load_manifest(manifest_path)
        _ensure_skeleton(manifest, args.pxd, args)
        stage_rec = manifest["pxds"][args.pxd]["stages"][args.stage]
        stage_rec["complete"] = _stage_complete(base_dir, args.stage, stage_rec.get("key_outputs", []))
        _atomic_write(manifest_path, manifest)
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()
    print(f"Manifest updated for {args.pxd}:{args.stage}")


def build_parser():
    p = argparse.ArgumentParser(description="HAMLET stage manifest utility")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--manifest", required=True)
        sp.add_argument("--base_dir", required=True)
        sp.add_argument("--outdir", required=True)
        sp.add_argument("--central_dir", required=True)

    p_init = sub.add_parser("init")
    add_common(p_init)
    p_init.add_argument("--pxds", required=True, help="Comma-separated PXDs")

    p_prepare = sub.add_parser("prepare")
    add_common(p_prepare)
    p_prepare.add_argument("--pxd", required=True)
    p_prepare.add_argument("--stage", required=True, choices=STAGES)

    p_mark = sub.add_parser("mark-complete")
    add_common(p_mark)
    p_mark.add_argument("--pxd", required=True)
    p_mark.add_argument("--stage", required=True, choices=STAGES)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "init":
        cmd_init(args)
        return 0
    if args.cmd == "prepare":
        return cmd_prepare(args)
    if args.cmd == "mark-complete":
        cmd_mark_complete(args)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
