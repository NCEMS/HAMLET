import json, os, shutil, sys
from pathlib import Path

REPO = Path(os.environ.get("HAMLET_REPO", Path.cwd())).resolve()
if not (REPO / "src" / "python" / "sdrf_builder.py").exists():
    raise SystemExit(f"Not a HAMLET repo: {REPO}. Run from the repo root, or set HAMLET_REPO.")
sys.path.insert(0, str(REPO / "src" / "agentic-metadata"))
sys.path.insert(0, str(REPO / "src" / "python"))
from agents.integration_agent import IntegrationAgent
from sdrf_builder import AgenticToSDRF

RAW = {
    "BiologicalAgent": "Biological_annotations",
    "TechnicalAgent": "technical_metadata_output",
    "ExperimentalDesignAgent": "experimental_design_output",
}


def build(pxd, outdir, force_labeling=None):
    outdir = Path(outdir)
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    agg_src = REPO / "store/aggregated_results_files" / f"{pxd}_aggregated_results.json"
    agg_path = outdir / agg_src.name
    if force_labeling:
        agg = json.loads(agg_src.read_text())
        agg["runAssessor"]["search_criteria"]["labeling"] = force_labeling
        agg_path.write_text(json.dumps(agg))
    else:
        shutil.copy(agg_src, agg_path)

    meti = outdir / "meti"
    meti.mkdir()
    shutil.copy(agg_path, meti / agg_path.name)

    agent = IntegrationAgent(str(meti))
    paths = {}
    for name, sub in RAW.items():
        src = REPO / "store/agentic_results_files" / pxd / sub / "temp_0.0" / f"{pxd}_PubText.json"
        enriched = agent.enrich(pxd, json.loads(src.read_text()), agent_type=name)
        dst = outdir / f"integrated_output/{name}/temp_0.0/{pxd}_PubText_enriched.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(json.dumps(enriched, indent=2))
        paths[name] = dst

    AgenticToSDRF(paths["TechnicalAgent"], paths["BiologicalAgent"],
                  paths["ExperimentalDesignAgent"], agg_path).to_sdrf(outdir / f"{pxd}.sdrf.tsv")
    shutil.rmtree(meti)
    agg_path.unlink()


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
