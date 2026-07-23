nextflow.enable.dsl = 2

boolean isDetectedDia(def detected_params_file) {
    try {
        def json = new groovy.json.JsonSlurper().parse(new File(detected_params_file.toString()))
        def diaVal = json?.detected_params?.DIA
        return (diaVal == true) || (diaVal?.toString()?.toLowerCase() == 'true')
    } catch (Exception e) {
        log.warn("Could not parse detected_params JSON at ${detected_params_file}; defaulting to DDA workflow. Reason: ${e.message}")
        return false
    }
}

String normalizeAcquisitionType(def acquisition_type) {
    return (acquisition_type ?: 'AUTO').toString().trim().toUpperCase()
}

def printPipelineHelp() {
    println """
HAMLET annotator Nextflow pipeline

USAGE
    nextflow run main.nf [nextflow options] --pxd <PXD...> [pipeline params]
    nextflow run main.nf [nextflow options] --pxd_csv <PXDs.csv> [pipeline params]
    nextflow run main.nf [nextflow options] --agentic_only true [--aggregated_results_dir <dir>]

NEXTFLOW OPTIONS (runtime)
    nextflow help run

PIPELINE PARAMS (this workflow)
    Input selection (required: choose one)
        --pxd <PXD000000>                 Single PXD accession
        --pxd_csv <PXDs.csv>              CSV with PXD IDs (first column)
        --num_pxds <N>                    Limit number of PXDs from CSV
        --agentic_only true               Skip organism_id, determine_taxids, search;
                                          create minimal aggregated results from
                                          fetch/run_assessor/determine_acq_params
                                          then run metadata extraction onwards
                                          (requires --pxd or --pxd_csv)

    Acquisition type routing
        --acquisition_type AUTO|DDA|DIA   Default: AUTO
            AUTO: per-PXD routing uses detected_params.json
            DDA : force DDA workflow/container for all PXDs
            DIA : force DIA workflow/container for all PXDs

    Detection
        --auto_detect true|false          Default: true

    Organism ID
        --denovo_threshold <N>            Default: 70 (may be overridden in config)
        --min_peptides_for_peptonizer <N> Default: 100 (may be overridden in config)

    Search
        --taxid <taxid>                               Default: 9606 (may be overridden)
        --search_min_ptm_psms <N>                     Default: 50
        --search_max_variable_mods <N>                Default: 4

    Download control
        --max_raw_files <N>               Default: 30 (null = all)
        --use_aria2c true|false           Default: true
        --aria2c_threads <N>              Default: 4
        --max_parallel_pxds <N>           Default: 10
        --download_timeout <duration>     Default: 4h
        --stage_manifest <path>           Default: results/pipeline_stage_manifest.json
            Manifest with per-PXD, per-stage Availability/Complete/key_outputs.

    Agentic-only mode
        --agentic_only true               Enable agentic-only mode
        --aggregated_results_dir <dir>    Directory with *_aggregated_results.json files
                                          Default: store/aggregated_results_files

    LLM metadata extraction
        --run_llm_extraction true|false   Default: false

    Organism ID sampling
        --organism_id_all true|false      Default: false
            false: if PRIDE + LLM both report a single taxid, run de novo +
                   Peptonizer on one representative file and broadcast the
                   result to all files in the PXD (saves GPU time)
            true : always run organism_id on every file

EXAMPLES
    # AUTO routing (default), multiple PXDs
    nextflow run main.nf --pxd_csv PXDs.csv -resume

    # Force DIA for everything
    nextflow run main.nf --pxd_csv PXDs.csv --acquisition_type DIA -resume

    # Single PXD (stage behavior controlled by stage_manifest)
    nextflow run main.nf --pxd PXD000070 -resume

    # Agentic-only: skip search stages, create minimal aggregated results, run metadata extraction
    nextflow run main.nf --agentic_only true --pxd_csv GSlist0.csv -resume
"""
}

/* -----------------------
 * params with defaults
 * --------------------- */
// Input modes: either single PXD or CSV file with multiple PXDs
params.pxd                = params.pxd                ?: null          // Single PXD to process
params.pxd_csv            = params.pxd_csv            ?: null          // CSV file with PXDs to process
params.num_pxds           = params.num_pxds           ?: null          // Limit number of PXDs from CSV (null = all)

params.year               = params.year               ?: '2021'
params.month              = params.month              ?: '09'
params.day                = params.day                ?: '01'
params.central_mzml_dir   = params.central_mzml_dir   ?: "${baseDir}/spectral_files"
params.outdir             = params.outdir             ?: "${baseDir}/results"
params.contaminants_fasta = params.contaminants_fasta ?: "${baseDir}/assets/UniversalContaminats.fasta"
params.taxid_list_file    = params.taxid_list_file    ?: "${baseDir}/assets/taxid_lists/CommonPRIDEtaxids.txt"

// No containers - all tools run via conda environments
// params.unified_container = removed (container-free pipeline)
// params.proteowizard_container = removed (container-free pipeline)
// params.proteowizard_wineprefix = removed (container-free pipeline)
params.sage_config        = params.sage_config        ?: "${baseDir}/assets/default_sage.config"

params.search_min_ptm_psms = params.search_min_ptm_psms ?: 50

params.search_max_variable_mods = params.search_max_variable_mods ?: 4  // Max variable mods (e.g., Phosphorylation, Oxidation)
params.high_confidence_q_threshold = params.high_confidence_q_threshold ?: 0.01
params.min_high_confidence_peptides = params.min_high_confidence_peptides ?: 10
params.taxid              = params.taxid              ?: '9606'
params.acquisition_type   = params.acquisition_type   ?: 'AUTO'  // AUTO, DDA, DIA
params.stage_manifest     = params.stage_manifest     ?: "${params.outdir}/pipeline_stage_manifest.json"

params.n_judge_runs         = params.n_judge_runs         ?: 3      // Number of judge runs for consensus (1 = single pass)
params.organism_id_all     = params.organism_id_all     ?: false  // Force organism_id on all files even when single taxid

// Organism identification parameters
params.denovo_threshold            = params.denovo_threshold            ?: 70
params.min_peptides_for_peptonizer = params.min_peptides_for_peptonizer ?: 100

// Cascadia model path (stored in repo assets, must be downloaded separately due to size)
params.cascadia_model_path = params.cascadia_model_path ?: "${baseDir}/assets/cascadia.ckpt"

// Peptonizer2000 source code path (runs directly from host, container-free)
params.peptonizer2000_host_path = params.peptonizer2000_host_path ?: "${baseDir}/src/Peptonizer2000"

// Auto-detection parameters (can be overridden by runAssessor results)
params.auto_detect = params.auto_detect ?: true  // Enable automatic parameter detection

// Search per-sample strategy for aggregation
// Controls both OPEN SEARCH (Pass 1) and CLOSED SEARCH (Pass 2) aggregation behavior:
//   false         = aggregate/pool both open and closed searches (default, fastest, bulk quantification)
//   true          = per-file closed search (per-sample quantification)
//   'closed_only' = per-file open search, aggregate closed search
//   'none'        = per-file for both open and closed searches

// Agentic-only mode: skip search and run metadata extraction on pre-computed aggregated results
params.agentic_only         = params.agentic_only         ?: false
params.aggregated_results_dir = params.aggregated_results_dir ?: "${baseDir}/store/aggregated_results_files"

workflow {

    def doHelp = params.containsKey('help') && (params.help == true || params.help?.toString()?.toLowerCase() == 'true')
    if( doHelp ) {
        printPipelineHelp()
        System.exit(0)
    }

    def acqType = normalizeAcquisitionType(params.acquisition_type)
    if( !(acqType in ['AUTO','DDA','DIA']) ) {
        error "Invalid --acquisition_type '${params.acquisition_type}'. Must be one of: AUTO, DDA, DIA"
    }

    log.info "Acquisition type mode: ${acqType}"

    // ==================== AGENTIC-ONLY WORKFLOW ====================
    // Run fetch, run_assessor, determine_acquisition_params; create minimal aggregated results;
    // skip organism_id, determine_taxids, search; run agentic metadata extraction
    if( params.agentic_only ) {
        log.info "=== AGENTIC-ONLY MODE ==="
        log.info "Pipeline: fetch → run_assessor → determine_acquisition_params → create_minimal_aggregated_results → agentic_metadata_extraction → llm_judge → finalize_sdrf"
        
        // Build PXD list from CSV or single PXD
        def pxd_list_agentic = []
        if (params.pxd_csv) {
            log.info "Reading PXDs from CSV: ${params.pxd_csv}"
            new File(params.pxd_csv).withReader { reader ->
                reader.readLine() // Skip header
                reader.eachLine { line ->
                    if (line.trim()) {
                        def parts = line.split(',')
                        if (parts[0].trim()) {
                            pxd_list_agentic << parts[0].trim()
                        }
                    }
                }
            }
        } else if (params.pxd) {
            pxd_list_agentic = [ params.pxd.toString().trim() ]
        } else {
            error "Must specify either --pxd (single PXD) or --pxd_csv (CSV file with PXDs) for agentic-only mode"
        }

        if (params.num_pxds) {
            pxd_list_agentic = pxd_list_agentic.take(params.num_pxds as int)
        }

        log.info "Will process ${pxd_list_agentic.size()} PXD(s) in agentic-only mode: ${pxd_list_agentic.join(', ')}"
        
        // Create channel from PXD list
        pxd_ch_agentic = Channel.fromList(pxd_list_agentic)
        
        // Fetch PXDs
        fetched_ch_agentic = fetch_pxd(pxd_ch_agentic)
            .map { pxd, work_path -> 
                tuple(pxd, file("${params.central_mzml_dir}/${pxd}"))
            }
        
        // Run runAssessor
        assessor_ch_agentic = run_assessor(fetched_ch_agentic)
            .map { pxd, fetched_dir, study_metadata -> tuple(pxd, fetched_dir, study_metadata) }
        
        // Determine acquisition parameters (with minimal LLM context)
        llm_results_ch_agentic = fetched_ch_agentic.map { pxd, fetched_dir ->
            def dummy_llm = file("${baseDir}/work/dummy_llm_${pxd}.empty")
            dummy_llm.parent.mkdirs()
            dummy_llm.text = ""
            tuple(pxd, dummy_llm)
        }
        
        acq_input_ch_agentic = assessor_ch_agentic
            .map { pxd, fetched_dir, study_metadata -> 
                tuple(pxd, fetched_dir, study_metadata)
            }
            .join(llm_results_ch_agentic, by: 0)
            .map { pxd, fetched_dir, study_metadata, llm_results ->
                tuple(pxd, fetched_dir, llm_results)
            }
        
        detected_ch_agentic = determine_acquisition_params(acq_input_ch_agentic)
        
        // Create minimal aggregated results
        minimal_agg_input_ch = assessor_ch_agentic
            .join(detected_ch_agentic, by: 0)
        
        minimal_agg_ch = create_minimal_aggregated_results(minimal_agg_input_ch)
        
        // Run agentic metadata extraction on minimal aggregated results
        agentic_input_ch_minimal = minimal_agg_ch
            .map { pxd, aggregated_results ->
                tuple(pxd, aggregated_results)
            }
        
        agentic_results_ch_minimal = agentic_metadata_extraction(agentic_input_ch_minimal)[0]
        
        // Run LLM judge
        llm_judge_input_ch_minimal = agentic_results_ch_minimal
            .map { pxd, metadata_extraction_output, aggregated_results -> tuple(pxd, metadata_extraction_output) }
        llm_judge_ch_minimal = llm_judge(llm_judge_input_ch_minimal)[0]
        
        // Finalize SDRF
        finalized_sdrf_input_ch_minimal = agentic_results_ch_minimal
            .join(llm_judge_ch_minimal)
            .map { pxd, metadata_extraction_output, aggregated_results, judge_output ->
                tuple(pxd, metadata_extraction_output, aggregated_results, judge_output)
            }
        finalized_sdrf_ch_minimal = finalize_sdrf(finalized_sdrf_input_ch_minimal)[0]
        
        // Run results summary
        results_summary(finalized_sdrf_ch_minimal.collect())
        
        return  // Exit early; skip main full workflow
    }
    
    // Ensure required directories exist for search infrastructure
    // DIA-NN needs diann_libraries directory to cache spectral libraries
    def diann_libs_dir = new File("${baseDir}/assets/diann_libraries")
    if (!diann_libs_dir.exists()) {
        log.info "Creating DIA-NN library cache directory: ${diann_libs_dir.absolutePath}"
        diann_libs_dir.mkdirs()
    }

    // Build PXD list from either single PXD or CSV file
    def pxd_list = []
    if (params.pxd_csv) {
        log.info "Reading PXDs from CSV: ${params.pxd_csv}"
        new File(params.pxd_csv).withReader { reader ->
            reader.readLine() // Skip header
            reader.eachLine { line ->
                if (line.trim()) {
                    def parts = line.split(',')
                    if (parts[0].trim()) {
                        pxd_list << parts[0].trim()
                    }
                }
            }
        }
    } else if (params.pxd) {
        pxd_list = [ params.pxd.toString().trim() ]
    } else {
        error "Must specify either --pxd (single PXD) or --pxd_csv (CSV file with PXDs)"
    }

    // Apply limit if specified
    if (params.num_pxds) {
        pxd_list = pxd_list.take(params.num_pxds as int)
    }

    if (pxd_list) {
        log.info "Will process ${pxd_list.size()} PXD(s) in parallel: ${pxd_list.join(', ')}"
    } else {
        log.info "No PXDs selected. Downstream steps will be skipped; results_summary will still run."
    }

    // Initialize/reconcile unified stage manifest before launching processes.
    // This computes stage completion from file checkpoints and preserves user-edited availability.
    def manifestCmd = [
        'python',
        "${baseDir}/src/python/stage_manifest.py",
        'init',
        '--manifest', params.stage_manifest.toString(),
        '--base_dir', baseDir.toString(),
        '--outdir', params.outdir.toString(),
        '--central_dir', params.central_mzml_dir.toString(),
        '--pxds', pxd_list.join(','),
    ]
    def manifestProc = new ProcessBuilder(manifestCmd.collect { it.toString() })
        .directory(new File(baseDir.toString()))
        .redirectErrorStream(true)
        .start()
    def manifestOut = manifestProc.inputStream.getText('UTF-8')
    def manifestRc = manifestProc.waitFor()
    if (manifestOut?.trim()) {
        log.info manifestOut.trim()
    }
    if (manifestRc != 0) {
        error "Failed to initialize stage manifest at ${params.stage_manifest} (exit=${manifestRc})"
    }

    // Create channel from final list
    pxd_ch = Channel.fromList(pxd_list)

    // Fetch all PXDs (runs in parallel)
    // Output: [pxd, fetched_dir]
    // fetch_pxd produces: tuple(pxd, fetched_dir)  
    fetched_ch = fetch_pxd(pxd_ch)
        .map { pxd, work_path -> 
            // Use stable canonical path instead of work-dir symlink for downstream cache stability
            tuple(pxd, file("${params.central_mzml_dir}/${pxd}"))
        }

    // Run runAssessor as an explicit pipeline stage so it can be rerun independently
    // (e.g., after updating the runAssessor submodule).
    assessor_ch = run_assessor(fetched_ch)
        .map { pxd, fetched_dir, study_metadata -> tuple(pxd, fetched_dir) }

    // Run LLM-based metadata extraction from publications FIRST.
    // LLM results inform determine_acquisition_params (e.g., Comment[AcquisitionMethod]).
    // Output: [pxd, llm_results]
    if (params.run_llm_extraction) {
        llm_results_ch = llm_extraction(fetched_ch)
    } else {
        llm_results_ch = fetched_ch.map { pxd, fetched_dir ->
            def dummy_llm = file("${baseDir}/work/dummy_llm_${pxd}.empty")
            dummy_llm.parent.mkdirs()
            dummy_llm.text = ""
            tuple(pxd, dummy_llm)
        }
    }

    // determine_acquisition_params consumes LLM input, but later stages still need the same
    // per-PXD metadata. Split once here, then carry LLM context forward with the PXD record.
    llm_results_ch
        .multiMap { pxd, llm_results ->
            for_detect: tuple(pxd, llm_results)
            for_context: tuple(pxd, llm_results)
        }
        .set { llm_split }

    llm_for_detect_ch = llm_split.for_detect
    llm_for_context_ch = llm_split.for_context

    // Auto-detect acquisition type and labeling after LLM extraction so LLM metadata is available.
    // Output: [pxd, fetched_dir, detected_params_json]
    if (params.auto_detect) {
        acq_input_ch = assessor_ch.join(llm_for_detect_ch, by: 0)
        detected_ch = determine_acquisition_params(acq_input_ch)
    } else {
        detected_ch = assessor_ch.join(llm_for_detect_ch, by: 0).map { pxd, fetched_dir, llm_results ->
            error "Manual parameter specification not yet supported in parallel mode. Use --auto_detect true"
        }
    }

    // Re-attach LLM metadata immediately after acquisition detection so downstream stages can
    // work from one per-PXD context channel instead of repeatedly rejoining raw LLM outputs.
    detected_with_llm_ch = detected_ch.join(llm_for_context_ch, by: 0)

    // If acquisition type is forced, normalize detected_params.json so downstream steps
    // (e.g., search orchestration) follow the requested workflow for all PXDs.
    if( acqType == 'DIA' || acqType == 'DDA' ) {
        def forceDia = (acqType == 'DIA')
        detected_ch = detected_ch.map { pxd, fetched_dir, detected_params ->
            def forced_detected = file("${baseDir}/work/forced_detected_params_${pxd}.json")
            forced_detected.parent.mkdirs()
            try {
                def json = new groovy.json.JsonSlurper().parse(new File(detected_params.toString()))
                if( json?.detected_params == null ) {
                    json.detected_params = [:]
                }
                json.detected_params.DIA = forceDia
                forced_detected.text = groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(json))
            } catch (Exception e) {
                log.warn("Could not rewrite detected_params JSON at ${detected_params}; creating minimal forced file. Reason: ${e.message}")
                def json = [detected_params: [DIA: forceDia]]
                forced_detected.text = groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(json))
            }
            tuple(pxd, fetched_dir, forced_detected)
        }
    }

    // Create channels for input files (these are shared across all PXDs)
    contaminants_ch = Channel.fromPath(params.contaminants_fasta, checkIfExists: true)
    taxid_list_ch = Channel.fromPath(params.taxid_list_file, checkIfExists: true)

    // Split the detected per-PXD context once at the point where downstream branches diverge.
    detected_with_llm_ch
        .multiMap { pxd, fetched_dir, detected_params, llm_results ->
            for_organism: tuple(pxd, fetched_dir, detected_params, llm_results)
            for_taxid_context: tuple(pxd, fetched_dir, detected_params, llm_results)
        }
        .set { detected_split }

    // Route to appropriate conda environment (DIA vs DDA) based on detected_params.json.
    // The organism_id process needs both static reference files and per-PXD LLM metadata.
    organism_input_ch = detected_split.for_organism
        .combine(contaminants_ch)
        .combine(taxid_list_ch)
        .map { pxd, fetched_dir, detected_params, llm_results, contaminants_fasta, taxid_list_file ->
            tuple(pxd, fetched_dir, detected_params, contaminants_fasta, taxid_list_file, llm_results)
        }

    // Run organism_id for all PXDs; stage_manifest controls per-PXD run/skip behavior.
    log.info "Running organism_id process (manifest-controlled per PXD)"
    // Keep per-PXD streaming semantics: each PXD advances downstream as soon as
    // its own organism_id result is available.
    organism_with_context_ch = organism_id(organism_input_ch)
    
    // Extract just organism_results for downstream processes that don't need context
    organism_results_ch = organism_with_context_ch.map { pxd, fetched_dir, detected_params, organism_results ->
        tuple(pxd, organism_results)
    }
    
    // Build taxid-ready per-PXD context anchored on acquisition detection so determine_taxids
    // still runs even when organism_id is ignored. Missing organism results fall back to an
    // empty directory, but the PXD record stays intact.
    def emptyOrganismDir = file("${baseDir}/work/empty_organism")
    emptyOrganismDir.mkdirs()
    if (!emptyOrganismDir.resolve("empty.json").exists()) {
        emptyOrganismDir.resolve("empty.json").text = "{}"
    }

    taxid_context_ch = detected_split.for_taxid_context
        .join(organism_results_ch, by: 0, remainder: true)
        .map { pxd, fetched_dir, detected_params, llm_results, organism_results ->
            tuple(pxd, fetched_dir, detected_params, llm_results, organism_results ?: emptyOrganismDir)
        }

    // Split the taxid-ready context into the distinct process inputs that need it.
    taxid_context_ch
        .multiMap { pxd, fetched_dir, detected_params, llm_results, organism_results ->
            for_taxids: tuple(pxd, fetched_dir, organism_results, llm_results)
            for_search: tuple(pxd, fetched_dir, detected_params)
            for_aggregate: tuple(pxd, fetched_dir, organism_results, llm_results)
            for_agentic: tuple(pxd, llm_results)
        }
        .set { taxid_context_split }

    taxid_input_ch = taxid_context_split.for_taxids
    
    // Determine taxids for each raw file from organism_id, LLM, and PRIDE metadata
    // Output: [pxd, taxid_mapping.json, warnings.json]
    taxid_mapping_ch = determine_taxids(taxid_input_ch)
    
    // Split taxid_mapping once so search and aggregation do not compete for the same queue items.
    taxid_mapping_ch
        .multiMap { pxd, mapping, warnings ->
            for_search: tuple(pxd, mapping)
            for_aggregate: tuple(pxd, warnings)
        }
        .set { taxid_mapping_split }

    // Run search for all PXDs; stage_manifest controls per-PXD run/skip behavior.
    search_input_ch = taxid_context_split.for_search
        .join(taxid_mapping_split.for_search, by: 0)
    search_results_ch = search(search_input_ch)
    
    // Build the aggregate input from the per-PXD context plus the two process outputs that
    // become available after taxid selection.
    aggregate_input_ch = taxid_context_split.for_aggregate
        .join(search_results_ch, by: 0)
        .join(taxid_mapping_split.for_aggregate, by: 0)
        .map { pxd, fetched_dir, organism_results, llm_results, search_results, taxid_warnings ->
            tuple(pxd, fetched_dir, organism_results, search_results, llm_results, taxid_warnings)
        }

    // Run aggregation after all per-PXD inputs are available.
    aggregated_results_ch = aggregate_results(aggregate_input_ch)[0]
    
    // Run downstream metadata/judge/finalize for all PXDs; stage_manifest controls per-PXD run/skip behavior.
    agentic_input_ch = aggregated_results_ch
        .map { pxd, aggregated_results, pipeline_json, pipeline_summary -> tuple(pxd, aggregated_results) }

    agentic_results_ch = agentic_metadata_extraction(agentic_input_ch)[0]

    llm_judge_input_ch = agentic_results_ch
        .map { pxd, metadata_extraction_output, aggregated_results -> tuple(pxd, metadata_extraction_output) }

    llm_judge_ch = llm_judge(llm_judge_input_ch)[0]

    finalized_sdrf_input_ch = agentic_results_ch
        .join(llm_judge_ch)
        .map { pxd, metadata_extraction_output, aggregated_results, judge_output ->
            tuple(pxd, metadata_extraction_output, aggregated_results, judge_output)
        }

    finalized_sdrf_ch = finalize_sdrf(finalized_sdrf_input_ch)[0]

    // Run ResultsSummary once after pipeline completion
    results_summary(finalized_sdrf_ch.collect())
}


/* -----------------------
 * PROCESS: determine_acquisition_params
 * --------------------- */
process determine_acquisition_params {

    tag "acqparams-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: false

    cache false

    errorStrategy 'ignore'  // Skip PXDs that fail auto-detection

    input:
    tuple val(pxd), path(fetched_dir), path(llm_results)

    output:
    tuple val(pxd), path(fetched_dir), path("detected_params.json")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage determine_acquisition_params || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi

    # Determine acquisition type and labeling from runAssessor + LLM + PRIDE evidence.
    # The script writes a persistent copy to spectral_files/<PXD>/detected_params.json
    # and reuses it on subsequent runs (skip-if-exists logic is inside the Python script).
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/determine_acquisition_params.py \\
        --input_dir ${fetched_dir} \\
        --output detected_params.json \\
        --central_mzml_dir ${params.central_mzml_dir} \\
        --pxd ${pxd} \\
        --llm_results_dir ${llm_results}

    # Display results
    echo "Detected parameters:"
    cat detected_params.json

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage determine_acquisition_params || true
    """
}

/* -----------------------
 * PROCESS: create_minimal_aggregated_results
 * --------------------- */
process create_minimal_aggregated_results {

    tag "minimal-agg-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true

    cache false

    errorStrategy 'finish'

    input:
    tuple val(pxd), path(fetched_dir, stageAs: "fetched/*"), path(study_metadata), path(detected_dir, stageAs: "detected/*")

    output:
    tuple val(pxd), path("${pxd}_aggregated_results.json")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    # detected_dir is a directory from determine_acquisition_params, extract the JSON
    detected_params_json=\$(find detected -name 'detected_params.json' -type f | head -1)

    python ${baseDir}/src/python/create_minimal_aggregated_results.py \\
        --pxd ${pxd} \\
        --fetched_dir fetched \\
        --study_metadata ${study_metadata} \\
        --detected_params "\$detected_params_json" \\
        --output ${pxd}_aggregated_results.json

    ls -lh ${pxd}_aggregated_results.json
    """
}

/* -----------------------
 * PROCESS: llm_extraction
 * --------------------- */
process llm_extraction {

    tag "llm-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: false

    cache 'deep'
    
    errorStrategy 'ignore'  // Continue pipeline even if LLM extraction fails

    input:
    tuple val(pxd), path(fetched_dir)

    output:
    tuple val(pxd), path("llm_results")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    # Create output directory
    mkdir -p llm_results

    # Skip if LLM results already exist in spectral_files (persistent cache)
    central_llm="${params.central_mzml_dir}/${pxd}/llm_results"
    if [ -d "\$central_llm" ] && [ "\$(ls -A \$central_llm 2>/dev/null)" ]; then
        echo "✓ Using cached LLM results from spectral_files: \$central_llm"
        cp -r "\$central_llm/." llm_results/
        exit 0
    fi
    
    # Check if OPENAI_API_KEY is set (use parameter expansion to avoid unbound variable error)
    if [ -z "\${OPENAI_API_KEY:-}" ]; then
        echo "WARNING: OPENAI_API_KEY not set. Skipping LLM extraction."
        echo '{}' > llm_results/empty.json
        exit 0
    fi
    
    # Step 1: Extract publication text from database
    echo "=== Extracting publication text for ${pxd} ==="
    
    # Create temporary CSV with just this PXD (use 'PXD' column name consistent with pipeline)
    echo "PXD" > temp_pxd.csv
    echo "${pxd}" >> temp_pxd.csv
    
    # Run GetTextcsvs.py to extract publication text
    # Use fetched_dir which points to central_mzml_dir/PXD* where metadata is stored
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/GetTextcsvs.py \
        --PXDcsv temp_pxd.csv \
        --results_path ${fetched_dir} \
        --outpath llm_results \
        --log_file events.jsonl || {
            echo "WARNING: Failed to extract publication text for ${pxd}"
            echo '{}' > llm_results/empty.json
            exit 0
        }
    
    # Check if publication text was found
    if [ ! -f "llm_results/PubText.json" ]; then
        echo "WARNING: No publication text found for ${pxd}"
        echo '{}' > llm_results/empty.json
        exit 0
    fi
    
    # Step 2: Run LLM extraction
    echo "=== Running LLM extraction for ${pxd} ==="
    
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/GPT_Extraction.py \\
        --inpath llm_results/PubText.json \\
        --prompt ${baseDir}/src/BaselinePrompt.txt \\
        --outpath llm_results \\
        --workers ${params.llm_workers} \\
        --PXD ${pxd} || {
            echo "WARNING: LLM extraction failed for ${pxd}"
            echo '{}' > llm_results/empty.json
            exit 0
        }
    
    echo "=== LLM extraction completed for ${pxd} ==="
    ls -la llm_results/

    # Persist results to spectral_files for future reruns
    central_llm="${params.central_mzml_dir}/${pxd}/llm_results"
    mkdir -p "\$central_llm"
    cp -r llm_results/. "\$central_llm/"
    echo "✓ LLM results persisted to spectral_files: \$central_llm"
    """
}

/* -----------------------
 * PROCESS: determine_taxids
 * --------------------- */
process determine_taxids {

    tag "taxid-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: false

    cache 'deep'

    errorStrategy 'ignore'  // Skip PXDs that fail taxid determination

    input:
    tuple val(pxd), path(fetched_dir), path(organism_results), path(llm_results)

    output:
    tuple val(pxd), path("taxid_mapping.json"), path("taxid_warnings.json")

    script:
    def default_taxid_arg = params.taxid ? "--default_taxid ${params.taxid}" : ""
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage determine_taxids || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi
    
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/determine_taxids.py \\
        --pxd ${pxd} \\
        --fetched_dir ${fetched_dir} \\
        --organism_results ${organism_results} \\
        --llm_results ${llm_results} \\
        ${default_taxid_arg} \\
        --output_mapping taxid_mapping.json \\
        --output_warnings taxid_warnings.json

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage determine_taxids || true
    """
}

/* -----------------------
 * PROCESS: fetch_pxd
 * --------------------- */
process fetch_pxd {

    tag "fetch-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: false

    // No caching - let FetchPXD.py handle cache logic internally
    // It checks for existing files and creates symlinks in work directory when needed
    cache false
    
    // Allow pipeline to continue if a specific PXD fails to download
    errorStrategy 'ignore'

    input:
    val pxd

    output:
    tuple val(pxd), path("${pxd}"), optional: true

    script:
    def aria2c_args = params.use_aria2c ? "--use_aria2c --aria2c_threads ${params.aria2c_threads}" : ""
    def max_files_arg = params.max_raw_files ? "--max_raw_files ${params.max_raw_files}" : ""
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage fetch || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi
    
    # FetchPXD.py handles all caching logic:
    # 1. Checks if files exist in central_mzml_dir
    # 2. If yes: creates symlink ${pxd} -> central_mzml_dir/PXD and exits (no re-download)
    # 3. If no: downloads and converts files to central_mzml_dir/PXD, then creates symlink
    # This way, empty central_mzml_dir won't cause false cache hits
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/FetchPXD.py \\
        --central_mzml_dir ${params.central_mzml_dir} \
        --PXD ${pxd} \
        --skip_run_assessor \
        ${aria2c_args} \
        ${max_files_arg} \
        --log_file fetch/events.jsonl

    # Clean up original .raw files after conversion to .mzML
    # Keep only .mzML files to save disk space (all downstream processes use only .mzML)
    echo "Cleaning up original .raw files..."
    find ${pxd} -type f -iname "*.raw" -delete
    echo "✓ Original .raw files removed"

    ls -R ${pxd} || true

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage fetch || true
    """
}

/* -----------------------
 * PROCESS: run_assessor
 * --------------------- */
process run_assessor {

    tag "assessor-${pxd}"

    publishDir "${params.outdir}/${pxd}/runAssessor", mode: 'copy', overwrite: false

    cache false

    errorStrategy 'terminate'

    input:
    tuple val(pxd), path(fetched_dir)

    output:
    tuple val(pxd), path(fetched_dir), path("study_metadata.json")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage run_assessor || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        cp ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json study_metadata.json
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi

    assessor_script="${params.runassessor_script}"
    if [ ! -f "\$assessor_script" ]; then
        echo "ERROR: runAssessor script not found at \$assessor_script"
        exit 1
    fi

    if ! conda run -p ${params.meti_env_path} python -c "import pypdf" >/dev/null 2>&1; then
        echo "ERROR: pypdf is required in meti_env for submodule runAssessor"
        exit 1
    fi

    mkdir -p ${params.central_mzml_dir}/${pxd}/runAssessor

    # Build modern RunAssessor CLI invocation and append staged mzML inputs.
    if [[ "\$assessor_script" == *"/src/runassessor.py" ]]; then
        assessor_cmd=(
            conda run -p ${params.meti_env_path} python "\$assessor_script"
            --verbose
            --metadata_filepath ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json
        )
        shopt -s nullglob
        for mzml in ${fetched_dir}/*.mzML ${fetched_dir}/*.mzML.gz; do
            assessor_cmd+=("\$mzml")
        done
        shopt -u nullglob

        if [ \${#assessor_cmd[@]} -le 8 ]; then
            echo "WARNING: No mzML files found for ${pxd}; writing empty study_metadata.json"
            echo '{}' > ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json
            cp ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json study_metadata.json
            exit 0
        fi

        "\${assessor_cmd[@]}"
        assessor_rc=\$?
    else
        echo "ERROR: Unsupported runAssessor entrypoint: \$assessor_script"
        exit 1
    fi

    if [ \$assessor_rc -eq 0 ]; then
        cp ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json study_metadata.json

        python ${baseDir}/src/python/stage_manifest.py mark-complete \
            --manifest ${params.stage_manifest} \
            --base_dir ${baseDir} \
            --outdir ${params.outdir} \
            --central_dir ${params.central_mzml_dir} \
            --pxd ${pxd} \
            --stage run_assessor || true
    else
        echo "WARNING: runAssessor failed for ${pxd}; this is critical and the pipeline cannot continue"
        exit 1
    fi
    """
}

/* -----------------------
 * PROCESS: organism_id
 * --------------------- */
process organism_id {

    tag "organism-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: false

    cache 'deep'

    errorStrategy 'ignore'  // Skip PXDs that fail taxa weighing or other issues

    time '8h'

    input:
    tuple val(pxd), path(fetched_dir), path(detected_params), path(contaminants_fasta), path(taxid_list_file), path(llm_results)

    output:
    tuple val(pxd), path(fetched_dir), path(detected_params), path("organism_results")

    script:
    def peptonizer_container_arg = params.peptonizer_container ? "--peptonizer_container ${params.peptonizer_container}" : ""
    """
    set +e  # Don't exit on errors; we'll handle them
    
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage organism_id || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi
    
    # Setup trap to ensure organism_results directory is created even if process is killed
    # This catches SIGTERM (sent by Nextflow on timeout) and creates empty results
    cleanup_handler() {
        if [ ! -d "organism_results" ]; then
            mkdir -p organism_results
        fi
        if [ ! -f "organism_results/empty.json" ]; then
            echo '{}' > organism_results/empty.json
        fi
        echo "TRAP: Ensured organism_results/empty.json exists"
    }
    trap cleanup_handler EXIT SIGTERM
    
    # make output
    mkdir -p organism_results

    # Read detected parameters
    DETECTED_DIA=\$(python -c "import json; print(json.load(open('${detected_params}'))['detected_params']['DIA'])")
    DETECTED_LABELING=\$(python -c "import json; print(json.load(open('${detected_params}'))['detected_params']['labeling'])")
    
    echo "Detected acquisition type: DDA/DIA = \$DETECTED_DIA"
    echo "Detected labeling: \$DETECTED_LABELING"
    
    if [ "\$DETECTED_DIA" = "True" ]; then
        echo "Using DIA workflow (Cascadia)"
        export CASCADIA_HOME=1
        export CASCADIA_MODEL='${params.cascadia_model_path}'
    else
        echo "Using DDA workflow (Casanovo)"
    fi

    # per-task caches for both Casanovo and Cascadia
    mkdir -p .cache/casanovo
    mkdir -p .cache/cascadia
    mkdir -p .cache/mpl
    mkdir -p .cache/numba
    mkdir -p .cache/tmp
    mkdir -p .cache/huggingface
    mkdir -p .cache/torch

    # --- Cache directory setup ---
    # 1) Matplotlib writable dir
    export MPLCONFIGDIR=\$PWD/.cache/mpl
    
    # 2) Numba: give it a writable cache directory (DON'T disable JIT!)
    export NUMBA_CACHE_DIR=\$PWD/.cache/numba

    # 3) Set temp directories - use /tmp for multiprocessing socket compatibility
    # (AF_UNIX socket paths from PyTorch DataLoader must be <108 chars; work-dir paths exceed this)
    export TMPDIR=/tmp
    export TMP=/tmp
    export TEMP=/tmp

    # 4) Cache directories for various tools
    export HF_HOME=\$PWD/.cache/huggingface
    export TORCH_HOME=\$PWD/.cache/torch

    # 5) Set Peptonizer2000 host path so OrganismID.py can properly mount it in singularity
    export PEPTONIZER2000_HOME='${params.peptonizer2000_host_path}'

    # 6) Assign GPU device via CUDA_VISIBLE_DEVICES.
    # The `accelerator` directive is only supported by SLURM/cloud executors, not `local`.
    # For local executor, maxForks=params.num_gpus throttles concurrency, and we use
    # task.index (global sequential counter) mod num_gpus to assign each concurrent
    # task to a distinct GPU. Any two concurrently running tasks always have consecutive
    # indices, so their mod values are always different.
    NUM_GPUS=${params.num_gpus}
    GPU_ID=\$(((${task.index} - 1) % NUM_GPUS))
    export CUDA_VISIBLE_DEVICES=\$GPU_ID
    echo "Task ${task.index} assigned to GPU \$GPU_ID (CUDA_VISIBLE_DEVICES=\$GPU_ID, NUM_GPUS=\$NUM_GPUS)"

    echo "Running organism ID: Stage 1 (Denovo) via separate conda envs, Stage 2 (Peptonizer) via repo workflow"

    # Run via cascadia_env to ensure conda dependencies are available
    conda run -p ${params.cascadia_env_path} --no-capture-output python ${baseDir}/src/python/OrganismID.py \
        --input_dir ${fetched_dir} \
        --output_dir organism_results \
        --contaminants_fasta ${contaminants_fasta} \
        --taxid_list_file ${taxid_list_file} \
        --denovo_threshold ${params.denovo_threshold} \
        --min_peptides_for_peptonizer ${params.min_peptides_for_peptonizer} \
        --casanovo_env_path ${params.casanovo_env_path} \
        --cascadia_env_path ${params.cascadia_env_path} \
        --cascadia_model_path ${params.cascadia_model_path} \
        --src_dir ${baseDir}/src \
        --snakemake_env_path ${params.meti_env_path} \
        --llm_results ${llm_results} \
        ${params.organism_id_all ? '--organism_id_all' : ''} \
        ${peptonizer_container_arg} \
        --log_file organism/events.jsonl \
        --results_base_dir ${params.outdir} \
        --pxd ${pxd}
    
    ORGANISM_EXIT_CODE=\$?
    
    # If organism_id failed (timeout or error), create empty/dummy results so downstream processes get valid tuple structure
    if [ \$ORGANISM_EXIT_CODE -ne 0 ]; then
        echo "WARNING: organism_id process failed with exit code \$ORGANISM_EXIT_CODE (likely timeout or GPU error)"
        echo "Creating empty organism_results so downstream processes can continue with PRIDE/LLM taxids only"
        echo '{}' > organism_results/empty.json
    fi

    ls -R organism_results || true

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage organism_id || true
    """
}

/* -----------------------
 * PROCESS: sage_search
 * --------------------- */
/* -----------------------
 * PROCESS: search
 * --------------------- */
process search {

    tag "search-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: false

    cache 'deep'

    errorStrategy 'ignore'

    input:
    tuple val(pxd), path(fetched_dir), path(detected_params), path(taxid_mapping)

    output:
    tuple val(pxd), path("search")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage search || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi
    
    mkdir -p search
    mkdir -p .cache/tmp .cache/mpl
    export TMPDIR=\$PWD/.cache/tmp TMP=\$PWD/.cache/tmp TEMP=\$PWD/.cache/tmp MPLCONFIGDIR=\$PWD/.cache/mpl

    # Extract labeling from detected_params.json
    DETECTED_LABELING=\$(conda run -p ${params.search_env_path} python3 -c "
import json
with open('${detected_params}') as f:
    d = json.load(f)
print(d['detected_params']['labeling'])
")

    # Extract taxid from taxid_mapping.json (get first value, others should be same)
    TAXID=\$(conda run -p ${params.search_env_path} python3 -c "
import json
with open('${taxid_mapping}') as f:
    d = json.load(f)
    if d['mappings']:
        print(list(d['mappings'].values())[0]['taxid'])
    else:
        print('0')
")

    # If no taxid found, skip
    if [ "\$TAXID" = "0" ] || [ -z "\$TAXID" ]; then
        echo "No taxids found in mapping" > search/skipped.txt
        exit 0
    fi

    conda run -p ${params.search_env_path} python ${baseDir}/src/python/search_orchestrator.py \\
        --mzml_dir ${fetched_dir} \\
        --output_dir search \\
        --detected_params ${detected_params} \\
        --taxid \$TAXID \\
        --labeling "\$DETECTED_LABELING" \\
        --sage_config ${params.sage_config} \\
        --min_ptm_psms ${params.search_min_ptm_psms} \\
        --max_ptm_classes ${params.search_max_variable_mods} \\
        --high_confidence_q_threshold ${params.high_confidence_q_threshold} \\
        --min_high_confidence_peptides ${params.min_high_confidence_peptides} \\
        --pxd ${pxd} \\
        --log_file search/events.jsonl || exit 1

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage search || true
    """
}


/* -----------------------
 * PROCESS: aggregate_results
 * --------------------- */
process aggregate_results {

    tag "aggregate-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true

    cache false

    errorStrategy 'ignore'

    input:
    tuple val(pxd), path(fetched_dir), path(organism_results), path(search_results), path(llm_results), path(taxid_warnings)

    output:
    tuple val(pxd), path("${pxd}_aggregated_results.json"), path("${pxd}_pipeline.json"), path("${pxd}_pipeline_summary.md")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage aggregate_results || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi
    
    echo "Generating aggregated results JSON for ${pxd}"
    
    sage_results_dir="/dev/null"
    if [ -d "${search_results}" ]; then
        sage_results_dir="${search_results}"
    fi

    llm_results_dir="/dev/null"
    if [ -d "${llm_results}" ]; then
        llm_results_dir="${llm_results}"
    fi
    
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/aggregate_results.py \\
        --pxd_id ${pxd} \
        --pxd_dir ${fetched_dir} \
        --organism_dir ${organism_results} \
        --sage_results_dir "\$sage_results_dir" \
        --llm_results_dir "\$llm_results_dir" \
        --taxid_warnings ${taxid_warnings} \
        --output_file ${pxd}_aggregated_results.json
    
    ls -la *.json || true

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage aggregate_results || true
    """
}
/* -----------------------
 * PROCESS: agentic_metadata_extraction
 * --------------------- */
process agentic_metadata_extraction {

    tag "agentic-${pxd}"

    publishDir "${params.outdir}/${pxd}/agentic_metadata", mode: 'copy', overwrite: true, saveAs: { name ->
        def normalized = name.replaceFirst('^\\./', '')
        if (!normalized || normalized == 'agentic_stage_output') {
            return null
        }
        normalized = normalized.replaceFirst('^agentic_stage_output/?', '')
        if (!normalized || normalized.startsWith('agentic_stage_output/') || normalized.startsWith('metadata_extraction_output/') || normalized.endsWith('.sdrf.tsv')) {
            return null
        }
        return "metadata_extraction_output/${normalized}"
    }

    cache false

    errorStrategy 'ignore'  // Continue if metadata extraction fails

    input:
    tuple val(pxd), path(aggregated_results)

    output:
    tuple val(pxd), path("agentic_stage_output"), path(aggregated_results)

    script:
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage agentic_metadata_extraction || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi

    mkdir -p agentic_stage_output

    # Ensure both variable names are available inside the task and inherited by conda run.
    export LLM_API_KEY="\${LLM_API_KEY:-\${OPENAI_API_KEY:-}}"
    export OPENAI_API_KEY="\${OPENAI_API_KEY:-\${LLM_API_KEY:-}}"
    
    # Propagate API key for the agentic model (OpenRouter/Gemma)
    export OPENROUTER_API_KEY="\${OPENROUTER_API_KEY:-}"

    # Run unified wrapper: performs agentic extraction and writes SDRF TSV.
    echo "=== Running Agentic Metadata Extraction wrapper for ${pxd} ==="
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/run_agentic_metadata.py \\
        --input ${aggregated_results} \\
        --outdir agentic_stage_output \\
        --pride_cache ${baseDir}/pride_survey/pride_cache \\
        --pmc_cache ${baseDir}/pride_survey/pmc_cache \
        --skip_sdrf_write || {
        echo "WARNING: Agentic metadata extraction failed for ${pxd} - continuing"
        mkdir -p agentic_stage_output
    }

    # Verify output
    ls -la agentic_stage_output/ || echo "No metadata extraction output"

    # Materialize only the canonical agentic output folders before manifest update.
    mkdir -p ${params.outdir}/${pxd}/agentic_metadata/metadata_extraction_output
    for rel_path in integrated_output technical_metadata_output Biological_annotations experimental_design_output; do
        if [ -e "agentic_stage_output/\${rel_path}" ]; then
            cp -r "agentic_stage_output/\${rel_path}" ${params.outdir}/${pxd}/agentic_metadata/metadata_extraction_output/ 2>/dev/null || true
        fi
    done

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage agentic_metadata_extraction || true
    """
}


/* -----------------------
 * PROCESS: llm_judge
 * --------------------- */
process llm_judge {

    tag "judge-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true, saveAs: { name ->
        def normalized = name.replaceFirst('^\\./', '')
        if (!normalized || normalized == 'judge_stage_output') {
            return null
        }
        normalized = normalized.replaceFirst('^judge_stage_output/?', '')
        if (!normalized || normalized.startsWith('judge_stage_output/') || normalized.startsWith('judge_output/')) {
            return null
        }
        return "judge_output/${normalized}"
    }

    cache false

    errorStrategy 'ignore'  // Non-blocking quality step; pipeline continues if judge fails

    input:
    tuple val(pxd), path(agentic_stage_output)

    output:
    tuple val(pxd), path("judge_stage_output")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage llm_judge || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi

    mkdir -p judge_stage_output

    # Propagate API key for the judge model (OpenRouter)
    export OPENROUTER_API_KEY="\${OPENROUTER_API_KEY:-}"

    if [ -z "\${OPENROUTER_API_KEY}" ]; then
        echo "WARNING: OPENROUTER_API_KEY not set. Skipping LLM judge."
        echo '{"skipped": true, "reason": "OPENROUTER_API_KEY not set"}' > judge_stage_output/skipped.json
        exit 0
    fi

    echo "=== Running LLM Judge for ${pxd} ==="
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/LLm_as_judge.py \\
        --pipeline \\
        --pxd ${pxd} \\
        --input_dir ${agentic_stage_output} \\
        --pmc_cache ${baseDir}/pride_survey/pmc_cache \\
        --n_judge_runs ${params.n_judge_runs} \\
        --outdir judge_stage_output || {
        echo "WARNING: LLM judge failed for ${pxd} - continuing"
        mkdir -p judge_stage_output
    }

    ls -la judge_stage_output/ || echo "No judge output"

    # Materialize only canonical judge outputs before manifest update.
    mkdir -p ${params.outdir}/${pxd}/judge_output
    for rel_path in json_outputs llm_judge_accuracy.png llm_judge_aggregate.png llm_judge_annotation_quality_counts.png llm_judge_annotation_review.csv llm_judge_coverage.csv llm_judge_per_paper.csv skipped.json; do
        if [ -e "judge_stage_output/\${rel_path}" ]; then
            cp -r "judge_stage_output/\${rel_path}" ${params.outdir}/${pxd}/judge_output/ 2>/dev/null || true
        fi
    done

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage llm_judge || true
    """
}


/* -----------------------
 * PROCESS: finalize_sdrf
 * --------------------- */
process finalize_sdrf {

    tag "final-sdrf-${pxd}"

    // NOTE: Nextflow's saveAs closure for a bare directory-type `path()`
    // output (finalize_stage_output here) is invoked exactly ONCE with the
    // directory's own name -- it is NOT recursed per nested file. That means
    // saveAs can only rename/filter the directory as a whole, never pick out
    // a nested subtree like post_judge/. Verified empirically with a minimal
    // standalone Nextflow script. So publishing of both the SDRF file and the
    // post_judge/ subtree is done via explicit `cp` in the script block below,
    // not through saveAs.
    publishDir "${params.outdir}/${pxd}/agentic_metadata", mode: 'copy', overwrite: true, saveAs: { name -> name.endsWith('.sdrf.tsv') ? name : null }
    publishDir "${baseDir}/store/hamlet_sdrfs", mode: 'copy', overwrite: true, saveAs: { name -> name.endsWith('.sdrf.tsv') ? name : null }

    cache false

    errorStrategy 'ignore'

    input:
    tuple val(pxd), path(agentic_stage_output), path(aggregated_results), path(judge_stage_output)

    output:
    tuple val(pxd), path("finalize_stage_output")
    path("${pxd}.sdrf.tsv"), optional: true

    script:
    """
    ${params.conda_init}

    MANIFEST_RC=0
    python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage finalize_sdrf || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi

    judge_args=""
    if [ -d "${judge_stage_output}" ]; then
        judge_args="--judge_dir ${judge_stage_output}"
    fi

    mkdir -p finalize_stage_output

    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/finalize_sdrf.py \
        --pxd ${pxd} \
        --input_dir ${agentic_stage_output} \
        --aggregated_json ${aggregated_results} \
        --output_dir finalize_stage_output \
        --pmc_cache ${baseDir}/pride_survey/pmc_cache \
        \${judge_args} || {
        echo "WARNING: SDRF finalization failed for ${pxd} - continuing"
    }

    # Promote flat SDRF to task root so Nextflow can publish it directly to hamlet_sdrfs/
    if [ -f "finalize_stage_output/${pxd}.sdrf.tsv" ]; then
        cp finalize_stage_output/${pxd}.sdrf.tsv ${pxd}.sdrf.tsv
        mkdir -p ${params.outdir}/${pxd}/agentic_metadata
        cp finalize_stage_output/${pxd}.sdrf.tsv ${params.outdir}/${pxd}/agentic_metadata/${pxd}.sdrf.tsv
    fi

    # Publish the post_judge/ subtree (second-pass judge evaluation run after
    # overrides are applied) explicitly via cp -- Nextflow's publishDir/saveAs
    # cannot reach into a nested subdirectory of a directory-type output (see
    # note above), so we copy it ourselves, excluding the internal prompt cache.
    if [ -d "finalize_stage_output/post_judge" ]; then
        dest="${params.outdir}/${pxd}/agentic_metadata/metadata_extraction_output/post_judge"
        mkdir -p "\$dest"
        shopt -s nullglob
        post_judge_items=(finalize_stage_output/post_judge/*)
        for item in "\${post_judge_items[@]}"; do
            base=\$(basename "\$item")
            case "\$base" in
                .prompt_cache*) continue ;;
            esac
            cp -r "\$item" "\$dest/"
        done
        shopt -u nullglob
    fi

    ls -la finalize_stage_output/ || echo "No finalized SDRF output"

    python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${params.stage_manifest} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage finalize_sdrf || true
    """
}


/* -----------------------
 * PROCESS: results_summary
 * --------------------- */
process results_summary {

    tag "results-summary"

    // Run on host; script reads repo files and writes a CSV
    cache 'deep'

    publishDir "${params.outdir}", mode: 'copy', overwrite: true

    input:
    val(done_list)

    output:
    path("ResultsSummary.csv")

    script:
    """
    python ${baseDir}/src/python/ResultsSummary.py \\
        --repo_root ${baseDir} \\
        --results_dir ${params.outdir} \\
        --work_dir ${baseDir}/work \\
        --downloads_dir ${params.central_mzml_dir} \\
        --nextflow_log ${baseDir}/.nextflow.log \\
        --main_nf ${baseDir}/main.nf \\
        --out_csv ResultsSummary.csv
    """
}