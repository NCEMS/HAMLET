import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
ORGANISM_ID_PATH = REPO_ROOT / "src/python/OrganismID.py"
SPEC = importlib.util.spec_from_file_location("OrganismID", ORGANISM_ID_PATH)
ORGANISM_ID = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ORGANISM_ID)


class TaxidBlockTests(unittest.TestCase):
    def test_loads_ranked_blocks(self):
        blocks = ORGANISM_ID.load_taxid_blocks(
            REPO_ROOT / "assets/taxid_lists/AllPRIDEtaxids.csv"
        )

        self.assertEqual(273, len(blocks))
        self.assertEqual(
            (1, ["9606", "10090", "4932", "3702", "562", "10116", "9913", "7227", "6239", "1280"]),
            blocks[0],
        )
        self.assertEqual(list(range(1, 274)), [block_number for block_number, _ in blocks])
        self.assertTrue(all(len(taxids) == 10 for _, taxids in blocks[:-1]))
        self.assertEqual(6, len(blocks[-1][1]))
        all_taxids = {taxid for _, taxids in blocks for taxid in taxids}
        self.assertNotIn("2", all_taxids)
        self.assertNotIn("9825", all_taxids)

    def test_score_must_strictly_exceed_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "peptonizer_result.csv"
            pd.DataFrame({"taxon_id": [9606], "score": [0.8]}).to_csv(result_path, index=False)
            self.assertEqual(
                ("9606", 0.8, False),
                ORGANISM_ID.evaluate_peptonizer_result(result_path, 0.8),
            )

    def test_stops_at_first_passing_block_and_publishes_one_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filtered_path = root / "sample_filtered70pct_slim.tsv"
            pd.DataFrame({"peptide": ["ABCDEFGHIJK"] * 5, "score": [0.9] * 5}).to_csv(
                filtered_path, sep="\t", index=False
            )
            calls = []
            original_runner = ORGANISM_ID.run_peptonizer_attempt

            def fake_runner(input_file, data_dir, log_dir, config_path, taxid_list_str, **kwargs):
                calls.append(taxid_list_str)
                Path(data_dir).mkdir(parents=True)
                Path(log_dir).mkdir(parents=True)
                output_path = Path(data_dir) / "peptonizer_result.csv"
                score = 0.5 if len(calls) == 1 else 0.9
                pd.DataFrame({
                    "taxon_name": ["test"],
                    "taxon_id": [taxid_list_str.split(",")[0]],
                    "score": [score],
                }).to_csv(output_path, index=False)
                return str(output_path)

            ORGANISM_ID.run_peptonizer_attempt = fake_runner
            try:
                outputs = ORGANISM_ID.generate_snakemake_commands(
                    [str(filtered_path)],
                    [(1, ["9606"]), (2, ["10090"]), (3, ["4932"])],
                    ["562"],
                    score_threshold=0.8,
                    min_peptides=5,
                )
            finally:
                ORGANISM_ID.run_peptonizer_attempt = original_runner

            self.assertEqual(["9606,562", "10090,562"], calls)
            self.assertEqual(1, len(outputs))
            self.assertEqual(1, len(list(root.rglob("peptonizer_result.csv"))))
            manifest_path = Path(outputs[0]).parent / "peptonizer_iteration_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            self.assertEqual(2, manifest["selected_block"])
            self.assertEqual("10090", manifest["selected_taxid"])


if __name__ == "__main__":
    unittest.main()