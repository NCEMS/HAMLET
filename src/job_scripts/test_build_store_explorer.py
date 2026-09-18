"""Focused tests for Store Explorer release-version detection."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "job_scripts"))

from build_store_explorer import annotated_release_version, publish_qc_summary


class StoreExplorerVersionTest(unittest.TestCase):
    def test_annotation_version_takes_precedence_over_current_code_version(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with (root / "PXD123456.sdrf.tsv").open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(
                    [
                        ["source name", "comment[sdrf annotation tool]"],
                        ["sample", "HAMLET-agentic v2.1.0"],
                    ]
                )

            self.assertEqual(annotated_release_version(root, "PXD123456"), "v2.1.0")

    def test_publish_qc_summary_accepts_static_comparison_schema(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            summary_path = root / "qc-summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "default_comparison_id": "v2.1.0__vs__v2.1.1",
                        "comparisons": [
                            {
                                "comparison_id": "v2.1.0__vs__v2.1.1",
                                "baseline_version": "v2.1.0",
                                "candidate_version": "v2.1.1",
                                "results": [{"pxd": "PXD123456", "sdrf_changed": True}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output_data_dir = root / "site-data"
            output_data_dir.mkdir()

            publish_qc_summary(summary_path, output_data_dir)

            published = json.loads((output_data_dir / "qc-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(published["schema_version"], 2)
            self.assertEqual(published["comparisons"][0]["candidate_version"], "v2.1.1")


if __name__ == "__main__":
    unittest.main()