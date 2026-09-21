"""Focused tests for Store Explorer release-version detection."""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "job_scripts"))

from build_store_explorer import active_release_versions, annotated_release_version, release_judge_metrics, publish_qc_summary


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

    def test_release_judge_metrics_prefers_final_sdrf_judge(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Path(temporary_directory) / "store"
            version = "v2.2.1"
            pxd = "PXD123456"
            (store / "releases" / version).mkdir(parents=True)
            (store / "releases" / version / "manifest.json").write_text(
                json.dumps({"release_version": version, "pxds": [{"pxd": pxd}]}),
                encoding="utf-8",
            )
            for judge_directory, accuracy in (("sdrf_judge", "1.0"), ("llm_refinement_judge", "0.5")):
                judge_path = store / "agentic_results_files" / version / pxd / judge_directory / "llm_judge_per_paper.csv"
                judge_path.parent.mkdir(parents=True, exist_ok=True)
                judge_path.write_text(
                    f"paper_id,judge_accuracy\n{pxd},{accuracy}\n",
                    encoding="utf-8",
                )

            summaries = release_judge_metrics(store)

        self.assertEqual(summaries[0]["judge_type"], "sdrf_judge")
        self.assertEqual(summaries[0]["records"][0]["metrics"]["judge_accuracy"], 1.0)

    def test_release_judge_metrics_supports_legacy_manifest_without_pxds(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Path(temporary_directory) / "store"
            version = "v2.0.0"
            pxd = "PXD123456"
            (store / "releases" / version).mkdir(parents=True)
            (store / "releases" / version / "manifest.json").write_text(
                json.dumps({"release_version": version}), encoding="utf-8"
            )
            sdrf_path = store / "hamlet_sdrfs" / version / f"{pxd}.sdrf.tsv"
            sdrf_path.parent.mkdir(parents=True)
            sdrf_path.write_text("a\nvalue\n", encoding="utf-8")
            judge_path = store / "agentic_results_files" / version / pxd / "judge_output" / "llm_judge_per_paper.csv"
            judge_path.parent.mkdir(parents=True)
            judge_path.write_text(
                f"paper_id,judge_accuracy\n{pxd},0.5\n", encoding="utf-8"
            )

            summaries = release_judge_metrics(store)

        self.assertEqual(summaries[0]["judge_type"], "llm_judge")
        self.assertEqual(summaries[0]["release_pxd_count"], 1)

    def test_release_judge_metrics_includes_unfinalized_versioned_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Path(temporary_directory) / "store"
            version = "v2.2.5"
            pxd = "PXD123456"
            sdrf_path = store / "hamlet_sdrfs" / version / f"{pxd}.sdrf.tsv"
            sdrf_path.parent.mkdir(parents=True)
            sdrf_path.write_text("a\nvalue\n", encoding="utf-8")
            judge_path = store / "agentic_results_files" / version / pxd / "sdrf_judge" / "llm_judge_per_paper.csv"
            judge_path.parent.mkdir(parents=True)
            judge_path.write_text(
                f"paper_id,judge_accuracy_adjusted\n{pxd},0.9\n", encoding="utf-8"
            )

            summaries = release_judge_metrics(store)

        self.assertEqual(summaries[0]["version"], version)
        self.assertEqual(summaries[0]["release_state"], "in_progress")
        self.assertEqual(summaries[0]["judge_type"], "sdrf_judge")
        self.assertEqual(summaries[0]["records"][0]["metrics"]["judge_accuracy_adjusted"], 0.9)

    def test_active_release_versions_reads_versioned_index(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            store = Path(temporary_directory) / "store"
            active_path = store / "releases" / "active.json"
            active_path.parent.mkdir(parents=True)
            active_path.write_text(
                json.dumps({"pxds": {"PXD123456": "v2.2.1", "invalid": "v2.2.1"}}),
                encoding="utf-8",
            )

            self.assertEqual(active_release_versions(store), {"PXD123456": "v2.2.1"})


if __name__ == "__main__":
    unittest.main()