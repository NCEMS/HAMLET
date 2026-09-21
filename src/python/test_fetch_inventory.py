"""Regression tests for source-aware incremental PRIDE fetching."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

from FetchPXD import (
    _convert_thermo_raw_to_mzml,
    local_raw_files_by_stem,
    mark_fetch_inventory_complete,
    missing_raw_file_records,
    write_fetch_inventory,
)
from stage_manifest import _fetch_complete, _run_assessor_complete


class FetchInventoryTest(unittest.TestCase):
    def test_retained_raw_is_missing_only_until_converted(self) -> None:
        selected_files = [
            {"file_name": "converted.raw", "ftp_url": "ftp://example/converted.raw"},
            {"file_name": "retained.raw", "ftp_url": "ftp://example/retained.raw"},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            pxd_dir = Path(temp_dir)
            (pxd_dir / "retained.RAW").touch()

            missing_files = missing_raw_file_records(selected_files, {"converted"})
            local_raw_files = local_raw_files_by_stem(str(pxd_dir))

        self.assertEqual([record["file_name"] for record in missing_files], ["retained.raw"])
        self.assertIn("retained", local_raw_files)

    def test_thermo_conversion_failure_is_attempted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "sample.raw"
            raw_path.write_bytes(b"raw")
            output_path = raw_path.with_suffix(".mzML")

            with patch("FetchPXD.subprocess.run", side_effect=__import__("subprocess").CalledProcessError(1, "ThermoRawFileParser")) as run:
                result = _convert_thermo_raw_to_mzml(str(raw_path), str(output_path))

        self.assertIsNone(result)
        self.assertEqual(run.call_count, 1)

    def test_fetch_manifest_requires_matching_complete_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            central_dir = Path(temp_dir)
            pxd_dir = central_dir / "PXDTEST"
            pxd_dir.mkdir()
            selected_files = [
                {"file_name": "first.raw", "ftp_url": "ftp://example/first.raw"},
                {"file_name": "second.raw", "ftp_url": "ftp://example/second.raw"},
            ]
            write_fetch_inventory(str(pxd_dir), "PXDTEST", selected_files, 0)
            (pxd_dir / "first.mzML").touch()
            (pxd_dir / "second.mzML").touch()

            self.assertFalse(_fetch_complete(central_dir, "PXDTEST", 0))
            mark_fetch_inventory_complete(str(pxd_dir))

            self.assertTrue(_fetch_complete(central_dir, "PXDTEST", 0))
            self.assertFalse(_fetch_complete(central_dir, "PXDTEST", 30))
            (pxd_dir / "second.mzML").unlink()
            self.assertFalse(_fetch_complete(central_dir, "PXDTEST", 0))

    def test_run_assessor_requires_all_selected_mzml_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            pxd_dir = base_dir / "spectral_files" / "PXDTEST"
            pxd_dir.mkdir(parents=True)
            selected_files = [
                {"file_name": "first.raw", "ftp_url": "ftp://example/first.raw"},
                {"file_name": "second.raw", "ftp_url": "ftp://example/second.raw"},
            ]
            write_fetch_inventory(str(pxd_dir), "PXDTEST", selected_files, 0)
            mark_fetch_inventory_complete(str(pxd_dir))
            (pxd_dir / "first.mzML").touch()
            (pxd_dir / "second.mzML").touch()
            report_path = pxd_dir / "runAssessor" / "study_metadata.json"
            report_path.parent.mkdir()
            report_path.write_text('{"files": {"PXDTEST/first.mzML": {}}}', encoding="utf-8")

            self.assertFalse(
                _run_assessor_complete(base_dir, base_dir / "spectral_files", "PXDTEST", [str(report_path)])
            )

            report_path.write_text(
                '{"files": {"PXDTEST/first.mzML": {}, "PXDTEST/second.mzML": {}}}',
                encoding="utf-8",
            )
            self.assertTrue(
                _run_assessor_complete(base_dir, base_dir / "spectral_files", "PXDTEST", [str(report_path)])
            )


if __name__ == "__main__":
    unittest.main()