"""Run the combined standalone fetch/assessment stage with HAMLET checkpoints."""

import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import stage_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submodule_dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--base_dir", required=True)
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--central_dir", required=True)
    parser.add_argument("--pxd", required=True)
    parser.add_argument("--max_raw_files", type=int, default=0)
    parser.add_argument("--cores", type=int, required=True)
    args, fetch_options = parser.parse_known_args()
    common = [
        "--manifest", args.manifest, "--base_dir", args.base_dir,
        "--outdir", args.outdir, "--central_dir", args.central_dir,
        "--max_raw_files", str(args.max_raw_files), "--pxd", args.pxd,
    ]
    manifest_script = str(Path(stage_manifest.__file__).resolve())

    def checkpoint(command, stage):
        result = subprocess.run(
            [sys.executable, manifest_script, command, *common, "--stage", stage],
            check=False,
        )
        if result.returncode not in (0, 3):
            raise RuntimeError(f"{command} {stage} failed: exit {result.returncode}")
        return result.returncode

    fetch_rc = checkpoint("prepare", "fetch")
    fetched = Path(args.central_dir) / args.pxd
    if fetch_rc == 0 and not Path(args.pxd).exists():
        print(f"WARNING: Fetch disabled without reusable inputs for {args.pxd}", file=sys.stderr)
        return 42
    assessor_rc = checkpoint("prepare", "run_assessor")
    script = Path(args.submodule_dir) / "src" / "FetchPXD.py"
    if fetch_rc == 3:
        command = [
            sys.executable, str(script), "--PXD", args.pxd,
            "--central_mzml_dir", args.central_dir,
            "--assessor_threads", str(args.cores), "--log_file", "fetch/events.jsonl",
            *fetch_options,
        ]
        if args.max_raw_files:
            command += ["--max_raw_files", str(args.max_raw_files)]
        command += ["--force_run_assessor"] if assessor_rc == 3 else ["--skip_run_assessor"]
        result = subprocess.run(command, check=False)
        if result.returncode:
            return result.returncode
        checkpoint("mark-complete", "fetch")
    elif assessor_rc == 3:
        sys.path.insert(0, str(script.parent))
        spec = importlib.util.spec_from_file_location("standalone_fetch", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.run_runAssessor(
            output_dir=str(fetched), central_mzml_dir=args.central_dir,
            pxd=args.pxd, force=True, n_threads=args.cores,
        )
    if assessor_rc == 3:
        checkpoint("mark-complete", "run_assessor")
    metadata = Path("runAssessor/study_metadata.json") if assessor_rc == 0 else fetched / "runAssessor/study_metadata.json"
    if not metadata.is_file():
        raise FileNotFoundError(metadata)
    shutil.copy2(metadata, "study_metadata.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
