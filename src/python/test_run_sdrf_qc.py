"""Focused tests for immutable SDRF QC fixture validation."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

from run_sdrf_qc import available_versions, compare_pair, metric_deltas, read_judge_category_metrics, requested_comparisons


class ReleaseComparisonTest(unittest.TestCase):
    def _write_release(self, store: Path, version: str, pxd: str, sdrf_text: str, judge_accuracy: str, review_rows: str) -> None:
        release_dir = store / "releases" / version
        release_dir.mkdir(parents=True, exist_ok=True)
        (store / "hamlet_sdrfs" / version).mkdir(parents=True, exist_ok=True)
        agentic = store / "agentic_results_files" / version / pxd / "metadata_extraction_output" / "post_judge"
        agentic.mkdir(parents=True, exist_ok=True)
        (store / "hamlet_sdrfs" / version / f"{pxd}.sdrf.tsv").write_text(sdrf_text, encoding="utf-8")
        (agentic / "llm_judge_per_paper.csv").write_text(
            "paper_id,mode,total_extracted,judge_n_correct,judge_accuracy\n"
            f"{pxd},strict,2,2,{judge_accuracy}\n",
            encoding="utf-8",
        )
        (agentic / "llm_judge_annotation_review.csv").write_text(review_rows, encoding="utf-8")
        (release_dir / "manifest.json").write_text(
            json.dumps({"release_version": version, "pxds": [{"pxd": pxd}]}) + "\n",
            encoding="utf-8",
        )

    def test_compare_pair_reports_sdrf_and_judge_deltas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Path(temporary_directory) / "store"
            review_v210 = (
                "paper_id,agent,error_category,corrected_value\n"
                "PXD123456,Biological,correct_explicit,\n"
                "PXD123456,Technical,hallucinated,\n"
            )
            review_v211 = (
                "paper_id,agent,error_category,corrected_value\n"
                "PXD123456,Biological,correct_explicit,\n"
                "PXD123456,Technical,correct_explicit,\n"
            )
            self._write_release(store, "v2.1.0", "PXD123456", "a\tb\n1\told.raw\n", "0.5", review_v210)
            self._write_release(store, "v2.1.1", "PXD123456", "a\tb\n1\tnew.raw\n", "1.0", review_v211)

            comparison = compare_pair(store, "v2.1.0", "v2.1.1")

        self.assertEqual(comparison["summary"]["shared_pxds"], 1)
        self.assertEqual(comparison["summary"]["changed_sdrfs"], 1)
        self.assertEqual(comparison["summary"]["judge_pairs_available"], 1)
        self.assertTrue(comparison["results"][0]["sdrf_changed"])
        self.assertEqual(comparison["results"][0]["judge_delta_status"], "available")
        self.assertAlmostEqual(comparison["results"][0]["judge_deltas"]["judge_accuracy"]["absolute_delta"], 0.5)
        self.assertIn("Technical", comparison["results"][0]["judge_category_deltas"])

    def test_available_versions_and_requested_pairs_are_version_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Path(temporary_directory) / "store" / "releases"
            for version in ("v2.1.1", "v2.1.0", "v2.2.0"):
                (store / version).mkdir(parents=True)

            versions = available_versions(store.parent)

        self.assertEqual(versions, ["v2.1.0", "v2.1.1", "v2.2.0"])
        arguments = type("Args", (), {"compare": [], "baseline_version": None, "candidate_version": None})()
        self.assertEqual(
            requested_comparisons(arguments, versions),
            [("v2.1.0", "v2.1.1"), ("v2.1.0", "v2.2.0"), ("v2.1.1", "v2.2.0")],
        )

    def test_metric_deltas_include_relative_change_when_defined(self) -> None:
        deltas = metric_deltas(
            {"judge_accuracy": 0.8, "judge_n_wrong": 0},
            {"judge_accuracy": 0.6, "judge_n_wrong": 2},
        )

        self.assertAlmostEqual(deltas["judge_accuracy"]["absolute_delta"], -0.2)
        self.assertAlmostEqual(deltas["judge_accuracy"]["relative_delta"], -0.25)
        self.assertEqual(deltas["judge_n_wrong"]["relative_delta"], None)

    def test_read_judge_category_metrics_uses_error_category(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "review.csv"
            path.write_text(
                "paper_id,agent,error_category,corrected_value\n"
                "PXD123456,Biological,correct_explicit,\n"
                "PXD123456,Biological,incomplete,revision\n",
                encoding="utf-8",
            )

            metrics = read_judge_category_metrics(path, "PXD123456")

        self.assertEqual(metrics["Biological"]["judge_n_incomplete"], 1)
        self.assertEqual(metrics["Biological"]["judge_n_corrected"], 1)

    def test_read_judge_category_metrics_supports_legacy_review_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "legacy_review.csv"
            path.write_text(
                "paper_id,agent,annotation_type,value_correct,value_complete,hallucination,type_mismatch,technical_origin,inference,corrected_value\n"
                "PXD123456,BiologicalAgent,species,True,True,False,False,False,,\n"
                "PXD123456,TechnicalAgent,instrument,False,True,False,False,False,,Orbitrap\n"
                "PXD123456,TechnicalAgent,modification,True,False,False,False,False,,\n",
                encoding="utf-8",
            )

            metrics = read_judge_category_metrics(path, "PXD123456")

        self.assertEqual(metrics["Biological"]["judge_n_correct"], 1)
        self.assertEqual(metrics["Technical"]["judge_n_wrong"], 1)
        self.assertEqual(metrics["Technical"]["judge_n_incomplete"], 1)


if __name__ == "__main__":
    unittest.main()