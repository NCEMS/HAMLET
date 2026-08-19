#!/usr/bin/env python3
import argparse
import fcntl
import glob
import json
import os
import shutil
import tempfile
import time
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


def _default_key_outputs(stage: str, pxd: str, args=None) -> List[str]:
    central_root = Path(args.central_dir) if args else Path("spectral_files")
    output_root = Path(args.outdir) if args else Path("results")
    if stage == "fetch":
        return [str(central_root / pxd / "*.mzML")]
    if stage == "run_assessor":
        return [str(central_root / pxd / "runAssessor" / "study_metadata.json")]
    if stage == "determine_acquisition_params":
        return [str(central_root / pxd / "detected_params.json")]
    if stage == "organism_id":
        return [
            str(output_root / pxd / "organism_results" / "CasanovoSequence" / "**" / "peptonizer_result.csv"),
            str(output_root / pxd / "organism_results" / "CascadiaSequence" / "**" / "peptonizer_result.csv"),
            str(output_root / pxd / "organism_results" / "CasanovoSequence" / pxd / "Peptonizer2000_data" / f"{pxd}_filtered70pct_slim" / "peptonizer_result.csv"),
            str(output_root / pxd / "organism_results" / "CascadiaSequence" / pxd / "Peptonizer2000_data" / f"{pxd}_filtered70pct_slim" / "peptonizer_result.csv"),
        ]
    if stage == "determine_taxids":
        return [
            str(output_root / pxd / "taxid_mapping.json"),
            str(output_root / pxd / "taxid_warnings.json"),
        ]
    if stage == "search":
        return [
            str(output_root / pxd / "search" / "dda_search" / "search_results.tsv"),
            str(output_root / pxd / "search" / "dia_search" / "search_results.tsv"),
        ]
    if stage == "aggregate_results":
        return [str(output_root / pxd / f"{pxd}_aggregated_results.json")]
    if stage == "agentic_metadata_extraction":
        return [
            str(output_root / pxd / "agentic_metadata" / "metadata_extraction_output" / "integrated_output" / "TechnicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json"),
            str(output_root / pxd / "agentic_metadata" / "metadata_extraction_output" / "integrated_output" / "BiologicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json"),
            str(output_root / pxd / "agentic_metadata" / "metadata_extraction_output" / "integrated_output" / "ExperimentalDesignAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json"),
        ]
    if stage == "llm_judge":
        return [
            str(output_root / pxd / "judge_output" / "llm_judge_per_paper.csv"),
            str(output_root / pxd / "judge_output" / "judge_output" / "llm_judge_per_paper.csv"),
        ]
    if stage == "finalize_sdrf":
        return [str(output_root / pxd / "agentic_metadata" / f"{pxd}.sdrf.tsv")]
    return []


def _expand(base_dir: Path, pattern: str) -> List[str]:
    return glob.glob(str(base_dir / pattern), recursive=True)


def _run_assessor_complete(base_dir: Path, central_dir: Path, pxd: str, key_outputs: List[str]) -> bool:
    # Output file(s) must exist first.
    if not all(_expand(base_dir, p) for p in key_outputs):
        return False

    # If there are no mzML inputs for this PXD, an empty 'files' dict in the
    # output is legitimate (nothing to process) and the stage is complete.
    mzml_inputs = list((central_dir / pxd).glob("*.mzML")) + list((central_dir / pxd).glob("*.mzML.gz"))
    if not mzml_inputs:
        return True

    # Otherwise, guard against a crashed/killed run_assessor process leaving
    # behind an empty template (study.create() writes this before any per-file
    # results are populated; if the process dies before study.store() runs
    # with real data, the empty template is all that's left on disk). Treat
    # that as incomplete so the stage gets retried instead of being cached
    # forever as "done".
    for output_pattern in key_outputs:
        for path in _expand(base_dir, output_pattern):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, json.JSONDecodeError):
                return False
            if not data.get("files"):
                return False
    return True


def _stage_complete(base_dir: Path, central_dir: Path, stage: str, key_outputs: List[str], pxd: str = None) -> bool:
    if stage == "run_assessor" and pxd:
        return _run_assessor_complete(base_dir, central_dir, pxd, key_outputs)
    if stage in {"fetch", "organism_id", "search", "llm_judge"}:
        # Any valid output is enough for these stage families.
        return any(_expand(base_dir, p) for p in key_outputs)
    return all(_expand(base_dir, p) for p in key_outputs)


def _fresh_matches(base_dir: Path, pattern: str, since_ts: float) -> List[str]:
    return [p for p in _expand(base_dir, pattern) if os.path.getmtime(p) >= since_ts]


def _stage_complete_since(base_dir: Path, central_dir: Path, stage: str, key_outputs: List[str], since_ts: float, pxd: str = None) -> bool:
    """
    Same matching semantics as `_stage_complete`, but every matched file must
    also have been modified at/after `since_ts`. Used to verify a stage that
    had a forced rerun requested has actually produced *new* outputs, rather
    than trusting leftover files from before the rerun was requested.
    """
    if stage == "run_assessor" and pxd:
        if not _run_assessor_complete(base_dir, central_dir, pxd, key_outputs):
            return False
        return all(_fresh_matches(base_dir, p, since_ts) for p in key_outputs)
    if stage in {"fetch", "organism_id", "search", "llm_judge"}:
        return any(_fresh_matches(base_dir, p, since_ts) for p in key_outputs)
    return all(_fresh_matches(base_dir, p, since_ts) for p in key_outputs)


def _upstream_ok(stages: Dict, stage: str) -> bool:
    """
    True if every stage before `stage` (in STAGES order) is either
    unavailable (intentionally disabled) or complete.

    A stage can never be considered complete if an earlier, available
    stage for the same PXD hasn't finished -- e.g. llm_judge/finalize_sdrf
    must be treated as incomplete whenever agentic_metadata_extraction
    reruns or is otherwise not done, even if their own key_outputs happen
    to still exist on disk from a previous run.
    """
    idx = STAGES.index(stage)
    for s in STAGES[:idx]:
        st = stages.get(s, {})
        if bool(st.get("availability", True)) and not bool(st.get("complete", False)):
            return False
    return True


def _effective_complete(base_dir: Path, central_dir: Path, stage: str, stages: Dict, pxd: str) -> bool:
    """
    Resolve the real completion state for `stage`, layering on top of the
    raw file-based `_stage_complete` check:
      - A stage can't be complete if an earlier available stage isn't
        (dependency cascade).
      - If `force_rerun_after` (epoch timestamp) is set, the stage is only
        complete once its key_outputs exist *and* were (re)written at/after
        that timestamp. This self-heals automatically as soon as the forced
        rerun actually produces fresh outputs -- unlike a plain boolean
        flag, it doesn't get stuck if the completion check races Nextflow's
        publishDir (which copies task outputs to their canonical location
        only after the task process exits).
    """
    st = stages.get(stage, {})
    if not _upstream_ok(stages, stage):
        return False
    since_ts = st.get("force_rerun_after")
    if since_ts:
        return _stage_complete_since(base_dir, central_dir, stage, st.get("key_outputs", []), float(since_ts), pxd=pxd)
    return _stage_complete(base_dir, central_dir, stage, st.get("key_outputs", []), pxd=pxd)


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
        legacy_defaults = _default_key_outputs(s, pxd)
        configured_defaults = _default_key_outputs(s, pxd, args)
        st.setdefault("key_outputs", configured_defaults)
        if st.get("key_outputs") == legacy_defaults:
            st["key_outputs"] = configured_defaults
        st.setdefault("force_rerun_after", None)
        if getattr(args, "store_backed_agentic_only", False) and STAGES.index(s) < STAGES.index("agentic_metadata_extraction"):
            st["availability"] = False
        # Drop the older boolean force_rerun flag (superseded by the
        # timestamp-based force_rerun_after field, which self-heals instead
        # of getting permanently stuck if mark-complete's check raced
        # Nextflow's publishDir). Any PXD that still genuinely needs a
        # forced rerun should get a fresh `set-force-rerun` call.
        st.pop("force_rerun", None)

        # Migrate legacy checkpoint patterns written by earlier manifest versions.
        if s == "agentic_metadata_extraction":
            legacy_prefix = f"results/{pxd}/agentic_metadata/integrated_output/"
            keys = st.get("key_outputs", [])
            if isinstance(keys, list) and any(isinstance(k, str) and k.startswith(legacy_prefix) for k in keys):
                st["key_outputs"] = _default_key_outputs(s, pxd, args)
        elif s == "organism_id":
            keys = st.get("key_outputs", [])
            if not isinstance(keys, list):
                st["key_outputs"] = _default_key_outputs(s, pxd, args)
            else:
                desired = _default_key_outputs(s, pxd, args)
                # Keep any custom patterns but ensure canonical defaults are present.
                seen = {k for k in keys if isinstance(k, str)}
                for k in desired:
                    if k not in seen:
                        keys.append(k)
                st["key_outputs"] = keys
        elif s == "llm_judge":
            keys = st.get("key_outputs", [])
            if not isinstance(keys, list):
                st["key_outputs"] = _default_key_outputs(s, pxd, args)
            else:
                desired = _default_key_outputs(s, pxd, args)
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
            stages = manifest["pxds"][pxd]["stages"]
            # Iterate in pipeline order so each stage's cascade check sees
            # the already-recomputed complete value of every earlier stage.
            for s in STAGES:
                st = stages[s]
                st["complete"] = _effective_complete(base_dir, Path(args.central_dir), s, stages, pxd=pxd)
                if st["complete"] and st.get("force_rerun_after"):
                    # The forced rerun has produced verifiably fresh output;
                    # the flag has done its job and can be cleared.
                    st["force_rerun_after"] = None
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

    stages_for_pxd = manifest["pxds"][args.pxd]["stages"]
    stage_rec = stages_for_pxd.get(args.stage, {})

    availability = bool(stage_rec.get("availability", True))
    complete = bool(stage_rec.get("complete", False))
    force_since = stage_rec.get("force_rerun_after")
    upstream_ok = _upstream_ok(stages_for_pxd, args.stage)

    if not upstream_ok:
        # An incomplete upstream stage always wins: this stage must (re)run
        # regardless of its own leftover outputs.
        complete = False
    # Honor explicit manifest completion for organism_id (skip recheck),
    # unless a forced rerun is pending for it.
    elif args.stage == "organism_id" and availability and complete and not force_since:
        pass
    else:
        complete = _effective_complete(base_dir, Path(args.central_dir), args.stage, stages_for_pxd, pxd=args.pxd)
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
        stages_for_pxd = manifest["pxds"][args.pxd]["stages"]
        stage_rec = stages_for_pxd[args.stage]
        stage_rec["complete"] = _effective_complete(base_dir, Path(args.central_dir), args.stage, stages_for_pxd, pxd=args.pxd)
        # A stage that just genuinely completed (with fresh-enough output,
        # per _effective_complete) has consumed any pending force_rerun
        # request; clear it so future runs don't get stuck.
        if stage_rec["complete"]:
            stage_rec["force_rerun_after"] = None
        _atomic_write(manifest_path, manifest)
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()
    print(f"Manifest updated for {args.pxd}:{args.stage}")


def cmd_set_force_rerun(args):
    """
    Force one or more PXDs to redo a stage (and, via the dependency
    cascade, every stage after it) the next time the pipeline runs --
    even if that stage's own key_outputs still exist on disk from a
    previous run (e.g. a stale/pre-fix SDRF).
    """
    manifest_path = Path(args.manifest)
    base_dir = Path(args.base_dir)
    pxds = [p.strip() for p in args.pxds.split(",") if p.strip()]

    lock_fh = _with_lock(manifest_path)
    try:
        manifest = _load_manifest(manifest_path)
        for pxd in pxds:
            _ensure_skeleton(manifest, pxd, args)
            stages_for_pxd = manifest["pxds"][pxd]["stages"]
            stages_for_pxd[args.stage]["force_rerun_after"] = None if args.clear else time.time()
            # Recompute this PXD's whole stage chain so the cascade is
            # reflected immediately (not just at the next `init`).
            for s in STAGES:
                stages_for_pxd[s]["complete"] = _effective_complete(base_dir, Path(args.central_dir), s, stages_for_pxd, pxd=pxd)
                if stages_for_pxd[s]["complete"] and stages_for_pxd[s].get("force_rerun_after"):
                    stages_for_pxd[s]["force_rerun_after"] = None
        _atomic_write(manifest_path, manifest)
    finally:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()
    action = "Cleared" if args.clear else "Set"
    print(f"{action} force_rerun on stage '{args.stage}' for {len(pxds)} PXD(s): {', '.join(pxds)}")


def build_parser():
    p = argparse.ArgumentParser(description="HAMLET stage manifest utility")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument("--manifest", required=True)
        sp.add_argument("--base_dir", required=True)
        sp.add_argument("--outdir", required=True)
        sp.add_argument("--central_dir", required=True)
        sp.add_argument("--store_backed_agentic_only", action="store_true",
                        help="Disable upstream stages for store-backed agentic finalization")

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

    p_force = sub.add_parser("set-force-rerun")
    add_common(p_force)
    p_force.add_argument("--pxds", required=True, help="Comma-separated PXDs")
    p_force.add_argument("--stage", required=True, choices=STAGES)
    p_force.add_argument("--clear", action="store_true", help="Clear force_rerun instead of setting it")

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
    if args.cmd == "set-force-rerun":
        cmd_set_force_rerun(args)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
