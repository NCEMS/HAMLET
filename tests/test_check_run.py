import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_RUN_PATH = REPO_ROOT / "src/job_scripts/check_run.py"
SPEC = importlib.util.spec_from_file_location("check_run", CHECK_RUN_PATH)
CHECK_RUN = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CHECK_RUN
SPEC.loader.exec_module(CHECK_RUN)


class CheckRunTests(unittest.TestCase):
    def test_finds_peptonizer_result_in_updated_results_from_original_results(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            pxd = "PXD002997"
            original_pxd_dir = run_dir / "results" / pxd
            original_pxd_dir.mkdir(parents=True)
            sample_name = f"{pxd}_sample"
            peptonizer_result = (
                run_dir
                / "results_updated"
                / pxd
                / "organism_results/CasanovoSequence"
                / sample_name
                / "Peptonizer2000_data"
                / f"{sample_name}_filtered70pct_slim"
                / "peptonizer_result.csv"
            )
            peptonizer_result.parent.mkdir(parents=True)
            peptonizer_result.write_text("taxon_id,score\n9606,0.9\n")

            statuses, records = CHECK_RUN.key_output_statuses(original_pxd_dir, pxd, {})
            record = next(item for item in records if item.column == "peptonizer_result")

            self.assertTrue(statuses["peptonizer_result"])
            self.assertTrue(record.exists)
            self.assertEqual(peptonizer_result, record.path)

    def test_finds_open_search_psms_when_quality_gate_skips_closed_search(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            pxd = "PXD002997"
            pxd_dir = run_dir / "results" / pxd
            open_results = pxd_dir / "search/dda_search/Open/results.sage.tsv"
            open_results.parent.mkdir(parents=True)
            open_results.write_text("peptide\tspectrum_q\nPEPTIDE\t0.5\n")

            _, records = CHECK_RUN.key_output_statuses(pxd_dir, pxd, {})
            record = next(item for item in records if item.column == "sage_open_search_psms")

            self.assertTrue(record.exists)
            self.assertEqual(open_results, record.path)
            self.assertNotIn("ptm_shepherd_modsummary", {item.column for item in records})


if __name__ == "__main__":
    unittest.main()