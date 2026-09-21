"""Focused tests for versioned store snapshot helpers."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "job_scripts"))

from materialize_store_versions import read_pxds, target_paths, versioned_sources


class StoreVersionMaterializationTest(unittest.TestCase):
    def test_read_pxds_excludes_header_and_invalid_accessions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "pxds.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows((("PXDs",), ("PXD123456",), ("PXDinvalid",)))

            self.assertEqual(read_pxds(path), ["PXD123456"])

    def test_versioned_sources_and_targets_use_version_subdirectories(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Path(temporary_directory) / "store"
            (store / "hamlet_sdrfs" / "v2.1.0").mkdir(parents=True)
            (store / "agentic_results_files" / "v2.1.0" / "PXD123456").mkdir(parents=True)
            (store / "hamlet_sdrfs" / "v2.1.0" / "PXD123456.sdrf.tsv").write_text("sdrf\n", encoding="utf-8")

            self.assertEqual(
                versioned_sources(store, "v2.1.0", ["PXD123456"]),
                (store / "hamlet_sdrfs" / "v2.1.0", store / "agentic_results_files" / "v2.1.0"),
            )
            self.assertEqual(target_paths(store, "v2.1.1"), (store / "hamlet_sdrfs" / "v2.1.1", store / "agentic_results_files" / "v2.1.1"))


if __name__ == "__main__":
    unittest.main()