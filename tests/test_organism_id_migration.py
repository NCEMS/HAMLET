import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/python"))

import determine_acquisition_params as detection
import organism_fingerprint
import run_submodule_fetch
import stage_manifest
import install_organism_id

SPEC = importlib.util.spec_from_file_location(
    "standalone_organism", ROOT / "submodules/MassSpecOrganismID/src/OrganismID.py")
STANDALONE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STANDALONE)


class MigrationTests(unittest.TestCase):
    def test_reused_results_survive_overwriting_publish_destination(self):
        for stage, name in [("organism_id", "organism_results"), ("search", "search")]:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                canonical = root / "results/PXD000001" / name
                canonical.mkdir(parents=True)
                (canonical / "result.csv").write_text("preserved")
                work = root / "work"
                work.mkdir()
                previous = Path.cwd()
                try:
                    os.chdir(work)
                    args = SimpleNamespace(pxd="PXD000001", stage=stage,
                                           outdir=str(root / "results"), central_dir="spectral")
                    # A retry may leave the old symlink-based materialization behind.
                    Path(name).symlink_to(canonical, target_is_directory=True)
                    stage_manifest._prepare_materialize(args, complete=True, availability=True)
                    self.assertFalse(Path(name).is_symlink())
                    shutil.rmtree(canonical)
                    shutil.copytree(name, canonical)
                    self.assertEqual((canonical / "result.csv").read_text(), "preserved")
                finally:
                    os.chdir(previous)

    @unittest.skipUnless(shutil.which("nextflow"), "Nextflow is required for manifest wiring regression")
    def test_nextflow_manifest_resolution_with_null_config_defaults(self):
        source = (ROOT / "main.nf").read_text()
        resolver = "String resolveStageManifest" + source.split(
            "String resolveStageManifest", 1)[1].split("List<String> buildPxdList", 1)[0]
        self.assertNotIn("${params.stage_manifest}", source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "manifest_test.nf"
            script.write_text('nextflow.enable.dsl = 2\n' + resolver + '''
assert resolveStageManifest([outdir: '/tmp/results'], baseDir) == '/tmp/results/pipeline_stage_manifest.json'
assert resolveStageManifest([outdir: '/tmp/results', update_from_existing: true], baseDir) == '/tmp/results/update_stage_manifest.json'
assert resolveStageManifest([outdir: '/tmp/results', stage_manifest: '/tmp/full.json'], baseDir) == '/tmp/full.json'
assert resolveStageManifest([outdir: '/tmp/results', update_from_existing: true, stage_manifest: '/tmp/full.json', update_stage_manifest: '/tmp/update.json'], baseDir) == '/tmp/update.json'
assert resolveStageManifest([outdir: 'relative'], baseDir) == new File(baseDir.toString(), 'relative/pipeline_stage_manifest.json').canonicalPath
assert stageManifestPath == params.update_stage_manifest.toString()

process verify_manifest {
    cpus 1
    memory '32 MB'
    output:
    path 'verified.txt'
    script:
    """
    test '${stageManifestPath}' = '${params.update_stage_manifest}'
    printf '%s' '${stageManifestPath}' > verified.txt
    """
}

workflow {
    verify_manifest()
}
''')
            result = subprocess.run(
                ["nextflow", "-log", str(root / "nextflow.log"), "run", str(script),
                 "-c", str(ROOT / "nextflow.config"), "-w", str(root / "work"),
                 "--outdir", str(root / "results"), "--update_from_existing", "true",
                 "--update_stage_manifest", str(root / "custom.json")],
                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=120,
                env={**os.environ, "NXF_OFFLINE": "true", "NXF_ANSI_LOG": "false"})
            self.assertEqual(result.returncode, 0, result.stdout)
            outputs = list((root / "work").glob("*/*/verified.txt"))
            self.assertEqual(len(outputs), 1, result.stdout)
            self.assertEqual(outputs[0].read_text(), str(root / "custom.json"))

    def test_explicit_acquisition_overrides_directory_and_parses_false(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            default = root / "detected_params.json"
            explicit = root / "explicit.json"
            default.write_text(json.dumps({"detected_params": {"DIA": True}}))
            explicit.write_text(json.dumps({"detected_params": {"DIA": "false"}}))
            self.assertFalse(STANDALONE.determine_use_cascadia(str(root), str(explicit)))
            explicit.write_text(json.dumps({"detected_params": {"DIA": "unknown"}}))
            with self.assertRaises(ValueError):
                STANDALONE.determine_use_cascadia(str(root), str(explicit))

    def test_force_cascadia_recreates_output_directory_and_uses_installed_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = root / "PXD000001"
            inputs.mkdir()
            (inputs / "sample.mzML").write_text("fixture")
            model = root / "model.ckpt"
            model.write_text("fixture")
            outputs = root / "organism"
            target = outputs / "CascadiaSequence/PXD000001_sample"
            target.mkdir(parents=True)
            (target / "PXD000001_sample.mztab").write_text("stale")

            def fake_predict(command, **kwargs):
                output_root = command[command.index("-o") + 1]
                Path(output_root + ".ssl").write_text("fixture")
                return SimpleNamespace(returncode=0)

            def fake_convert(source, destination):
                Path(destination).write_text("fresh")

            with patch.object(STANDALONE.subprocess, "run", side_effect=fake_predict) as run, \
                    patch.object(STANDALONE, "convert_ssl_to_mztab", side_effect=fake_convert):
                results = STANDALONE.run_de_novo_sequencing(
                    str(inputs), str(outputs), cascadia_model_path=str(model),
                    use_cascadia=True, force=True)
            self.assertEqual(len(results), 1)
            self.assertEqual(Path(results[0]).read_text(), "fresh")
            self.assertTrue(run.call_args.args[0][1].endswith("cascadia_wrapper.py"))

    def test_llm_detection_recomputes_fetch_json_and_override_is_local(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            central = root / "spectral"
            pxd = central / "PXD000001"
            pxd.mkdir(parents=True)
            cached = pxd / "detected_params.json"
            cached.write_text(json.dumps({"detected_params": {"DIA": False}}))
            llm = root / "llm"
            llm.mkdir()
            (llm / "PXD000001_Metadata.json").write_text(json.dumps({
                "sample.raw": {"Comment[AcquisitionMethod]": ["DIA"]},
            }))
            output = root / "output.json"
            argv = ["detect", "--input_dir", str(pxd), "--output", str(output),
                    "--central_mzml_dir", str(central), "--pxd", "PXD000001",
                    "--llm_results_dir", str(llm), "--force"]
            with patch.object(sys, "argv", argv):
                detection.main()
            self.assertTrue(json.loads(output.read_text())["detected_params"]["DIA"])
            self.assertEqual(json.loads(output.read_text())["detected_params"]["acquisition_source"],
                             "llm_metadata")
            preserved = cached.read_bytes()
            with patch.object(sys, "argv", argv + ["--acquisition_type", "DDA"]):
                detection.main()
            self.assertFalse(json.loads(output.read_text())["detected_params"]["DIA"])
            self.assertEqual(cached.read_bytes(), preserved)

    def test_disabled_organism_has_both_required_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            try:
                os.chdir(directory)
                args = SimpleNamespace(pxd="PXD000001", stage="organism_id",
                                       outdir="results", central_dir="spectral")
                stage_manifest._prepare_materialize(args, complete=False, availability=False)
                self.assertEqual(json.loads(Path("organism_status.json").read_text())["status"],
                                 "skipped")
                self.assertEqual(Path("organism_status.json").read_bytes(),
                                 Path("organism_results/organism_status.json").read_bytes())
            finally:
                os.chdir(previous)

    def test_status_fingerprint_and_no_result_completion(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = root / "PXD000001/organism_status.json"
            status.parent.mkdir()
            args = SimpleNamespace(outdir=str(root), organism_fingerprint="new")
            status.write_text(json.dumps({"status": "no_usable_results",
                                          "execution_fingerprint": "old"}))
            self.assertFalse(stage_manifest._stage_complete(
                root, root, "organism_id", [], "PXD000001", args))
            status.write_text(json.dumps({"status": "no_usable_results",
                                          "execution_fingerprint": "new"}))
            self.assertTrue(stage_manifest._stage_complete(
                root, root, "organism_id", [], "PXD000001", args))
            status.write_text(json.dumps({"status": "execution_failed",
                                          "execution_fingerprint": "new"}))
            self.assertFalse(stage_manifest._stage_complete(
                root, root, "organism_id", [], "PXD000001", args))

    def test_new_fingerprint_invalidates_downstream_before_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(
                manifest=str(root / "manifest.json"), base_dir=str(root),
                outdir=str(root / "results"), central_dir=str(root / "spectral"),
                pxd="PXD000001", stage="organism_id", max_raw_files=None,
                organism_fingerprint="new",
            )
            manifest = {"version": 1, "pxds": {}}
            stage_manifest._ensure_skeleton(manifest, args.pxd, args)
            for record in manifest["pxds"][args.pxd]["stages"].values():
                record["complete"] = True
            Path(args.manifest).write_text(json.dumps(manifest))
            previous = Path.cwd()
            try:
                os.chdir(root)
                Path("organism_status.json").write_text(json.dumps({
                    "status": "no_usable_results", "execution_fingerprint": "new",
                }))
                stage_manifest.cmd_mark_complete(args)
            finally:
                os.chdir(previous)
            stages = json.loads(Path(args.manifest).read_text())["pxds"][args.pxd]["stages"]
            self.assertTrue(stages["organism_id"]["complete"])
            self.assertEqual(stages["organism_id"]["execution_fingerprint"], "new")
            self.assertFalse(stages["search"]["complete"])
            self.assertIsNotNone(stages["search"]["force_rerun_after"])

    def test_fingerprint_ignores_task_path_but_detects_content_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a, b = root / "task1/input.json", root / "task2/input.json"
            a.parent.mkdir()
            b.parent.mkdir()
            a.write_text("{}")
            b.write_text("{}")
            submodule = ROOT / "submodules/MassSpecOrganismID"
            first = organism_fingerprint.fingerprint(submodule, [a], "settings")
            self.assertEqual(first, organism_fingerprint.fingerprint(submodule, [b], "settings"))
            b.write_text('{"changed":true}')
            self.assertNotEqual(first, organism_fingerprint.fingerprint(submodule, [b], "settings"))

    def test_combined_fetch_runs_submodule_with_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            root = Path(directory)
            central = root / "spectral"
            pxd = central / "PXD000001"
            (pxd / "runAssessor").mkdir(parents=True)
            (pxd / "runAssessor/study_metadata.json").write_text('{"files":{}}')
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                if "prepare" in command:
                    return SimpleNamespace(returncode=3)
                if command[1].endswith("FetchPXD.py"):
                    Path("PXD000001").symlink_to(pxd)
                return SimpleNamespace(returncode=0)

            argv = ["fetch", "--submodule_dir", str(ROOT / "submodules/MassSpecOrganismID"),
                    "--manifest", str(root / "manifest.json"), "--base_dir", str(ROOT),
                    "--outdir", str(root / "results"), "--central_dir", str(central),
                    "--pxd", "PXD000001", "--cores", "4", "--use_aria2c"]
            try:
                os.chdir(root)
                with patch.object(sys, "argv", argv), patch.object(
                        run_submodule_fetch.subprocess, "run", side_effect=fake_run):
                    self.assertEqual(run_submodule_fetch.main(), 0)
                command = next(command for command in calls if command[1].endswith("FetchPXD.py"))
                self.assertIn("--force_run_assessor", command)
                self.assertNotIn("--skip_run_assessor", command)
                self.assertIn("--use_aria2c", command)
                self.assertEqual(command[command.index("--assessor_threads") + 1], "4")
                self.assertTrue(Path("study_metadata.json").is_file())
            finally:
                os.chdir(previous)

    def test_installer_is_idempotent_and_protects_local_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / "submodules/peptonizer2000"
            checkout.parent.mkdir()
            source = ROOT / "submodules/MassSpecOrganismID/submodules/peptonizer2000"
            subprocess.run(["git", "clone", "--shared", "--quiet", str(source), str(checkout)],
                           check=True)
            shutil.copytree(ROOT / "submodules/MassSpecOrganismID/patches", root / "patches")
            real_run = subprocess.run
            pip_calls = []

            def fake_pip(command, **kwargs):
                if command[1:4] == ["-m", "pip", "install"]:
                    pip_calls.append(command)
                    return SimpleNamespace(returncode=0)
                return real_run(command, **kwargs)

            with patch.object(install_organism_id.subprocess, "run", side_effect=fake_pip):
                install_organism_id.install(root)
                install_organism_id.install(root)
                self.assertEqual(len(pip_calls), 2)
                target = checkout / "peptonizer/peptonizer/fetch_peptides_and_filter_taxa.py"
                target.write_text(target.read_text() + "\n# local work\n")
                before = target.read_bytes()
                with self.assertRaises(RuntimeError):
                    install_organism_id.install(root)
                self.assertEqual(target.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
