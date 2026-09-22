"""Focused tests for release-aware store promotion."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "job_scripts"))

from updatestore import promotion_plan, promote_record, release_annotation, release_record, write_release_manifest


class StorePromotionTest(unittest.TestCase):
    def _write_result(self, root, pxd="PXD123456"):
        result = root / "results" / pxd
        metadata = result / "agentic_metadata"
        refinement_judge = result / "llm_refinement_judge"
        final_judge = result / "sdrf_judge"
        metadata.mkdir(parents=True)
        refinement_judge.mkdir()
        final_judge.mkdir()
        with (metadata / f"{pxd}.sdrf.tsv").open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(
                [
                    ["source name", "comment[data file]", "comment[sdrf annotation tool]"],
                    ["sample", "run.raw", "HAMLET-agentic v2.1.0"],
                ]
            )
        (metadata / f"{pxd}.confidence.sdrf.tsv").write_text("field\tvalue\n", encoding="utf-8")
        (refinement_judge / "llm_judge_per_paper.csv").write_text("paper_id,judge_accuracy\nPXD123456,0.5\n", encoding="utf-8")
        (final_judge / "llm_judge_per_paper.csv").write_text("paper_id,judge_accuracy\nPXD123456,1.0\n", encoding="utf-8")

    def test_promote_record_archives_and_stamps_versioned_sdrf(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()
            aggregates = store / "aggregated_results_files"
            canonical_aggregates = aggregates / "v2.0.0"
            canonical_aggregates.mkdir(parents=True)
            canonical_aggregate = canonical_aggregates / "PXD123456_aggregated_results.json"
            canonical_aggregate.write_text('{"pxd_id": "PXD123456"}\n', encoding="utf-8")
            (aggregates / canonical_aggregate.name).symlink_to(Path("v2.0.0") / canonical_aggregate.name)

            records, incomplete = promotion_plan(root / "results", store, "v2.1.1")
            self.assertEqual(incomplete, [])
            promoted = promote_record(records[0], store, release_annotation("v2.1.1"))
            write_release_manifest(store, root / "results", "v2.1.1", [promoted])

            archive_sdrf = store / "hamlet_sdrfs" / "v2.1.1" / "PXD123456.sdrf.tsv"
            self.assertIn("HAMLET-agentic v2.1.1", archive_sdrf.read_text(encoding="utf-8"))
            self.assertFalse((store / "hamlet_sdrfs" / "PXD123456.sdrf.tsv").exists())
            self.assertTrue((store / "agentic_results_files" / "v2.1.1" / "PXD123456" / "sdrf_judge" / "llm_judge_per_paper.csv").is_file())
            self.assertFalse((store / "agentic_results_files" / "PXD123456").exists())
            self.assertFalse((store / "aggregated_results_files" / "v2.1.1").exists())
            self.assertIn("v2.1.1", (store / "releases" / "active.json").read_text(encoding="utf-8"))
            manifest = (store / "releases" / "v2.1.1" / "manifest.json").read_text(encoding="utf-8")
            self.assertIn("hamlet_sdrfs/v2.1.1", manifest)
            self.assertIn("aggregated_results_files/v2.0.0/PXD123456_aggregated_results.json", manifest)
            self.assertTrue((store / "releases" / "v2.1.1" / "manifest.json").is_file())

    def test_existing_release_is_immutable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()
            aggregates = store / "aggregated_results_files"
            aggregates.mkdir()
            (aggregates / "PXD123456_aggregated_results.json").write_text('{"pxd_id": "PXD123456"}\n', encoding="utf-8")
            (store / "releases" / "v2.1.1").mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "already immutable"):
                promotion_plan(root / "results", store, "v2.1.1")

    def test_requires_flat_aggregate_source(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()
            (store / "aggregated_results_files").mkdir()

            with self.assertRaisesRegex(ValueError, "missing aggregate source"):
                promotion_plan(root / "results", store, "v2.2.1")

    def test_accepts_historical_result_without_judge_outputs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            result = root / "results" / "PXD123456"
            (result / "llm_refinement_judge" / "llm_judge_per_paper.csv").unlink()
            (result / "sdrf_judge" / "llm_judge_per_paper.csv").unlink()
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()
            aggregates = store / "aggregated_results_files"
            aggregates.mkdir()
            (aggregates / "PXD123456_aggregated_results.json").write_text('{"pxd_id": "PXD123456"}\n', encoding="utf-8")

            record = promotion_plan(root / "results", store, "v2.1.2")[0][0]
            promote_record(record, store, release_annotation("v2.1.2"))

            archive = store / "agentic_results_files" / "v2.1.2" / "PXD123456"
            self.assertFalse((archive / "llm_refinement_judge").exists())
            self.assertFalse((archive / "sdrf_judge").exists())

    def test_promotion_leaves_flat_agentic_compatibility_path_untouched(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            store = root / "store"
            agentic_root = store / "agentic_results_files"
            agentic_root.mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()
            aggregates = store / "aggregated_results_files"
            aggregates.mkdir()
            (aggregates / "PXD123456_aggregated_results.json").write_text('{"pxd_id": "PXD123456"}\n', encoding="utf-8")
            previous_agentic = root / "previous-agentic"
            previous_agentic.mkdir()
            (previous_agentic / "old.txt").write_text("old\n", encoding="utf-8")
            (agentic_root / "PXD123456").symlink_to(previous_agentic, target_is_directory=True)

            record = promotion_plan(root / "results", store, "v2.2.1")[0][0]
            promote_record(record, store, release_annotation("v2.2.1"))

            active = agentic_root / "PXD123456"
            self.assertTrue(active.is_symlink())
            self.assertTrue((active / "old.txt").is_file())
            self.assertTrue((agentic_root / "v2.2.1" / "PXD123456" / "PXD123456.sdrf.tsv").is_file())

    def test_in_progress_promotes_only_complete_bundles(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root, "PXD123456")
            self._write_result(root, "PXD654321")
            (root / "results" / "PXD654321" / "sdrf_judge" / "llm_judge_per_paper.csv").unlink()
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            (store / "hamlet_sdrfs").mkdir()
            aggregates = store / "aggregated_results_files"
            aggregates.mkdir()
            for pxd in ("PXD123456", "PXD654321"):
                (aggregates / f"{pxd}_aggregated_results.json").write_text('{"pxd_id": "' + pxd + '"}\n', encoding="utf-8")

            records, incomplete = promotion_plan(
                root / "results", store, "v2.2.5", allow_incomplete=True, require_final_judge=True
            )
            self.assertEqual([record["pxd"] for record in records], ["PXD123456"])
            self.assertEqual(incomplete, ["PXD654321"])
            promote_record(records[0], store, release_annotation("v2.2.5"))

            self.assertTrue((store / "hamlet_sdrfs" / "v2.2.5" / "PXD123456.sdrf.tsv").is_file())
            self.assertFalse((store / "hamlet_sdrfs" / "v2.2.5" / "PXD654321.sdrf.tsv").exists())
            (root / "results" / "PXD654321" / "sdrf_judge" / "llm_judge_per_paper.csv").write_text(
                "paper_id,judge_accuracy\nPXD654321,1.0\n", encoding="utf-8"
            )

            finalized, incomplete = promotion_plan(
                root / "results", store, "v2.2.5", allow_existing=True, require_final_judge=True
            )
            self.assertEqual(incomplete, [])
            self.assertTrue(finalized[0]["existing_snapshot"])
            self.assertEqual(release_record(finalized[0], store, release_annotation("v2.2.5"))["pxd"], "PXD123456")

    def test_promotion_leaves_flat_sdrf_compatibility_path_untouched(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_result(root)
            store = root / "store"
            (store / "agentic_results_files").mkdir(parents=True)
            sdrf_root = store / "hamlet_sdrfs"
            legacy_root = sdrf_root / "v2.0.0"
            legacy_root.mkdir(parents=True)
            legacy = legacy_root / "PXD123456.sdrf.tsv"
            legacy.write_text("legacy\n", encoding="utf-8")
            (sdrf_root / "PXD123456.sdrf.tsv").symlink_to(Path("v2.0.0") / legacy.name)
            aggregates = store / "aggregated_results_files"
            aggregates.mkdir()
            (aggregates / "PXD123456_aggregated_results.json").write_text('{"pxd_id": "PXD123456"}\n', encoding="utf-8")

            record = promotion_plan(root / "results", store, "v2.2.1")[0][0]
            promote_record(record, store, release_annotation("v2.2.1"))

            active = sdrf_root / "PXD123456.sdrf.tsv"
            self.assertTrue(active.is_symlink())
            self.assertEqual(legacy.read_text(encoding="utf-8"), "legacy\n")


if __name__ == "__main__":
    unittest.main()