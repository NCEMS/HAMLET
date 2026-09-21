"""Focused tests for historical store release snapshots."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "job_scripts"))

from snapshot_store_release import build_manifest, category_metrics, read_pxds


class StoreReleaseSnapshotTest(unittest.TestCase):
    def test_read_pxds_excludes_header_and_invalid_values(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "pxds.csv"
            path.write_text("PXDs\nPXD123456\nPXDinvalid\nPXD654321\n", encoding="utf-8")

            self.assertEqual(read_pxds(path), ["PXD123456", "PXD654321"])

    def test_snapshot_records_available_and_missing_judge_metrics(self):
        def content_for_path(_, __, path):
            if path.endswith("PXD123456.sdrf.tsv"):
                return b"source name\tcomment[data file]\nsample\trun.raw\n"
            if "PXD123456" in path and path.endswith("llm_judge_per_paper.csv"):
                return b"paper_id,mode,total_extracted,judge_n_correct,judge_accuracy\nPXD123456,strict,2,2,1.0\n"
            if path.endswith("PXD999999.sdrf.tsv"):
                return b"source name\tcomment[data file]\nsample\trun.raw\n"
            return None

        with patch("snapshot_store_release.git_bytes", side_effect=content_for_path):
            manifest = build_manifest(REPO_ROOT, "v2.1.0", "revision", ["PXD123456", "PXD999999"])

        available, missing = manifest["pxds"]
        self.assertEqual(available["judge"]["metrics"]["judge_accuracy"], 1.0)
        self.assertEqual(available["judge"]["metrics"]["judge_n_correct"], 2)
        self.assertEqual(missing["judge"]["status"], "missing")
        self.assertEqual(available["sdrf"]["status"], "available")

    def test_category_metrics_follow_authoritative_error_categories(self):
        review = (
            b"paper_id,agent,error_category,corrected_value\n"
            b"PXD123456,Biological,correct_explicit,\n"
            b"PXD123456,Biological,hallucinated,changed\n"
            b"PXD123456,Technical,meti_only,\n"
        )

        metrics = category_metrics(review, "PXD123456")

        self.assertEqual(metrics["Biological"]["total_extracted"], 2)
        self.assertEqual(metrics["Biological"]["judge_n_hallucinated"], 1)
        self.assertEqual(metrics["Biological"]["judge_n_corrected"], 1)
        self.assertEqual(metrics["Technical"]["judge_accuracy_adjusted"], 1.0)


if __name__ == "__main__":
    unittest.main()