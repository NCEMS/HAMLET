import csv
import contextlib
import io
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generator", ROOT / "src/job_scripts/gen_slurm_per_pxd.py")
GEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GEN)


class GeneratorTests(unittest.TestCase):
    def test_both_modes_generate_valid_shell_without_submission(self):
        for mode in ("full", "organism"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                prior = root / "old/results/PXD000001"
                for name in ("search", "llm_results", "runAssessor"):
                    (prior / name).mkdir(parents=True)
                for name in ("taxid_warnings.json", "runAssessor/study_metadata.json"):
                    (prior / name).write_text("{}")
                source = root / "pxds.csv"
                with source.open("w", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["accession", "aggregated_results_json_path"])
                    writer.writerow(["PXD000001", str(prior / "agentic_metadata/metadata_extraction_output/PXD000001_aggregated_results.json")])
                    writer.writerow(["PXD000001", "duplicate"])
                template = root / "template.slurm"
                template.write_text((ROOT / f"assets/templates/HAMLETGPU{mode}.slurm").read_text().replace(
                    "/storage/group/epo2/default/ims86/git_repos/HAMLET/HAMLETruns", str(root / "runs")))
                files = GEN.generate_slurm_files(template, source, root / "scripts")
                self.assertEqual(len(files), 1)
                content = files[0].read_text()
                self.assertNotIn("PXD######", content)
                self.assertNotIn("__EXISTING_RESULTS__", content)
                self.assertIn("--mode " + ("'organism only'" if mode == "organism" else "full"), content)
                self.assertNotIn("--run_search", content)
                if mode == "organism":
                    self.assertIn(str(prior.parent), content)
                subprocess.run(["bash", "-n", str(files[0])], check=True)
                self.assertTrue(any((root / "runs").iterdir()))
                with self.assertRaises(FileExistsError):
                    GEN.generate_slurm_files(template, source, root / "scripts")

    def test_archive_requires_restored_results(self):
        with self.assertRaisesRegex(ValueError, "archived"):
            GEN.existing_results_root({"accession": "PXD000001",
                                       "aggregated_results_json_path": "/archive.tar::member"})

    def test_explicit_restored_root_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "missing prior inputs"):
                GEN.existing_results_root({"accession": "PXD000001"}, directory)

    def test_aggregate_alone_is_sufficient(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / "PXD000001"
            prior.mkdir()
            aggregate = prior / "PXD000001_aggregated_results.json"
            aggregate.write_text(json.dumps({"pxd_id": "PXD000001", "search": {"preserved": True}}))
            self.assertEqual(GEN.existing_results_root({"accession": "PXD000001"}, root), root)
            aggregate.write_text('{"pxd_id":"PXD000002"}')
            with self.assertRaisesRegex(ValueError, "invalid prior aggregate"):
                GEN.existing_results_root({"accession": "PXD000001"}, root)

    def test_invalid_accession_rejected_before_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pxds.csv"
            source.write_text("accession\nnot-a-pxd\n")
            with self.assertRaisesRegex(ValueError, "Invalid PXD"):
                GEN.generate_slurm_files(ROOT / "assets/templates/HAMLETGPUfull.slurm",
                                         source, root / "scripts")
            self.assertFalse((root / "scripts").exists())

    def test_skip_unavailable_is_explicit_and_never_submits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "pxds.csv"
            source.write_text("accession,aggregated_results_json_path\nPXD000001,/archive.tar::member\n")
            template = ROOT / "assets/templates/HAMLETGPUorganism.slurm"
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors), self.assertRaisesRegex(ValueError, "No scripts"):
                GEN.generate_slurm_files(template, source, root / "scripts",
                                         skip_unavailable=True)
            self.assertIn("SKIPPED: PXD000001", errors.getvalue())
            self.assertFalse((root / "scripts").exists())


if __name__ == "__main__":
    unittest.main()
