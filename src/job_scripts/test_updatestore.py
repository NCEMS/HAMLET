"""Focused tests for release-aware store promotion."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "job_scripts"))

from updatestore import promotion_plan, promote_record, release_annotation, write_release_manifest


class StorePromotionTest(unittest.TestCase):
    def _write_result(self, root, pxd="PXD123456"):
        result = root / "results" / pxd
        metadata = result / "agentic_metadata"
        judge = result / "judge_output"
        metadata.mkdir(parents=True)
        judge.mkdir()
        with (metadata / f"{pxd}.sdrf.tsv").open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(
                [
                    ["source name", "comment[data file]", "comment[sdrf annotation tool]"],
                    ["sample", "run.raw", "HAMLET-agentic v2.1.0"],
                ]
            )
        (metadata / f"{pxd}.confidence.sdrf.tsv").write_text("field\tvalue\n", encoding="utf-8")
        (judge / "llm_judge_per_paper.csv").write_text("paper_id,judge_accuracy\nPXD123456,1.0\n", encoding="utf-8")

    def test_promote_record_archives_and_stamps_active_sdrf(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()

            records = promotion_plan(root / "results", store, "v2.1.1")
            promoted = promote_record(records[0], store, release_annotation("v2.1.1"))
            write_release_manifest(store, root / "results", "v2.1.1", [promoted])

            active_sdrf = store / "hamlet_sdrfs" / "PXD123456.sdrf.tsv"
            archive_sdrf = store / "hamlet_sdrfs" / "v2.1.1" / "PXD123456.sdrf.tsv"
            self.assertIn("HAMLET-agentic v2.1.1", active_sdrf.read_text(encoding="utf-8"))
            self.assertEqual(active_sdrf.read_bytes(), archive_sdrf.read_bytes())
            self.assertTrue((store / "agentic_results_files" / "PXD123456" / "judge_output" / "llm_judge_per_paper.csv").is_file())
            self.assertTrue((store / "agentic_results_files" / "v2.1.1" / "PXD123456" / "judge_output" / "llm_judge_per_paper.csv").is_file())
            self.assertIn("v2.1.1", (store / "releases" / "active.json").read_text(encoding="utf-8"))
            manifest = (store / "releases" / "v2.1.1" / "manifest.json").read_text(encoding="utf-8")
            self.assertIn("hamlet_sdrfs/v2.1.1", manifest)
            self.assertTrue((store / "releases" / "v2.1.1" / "manifest.json").is_file())

    def test_existing_release_is_immutable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()
            (store / "releases" / "v2.1.1").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "already immutable"):
                promotion_plan(root / "results", store, "v2.1.1")


if __name__ == "__main__":
    unittest.main()