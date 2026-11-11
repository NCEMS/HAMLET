# HAMLET Key Output Files

Set `${RUN_DIR}` to the absolute path of the HAMLET run directory. Replace the other variables with values for the run:

- `${PXD}`: PRIDE project accession, for example `PXD005463`.
- `${SAMPLE}`: a sample file basename without `.raw` or `.mzML`.
- `${FILTER_THRESHOLD}`: integer peptide-score threshold percentage, for example `70`.
- `${PUBMED_ID}`: PubMed identifier associated with the project.
- `${SLURM_JOB_ID}`: SLURM job identifier.

| Column label | Absolute generalized path | Description |
|---|---|---|
| `nextflow_log` | `${RUN_DIR}/nextflow.log` | Main Nextflow execution log, including process scheduling, caching, failures, and run completion details. |
| `aggregated_results` | `${RUN_DIR}/results/${PXD}/${PXD}_aggregated_results.json` | Combined project-level output containing runAssessor, organism identification, search, metadata, and pipeline summaries. |
| `pipeline_summary` | `${RUN_DIR}/results/${PXD}/${PXD}_pipeline.json` | Project-level pipeline status, event, warning, decision, and missing-output summary. |
| `generated_sdrf` | `${RUN_DIR}/results/${PXD}/agentic_metadata/${PXD}.sdrf.tsv` | Final agent-generated SDRF metadata table for the project samples. |
| `biological_metadata` | `${RUN_DIR}/results/${PXD}/agentic_metadata/metadata_extraction_output/integrated_output/BiologicalAgent/temp_0.0/${PXD}_PubText_enriched.json` | Biological metadata extracted and enriched from project and publication evidence. |
| `experimental_design_metadata` | `${RUN_DIR}/results/${PXD}/agentic_metadata/metadata_extraction_output/integrated_output/ExperimentalDesignAgent/temp_0.0/${PXD}_PubText_enriched.json` | Extracted experimental-design metadata, including samples, conditions, and study structure. |
| `technical_metadata` | `${RUN_DIR}/results/${PXD}/agentic_metadata/metadata_extraction_output/integrated_output/TechnicalAgent/temp_0.0/${PXD}_PubText_enriched.json` | Extracted technical metadata describing acquisition, preparation, instrumentation, and analysis. |
| `casanovo_mztab` | `${RUN_DIR}/results/${PXD}/organism_results/CasanovoSequence/${PXD}_${SAMPLE}/${PXD}_${SAMPLE}.mztab` | Casanovo de novo peptide-spectrum predictions. One non-empty file is required for every processed sample. |
| `filtered_peptides` | `${RUN_DIR}/results/${PXD}/organism_results/CasanovoSequence/${PXD}_${SAMPLE}/${PXD}_${SAMPLE}_filtered${FILTER_THRESHOLD}pct.tsv` | Casanovo predictions retained after applying the configured peptide-score threshold. One non-empty file is required for every processed sample. |
| `peptonizer_result` | `${RUN_DIR}/results/${PXD}/organism_results/CasanovoSequence/${PXD}_${SAMPLE}/Peptonizer2000_data/${PXD}_${SAMPLE}_filtered${FILTER_THRESHOLD}pct_slim/peptonizer_result.csv` | Peptonizer2000 taxon scores inferred from filtered de novo peptides. One non-empty file is required for every processed sample. |
| `peptonizer_plot` | `${RUN_DIR}/results/${PXD}/organism_results/CasanovoSequence/${PXD}_${SAMPLE}/Peptonizer2000_data/${PXD}_${SAMPLE}_filtered${FILTER_THRESHOLD}pct_slim/peptonizer_result.png` | Visualization of Peptonizer2000 organism-identification scores. One non-empty file is required for every processed sample. |
| `runassessor_metadata` | `${RUN_DIR}/results/${PXD}/runAssessor/study_metadata.json` | runAssessor-derived acquisition characteristics, spectral statistics, tolerances, labeling, and quality findings. |
| `sdrf_judge_result` | `${RUN_DIR}/results/${PXD}/sdrf_judge/json_outputs/${PXD}.json` | Structured SDRF quality-judging results and field-level assessments for the project. |
| `sdrf_judge_accuracy_plot` | `${RUN_DIR}/results/${PXD}/sdrf_judge/llm_judge_accuracy.png` | Plot summarizing SDRF judge accuracy metrics. |
| `sdrf_judge_per_paper` | `${RUN_DIR}/results/${PXD}/sdrf_judge/llm_judge_per_paper.csv` | Per-publication SDRF judge scores and evaluation metrics. |
| `sage_open_search_psms` | `${RUN_DIR}/results/${PXD}/search/dda_search/Open/search_results.tsv` | SAGE open-search peptide-spectrum matches and associated scores. |
| `stage_manifest` | `${RUN_DIR}/results/pipeline_stage_manifest.json` | Run-level manifest recording stage statuses, output locations, and execution provenance. |
| `slurm_log` | `${RUN_DIR}/slurm_${SLURM_JOB_ID}.log` | Standard output and error captured by SLURM for the submitted HAMLET job. |
| `pride_metadata` | `${RUN_DIR}/spectral_files/${PXD}/${PXD}_PRIDEmetadata.json` | Project, sample, file, organism, instrument, and publication metadata retrieved from PRIDE. |
| `publication_metadata` | `${RUN_DIR}/spectral_files/${PXD}/pmc_json/${PXD}_${PUBMED_ID}.json` | Full-text publication metadata and evidence retrieved for the project-associated PubMed record. |
