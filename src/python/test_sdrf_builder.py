"""Regression tests for the compatibility facade during SDRF refactoring."""

import json
import csv
import sys
import tempfile
import unittest
import warnings
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src" / "python"))

from sdrf_builder import AgenticToSDRF
from sdrf_adapters import agentic_evidence, judge_evidence
from sdrf_evidence import FieldEvidence
from sdrf_resolution import resolve_field
from sdrf_schema import SDRF_MAPPING_RULES, render_columns, source_precedence_for
from sdrf_protocol import parse_mass_tolerances
from sdrf_modifications import parse_protocol_modifications
from hamlet_version import HAMLET_VERSION


class AgenticToSdrfParityTest(unittest.TestCase):
    def _builder_from_archive(self, pxd: str) -> AgenticToSDRF:
        result_dir = REPO_ROOT / "store" / "agentic_results_files" / pxd
        metadata_dir = result_dir / "metadata_extraction_output" / "integrated_output"
        if not metadata_dir.exists():
            metadata_dir = result_dir / "integrated_output"
        return AgenticToSDRF(
            tech_json=metadata_dir / "TechnicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            bio_json=metadata_dir / "BiologicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            exp_json=metadata_dir / "ExperimentalDesignAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            aggregated_json=REPO_ROOT / "store" / "aggregated_results_files" / f"{pxd}_aggregated_results.json",
        )

    def test_pxd073162_matches_frozen_baseline(self) -> None:
        pxd = "PXD073162"
        metadata_dir = REPO_ROOT / "results_baseline" / pxd / "agentic_metadata" / "metadata_extraction_output"
        override_path = REPO_ROOT / "results_baseline" / pxd / "judge_output" / "json_outputs" / f"{pxd}_sdrf_overrides.json"
        baseline_path = REPO_ROOT / "results_baseline" / pxd / "agentic_metadata" / f"{pxd}.sdrf.tsv"

        with override_path.open(encoding="utf-8") as handle:
            override_document = json.load(handle)
        overrides = {
            str(info["builder_field"]): str(info["selected_value"])
            for info in override_document.get("field_overrides", {}).values()
            if info.get("apply_override") and info.get("selected_value")
        }

        builder = AgenticToSDRF(
            tech_json=metadata_dir / "integrated_output" / "TechnicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            bio_json=metadata_dir / "integrated_output" / "BiologicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            exp_json=metadata_dir / "integrated_output" / "ExperimentalDesignAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            aggregated_json=metadata_dir / f"{pxd}_aggregated_results.json",
            overrides=overrides,
            judge_document=override_document,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_path = Path(temporary_directory) / f"{pxd}.sdrf.tsv"
            builder.to_sdrf(generated_path)
            self.assertEqual(generated_path.read_bytes(), baseline_path.read_bytes())
            sidecar_path = Path(temporary_directory) / f"{pxd}.confidence.sdrf.tsv"
            builder.to_confidence_sidecar(sidecar_path)
            with sidecar_path.open(encoding="utf-8", newline="") as handle:
                sidecar_rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertTrue(sidecar_rows)
            self.assertTrue(all(row["source name"] for row in sidecar_rows))
            instrument = next(row for row in sidecar_rows if row["logical field"] == "instrument")
            self.assertEqual(instrument["judge corrected value"], "Q Exactive HF")
            self.assertEqual(instrument["judge hallucination"], "True")

    def test_judge_correction_overrides_source_precedence(self) -> None:
        resolved = resolve_field(
            "organism",
            (
                FieldEvidence("organism", "Incorrect organism", "biological_agent", "sample"),
                FieldEvidence(
                    "organism",
                    "Candidate organism",
                    "pride",
                    "sample",
                    judge_corrected_value="Correct organism",
                    judge_verdict="high",
                ),
            ),
        )
        self.assertEqual(resolved.value, "Correct organism")
        self.assertEqual(resolved.resolution_rule, "judge_corrected_value")
        self.assertEqual(resolved.assessment_state, "assessed")

    def test_validated_value_precedes_unassessed_source(self) -> None:
        resolved = resolve_field(
            "instrument",
            (
                FieldEvidence("instrument", "Agent instrument", "technical_agent", "assay"),
                FieldEvidence("instrument", "Validated instrument", "runassessor", "assay", judge_verdict="high"),
            ),
        )
        self.assertEqual(resolved.value, "Validated instrument")
        self.assertEqual(resolved.resolution_rule, "judge_validated_value")

    def test_source_precedence_marks_unassessed_values_derived(self) -> None:
        resolved = resolve_field(
            "instrument",
            (
                FieldEvidence("instrument", "RunAssessor instrument", "runassessor", "assay"),
                FieldEvidence("instrument", "Agent instrument", "technical_agent", "assay"),
            ),
        )
        self.assertEqual(resolved.value, "Agent instrument")
        self.assertEqual(resolved.resolution_rule, "source_precedence:technical_agent")
        self.assertEqual(resolved.assessment_state, "derived")

    def test_archived_agent_and_judge_documents_normalize_to_evidence(self) -> None:
        pxd = "PXD073162"
        root = REPO_ROOT / "results_baseline" / pxd
        bio_path = root / "agentic_metadata" / "metadata_extraction_output" / "integrated_output" / "BiologicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json"
        judge_path = root / "judge_output" / "json_outputs" / f"{pxd}_sdrf_overrides.json"

        with bio_path.open(encoding="utf-8") as handle:
            biological = json.load(handle)
        with judge_path.open(encoding="utf-8") as handle:
            judge = json.load(handle)

        agent_records = agentic_evidence(
            biological,
            source="biological_agent",
            scope="sample",
            field_aliases={"species": "organism", "tissue": "organism_part", "disease_state": "disease"},
        )
        organism = next(record for record in agent_records if record.field == "organism")
        self.assertEqual(organism.value, "S. clava")
        self.assertEqual(organism.agent_confidence, 0.85)
        self.assertTrue(organism.evidence)

        judge_records = judge_evidence(judge)
        instrument = next(record for record in judge_records if record.field == "instrument")
        self.assertEqual(instrument.judge_corrected_value, "Q Exactive HF")
        self.assertTrue(instrument.judge_hallucination)
        self.assertTrue(instrument.metadata["apply_override"])

    def test_schema_registry_covers_all_sdrf_namespaces(self) -> None:
        namespaces = {rule.namespace for rule in SDRF_MAPPING_RULES}
        headers = {rule.header for rule in SDRF_MAPPING_RULES}
        self.assertTrue({"characteristics", "comment", "factor value", "core"}.issubset(namespaces))
        self.assertIn("comment[modification parameters]", headers)
        self.assertIn("factor value[experimental design]", headers)
        self.assertEqual(source_precedence_for("instrument"), ("runassessor", "technical_agent", "aggregate"))

    def test_renderer_columns_expand_only_declared_many_fields(self) -> None:
        columns = render_columns({"source_name", "label", "modification", "data_file"}, {"label": 2, "modification": 3})
        self.assertEqual(columns, [
            "source name", "comment[label]#0", "comment[label]#1",
            "comment[modification parameters]#0", "comment[modification parameters]#1",
            "comment[modification parameters]#2", "comment[data file]",
        ])

    def test_mass_tolerance_parser_prefers_structured_values_then_protocol_text(self) -> None:
        self.assertEqual(
            parse_mass_tolerances({"tolerances": {"recommended overall precursor tolerance (ppm)": 8, "recommended overall fragment tolerance (ppm)": 12}}, ""),
            ("8 ppm", "12 ppm"),
        )
        self.assertEqual(
            parse_mass_tolerances({}, "Search used 6 ppm for precursor and 20 ppm for fragment ions."),
            ("6 ppm", "20 ppm"),
        )

    def test_mass_tolerance_parser_uses_recommended_value_not_diagnostic_bound(self) -> None:
        self.assertEqual(
            parse_mass_tolerances(
                {"tolerances": {
                    "recommended overall fragment tolerance (m/z)": 0.5,
                    "overall_lower_fragment_tolerance_m/z": -0.448627,
                }},
                "",
            ),
            (None, "0.5 m/z"),
        )

    def test_mass_tolerance_parser_warns_and_rejects_non_positive_recommendation(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(
                parse_mass_tolerances(
                    {"tolerances": {"recommended overall fragment tolerance (ppm)": -0.5}},
                    "",
                    warning_context="PXDTEST",
                ),
                (None, None),
            )

        self.assertEqual(len(caught), 1)
        self.assertIn("PXDTEST: ignoring non-positive recommended tolerance -0.5 ppm", str(caught[0].message))

    def test_mass_tolerance_overrides_precede_derived_values(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._overrides = {
            "precursor_tolerance": "10 ppm",
            "fragment_tolerance": "0.7 Da",
        }
        builder._ra_search = {
            "tolerances": {
                "recommended overall precursor tolerance (ppm)": 3951,
                "recommended overall fragment tolerance (ppm)": -0.488816,
            },
        }
        builder._data_proc = ""
        builder._sample_proc = ""

        self.assertEqual(builder._get_mass_tolerances(), ("10 ppm", "0.7 Da"))

    def test_protocol_modification_parser_preserves_order_and_residues(self) -> None:
        modifications = parse_protocol_modifications(
            "Carbamidomethylation, oxidation and methylation on lysine and arginine were included.",
            "iodoacetamide",
        )
        self.assertEqual([item["uid"] for item in modifications], [4, 35, 34])
        self.assertEqual(modifications[-1]["residues"], "KR")

    def test_archived_pride_only_file_inventory_and_multi_enzyme_studies(self) -> None:
        pride_only_columns, pride_only_rows = self._builder_from_archive("PXD000070").build_rows()
        self.assertEqual(len(pride_only_rows), 6)
        self.assertEqual(len({row["comment[data file]"] for row in pride_only_rows}), 6)
        self.assertIn("comment[cleavage agent details]", pride_only_columns)

        multi_enzyme_columns, multi_enzyme_rows = self._builder_from_archive("PXD001454").build_rows()
        self.assertTrue(multi_enzyme_rows)
        self.assertIn("comment[cleavage agent details]", multi_enzyme_columns)
        self.assertTrue(all(row["comment[data file]"] for row in multi_enzyme_rows))

    def test_pride_only_inventory_seeds_pxd014528_rows(self) -> None:
        columns, rows = self._builder_from_archive("PXD014528").build_rows()
        self.assertEqual(len(rows), 48)
        self.assertEqual(len({row["comment[data file]"] for row in rows}), 48)
        self.assertIn("comment[data file]", columns)

    def test_silac_technical_labeling_expands_each_file_to_heavy_and_light_rows(self) -> None:
        builder = self._builder_from_archive("PXD005463")
        columns, rows = builder.build_rows()
        self.assertEqual(len(rows), 6)
        self.assertEqual([row["comment[data file]"] for row in rows], [
            "qExPlus02_01602.raw", "qExPlus02_01602.raw",
            "qExPlus02_01603.raw", "qExPlus02_01603.raw",
            "qExPlus02_01604.raw", "qExPlus02_01604.raw",
        ])
        self.assertIn("comment[label]#1", columns)
        self.assertEqual(rows[0]["comment[label]#0"], "AC=PRIDE:0000615;NT=SILAC heavy R:13C(6)15N(4)")
        self.assertEqual(rows[0]["comment[label]#1"], "AC=PRIDE:0000617;NT=SILAC heavy K:13C(6)15N(2)")
        self.assertEqual(rows[1]["comment[label]#0"], "AC=PRIDE:0000611;NT=SILAC light R:12C(6)14N(4)")
        self.assertEqual(rows[1]["comment[label]#1"], "AC=PRIDE:0000613;NT=SILAC light K:12C(6)14N(2)")

    def test_aggregate_biological_replicate_count_is_not_sample_identifier(self) -> None:
        builder = self._builder_from_archive("PXD005463")
        self.assertEqual(builder._exp["number_of_biological_replicates"]["resolved"], "2")

        _, rows = builder.build_rows()

        self.assertTrue(rows)
        self.assertTrue(all(
            row["characteristics[biological replicate]"] == "not available"
            for row in rows
        ))

    def test_aggregate_fraction_and_technical_replicate_counts_are_not_identifiers(self) -> None:
        builder = self._builder_from_archive("PXD005463")
        self.assertEqual(builder._exp["number_of_fractions"]["resolved"], "6")
        self.assertEqual(builder._exp["number_of_technical_replicates"]["resolved"], "2")

        _, rows = builder.build_rows()

        self.assertTrue(rows)
        self.assertTrue(all(
            row["comment[fraction identifier]"] == "not available"
            and row["comment[technical replicate]"] == "not available"
            for row in rows
        ))

    def test_scalar_biological_replicate_override_is_not_broadcast(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._overrides = {"biological_replicate": "2"}

        self.assertEqual(builder._get_biological_replicate(), "not available")

    def test_scalar_fraction_and_technical_replicate_overrides_are_not_broadcast(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._overrides = {"fraction_identifier": "6", "technical_replicate": "2"}

        self.assertEqual(builder._get_fraction_identifier(), "not available")
        self.assertEqual(builder._get_technical_replicate(), "not available")

    def test_annotation_tool_uses_canonical_hamlet_version(self) -> None:
        builder = self._builder_from_archive("PXD005463")

        _, rows = builder.build_rows()

        self.assertTrue(rows)
        self.assertEqual(
            {row["comment[sdrf annotation tool]"] for row in rows},
            {f"HAMLET-agentic {HAMLET_VERSION}"},
        )

    def test_silac_channel_expansion_requires_per_file_modification_evidence(self) -> None:
        builder = self._builder_from_archive("PXD005463")
        builder._mods_per_stem = {}
        self.assertEqual(builder._get_channels("qExPlus02_01602"), [["not available"]])

    def test_tmt10_technical_label_expands_pride_inventory(self) -> None:
        columns, rows = self._builder_from_archive("PXD011799").build_rows()
        self.assertEqual(len(rows), 480)
        self.assertEqual(len({row["comment[data file]"] for row in rows}), 48)
        self.assertEqual(columns.count("comment[label]#0"), 1)
        self.assertEqual([row["comment[label]#0"] for row in rows[:10]], [
            "TMT126", "TMT127N", "TMT127C", "TMT128N", "TMT128C",
            "TMT129N", "TMT129C", "TMT130N", "TMT130C", "TMT131",
        ])
        self.assertEqual(len({row["comment[data file]"] for row in rows[:10]}), 1)


if __name__ == "__main__":
    unittest.main()