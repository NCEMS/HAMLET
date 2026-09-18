"""Focused tests for Store Explorer release-version detection."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "job_scripts"))

from build_store_explorer import annotated_release_version


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


if __name__ == "__main__":
    unittest.main()