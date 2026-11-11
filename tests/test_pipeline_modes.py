import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/python"))

import aggregate_results as aggregation
import determine_taxids


PXD = "PXD000001"


def stored_aggregate():
    return {
        "pxd_id": PXD,
        "runAssessor": {"files": {"sample.mzML": {"instrument": "preserved"}}},
        "organism_identification": {
            "results": [{
                "file_path": "/deleted/CasanovoSequence/PXD000001_sample/Peptonizer2000_data/sample_filtered70pct_slim/peptonizer_result.csv",
                "data": [{"taxon_id": 10090, "score": 0.99}, {"taxon_id": 9606, "score": 0.01}],
                "num_predictions": 2,
            }],
            "summary": {"num_files_processed": 1},
        },
        "PTM-shepherd_open_search": {"old": "open"},
        "PTM-shepherd_closed_search": {"old": "closed"},
        "Search_and_modification_results": {"old": "search"},
        "modification_site_fractions": {"old": "fractions"},
        "taxid_warnings": {"old": "warnings"},
        "llm_extracted_metadata": {"sample.raw": {"Characteristics[OrganismTaxid]": ["10090"]}},
        "pride_metadata": {"project": {"organisms": [{"accession": "NEWT:10090"}]}},
        "consolidated_pipeline": {"historical": "events"},
        "custom_section": {"must": ["survive", "unchanged"]},
        "input_paths": {"organism_dir": "/deleted/organism", "sage_results_dir": "/deleted/search"},
        "processing_summary": {"custom_counter": 7},
    }


class AggregateUpdateTests(unittest.TestCase):
    def aggregate(self, root, mode, base=True):
        source = root / "existing.json"
        if base:
            source.write_text(json.dumps(stored_aggregate()))
        with contextlib.redirect_stdout(io.StringIO()):
            return aggregation.aggregate_results(
                PXD, str(root / "spectra"), str(root / "organism"),
                str(root / "search"), str(root / "llm"), str(root / "pride"),
                str(root / "warnings.json"), str(root / "output.json"),
                existing_aggregate=str(source), mode=mode,
            )

    def test_partial_modes_preserve_every_unselected_section_without_sources(self):
        for mode, fields in aggregation.MODE_SECTIONS.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                base = stored_aggregate()
                fresh_organism = [{"data": [{"taxon_id": 7227}], "num_predictions": 1}]
                with patch.object(aggregation, "load_organism_results", return_value=fresh_organism), \
                        patch.object(aggregation, "load_sage_results", return_value={
                            "Search_and_modification_results": {"new": "search"},
                        }), patch.object(aggregation, "load_runAssessor", return_value={"new": "assessment"}):
                    result = self.aggregate(root, mode)
                for key in base:
                    if key not in (*fields, "input_paths", "processing_summary"):
                        self.assertEqual(result[key], base[key], key)
                self.assertEqual(result["run_mode"], mode)
                self.assertEqual(result["processing_summary"]["custom_counter"], 7)
                self.assertTrue(result["processing_summary"]["organism_results_found"])
                self.assertEqual(json.loads((root / "existing.json").read_text()), base)
                self.assertEqual(json.loads((root / "output.json").read_text()), result)
                if mode == "search_only":
                    self.assertEqual(result["Search_and_modification_results"], {"new": "search"})
                    self.assertIsNone(result["modification_site_fractions"])
                elif mode == "organism_only":
                    self.assertEqual(result["organism_identification"]["results"], fresh_organism)
                else:
                    self.assertEqual(result["runAssessor"], {"new": "assessment"})

    def test_missing_aggregate_rebuilds_from_stage_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "spectra/runAssessor"
            source.mkdir(parents=True)
            (source / "study_metadata.json").write_text('{"files":{"sample.mzML":{}}}')
            with patch.object(aggregation, "load_organism_results", return_value=[
                {"num_predictions": 1, "data": [{"taxon_id": 9606}]},
            ]), patch.object(aggregation, "load_sage_results", return_value={
                "Search_and_modification_results": {"recovered": True},
            }):
                result = self.aggregate(root, "organism_only", base=False)
            self.assertEqual(result["runAssessor"], {"files": {"sample.mzML": {}}})
            self.assertTrue(result["Search_and_modification_results"]["recovered"])
            self.assertEqual(result["organism_identification"]["results"][0]["num_predictions"], 1)

    def test_selected_empty_results_replace_stale_results(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.aggregate(Path(directory), "organism_only")
            self.assertEqual(result["organism_identification"], {"results": [], "summary": {}})
            self.assertFalse(result["processing_summary"]["organism_results_found"])
            self.assertEqual(result["Search_and_modification_results"], {"old": "search"})

    def test_full_update_refreshes_all_stages_but_preserves_extra_data(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.aggregate(Path(directory), "full")
            self.assertEqual(result["organism_identification"]["results"], [])
            self.assertIsNone(result["Search_and_modification_results"])
            self.assertEqual(result["custom_section"], stored_aggregate()["custom_section"])
            self.assertEqual(result["llm_extracted_metadata"], stored_aggregate()["llm_extracted_metadata"])

    def test_invalid_existing_aggregates_fail_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.json"
            for content in ("invalid json", "[]", '{"pxd_id":"PXD000002"}'):
                with self.subTest(content=content):
                    path.write_text(content)
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        aggregation.load_existing_aggregate(path, PXD)
                    self.assertEqual(path.read_text(), content)

    def test_taxid_sources_use_embedded_predictions_and_metadata(self):
        organisms, llm, pride = determine_taxids.aggregate_taxid_sources(stored_aggregate())
        self.assertEqual(organisms, {"sample.raw": "10090"})
        self.assertEqual(llm, {"sample.raw": "10090"})
        self.assertEqual(pride, "10090")
        base = stored_aggregate()
        base["organism_identification"]["results"][0]["file_path"] = base[
            "organism_identification"]["results"][0]["file_path"].replace("Casanovo", "Cascadia")
        self.assertEqual(determine_taxids.aggregate_taxid_sources(base)[0], organisms)

    def test_csv_and_embedded_predictions_resolve_the_same_raw_filename(self):
        for sequencer in ("CasanovoSequence", "CascadiaSequence"):
            with self.subTest(sequencer=sequencer), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                csv_path = root / sequencer / f"{PXD}_sample/Peptonizer2000_data/sample_filtered70pct_slim/peptonizer_result.csv"
                csv_path.parent.mkdir(parents=True)
                csv_path.write_text("taxon_name,taxon_id,score\nhuman,9606,0.01\nmouse,10090,0.99\n")
                with contextlib.redirect_stdout(io.StringIO()):
                    organisms, warnings = determine_taxids.parse_organism_id_results(root)
                self.assertEqual(warnings, [])
                self.assertEqual(organisms, determine_taxids.aggregate_taxid_sources(stored_aggregate())[0])


STUB_PROCESSES = r'''
process fetch_pxd {
    input: val pxd
    output:
    tuple val(pxd), path("fetched")
    path("study_metadata.json")
    script: """
    mkdir fetched
    echo '{}' > study_metadata.json
    """
}
process determine_acquisition_params {
    input: tuple val(pxd), path(fetched_dir), path(llm_results)
    output: tuple val(pxd), path(fetched_dir), path("detected_params.json")
    script: """
    echo '{"detected_params":{"DIA":false}}' > detected_params.json
    """
}
process organism_id {
    input: tuple val(pxd), path(fetched_dir), path(detected_params), path(contaminants), path(taxids), path(llm_results)
    output: tuple val(pxd), path(fetched_dir), path(detected_params), path("organism_results"), path("organism_status.json")
    script: """
    mkdir organism_results
    echo '{"status":"no_usable_results"}' > organism_status.json
    cp organism_status.json organism_results/
    """
}
process search {
    input: tuple val(pxd), path(fetched_dir), path(detected_params), path(mapping)
    output: tuple val(pxd), path("search")
    script: """
    mkdir search
    echo fixture > search/completed.txt
    """
}
process llm_extraction {
    input: tuple val(pxd), path(fetched_dir)
    output: tuple val(pxd), path("llm_results")
    script: """
    mkdir llm_results
    """
}
process agentic_metadata_extraction {
    input: tuple val(pxd), path(aggregated_results)
    output: tuple val(pxd), path("agentic_stage_output"), path(aggregated_results)
    script: """
    mkdir agentic_stage_output
    """
}
process llm_judge {
    input: tuple val(pxd), path(agentic_output)
    output: tuple val(pxd), path("judge_output")
    script: """
    mkdir judge_output
    """
}
process finalize_sdrf {
    input: tuple val(pxd), path(agentic_output), path(aggregate), path(judge)
    output:
    tuple val(pxd), path("final.sdrf.tsv")
    path("final.txt")
    script: """
    touch final.sdrf.tsv final.txt
    """
}
process results_summary {
    input: val(done)
    output: path("summary.txt")
    script: """
    echo complete > summary.txt
    """
}
'''


@unittest.skipUnless(shutil.which("nextflow"), "Nextflow is required for mode routing tests")
class ModeRoutingTests(unittest.TestCase):
    def test_normalization_and_removed_flags(self):
        source = (ROOT / "main.nf").read_text()
        normalizer = "String normalizePipelineMode" + source.split(
            "String normalizePipelineMode", 1)[1].split("def pipelineMode", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "normalize.nf"
            script.write_text(normalizer + '''
assert normalizePipelineMode(null) == 'full'
assert normalizePipelineMode('FULL') == 'full'
for (mode in ['runassessor', 'organism', 'search', 'agentic']) {
    for (separator in [' ', '-', '_']) {
        assert normalizePipelineMode(" ${mode}${separator}only ") == "${mode}_only"
    }
}
for (invalid in ['', 'unknown', 'organism', true, false]) {
    try {
        normalizePipelineMode(invalid)
        assert false: "Accepted invalid mode ${invalid}"
    } catch (IllegalArgumentException expected) {
        assert expected.message.contains('Invalid --mode')
    }
}
workflow {}
''')
            env = {**os.environ, "NXF_OFFLINE": "true", "NXF_ANSI_LOG": "false"}
            result = subprocess.run(
                ["nextflow", "-log", str(root / "normalize.log"), "run", str(script)],
                cwd=root, env=env, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout)
            for arguments, message in (
                (["--run_search", "false"], "--run_search has been removed"),
                (["--mode", "invalid"], "Invalid --mode"),
                (["--mode", "search only", "--update_from_existing", "true"],
                 "--update_from_existing requires --existing_results_dir"),
            ):
                with self.subTest(arguments=arguments):
                    result = subprocess.run(
                        ["nextflow", "-log", str(root / "validation.log"), "run",
                         str(ROOT / "main.nf"), *arguments],
                        cwd=root, env=env, text=True, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, timeout=120)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn(message, result.stdout)

    def test_all_modes_route_and_partial_modes_publish_updated_aggregates(self):
        source = (ROOT / "main.nf").read_text()
        prefix = source.split("/* -----------------------\n * PROCESS: determine_acquisition_params", 1)[0]
        aggregate_process = "process aggregate_results {" + source.split(
            "process aggregate_results {", 1)[1].split(
                "/* -----------------------\n * PROCESS: create_minimal_aggregated_results", 1)[0]
        taxid_process = "process determine_taxids {" + source.split(
            "process determine_taxids {", 1)[1].split(
                "/* -----------------------\n * PROCESS: fetch_pxd", 1)[0]
        expected = {
            "full": {"fetch_pxd", "determine_acquisition_params", "organism_id", "determine_taxids",
                     "search", "aggregate_results", "agentic_metadata_extraction", "llm_judge",
                     "finalize_sdrf", "results_summary"},
            "runassessor only": {"fetch_pxd", "aggregate_results", "results_summary"},
            "organism only": {"fetch_pxd", "determine_acquisition_params", "organism_id",
                              "aggregate_results", "results_summary"},
            "search only": {"fetch_pxd", "determine_acquisition_params", "determine_taxids",
                            "search", "aggregate_results", "results_summary"},
            "agentic only": {"agentic_metadata_extraction", "llm_judge", "finalize_sdrf", "results_summary"},
        }
        for mode, processes in expected.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "src").symlink_to(ROOT / "src", target_is_directory=True)
                script = root / "modes.nf"
                script.write_text(prefix + STUB_PROCESSES + aggregate_process + taxid_process)
                prior = root / f"prior/{PXD}"
                prior.mkdir(parents=True)
                (prior / f"{PXD}_aggregated_results.json").write_text(json.dumps(stored_aggregate()))
                spectra = root / f"spectra/{PXD}"
                (spectra / "runAssessor").mkdir(parents=True)
                (spectra / "runAssessor/study_metadata.json").write_text('{"files":{"sample.mzML":{}}}')
                (spectra / "sample.mzML").write_text("fixture")
                if mode in ("full", "organism only"):
                    (root / "reference.fasta").write_text(">fixture\nPEPTIDE\n")
                    (root / "taxids.csv").write_text("taxid\n9606\n")
                bin_dir = root / "bin"
                bin_dir.mkdir()
                conda = bin_dir / "conda"
                conda.write_text(f'#!/bin/sh\nshift\nshift 2\nshift\nexec "{sys.executable}" "$@"\n')
                conda.chmod(0o755)
                config = root / "nextflow.config"
                config.write_text(f'''
params {{
    mode = 'full'
    pxd = '{PXD}'
    outdir = '{root}/results'
    central_mzml_dir = '{root}/spectra'
    meti_env_path = '{Path(sys.executable).parent.parent}'
    organism_id_submodule_dir = '{ROOT}/submodules/MassSpecOrganismID'
    contaminants_fasta = '{root}/reference.fasta'
    taxid_blocks_file = '{root}/taxids.csv'
    conda_init = 'true'
    run_llm_extraction = false
    stage_manifest = null
    update_stage_manifest = null
    max_raw_files = 1
}}
process {{
    executor = 'local'
    cpus = 1
    memory = '128 MB'
}}
''')
                trace = root / "trace.tsv"
                command = ["nextflow", "-log", str(root / "nextflow.log"), "run", str(script),
                           "-w", str(root / "work"), "-with-trace", str(trace), "--mode", mode]
                if mode == "agentic only":
                    command += ["--aggregated_results_dir", str(prior)]
                else:
                    command += ["--update_from_existing", "true", "--existing_results_dir", str(prior.parent)]
                result = subprocess.run(
                    command, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    timeout=180, env={**os.environ, "NXF_OFFLINE": "true", "NXF_ANSI_LOG": "false",
                                      "PATH": f"{bin_dir}:{os.environ['PATH']}"})
                self.assertEqual(result.returncode, 0, result.stdout)
                rows = [line.split("\t") for line in trace.read_text().splitlines()]
                names = {row[rows[0].index("name")].split(" (")[0] for row in rows[1:]}
                self.assertEqual(names, processes, result.stdout)
                if mode != "agentic only":
                    output = root / f"results/{PXD}/{PXD}_aggregated_results.json"
                    self.assertTrue(output.exists(), result.stdout)
                    data = json.loads(output.read_text())
                    self.assertEqual(data["custom_section"], stored_aggregate()["custom_section"])
                    if mode == "search only":
                        self.assertEqual(data["organism_identification"], stored_aggregate()["organism_identification"])
                        mappings = list((root / "work").glob("*/*/taxid_mapping.json"))
                        self.assertEqual(json.loads(mappings[0].read_text())["mappings"]["sample.raw"]["taxid"], "10090")
                    if mode == "organism only":
                        self.assertEqual(data["Search_and_modification_results"], {"old": "search"})


if __name__ == "__main__":
    unittest.main()
