"""Focused repository-provenance tests for final SDRF judge metrics."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

from sdrf_judge import (
    _classify_row,
    _compute_single_paper_stats,
    _matching_technical_origins,
    load_technical_reference,
)


class RepositoryProvenanceTest(unittest.TestCase):
    def test_technical_reference_tags_each_authoritative_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            agentic_dir = Path(temporary_directory)
            technical_dir = agentic_dir / "integrated_output" / "TechnicalAgent" / "temp_0.0"
            technical_dir.mkdir(parents=True)
            (technical_dir / "PXD123456_enriched.json").write_text(
                json.dumps({
                    "instrument": {"sources": {"meti": {"value": "Orbitrap Fusion Lumos"}}},
                    "mass_analyzer": {"sources": {"meti": {"value": "Orbitrap"}}},
                    "_meti_data": {"ptms": {"records": [{"name": "phosphorylated residue"}]}},
                    "per_raw_file": {
                        "sample": {"modifications": [{"name": "Iodoacetamide derivative", "targets": ["C"]}]}
                    },
                }),
                encoding="utf-8",
            )

            reference = load_technical_reference("PXD123456", str(agentic_dir))

        self.assertEqual(
            _matching_technical_origins("instrument", "Orbitrap Fusion Lumos", reference),
            {"runassessor"},
        )
        self.assertEqual(
            _matching_technical_origins("mass_analyzer", "Orbitrap", reference),
            {"runassessor"},
        )
        self.assertEqual(
            _matching_technical_origins("modification", "phosphorylated residue", reference),
            {"pride_repository"},
        )
        self.assertEqual(
            _matching_technical_origins("modification", "Iodoacetamide derivative (C)", reference),
            {"ptm_shepherd"},
        )

    def test_repository_categories_are_not_counted_as_hallucinations(self) -> None:
        rows = [
            {"repository_origin": "runassessor", "hallucination": False, "value_correct": False, "value_complete": True},
            {"repository_origin": "pride_repository", "hallucination": False, "value_correct": False, "value_complete": True},
            {"repository_origin": "ptm_shepherd", "hallucination": False, "value_correct": False, "value_complete": True},
            {"repository_origin": None, "hallucination": True, "value_correct": False, "value_complete": True},
            {"repository_origin": None, "hallucination": False, "value_correct": True, "value_complete": True},
        ]

        for row in rows:
            row["error_category"] = _classify_row(row)
        stats = _compute_single_paper_stats("PXD123456", rows)

        self.assertEqual(stats["judge_n_hallucinated"], 1)
        self.assertEqual(stats["judge_n_technical_not_in_text"], 3)
        self.assertEqual(stats["judge_n_runassessor_only"], 1)
        self.assertEqual(stats["judge_n_pride_repository_only"], 1)
        self.assertEqual(stats["judge_n_ptm_shepherd_only"], 1)
        self.assertEqual(stats["judge_accuracy"], 0.2)
        self.assertEqual(stats["judge_accuracy_adjusted"], 0.8)

    def test_runassessor_acquisition_code_matches_rendered_sdrf_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            aggregate_path = Path(temporary_directory) / "PXD123456_aggregated_results.json"
            aggregate_path.write_text(
                json.dumps({"runAssessor": {"search_criteria": {"acquisition_type": "DDA"}}}),
                encoding="utf-8",
            )

            reference = load_technical_reference("PXD123456", aggregated_results_path=str(aggregate_path))

        self.assertEqual(
            _matching_technical_origins("acquisition_method", "data-dependent acquisition", reference),
            {"runassessor"},
        )


if __name__ == "__main__":
    unittest.main()