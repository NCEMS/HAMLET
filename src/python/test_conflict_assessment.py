"""Regression tests for direct HAMLET SDRF gold-cohort comparison."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

import conflictAssessment


SDRF_HEADER = "\t".join(
    (
        "source name",
        "characteristics[organism]",
        "comment[instrument]",
        "comment[data file]",
    )
)


class ExplicitSdrfComparisonTest(unittest.TestCase):
    def _write_sdrf(self, path: Path, organism: str) -> None:
        path.write_text(
            "{}\n{}\n".format(
                SDRF_HEADER,
                "\t".join(("sample-1", organism, "Orbitrap", "run-1.raw")),
            ),
            encoding="utf-8",
        )

    def test_explicit_paths_create_candidate_vs_hamlet_gold_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            candidate_path = root / "candidate.sdrf.tsv"
            gold_path = root / "gold.sdrf.tsv"
            output_dir = root / "reports"
            self._write_sdrf(candidate_path, "Homo sapiens")
            self._write_sdrf(gold_path, "Mus musculus")

            with patch.object(
                sys,
                "argv",
                [
                    "conflictAssessment.py",
                    "--pxd",
                    "PXD123456",
                    "--assessed-sdrf",
                    str(candidate_path),
                    "--gold-sdrf",
                    str(gold_path),
                    "--output-dir",
                    str(output_dir),
                ],
            ):
                with self.assertRaises(SystemExit) as raised:
                    conflictAssessment.main()

            self.assertEqual(raised.exception.code, 0)
            report_dir = output_dir / "PXD123456" / "candidate_vs_hamlet_gold"
            summary = json.loads((report_dir / "conflict_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["comparison"], "candidate_vs_hamlet_gold")
            self.assertEqual(summary["files"]["coverage"], 1.0)
            self.assertEqual(summary["categories"]["Biological"]["micro_f1"], 0.0)
            self.assertEqual(summary["categories"]["Technical"]["micro_f1"], 1.0)
            self.assertTrue((report_dir / "conflict_report.md").is_file())
            self.assertTrue((report_dir / "sample_field_metrics.tsv").is_file())

    def test_explicit_paths_must_be_paired(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "conflictAssessment.py",
                "--pxd",
                "PXD123456",
                "--assessed-sdrf",
                "candidate.sdrf.tsv",
            ],
        ):
            with self.assertRaisesRegex(SystemExit, "must be supplied together"):
                conflictAssessment.main()


if __name__ == "__main__":
    unittest.main()