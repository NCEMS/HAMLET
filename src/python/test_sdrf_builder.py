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
from sdrf_adapters import ModificationEvidence, agentic_evidence, judge_evidence, modification_evidence
from sdrf_evidence import FieldEvidence
from sdrf_resolution import resolve_field
from sdrf_schema import SDRF_MAPPING_RULES, render_columns, source_precedence_for
from sdrf_protocol import parse_mass_tolerances
from sdrf_modifications import parse_protocol_modifications
from hamlet_version import HAMLET_VERSION


def _direct_per_raw(value, *, unit=None, accession=None):
    candidate = {
        "value": value,
        "source": "runassessor",
        "scope": "assay",
        "source_path": "runAssessor.files.run_1.mzML",
        "cv_accession": accession,
        "cv_name": unit,
        "valid": True,
    }
    return {
        "resolved": value,
        "candidates": [candidate],
        "selected_source_index": 0,
    }


class AgenticToSdrfParityTest(unittest.TestCase):
    @staticmethod
    def _archive_raw_files(pxd: str) -> list[str]:
        aggregate_path = REPO_ROOT / "store" / "aggregated_results_files" / f"{pxd}_aggregated_results.json"
        with aggregate_path.open(encoding="utf-8") as handle:
            aggregate = json.load(handle)
        return [
            str(record.get("fileName") or "").strip()
            for record in aggregate.get("pride_metadata", {}).get("files", [])
            if isinstance(record, dict) and str(record.get("fileName") or "").lower().endswith(".raw")
        ]

    def _builder_from_archive(self, pxd: str) -> AgenticToSDRF:
        result_dir = REPO_ROOT / "store" / "agentic_results_files" / pxd
        metadata_dir = result_dir / "metadata_extraction_output" / "integrated_output"
        if not metadata_dir.exists():
            metadata_dir = result_dir / "integrated_output"
        return AgenticToSDRF(
            tech_json=metadata_dir / "TechnicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            bio_json=metadata_dir / "BiologicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            exp_json=metadata_dir / "ExperimentalDesignAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            raw_files=self._archive_raw_files(pxd),
            pxd_id=pxd,
        )

    def test_pxd073162_generates_sdrf_and_confidence_sidecar(self) -> None:
        pxd = "PXD073162"
        result_dir = REPO_ROOT / "store" / "agentic_results_files" / pxd
        metadata_dir = result_dir / "metadata_extraction_output" / "integrated_output"
        override_path = result_dir / "judge_output" / "json_outputs" / f"{pxd}_sdrf_overrides.json"

        with override_path.open(encoding="utf-8") as handle:
            override_document = json.load(handle)
        overrides = {
            str(info["builder_field"]): str(info["selected_value"])
            for info in override_document.get("field_overrides", {}).values()
            if info.get("apply_override") and info.get("selected_value")
        }

        builder = AgenticToSDRF(
            tech_json=metadata_dir / "TechnicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            bio_json=metadata_dir / "BiologicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            exp_json=metadata_dir / "ExperimentalDesignAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json",
            raw_files=self._archive_raw_files(pxd),
            pxd_id=pxd,
            overrides=overrides,
            judge_document=override_document,
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            generated_path = Path(temporary_directory) / f"{pxd}.sdrf.tsv"
            builder.to_sdrf(generated_path)
            self.assertTrue(generated_path.read_text(encoding="utf-8").strip())
            sidecar_path = Path(temporary_directory) / f"{pxd}.confidence.sdrf.tsv"
            builder.to_confidence_sidecar(sidecar_path)
            with sidecar_path.open(encoding="utf-8", newline="") as handle:
                sidecar_rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertTrue(sidecar_rows)
            self.assertTrue(all(row["source name"] for row in sidecar_rows))
            instrument = next(row for row in sidecar_rows if row["logical field"] == "instrument")
            self.assertEqual(instrument["judge corrected value"], "Q Exactive HF")
            self.assertEqual(instrument["judge hallucination"], "True")
            self.assertTrue(json.loads(instrument["source records"]))

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
        root = REPO_ROOT / "store" / "agentic_results_files" / pxd
        bio_path = root / "metadata_extraction_output" / "integrated_output" / "BiologicalAgent" / "temp_0.0" / f"{pxd}_PubText_enriched.json"
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
        builder._tech = {"per_raw_file": {}}

        self.assertEqual(builder._get_mass_tolerances("run_1"), ("10 ppm", "0.7 Da"))

    def test_modification_evidence_only_uses_supplied_structured_records(self) -> None:
        records = modification_evidence(
            [{"name": "Oxidation", "accession": "UNIMOD:35"}],
            {"ptm": {"resolved": "Oxidation; Acetylation"}},
            [{
                "unimod_id": 35,
                "mod_name": "Oxidation",
                "allowed_residues": "M",
                "allowed_terms": "N-term",
                "fraction_modified": 0.01,
            }],
            raw_stem="run_1",
        )

        self.assertEqual(len(records), 4)
        self.assertEqual(records[0].accession, "UNIMOD:35")
        self.assertEqual(records[2].name, "Acetylation")
        self.assertEqual(records[3].targets, ("M", "N-term"))
        self.assertEqual(records[3].fraction_modified, 0.01)

    def test_modification_evidence_excludes_pride_no_ptm_declaration(self) -> None:
        records = modification_evidence(
            [{
                "name": "No PTMs are included in the dataset",
                "accession": "PRIDE:0000398",
            }],
            {},
            [],
            raw_stem="run_1",
        )

        self.assertEqual(records, ())

    def test_modification_evidence_omits_missing_target_sentinels(self) -> None:
        records = modification_evidence(
            [],
            {},
            [{
                "unimod_id": 2,
                "mod_name": "Amidation",
                "allowed_residues": float("nan"),
                "allowed_terms": "C-term",
            }],
            raw_stem="run_1",
        )

        self.assertEqual(records[0].targets, ("C-term",))

    def test_modification_renderer_marks_only_explicit_status_conflicts(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._modification_records = lambda raw_stem: (
            ModificationEvidence("Oxidation", "UNIMOD:35", ("M",), "Fixed", "pride", "study", "pride[0]", "Oxidation"),
            ModificationEvidence("Oxidation", "UNIMOD:35", ("M",), "Variable", "technical_agent", "study", "technical.ptm[0]", "Oxidation"),
            ModificationEvidence("Acetylation", None, (), None, "technical_agent", "study", "technical.ptm[1]", "Acetylation"),
        )

        self.assertEqual(builder._get_modification_params("run_1"), [
            "NT=Oxidation;AC=UNIMOD:35;MT=!;TA=M",
            "NT=Acetylation;MT=?",
        ])

    def test_modification_renderer_merges_matching_name_and_search_accession(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._modification_records = lambda raw_stem: (
            ModificationEvidence("Formylation", None, (), None, "technical_agent", "study", "technical.ptm[0]", "Formylation"),
            ModificationEvidence("Formylation", "UNIMOD:122", ("K", "N-term"), None, "ptm_shepherd", "assay", "search.run_1[0]", "Formylation", raw_stem="run_1", fraction_modified=0.12),
        )

        self.assertEqual(builder._get_modification_params("run_1"), [
            "NT=Formylation;AC=UNIMOD:122;MT=?;TA=K,N-term",
        ])

    def test_confidence_sidecar_includes_normalized_source_records(self) -> None:
        builder = self._builder_from_archive("PXD000070")
        with tempfile.TemporaryDirectory() as temporary_directory:
            sidecar_path = Path(temporary_directory) / "PXD000070.confidence.sdrf.tsv"
            builder.to_confidence_sidecar(sidecar_path)
            with sidecar_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))

        self.assertTrue(rows)
        instrument = next(row for row in rows if row["logical field"] == "instrument")
        records = json.loads(instrument["source records"])
        self.assertTrue(records)
        self.assertIn("scope", records[0])

    def test_builder_does_not_derive_cleavage_or_tolerance_from_protocol_text(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._overrides = {}
        builder._tech = {"cleavage_agent": {"resolved": None}}
        builder._ra_search = {}
        builder._sample_proc = "Digested with trypsin; searched at 10 ppm."
        builder._data_proc = "Fragment tolerance 0.5 Da."

        self.assertEqual(builder._get_cleavage_agent(), "not available")
        self.assertEqual(builder._get_mass_tolerances("run_1"), (None, None))

    def test_builder_renders_enriched_documents_without_aggregate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            tech_path = root / "technical.json"
            bio_path = root / "biological.json"
            exp_path = root / "experimental.json"
            tech_path.write_text(json.dumps({
                "instrument": {"resolved": "Q Exactive"},
                "cleavage_agent": {"resolved": "trypsin"},
                "precursor_tolerance": {"resolved": "10 ppm"},
                "fragment_tolerance": {"resolved": "0.02 Da"},
                "per_raw_file": {
                    "run_1": {
                        "instrument": _direct_per_raw("Q Exactive", accession="MS:1001911"),
                        "acquisition": _direct_per_raw("DDA"),
                        "label": _direct_per_raw("label-free"),
                        "dissociation": _direct_per_raw("HCD"),
                        "ms2_analyzer": _direct_per_raw("Orbitrap"),
                        "modifications": [],
                    },
                },
                "_meti_data": {"ptms": {"records": []}},
            }), encoding="utf-8")
            bio_path.write_text(json.dumps({"species": {"resolved": "Homo sapiens"}}), encoding="utf-8")
            exp_path.write_text("{}", encoding="utf-8")

            builder = AgenticToSDRF(
                tech_json=tech_path,
                bio_json=bio_path,
                exp_json=exp_path,
                raw_files=["run_1.raw"],
                pxd_id="PXD999999",
            )
            columns, rows = builder.build_rows()

        self.assertIn("comment[precursor mass tolerance]", columns)
        self.assertEqual(rows[0]["comment[data file]"], "run_1.raw")
        self.assertEqual(rows[0]["comment[instrument]"], "NT=Q Exactive;AC=MS:1001911")
        self.assertEqual(rows[0]["comment[fragment mass tolerance]"], "0.02 Da")

    def test_builder_preserves_explicit_trypsin_p_and_direct_ms2_analyzer(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._overrides = {}
        builder._tech = {
            "cleavage_agent": {"resolved": "Trypsin/P"},
            "ms2_analyzer": {"resolved": "ion trap"},
        }

        self.assertEqual(builder._get_cleavage_agent(), "NT=Trypsin/P;AC=MS:1001313")
        self.assertEqual(builder._get_ms2_analyzer("run_1"), "ion trap")

    def test_dissociation_map_normalizes_runassessor_separator_spellings(self) -> None:
        cid = "NT=collision-induced dissociation;AC=MS:1000133"
        hcd = "NT=beam-type collision-induced dissociation;AC=MS:1000422"

        for raw in ("LR IT CID", "LR_IT_CID", "lr-it-cid", " lr it cid "):
            self.assertEqual(AgenticToSDRF._map_dissociation(raw), cid, raw)
        for raw in ("HR HCD", "HR_HCD", "hr-hcd", "hcd"):
            self.assertEqual(AgenticToSDRF._map_dissociation(raw), hcd, raw)
        self.assertEqual(AgenticToSDRF._map_dissociation("??"), "not available")

    def test_builder_preserves_supplied_multi_value_sex(self) -> None:
        builder = AgenticToSDRF.__new__(AgenticToSDRF)
        builder._overrides = {}
        builder._resolve_sample_field = lambda field: "male and female"

        self.assertEqual(builder._get_sex(), "male and female")

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
        builder._tech["per_raw_file"] = {
            Path(raw_file).stem: {
                "modifications": [{
                    "name": "SILAC heavy K",
                    "accession": "UNIMOD:259",
                    "source": "ptm_shepherd",
                    "scope": "assay",
                    "source_path": "test.fixture",
                    "source_value": "SILAC heavy K",
                }],
            }
            for raw_file in builder._get_raw_files()
        }
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