"""Focused tests for immutable SDRF QC fixture validation."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

from run_sdrf_qc import changed_pxds_from_paths, load_fixture_manifest, metric_deltas, read_judge_category_metrics


class FixtureValidationTest(unittest.TestCase):
    def _write_fixture_manifest(self, root: Path, digest: str) -> None:
        (root / "PXD123456").mkdir()
        (root / "PXD123456" / "PXD123456.sdrf.tsv").write_text(
            "source name\tcomment[data file]\nsource\trun.raw\n", encoding="utf-8"
        )
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "fixture_version": root.name,
                    "cohort": [
                        {
                            "pxd": "PXD123456",
                            "artifacts": [
                                {
                                    "fixture_path": "PXD123456.sdrf.tsv",
                                    "bytes": (root / "PXD123456" / "PXD123456.sdrf.tsv").stat().st_size,
                                    "sha256": digest,
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_load_fixture_manifest_validates_artifact_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "v2.1.0"
            root.mkdir()
            artifact = root / "PXD123456" / "PXD123456.sdrf.tsv"
            digest = hashlib.sha256(b"source name\tcomment[data file]\nsource\trun.raw\n").hexdigest()
            self._write_fixture_manifest(root, digest)

            manifest, records = load_fixture_manifest(root)

            self.assertEqual(manifest["fixture_version"], "v2.1.0")
            self.assertIn("PXD123456", records)
            artifact.write_text(
                "source name\tcomment[data file]\nsource\trun.xyz\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                load_fixture_manifest(root)

    def test_changed_pxds_only_accepts_stored_sdrf_paths(self) -> None:
        changed = changed_pxds_from_paths(
            (
                "store/hamlet_sdrfs/PXD003544.sdrf.tsv",
                "store/hamlet_sdrfs/PXD003544.confidence.sdrf.tsv",
                "store/hamlet_sdrfs/PXD044188.sdrf.tsv",
                "docs/PXD032144.sdrf.tsv",
            )
        )

        self.assertEqual(changed, ["PXD003544", "PXD044188"])

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


if __name__ == "__main__":
    unittest.main()