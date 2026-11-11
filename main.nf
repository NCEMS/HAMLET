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

String normalizePipelineMode(def mode) {
    def normalized = (mode == null ? 'full' : mode).toString().trim().toLowerCase().replaceAll(/[\s-]+/, '_')
    if (!(normalized in ['full', 'runassessor_only', 'organism_only', 'search_only', 'agentic_only'])) {
        throw new IllegalArgumentException("Invalid --mode '${mode}'. Choose full, 'runassessor only', 'organism only', 'search only', or 'agentic only'")
    }
    return normalized
}

def pipelineMode = normalizePipelineMode(params.mode)
def runOrganismId = pipelineMode in ['full', 'organism_only']
def runSearch = pipelineMode in ['full', 'search_only']
def runAgenticMetadata = pipelineMode == 'full'

String resolveStageManifest(def config, def baseDir) {
    def selected = config.update_from_existing ? config.update_stage_manifest : config.stage_manifest
    def filename = config.update_from_existing ? 'update_stage_manifest.json' : 'pipeline_stage_manifest.json'
    def configured = new File((selected ?: "${config.outdir}/${filename}").toString())
    return configured.isAbsolute() ? configured.canonicalPath : new File(baseDir.toString(), configured.path).canonicalPath
}

def stageManifestPath = resolveStageManifest(params, baseDir)

List<String> buildPxdList(def params) {
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
    if (params.num_pxds && params.num_pxds > 0) {
        pxd_list = pxd_list.take(params.num_pxds as int)
    }
    return pxd_list
}

def printPipelineHelp() {
    println """
HAMLET annotator Nextflow pipeline

USAGE
    nextflow run main.nf [nextflow options] --pxd <PXD...> [pipeline params]
    nextflow run main.nf [nextflow options] --pxd_csv <PXDs.csv> [pipeline params]
    nextflow run main.nf [nextflow options] --mode 'agentic only' --pxd <PXD...>

NEXTFLOW OPTIONS (runtime)
    nextflow help run

PIPELINE PARAMS (this workflow)
    Input selection (required: choose one)
        --pxd <PXD000000>                 Single PXD accession
        --pxd_csv <PXDs.csv>              CSV with PXD IDs (first column)
        --num_pxds <N>                    Limit number of PXDs from CSV

    Pipeline mode (default: full; underscores and hyphens also accepted)
        --mode full                      Run all stages through SDRF finalization
        --mode 'runassessor only'         Fetch/assess, then write aggregated results
        --mode 'organism only'            Identify organisms, then write aggregated results
        --mode 'search only'              Run database search, then write aggregated results
        --mode 'agentic only'             Reuse stored aggregated results and run
                                          metadata extraction, judge, and SDRF finalization
                                          (requires --pxd or --pxd_csv)
        --aggregated_results_dir <dir>    Directory with *_aggregated_results.json files
                                          Default: store/aggregated_results_files

    Update-from-existing mode
        --update_from_existing true       Reuse a prior run's per-PXD directory tree and
                                          refresh the selected mode's sections of its aggregate.
                                          Untouched data survives missing source files.
                                          Missing aggregates are rebuilt from stage outputs.
        --existing_results_dir <dir>      Required with --update_from_existing: a prior run's
                                          --outdir (must differ from this run's --outdir)

    Acquisition type routing
        --acquisition_type AUTO|DDA|DIA   Default: AUTO
            AUTO: per-PXD routing uses detected_params.json
            DDA : force DDA workflow/container for all PXDs
            DIA : force DIA workflow/container for all PXDs

    Detection
        --auto_detect true|false          Default: true

    Organism ID
        --denovo_threshold <N>            Default: 70 (may be overridden in config)
        --min_peptides_for_peptonizer <N> Default: 5 (may be overridden in config)
        --taxid_blocks_file <CSV>         Default: assets/taxid_lists/AllPRIDEtaxids.csv
        --peptonizer_score_threshold <N>  Default: 0.8 (strictly greater than)

    Search
        --taxid <taxid>                               Default: 9606 (may be overridden)
        --search_min_ptm_psms <N>                     Default: 50
        --search_max_variable_mods <N>                Default: 3

    Download control
        --max_raw_files <N>               Default: 30 (null = all)
        --globus true|false               Use Globus for PRIDE RAW transfers
        --globus_destination_collection   Destination collection UUID;
                                          default: local Globus Connect Personal collection
        --globus_destination_base <path>  Collection path corresponding to central_mzml_dir
        --use_aria2c true|false           Default: true
        --aria2c_threads <N>              Default: 16 (profile-dependent)
        --stage_manifest <path>           Default: results/pipeline_stage_manifest.json
            Manifest with per-PXD, per-stage Availability/Complete/key_outputs.

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

    # Fetch one RAW with Globus, convert it, and run only runAssessor
    nextflow run main.nf --pxd PXD000070 --globus --mode 'runassessor only' --max_raw_files 1

    # Agentic-only: reuse stored aggregates
    nextflow run main.nf --mode 'agentic only' --pxd_csv GSlist0.csv -resume
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
params.taxid_blocks_file  = params.taxid_blocks_file  ?: "${baseDir}/assets/taxid_lists/AllPRIDEtaxids.csv"

// No containers - all tools run via conda environments
// params.unified_container = removed (container-free pipeline)
// params.proteowizard_container = removed (container-free pipeline)
// params.proteowizard_wineprefix = removed (container-free pipeline)
params.sage_config        = params.sage_config        ?: "${baseDir}/assets/default_sage.config"

params.search_min_ptm_psms = params.search_min_ptm_psms ?: 50

params.search_max_variable_mods = params.search_max_variable_mods ?: 3
params.high_confidence_q_threshold = params.high_confidence_q_threshold ?: 0.01
params.min_high_confidence_peptides = params.min_high_confidence_peptides ?: 10
params.taxid              = params.taxid              ?: '9606'
params.acquisition_type   = params.acquisition_type   ?: 'AUTO'  // AUTO, DDA, DIA
params.globus            = params.globus            ?: false
params.globus_source_collection = params.globus_source_collection ?: '47772002-3e5b-4fd3-b97c-18cee38d6df2'
params.globus_destination_collection = params.globus_destination_collection ?: null
params.globus_destination_base = params.globus_destination_base ?: params.central_mzml_dir

params.n_judge_runs         = params.n_judge_runs         ?: 3      // Number of judge runs for consensus (1 = single pass)
params.organism_id_all     = params.organism_id_all     ?: false  // Force organism_id on all files even when single taxid

// Organism identification parameters
params.denovo_threshold            = params.denovo_threshold            ?: 70
params.min_peptides_for_peptonizer = params.min_peptides_for_peptonizer ?: 5
params.peptonizer_score_threshold  = params.peptonizer_score_threshold  ?: 0.8

// Cascadia model path (stored in repo assets, must be downloaded separately due to size)
params.cascadia_model_path = params.cascadia_model_path ?: "${baseDir}/assets/cascadia.ckpt"

// Peptonizer2000 source code path (runs directly from host, container-free)
params.peptonizer2000_host_path = params.peptonizer2000_host_path ?: "${params.organism_id_submodule_dir}/submodules/peptonizer2000"

// Auto-detection parameters (can be overridden by runAssessor results)
params.auto_detect = params.containsKey('auto_detect') ? params.auto_detect : true

params.aggregated_results_dir = params.aggregated_results_dir ?: "${baseDir}/store/aggregated_results_files"
params.update_from_existing  = params.update_from_existing  ?: false
params.existing_results_dir  = params.existing_results_dir  ?: null

// Search per-sample strategy for aggregation
// Controls both OPEN SEARCH (Pass 1) and CLOSED SEARCH (Pass 2) aggregation behavior:
//   false         = aggregate/pool both open and closed searches (default, fastest, bulk quantification)
//   true          = per-file closed search (per-sample quantification)
//   'closed_only' = per-file open search, aggregate closed search
//   'none'        = per-file for both open and closed searches

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
    params.acquisition_type = acqType

    for (legacyFlag in ['agentic_only', 'runAssessorOnly', 'run_organism_id', 'run_search', 'run_agentic_metadata']) {
        if (params.containsKey(legacyFlag)) {
            error "--${legacyFlag} has been removed; select --mode instead"
        }
    }
    log.info "Pipeline mode: ${pipelineMode}"

    if( params.update_from_existing ) {
        if (pipelineMode == 'agentic_only') {
            error "--update_from_existing cannot be combined with --mode 'agentic only'; use --aggregated_results_dir instead"
        }
        if( !params.existing_results_dir ) {
            error "--update_from_existing requires --existing_results_dir <path to a prior run's --outdir>"
        }
        def existingRoot = new File(params.existing_results_dir.toString()).canonicalFile
        def newOutdirRoot = new File(params.outdir.toString()).canonicalFile
        if( existingRoot == newOutdirRoot ) {
            error "--outdir must differ from --existing_results_dir to preserve the prior run"
        }
        log.info "Updating ${pipelineMode} sections from ${existingRoot}; preserving other aggregate data"
    }

    // ==================== AGENTIC-ONLY WORKFLOW ====================
    // Reuse stored full aggregated results and run only metadata extraction, judging, and SDRF finalization.
    if( pipelineMode == 'agentic_only' ) {
        log.info "=== AGENTIC-ONLY MODE ==="
        log.info "Pipeline: stored aggregated results → agentic_metadata_extraction → llm_judge → finalize_sdrf"
        
        // Build PXD list from CSV or single PXD
        def pxd_list_agentic = buildPxdList(params)
        
        log.info "Will process ${pxd_list_agentic.size()} PXD(s) in parallel: ${pxd_list_agentic.join(', ')}"
        
        def stored_aggregates = pxd_list_agentic.collect { pxd ->
            def aggregate = file("${params.aggregated_results_dir}/${pxd}_aggregated_results.json")
            if (!aggregate.exists()) {
                error "Missing stored aggregate for ${pxd}: ${aggregate}"
            }
            tuple(pxd, aggregate)
        }

        aggregated_results_ch = Channel.fromList(stored_aggregates)

        // Agentic metadata extraction reuses the stored full aggregate.
        // Outputs: [pxd, agentic_stage_output, aggregated_results]
        agentic_results_ch_minimal = agentic_metadata_extraction(aggregated_results_ch)
        
        // llm_judge expects only [pxd, agentic_stage_output], so select first 2 elements
        llm_judge_input_ch_minimal = agentic_results_ch_minimal
            .map { pxd, agentic_output, agg_results -> [pxd, agentic_output] }
        
        // llm_judge outputs: [pxd, judge_stage_output]
        llm_judge_ch_minimal = llm_judge(llm_judge_input_ch_minimal)[0]
        
        // finalize_sdrf needs: [pxd, agentic_stage_output, aggregated_results, judge_stage_output]
        // agentic_results_ch_minimal = [pxd, agentic_stage_output, aggregated_results]
        // llm_judge_ch_minimal = [pxd, judge_stage_output]
        // Retain the aggregate so final judging can use RunAssessor provenance.
        finalize_input_ch_minimal = agentic_results_ch_minimal
            .map { pxd, agentic_output, agg_results -> [pxd, agentic_output, agg_results] }
            .join(llm_judge_ch_minimal, by: 0)
        
        finalize_results_ch_minimal = finalize_sdrf(finalize_input_ch_minimal)
        
        // Results summary for agentic-only
        // finalize_sdrf has 2 outputs; select first (tuple with pxd, path) before collecting
        results_summary(finalize_results_ch_minimal[0].collect())
        
        // Exit after agentic-only workflow
        return
    }
    
    // Ensure required directories exist for search infrastructure
    // DIA-NN needs diann_libraries directory to cache spectral libraries
    def diann_libs_dir = new File("${baseDir}/assets/diann_libraries")
    if (!diann_libs_dir.exists()) {
        log.info "Creating DIA-NN library cache directory: ${diann_libs_dir.absolutePath}"
        diann_libs_dir.mkdirs()
    }


    // Build PXD list from either single PXD or CSV file
    def pxd_list = buildPxdList(params)

    if (pxd_list) {
        log.info "Will process ${pxd_list.size()} PXD(s) in parallel: ${pxd_list.join(', ')}"
    } else {
        log.info "No PXDs selected. Downstream steps will be skipped; results_summary will still run."
    }

    // Initialize/reconcile unified stage manifest before launching processes.
    // This computes stage completion from file checkpoints and preserves user-edited availability.
    def manifestCmd = [
        "${params.meti_env_path}/bin/python",
        "${baseDir}/src/python/stage_manifest.py",
        'init',
        '--manifest', stageManifestPath,
        '--base_dir', baseDir.toString(),
        '--outdir', params.outdir.toString(),
        '--central_dir', params.central_mzml_dir.toString(),
        '--max_raw_files', (params.max_raw_files ?: 0).toString(),
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
        error "Failed to initialize stage manifest at ${stageManifestPath} (exit=${manifestRc})"
    }

    // Create channel from final list
    pxd_ch = Channel.fromList(pxd_list)

    // Fetch all PXDs (runs in parallel)
    // Output: [pxd, fetched_dir]
    // fetch_pxd produces: tuple(pxd, fetched_dir)  
    fetched_ch = fetch_pxd(pxd_ch)[0]
        .map { pxd, work_path -> 
            // Use stable canonical path instead of work-dir symlink for downstream cache stability
            tuple(pxd, file("${params.central_mzml_dir}/${pxd}"))
        }

    // The combined fetch task also supplies RunAssessor outputs.
    assessor_ch = fetched_ch

    // Run LLM-based metadata extraction from publications FIRST.
    // LLM results inform determine_acquisition_params (e.g., Comment[AcquisitionMethod]).
    // Output: [pxd, llm_results]
    if (params.run_llm_extraction && !params.update_from_existing && pipelineMode != 'runassessor_only') {
        llm_results_ch = llm_extraction(fetched_ch)
    } else {
        llm_results_ch = fetched_ch.map { pxd, fetched_dir ->
            if (params.update_from_existing) {
                def prior = file("${params.existing_results_dir}/${pxd}/llm_results")
                if (prior.isDirectory()) {
                    return tuple(pxd, prior)
                }
            }
            def dummy_llm = file("${baseDir}/work/dummy_llm_${pxd}.empty")
            dummy_llm.parent.mkdirs()
            dummy_llm.text = ""
            tuple(pxd, dummy_llm)
        }
    }

    if (pipelineMode == 'runassessor_only') {
        def emptyDir = file("${workDir}/runassessor_only_empty")
        emptyDir.mkdirs()
        def emptyOrganism = emptyDir.resolve("organism_results")
        def emptySearch = emptyDir.resolve("search")
        emptyOrganism.mkdirs()
        emptySearch.mkdirs()
        def emptyWarnings = emptyDir.resolve("taxid_warnings.json")
        emptyWarnings.text = '{"warnings":[]}'
        aggregate_input_ch = assessor_ch.join(llm_results_ch, by: 0).map { pxd, fetched_dir, llm_results ->
            def priorOrganism = params.update_from_existing ? file("${params.existing_results_dir}/${pxd}/organism_results") : emptyOrganism
            def priorSearch = params.update_from_existing ? file("${params.existing_results_dir}/${pxd}/search") : emptySearch
            def priorWarnings = params.update_from_existing ? file("${params.existing_results_dir}/${pxd}/taxid_warnings.json") : emptyWarnings
            tuple(pxd, fetched_dir, priorOrganism.isDirectory() ? priorOrganism : emptyOrganism,
                  priorSearch.isDirectory() ? priorSearch : emptySearch, llm_results,
                  priorWarnings.isFile() ? priorWarnings : emptyWarnings)
        }
        aggregated_results_ch = aggregate_results(aggregate_input_ch)[0]
        results_summary(aggregated_results_ch.collect())
        return
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

    detected_with_llm_ch = detected_ch.join(llm_for_context_ch, by: 0)

    // Split the detected per-PXD context once at the point where downstream branches diverge.
    detected_with_llm_ch
        .multiMap { pxd, fetched_dir, detected_params, llm_results ->
            for_organism: tuple(pxd, fetched_dir, detected_params, llm_results)
            for_taxid_context: tuple(pxd, fetched_dir, detected_params, llm_results)
        }
        .set { detected_split }

    // Build taxid-ready per-PXD context anchored on acquisition detection so determine_taxids
    // still runs even when organism_id is ignored. Missing organism results fall back to an
    // empty directory, but the PXD record stays intact.
    def emptyOrganismDir = file("${baseDir}/work/empty_organism")
    emptyOrganismDir.mkdirs()
    if (!emptyOrganismDir.resolve("empty.json").exists()) {
        emptyOrganismDir.resolve("empty.json").text = "{}"
    }
    emptyOrganismDir.resolve("organism_status.json").text = '{"status":"skipped","reason":"pipeline_mode"}'
    def failedOrganismDir = file("${baseDir}/work/failed_organism")
    failedOrganismDir.mkdirs()
    failedOrganismDir.resolve("organism_status.json").text = '{"status":"execution_failed","reason":"no_nextflow_organism_output"}'

    if( runOrganismId ) {
        // Only organism modes require these reference files.
        contaminants_ch = Channel.fromPath(params.contaminants_fasta, checkIfExists: true)
        taxid_blocks_ch = Channel.fromPath(params.taxid_blocks_file, checkIfExists: true)
        organism_input_ch = detected_split.for_organism
            .combine(contaminants_ch)
            .combine(taxid_blocks_ch)
            .map { pxd, fetched_dir, detected_params, llm_results, contaminants_fasta, taxid_blocks_file ->
                tuple(pxd, fetched_dir, detected_params, contaminants_fasta, taxid_blocks_file, llm_results)
            }
        // Run organism_id for all PXDs; stage_manifest controls per-PXD run/skip behavior.
        log.info "Running organism_id process (manifest-controlled per PXD)"
        // Keep per-PXD streaming semantics: each PXD advances downstream as soon as
        // its own organism_id result is available.
        organism_with_context_ch = organism_id(organism_input_ch)

        // Extract just organism_results for downstream processes that don't need context
        organism_results_ch = organism_with_context_ch.map { pxd, fetched_dir, detected_params, organism_results, organism_status ->
            tuple(pxd, organism_results)
        }
    } else {
        log.info "Skipping organism_id (mode: ${pipelineMode})"
        organism_results_ch = detected_split.for_organism.map { pxd, fetched_dir, detected_params, llm_results ->
            if (params.update_from_existing) {
                def prior = file("${params.existing_results_dir}/${pxd}/organism_results")
                if (prior.isDirectory()) {
                    return tuple(pxd, prior)
                }
                log.info "No prior organism source files for ${pxd}; using existing aggregate if available"
            }
            tuple(pxd, emptyOrganismDir)
        }
    }

    taxid_context_ch = detected_split.for_taxid_context
        .join(organism_results_ch, by: 0, remainder: true)
        .map { pxd, fetched_dir, detected_params, llm_results, organism_results ->
            tuple(pxd, fetched_dir, detected_params, llm_results, organism_results ?: failedOrganismDir)
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
    
    // Placeholder search directory + taxid warnings used when the search stage is skipped.
    def emptySearchDir = file("${baseDir}/work/empty_search")
    emptySearchDir.mkdirs()
    if (!emptySearchDir.resolve("skipped.txt").exists()) {
        emptySearchDir.resolve("skipped.txt").text = "Search stage disabled by pipeline mode\n"
    }
    def emptyTaxidWarnings = file("${baseDir}/work/empty_taxid_warnings.json")
    if (!emptyTaxidWarnings.exists()) {
        emptyTaxidWarnings.text = '{"warnings": []}\n'
    }

    if( runSearch ) {
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
        taxid_warnings_ch = taxid_mapping_split.for_aggregate
    } else {
        log.info "Skipping determine_taxids/search (mode: ${pipelineMode})"
        search_results_ch = taxid_context_split.for_search.map { pxd, fetched_dir, detected_params ->
            if (params.update_from_existing) {
                def prior = file("${params.existing_results_dir}/${pxd}/search")
                if (prior.isDirectory()) {
                    return tuple(pxd, prior)
                }
                log.info "No prior search source files for ${pxd}; using existing aggregate if available"
            }
            tuple(pxd, emptySearchDir)
        }
        taxid_warnings_ch = taxid_context_split.for_search.map { pxd, fetched_dir, detected_params ->
            if (params.update_from_existing) {
                def prior = file("${params.existing_results_dir}/${pxd}/taxid_warnings.json")
                if (prior.isFile()) {
                    return tuple(pxd, prior)
                }
            }
            tuple(pxd, emptyTaxidWarnings)
        }
    }

    // Build the aggregate input from the per-PXD context plus the two process outputs that
    // become available after taxid selection.
    aggregate_input_ch = taxid_context_split.for_aggregate
        .join(search_results_ch, by: 0)
        .join(taxid_warnings_ch, by: 0)
        .map { pxd, fetched_dir, organism_results, llm_results, search_results, taxid_warnings ->
            tuple(pxd, fetched_dir, organism_results, search_results, llm_results, taxid_warnings)
        }

    // Run aggregation after all per-PXD inputs are available.
    aggregated_results_ch = aggregate_results(aggregate_input_ch)[0]
    
    if( runAgenticMetadata ) {
        // Run downstream metadata/judge/finalize for all PXDs; stage_manifest controls per-PXD run/skip behavior.
        agentic_input_ch = aggregated_results_ch
            .map { pxd, aggregated_results, pipeline_json, pipeline_summary -> tuple(pxd, aggregated_results) }

        agentic_results_ch = agentic_metadata_extraction(agentic_input_ch)[0]

        llm_judge_input_ch = agentic_results_ch
            .map { pxd, metadata_extraction_output, aggregated_results -> tuple(pxd, metadata_extraction_output) }

        llm_judge_ch = llm_judge(llm_judge_input_ch)[0]

        finalized_sdrf_input_ch = agentic_results_ch
            .map { pxd, metadata_extraction_output, aggregated_results -> tuple(pxd, metadata_extraction_output, aggregated_results) }
            .join(llm_judge_ch)

        finalized_sdrf_ch = finalize_sdrf(finalized_sdrf_input_ch)[0]

        // Run ResultsSummary once after pipeline completion
        results_summary(finalized_sdrf_ch.collect())
    } else {
        log.info "Stopping after aggregation (mode: ${pipelineMode})"
        results_summary(aggregated_results_ch.collect())
    }
}


/* -----------------------
 * PROCESS: determine_acquisition_params
 * --------------------- */
process determine_acquisition_params {

    tag "acqparams-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true,
        saveAs: { name -> name == 'detected_params.json' ? name : null }

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
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${stageManifestPath} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage determine_acquisition_params --refresh || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi

    # Determine acquisition type and labeling from runAssessor + LLM + PRIDE evidence.
    # Refresh the fetch-time detection with LLM evidence. Forced routing stays task-local.
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/determine_acquisition_params.py \\
        --input_dir ${fetched_dir} \\
        --output detected_params.json \\
        --central_mzml_dir ${params.central_mzml_dir} \\
        --pxd ${pxd} \\
        --llm_results_dir ${llm_results} \\
        --acquisition_type ${params.acquisition_type} \\
        --force

    # Display results
    echo "Detected parameters:"
    cat detected_params.json

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${stageManifestPath} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage determine_acquisition_params || true
    """
}

/* -----------------------
 * PROCESS: llm_extraction
 * --------------------- */
process llm_extraction {

    tag "llm-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true

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
    
    # OpenRouter is the sole configured LLM endpoint.
    if [ -z "\${OPENROUTER_API_KEY:-}" ]; then
        echo "WARNING: OPENROUTER_API_KEY not set. Skipping LLM extraction."
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

    cache (params.update_from_existing ? false : 'deep')

    errorStrategy(params.update_from_existing ? 'terminate' : 'ignore')

    input:
    tuple val(pxd), path(fetched_dir), path(organism_results), path(llm_results)

    output:
    tuple val(pxd), path("taxid_mapping.json"), path("taxid_warnings.json")

    script:
    def default_taxid_arg = params.taxid ? "--default_taxid ${params.taxid}" : ""
    def existing_aggregate_arg = params.update_from_existing && !runOrganismId ?
        "--existing_aggregate '${file("${params.existing_results_dir}/${pxd}/${pxd}_aggregated_results.json")}'" : ""
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${stageManifestPath} \
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
        ${existing_aggregate_arg} \\
        ${default_taxid_arg} \\
        --output_mapping taxid_mapping.json \\
        --output_warnings taxid_warnings.json

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${stageManifestPath} \
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

    // No caching - let FetchPXD.py handle cache logic internally
    // It checks for existing files and creates symlinks in work directory when needed
    cache false
    publishDir "${params.outdir}/${pxd}/runAssessor", mode: 'copy', overwrite: true,
        saveAs: { name -> name == 'study_metadata.json' ? name : null }
    
    // Allow pipeline to continue if a specific PXD fails to download
    errorStrategy 'ignore'

    input:
    val pxd

    output:
    tuple val(pxd), path("${pxd}"), optional: true
    path("study_metadata.json"), optional: true

    script:
    def aria2c_args = params.use_aria2c ? "--use_aria2c --aria2c_threads ${params.aria2c_threads}" : ""
    def manifest_max_raw_files = params.max_raw_files ?: 0
    def globus_destination_base = params.globus_destination_base ?: params.central_mzml_dir
    def globus_args = params.globus ? "--globus --globus_source_collection ${params.globus_source_collection} --globus_destination_base ${globus_destination_base}" : ""
    def globus_destination_arg = params.globus_destination_collection ? "--globus_destination_collection ${params.globus_destination_collection}" : ""
    """
    # Initialize conda
    ${params.conda_init}

    conda run -p ${params.meti_env_path} --no-capture-output python ${baseDir}/src/python/run_submodule_fetch.py \\
        --submodule_dir ${params.organism_id_submodule_dir} \
        --manifest ${stageManifestPath} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --cores ${task.cpus} \
        --max_raw_files ${manifest_max_raw_files} \
        ${globus_args} \
        ${globus_destination_arg} \
        ${aria2c_args}
    """
}

/* -----------------------
 * PROCESS: run_assessor
 * --------------------- */
process run_assessor {

    tag "assessor-${pxd}"

    publishDir "${params.outdir}/${pxd}/runAssessor", mode: 'copy', overwrite: false,
        saveAs: { name -> name == 'study_metadata.json' ? name : null }

    cache false

    errorStrategy 'ignore'

    input:
    tuple val(pxd), path(fetched_dir)

    output:
    tuple val(pxd), path(fetched_dir), path("study_metadata.json")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${stageManifestPath} \
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
            --n_threads ${task.cpus}
            --metadata_filepath ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json
        )
        mzml_count=0
        shopt -s nullglob
        for mzml in ${fetched_dir}/*.mzML ${fetched_dir}/*.mzML.gz; do
            assessor_cmd+=("\$mzml")
            mzml_count=\$((mzml_count + 1))
        done
        shopt -u nullglob

        if [ \$mzml_count -eq 0 ]; then
            echo "WARNING: No mzML files found for ${pxd}; writing empty study_metadata.json"
            echo '{}' > ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json
            cp ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json study_metadata.json
            exit 0
        fi

        assessor_rc=0
        "\${assessor_cmd[@]}" || assessor_rc=\$?
    else
        echo "ERROR: Unsupported runAssessor entrypoint: \$assessor_script"
        exit 1
    fi

    if [ \$assessor_rc -eq 0 ]; then
        cp ${params.central_mzml_dir}/${pxd}/runAssessor/study_metadata.json study_metadata.json

        ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
            --manifest ${stageManifestPath} \
            --base_dir ${baseDir} \
            --outdir ${params.outdir} \
            --central_dir ${params.central_mzml_dir} \
            --pxd ${pxd} \
            --stage run_assessor || true
    else
        echo "ERROR: runAssessor failed for ${pxd} with exit code \$assessor_rc"
        exit \$assessor_rc
    fi
    """
}

/* -----------------------
 * PROCESS: organism_id
 * --------------------- */
process organism_id {

    tag "organism-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true,
        saveAs: { name -> name in ['organism_results', 'organism_status.json'] ? name : null }

    cache false

    errorStrategy(params.update_from_existing ? 'terminate' : 'ignore')

    time '8h'

    input:
    tuple val(pxd), path(fetched_dir), path(detected_params), path(contaminants_fasta), path(taxid_blocks_file), path(llm_results)

    output:
    tuple val(pxd), path(fetched_dir), path(detected_params), path("organism_results"), path("organism_status.json")

    script:
    def peptonizer_container_arg = params.peptonizer_container ? "--peptonizer_container ${params.peptonizer_container}" : ""
    """
    # Initialize conda
    ${params.conda_init}

    FINGERPRINT=\$(conda run -p ${params.meti_env_path} python ${baseDir}/src/python/organism_fingerprint.py \
        --manifest ${stageManifestPath} --pxd ${pxd} \
        --submodule ${params.organism_id_submodule_dir} \
        --files ${detected_params} ${contaminants_fasta} ${taxid_blocks_file} ${llm_results} \
            ${params.skin_contaminants_fasta} ${params.casanovo_config_path} ${params.unimod_xml} \
        --assets ${params.taxonomy_dir}/nodes.dmp ${params.taxonomy_dir}/names.dmp ${params.cascadia_model_path} \
        --settings '${params.denovo_threshold}|${params.min_peptides_for_peptonizer}|${params.peptonizer_score_threshold}|${params.organism_id_all}|${params.casanovo_env_path}|${params.cascadia_env_path}|${params.meti_env_path}|${params.cascadia_model_path}|${params.taxonomy_dir}')

    MANIFEST_RC=0
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${stageManifestPath} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --organism_fingerprint "\$FINGERPRINT" \
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
        if [ ! -f "organism_status.json" ]; then
            echo '{"status":"interrupted_or_wrapper_failure","reason":"organism_id did not write a status file"}' > organism_status.json
        fi
        echo "TRAP: Ensured organism_results/empty.json exists"
    }
    trap cleanup_handler EXIT SIGTERM
    
    # make output
    mkdir -p organism_results

    # Read detected parameters
    DETECTED_DIA=\$(${params.meti_env_path}/bin/python -c "import json; print(json.load(open('${detected_params}'))['detected_params']['DIA'])")
    
    echo "Detected acquisition type: DDA/DIA = \$DETECTED_DIA"
    
    if [ "\$DETECTED_DIA" = "True" ]; then
        echo "Using DIA workflow (Cascadia)"
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

    # Keep the installed Cascadia wrapper offline using HAMLET's Unimod reference.
    export UNIMOD_XML='${params.unimod_xml}'

    # Hold an exclusive GPU lease until this task exits.
        CASANOVO_CONFIG='${params.casanovo_config_path}'
        if [[ "\$CASANOVO_CONFIG" == *casanovo_cpu.config ]]; then
            export CUDA_VISIBLE_DEVICES=""
            echo "Task ${task.index} configured for CPU de novo sequencing"
        else
            source ${baseDir}/src/bash/lease_organism_gpu.sh
            lease_organism_gpu '${params.num_gpus}' '${params.organism_gpu_lock_dir}'
        fi

    echo "Running organism ID: Stage 1 (Denovo) via separate conda envs, Stage 2 (Peptonizer) via repo workflow"

    ORGANISM_EXIT_CODE=0
    conda run -p ${params.meti_env_path} --no-capture-output python ${params.organism_id_submodule_dir}/src/OrganismID.py \
        --input_dir ${fetched_dir} \
        --output_dir organism_results \
        --contaminants_fasta ${contaminants_fasta} \
        --taxid_blocks_file ${taxid_blocks_file} \
        --peptonizer_score_threshold ${params.peptonizer_score_threshold} \
        --denovo_threshold ${params.denovo_threshold} \
        --min_peptides_for_peptonizer ${params.min_peptides_for_peptonizer} \
        --casanovo_env_path ${params.casanovo_env_path} \
        --casanovo_config_path ${params.casanovo_config_path} \
        --cascadia_env_path ${params.cascadia_env_path} \
        --cascadia_model_path ${params.cascadia_model_path} \
        --detected_params ${detected_params} \
        --skin_contaminants_fasta ${params.skin_contaminants_fasta} \
        --taxonomy_dir ${params.taxonomy_dir} \
        --peptonizer_home ${params.peptonizer2000_host_path} \
        --cores ${task.cpus} \
        --force \
        --snakemake_env_path ${params.meti_env_path} \
        --llm_results ${llm_results} \
        ${params.organism_id_all ? '--organism_id_all' : ''} \
        ${peptonizer_container_arg} \
        --log_file organism/events.jsonl \
        --results_base_dir ${params.outdir} \
        --pxd ${pxd} \
        --status_file organism_status.json || ORGANISM_EXIT_CODE=\$?
    
    # If organism_id failed (timeout or error), create empty/dummy results so downstream processes get valid tuple structure
    if [ \$ORGANISM_EXIT_CODE -ne 0 ]; then
        echo "WARNING: organism_id process failed with exit code \$ORGANISM_EXIT_CODE (likely timeout or GPU error)"
        echo "Creating empty organism_results so downstream processes can continue with PRIDE/LLM taxids only"
        echo '{}' > organism_results/empty.json
        printf '{"status":"execution_failed","reason":"organism_id exit code %s"}\n' "\$ORGANISM_EXIT_CODE" > organism_status.json
    fi

    conda run -p ${params.meti_env_path} python -c \
        "import json; p='organism_status.json'; d=json.load(open(p)); d['execution_fingerprint']='\$FINGERPRINT'; json.dump(d,open(p,'w'),indent=2)"
    cp organism_status.json organism_results/organism_status.json
    ls -R organism_results || true

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${stageManifestPath} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --organism_fingerprint "\$FINGERPRINT" \
        --stage organism_id
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

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true

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
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${stageManifestPath} \
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

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${stageManifestPath} \
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

    errorStrategy 'terminate'

    input:
    tuple val(pxd), path(fetched_dir), path(organism_results), path(search_results), path(llm_results), path(taxid_warnings)

    output:
    tuple val(pxd), path("${pxd}_aggregated_results.json"), path("${pxd}_pipeline.json"), path("${pxd}_pipeline_summary.md")

    script:
    def existing_aggregate_arg = params.update_from_existing ?
        "--existing_aggregate '${file("${params.existing_results_dir}/${pxd}/${pxd}_aggregated_results.json")}'" : ""
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${stageManifestPath} \
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
        --mode ${pipelineMode} \
        ${existing_aggregate_arg} \
        --output_file ${pxd}_aggregated_results.json
    
    ls -la *.json || true

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${stageManifestPath} \
        --base_dir ${baseDir} \
        --outdir ${params.outdir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage aggregate_results || true
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

    errorStrategy 'terminate'

    input:
    tuple val(pxd), path(aggregated_results)

    output:
    tuple val(pxd), path("agentic_stage_output"), path(aggregated_results)

    script:
    def store_backed_agentic_args = pipelineMode == 'agentic_only' ? "--store_backed_agentic_only" : ""
    def configuredOutdir = new File(params.outdir.toString())
    def outputDir = configuredOutdir.isAbsolute() ? configuredOutdir.canonicalPath : new File(baseDir.toString(), params.outdir.toString()).canonicalPath
    def manifestPath = stageManifestPath
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${manifestPath} \
        --base_dir ${baseDir} \
        --outdir ${outputDir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage agentic_metadata_extraction \
        ${store_backed_agentic_args} || MANIFEST_RC=\$?
    if [ \$MANIFEST_RC -eq 0 ]; then
        exit 0
    elif [ \$MANIFEST_RC -ne 3 ]; then
        exit \$MANIFEST_RC
    fi

    mkdir -p agentic_stage_output

    if [ -z "\${OPENROUTER_API_KEY:-}" ]; then
        echo "ERROR: OPENROUTER_API_KEY is required for agentic metadata extraction." >&2
        exit 1
    fi

    # Run unified wrapper: performs agentic extraction and writes SDRF TSV.
    echo "=== Running Agentic Metadata Extraction wrapper for ${pxd} ==="
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/run_agentic_metadata.py \\
        --input ${aggregated_results} \\
        --outdir agentic_stage_output \\
        --pride_cache ${baseDir}/pride_survey/pride_cache \\
        --pmc_cache ${baseDir}/pride_survey/pmc_cache \
        --skip_sdrf_write

    # Verify output
    ls -la agentic_stage_output/ || echo "No metadata extraction output"

    # Materialize only the canonical agentic output folders before manifest update.
    mkdir -p ${outputDir}/${pxd}/agentic_metadata/metadata_extraction_output
    for rel_path in integrated_output technical_metadata_output Biological_annotations experimental_design_output; do
        if [ -e "agentic_stage_output/\${rel_path}" ]; then
            cp -r "agentic_stage_output/\${rel_path}" ${outputDir}/${pxd}/agentic_metadata/metadata_extraction_output/
        fi
    done

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${manifestPath} \
        --base_dir ${baseDir} \
        --outdir ${outputDir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage agentic_metadata_extraction \
        ${store_backed_agentic_args} || true
    """
}


/* -----------------------
 * PROCESS: llm_judge
 * --------------------- */
process llm_judge {

    tag "llm-refinement-judge-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true, saveAs: { name ->
        def normalized = name.replaceFirst('^\\./', '')
        if (!normalized || normalized == 'judge_stage_output') {
            return null
        }
        normalized = normalized.replaceFirst('^judge_stage_output/?', '')
        if (!normalized || normalized.startsWith('judge_stage_output/') || normalized.startsWith('llm_refinement_judge/')) {
            return null
        }
        return "llm_refinement_judge/${normalized}"
    }

    cache false

    errorStrategy 'ignore'  // Non-blocking quality step; pipeline continues if judge fails

    input:
    tuple val(pxd), path(agentic_stage_output)

    output:
    tuple val(pxd), path("judge_stage_output")

    script:
    def store_backed_agentic_args = pipelineMode == 'agentic_only' ? "--store_backed_agentic_only" : ""
    def configuredOutdir = new File(params.outdir.toString())
    def outputDir = configuredOutdir.isAbsolute() ? configuredOutdir.canonicalPath : new File(baseDir.toString(), params.outdir.toString()).canonicalPath
    def manifestPath = stageManifestPath
    """
    # Initialize conda
    ${params.conda_init}

    MANIFEST_RC=0
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${manifestPath} \
        --base_dir ${baseDir} \
        --outdir ${outputDir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage llm_judge \
        ${store_backed_agentic_args} || MANIFEST_RC=\$?
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

    # Materialize the pre-SDRF judge that supplies safe refinement overrides.
    mkdir -p ${outputDir}/${pxd}/llm_refinement_judge
    for rel_path in json_outputs llm_judge_accuracy.png llm_judge_aggregate.png llm_judge_annotation_quality_counts.png llm_judge_annotation_review.csv llm_judge_coverage.csv llm_judge_per_paper.csv skipped.json; do
        if [ -e "judge_stage_output/\${rel_path}" ]; then
            cp -r "judge_stage_output/\${rel_path}" ${outputDir}/${pxd}/llm_refinement_judge/
        fi
    done

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${manifestPath} \
        --base_dir ${baseDir} \
        --outdir ${outputDir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage llm_judge \
        ${store_backed_agentic_args} || true
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
    // a nested subtree like sdrf_judge/. Verified empirically with a minimal
    // standalone Nextflow script. So publishing of both the SDRF file and the
    // final SDRF judge subtree is done via explicit `cp` in the script block below,
    // not through saveAs.
    publishDir "${params.outdir}/${pxd}/agentic_metadata", mode: 'copy', overwrite: true, saveAs: { name -> name.endsWith('.sdrf.tsv') ? name : null }

    cache false

    errorStrategy 'terminate'

    input:
    tuple val(pxd), path(agentic_stage_output), path(aggregated_results), path(judge_stage_output)

    output:
    tuple val(pxd), path("finalize_stage_output")
    path("${pxd}.sdrf.tsv"), optional: true

    script:
    def store_backed_agentic_args = pipelineMode == 'agentic_only' ? "--store_backed_agentic_only" : ""
    def configuredOutdir = new File(params.outdir.toString())
    def outputDir = configuredOutdir.isAbsolute() ? configuredOutdir.canonicalPath : new File(baseDir.toString(), params.outdir.toString()).canonicalPath
    def manifestPath = stageManifestPath
    """
    ${params.conda_init}

    MANIFEST_RC=0
    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py prepare \
        --manifest ${manifestPath} \
        --base_dir ${baseDir} \
        --outdir ${outputDir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage finalize_sdrf \
        ${store_backed_agentic_args} || MANIFEST_RC=\$?
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
        --aggregated_results ${aggregated_results} \
        --pmc_cache ${baseDir}/pride_survey/pmc_cache \
        --output_dir finalize_stage_output \
        \${judge_args}

    # Copy final SDRF outputs into the configured result directory.
    if [ -f "finalize_stage_output/${pxd}.sdrf.tsv" ]; then
        mkdir -p ${outputDir}/${pxd}/agentic_metadata
        cp finalize_stage_output/${pxd}.sdrf.tsv ${outputDir}/${pxd}/agentic_metadata/${pxd}.sdrf.tsv
    fi
    if [ -f "finalize_stage_output/${pxd}.confidence.sdrf.tsv" ]; then
        mkdir -p ${outputDir}/${pxd}/agentic_metadata
        cp finalize_stage_output/${pxd}.confidence.sdrf.tsv ${outputDir}/${pxd}/agentic_metadata/${pxd}.confidence.sdrf.tsv
    fi
    if [ -f "finalize_stage_output/${pxd}.sdrf_refinement_report.json" ]; then
        mkdir -p ${outputDir}/${pxd}/agentic_metadata
        cp finalize_stage_output/${pxd}.sdrf_refinement_report.json ${outputDir}/${pxd}/agentic_metadata/${pxd}.sdrf_refinement_report.json
    fi
    if [ -f "finalize_stage_output/${pxd}.sdrf_refinement_metrics.json" ]; then
        mkdir -p ${outputDir}/${pxd}/agentic_metadata
        cp finalize_stage_output/${pxd}.sdrf_refinement_metrics.json ${outputDir}/${pxd}/agentic_metadata/${pxd}.sdrf_refinement_metrics.json
    fi

    # Publish the final SDRF judge subtree explicitly via cp -- Nextflow's publishDir/saveAs
    # cannot reach into a nested subdirectory of a directory-type output (see
    # note above), so we copy it ourselves, excluding the internal prompt cache.
    if [ -d "finalize_stage_output/sdrf_judge" ]; then
        dest="${outputDir}/${pxd}/sdrf_judge"
        mkdir -p "\$dest"
        shopt -s nullglob
        final_judge_items=(finalize_stage_output/sdrf_judge/*)
        for item in "\${final_judge_items[@]}"; do
            base=\$(basename "\$item")
            case "\$base" in
                .prompt_cache*) continue ;;
            esac
            cp -r "\$item" "\$dest/"
        done
        shopt -u nullglob
    fi

    ls -la finalize_stage_output/ || echo "No finalized SDRF output"

    ${params.meti_env_path}/bin/python ${baseDir}/src/python/stage_manifest.py mark-complete \
        --manifest ${manifestPath} \
        --base_dir ${baseDir} \
        --outdir ${outputDir} \
        --central_dir ${params.central_mzml_dir} \
        --pxd ${pxd} \
        --stage finalize_sdrf \
        ${store_backed_agentic_args} || true
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