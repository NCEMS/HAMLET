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

NEXTFLOW OPTIONS (runtime)
    nextflow help run

PIPELINE PARAMS (this workflow)
    Input selection (required: choose one)
        --pxd <PXD000000>                 Single PXD accession
        --pxd_csv <PXDs.csv>              CSV with PXD IDs (first column)
        --num_pxds <N>                    Limit number of PXDs from CSV

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
        --run_search true|false                        Default: false
        --taxid <taxid>                               Default: 9606 (may be overridden)
        --search_min_ptm_psms <N>                     Default: 50
        --search_max_variable_mods <N>                Default: 4

    Download control
        --max_raw_files <N>               Default: 30 (null = all)
        --use_aria2c true|false           Default: true
        --aria2c_threads <N>              Default: 4
        --max_parallel_pxds <N>           Default: 10
        --download_timeout <duration>     Default: 4h

    Organism identification
        --run_organism_id true|false      Default: true

    LLM metadata extraction
        --run_llm_extraction true|false   Default: false
        --run_agentic_metadata true|false Default: false

EXAMPLES
    # AUTO routing (default), multiple PXDs
    nextflow run main.nf --pxd_csv PXDs.csv -resume

    # Force DIA for everything
    nextflow run main.nf --pxd_csv PXDs.csv --acquisition_type DIA -resume

    # Single PXD, no search
    nextflow run main.nf --pxd PXD000070 --run_search false -resume
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

params.run_search         = params.run_search         ?: false
// Search routing (simplified):
//   - if run_search=true and DDA: open search -> PTM-Shepherd -> closed search
//   - if run_search=true and DIA: DIA-NN inference only (default mods)
// Backwards-compat: old values 'open_only'/'open_and_closed' are treated as true.
params.search_min_ptm_psms = params.search_min_ptm_psms ?: 50

params.run_organism_id    = params.run_organism_id    ?: true   // Run organism_id (de novo + Peptonizer)
params.search_max_variable_mods = params.search_max_variable_mods ?: 4  // Max variable mods (e.g., Phosphorylation, Oxidation)
params.high_confidence_q_threshold = params.high_confidence_q_threshold ?: 0.01
params.min_high_confidence_peptides = params.min_high_confidence_peptides ?: 10
params.taxid              = params.taxid              ?: '9606'
params.acquisition_type   = params.acquisition_type   ?: 'AUTO'  // AUTO, DDA, DIA

params.run_agentic_metadata = params.run_agentic_metadata ?: false  // Enable LLM metadata extraction after aggregation

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
    
    // Ensure required directories exist for search infrastructure
    // DIA-NN needs diann_libraries directory to cache spectral libraries
    def diann_libs_dir = new File("${baseDir}/assets/diann_libraries")
    if (!diann_libs_dir.exists()) {
        log.info "Creating DIA-NN library cache directory: ${diann_libs_dir.absolutePath}"
        diann_libs_dir.mkdirs()
    }

    // Create PXD channel from either single PXD or CSV file
    if (params.pxd_csv) {
        // Read PXDs from CSV file
        log.info "Reading PXDs from CSV: ${params.pxd_csv}"
        
        // Read and collect PXDs to list first
        def pxd_list = []
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
        
        // Apply limit if specified
        if (params.num_pxds) {
            pxd_list = pxd_list.take(params.num_pxds as int)
        }
        
        log.info "Will process ${pxd_list.size()} PXD(s) in parallel: ${pxd_list.join(', ')}"
        
        // Create channel from list
        pxd_ch = Channel.fromList(pxd_list)
        
    } else if (params.pxd) {
        // Single PXD mode
        log.info "Processing single PXD: ${params.pxd}"
        pxd_ch = Channel.of(params.pxd)
    } else {
        error "Must specify either --pxd (single PXD) or --pxd_csv (CSV file with PXDs)"
    }

    // Fetch all PXDs (runs in parallel)
    // Output: [pxd, fetched_dir]
    // fetch_pxd produces: tuple(pxd, fetched_dir)  
    fetched_ch = fetch_pxd(pxd_ch)
        .map { pxd, work_path -> 
            // Use stable canonical path instead of work-dir symlink for downstream cache stability
            tuple(pxd, file("${params.central_mzml_dir}/${pxd}"))
        }

    // Auto-detect acquisition type and labeling from runAssessor results
    // Output: [pxd, fetched_dir, detected_params_json]
    if (params.auto_detect) {
        detected_ch = parse_runAssessor(fetched_ch)
    } else {
        // Create a dummy channel with user-provided params - need to create a JSON file
        detected_ch = fetched_ch.map { pxd, fetched_dir ->
            // This would need to create a dummy JSON, but for now we'll require auto_detect
            error "Manual parameter specification not yet supported in parallel mode. Use --auto_detect true"
        }
    }

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
    
    // Run LLM-based metadata extraction from publications (optional, runs in parallel)
    // Output: [pxd, llm_results]
    if (params.run_llm_extraction) {
        llm_results_ch = llm_extraction(fetched_ch)
    } else {
        // Create dummy files with unique names per PXD to avoid collisions
        llm_results_ch = fetched_ch.map { pxd, fetched_dir ->
            // Create a unique placeholder file for this PXD
            def dummy_llm = file("${baseDir}/work/dummy_llm_${pxd}.empty")
            dummy_llm.parent.mkdirs()
            dummy_llm.text = ""
            tuple(pxd, dummy_llm)
        }
    }

    // Create channels for input files (these are shared across all PXDs)
    contaminants_ch = Channel.fromPath(params.contaminants_fasta, checkIfExists: true)
    taxid_list_ch = Channel.fromPath(params.taxid_list_file, checkIfExists: true)

    // Route to appropriate conda environment (DIA vs DDA) based on detected_params.json
    // Cascadia (DIA) and Casanovo (DDA) environments selected by organism_id process
    organism_input_ch = detected_ch.combine(contaminants_ch).combine(taxid_list_ch)

    // Run organism ID (optional) or use dummy results
    if (params.run_organism_id) {
        log.info "Running organism_id process (de novo + Peptonizer)"
        organism_with_context_ch = organism_id(organism_input_ch)
    } else {
        log.info "Skipping organism_id process (--run_organism_id false). Will use LLM + PRIDE metadata only."
        // Create dummy organism_results for each PXD to maintain channel structure
        organism_with_context_ch = organism_input_ch.map { pxd, fetched_dir, detected_params, contaminants, taxid_list ->
            def dummy_organism = file("${baseDir}/work/dummy_organism_${pxd}.empty")
            dummy_organism.parent.mkdirs()
            dummy_organism.text = "{}"
            tuple(pxd, fetched_dir, detected_params, dummy_organism)
        }
    }
    
    // Extract just organism_results for downstream processes that don't need context
    organism_results_ch = organism_with_context_ch.map { pxd, fetched_dir, detected_params, organism_results ->
        tuple(pxd, organism_results)
    }
    
    // Pre-join all inputs for determine_taxids by PXD key to prevent channel multiplication
    // This ensures exactly 1 task invocation per PXD (not duplicates from implicit Nextflow grouping)
    taxid_input_ch = organism_with_context_ch
        .map { pxd, fetched_dir, detected_params, organism_results -> 
            tuple(pxd, fetched_dir, organism_results) 
        }
        .join(llm_results_ch, by: 0, remainder: true)
        .map { pxd, fetched_dir, organism_results, llm_results -> 
            tuple(pxd, fetched_dir, organism_results, llm_results) 
        }
    
    // Determine taxids for each raw file from organism_id, LLM, and PRIDE metadata
    // Output: [pxd, taxid_mapping.json, warnings.json]
    taxid_mapping_ch = determine_taxids(taxid_input_ch)
    
    // Run search if enabled
    // Accept true/false and legacy tri-state strings.
    def run_search_str = params.run_search == null ? 'false' : params.run_search.toString().trim().toLowerCase()
    def do_search = (run_search_str in ['true','open_only','open_and_closed'])
    if (do_search) {
        // Use organism_with_context_ch to get fetched_dir and detected_params, then add taxid_mapping
        // Output: [pxd, search_results]
        search_input_ch = organism_with_context_ch
            .map { pxd, fetched_dir, detected_params, organism_results -> tuple(pxd, fetched_dir, detected_params) }
            .join(taxid_mapping_ch.map { pxd, mapping, warnings -> tuple(pxd, mapping) })
        
        search_results_ch = search(search_input_ch)
    } else {
        // Create dummy files with unique names per PXD to avoid collisions
        search_results_ch = organism_with_context_ch.map { pxd, fetched_dir, detected_params, organism_results ->
            // Create a unique placeholder file for this PXD
            def dummy_sage = file("${baseDir}/work/dummy_sage_${pxd}.empty")
            dummy_sage.parent.mkdirs()
            dummy_sage.text = ""
            tuple(pxd, dummy_sage)
        }
    }
    
    // Combine all results for aggregation
    // Join channels by PXD ID to match results together
    // We need: [pxd, fetched_dir, organism_results, search_results, llm_results, taxid_warnings]
    combined_ch = organism_with_context_ch
        .map { pxd, fetched_dir, detected_params, organism_results -> tuple(pxd, fetched_dir, organism_results) }
        .join(search_results_ch)            // Join on pxd: [pxd, fetched_dir, organism_results, search_results]
        .join(llm_results_ch)             // Join on pxd: [pxd, fetched_dir, organism_results, search_results, llm_results]
        .join(taxid_mapping_ch.map { pxd, mapping, warnings -> tuple(pxd, warnings) })  // Add warnings
    
    // Split combined_ch into two branches to allow reuse for both aggregate and agentic processes
    combined_ch
        .multiMap { pxd, fetched_dir, organism_results, search_results, llm_results, taxid_warnings ->
            for_aggregate: tuple(pxd, fetched_dir, organism_results, search_results, llm_results, taxid_warnings)
            for_agentic: tuple(pxd, llm_results)
        }
        .set { combined_split }
    
    // Run aggregation after all processes complete
    aggregated_results_ch = aggregate_results(combined_split.for_aggregate)
    
    // Conditionally run agentic metadata extraction if enabled
    // Also build a final barrier channel so we can run ResultsSummary exactly once
    // after the last enabled step completes for all PXDs.
    def final_barrier_ch
    if (params.run_agentic_metadata) {
        // Extract llm_results and aggregate path for agentic metadata process
        // aggregated_results_ch contains: [pxd, aggregated_results.json, pipeline.json, pipeline_summary.md]
        // combined_split.for_agentic contains: [pxd, llm_results]
        // Join and filter out any entries where aggregated_results is null (failed upstream processes)
        agentic_input_ch = aggregated_results_ch
            .map { pxd, aggregated_results, pipeline_json, pipeline_summary -> tuple(pxd, aggregated_results) }
            .join(combined_split.for_agentic, remainder: true)
            .filter { pxd, aggregated_results, llm_results -> aggregated_results != null }
        
        agentic_results_ch = agentic_metadata_extraction(agentic_input_ch)

        // Ensure summary waits for agentic extraction too
        final_barrier_ch = aggregated_results_ch
            .map { pxd, aggregated_results, pipeline_json, pipeline_summary -> tuple(pxd, aggregated_results) }
            .join(agentic_results_ch)
            .map { pxd, aggregated_results, metadata_extraction_output -> tuple(pxd, aggregated_results) }
    } else {
        final_barrier_ch = aggregated_results_ch
            .map { pxd, aggregated_results, pipeline_json, pipeline_summary -> tuple(pxd, aggregated_results) }
    }

    // Run ResultsSummary once after pipeline completion
    results_summary(final_barrier_ch.collect())
}


/* -----------------------
 * PROCESS: parse_runAssessor
 * --------------------- */
process parse_runAssessor {

    tag "detect-${fetched_dir.name}"

    publishDir "${params.outdir}/${fetched_dir.name}", mode: 'copy', overwrite: false

    cache 'deep'

    errorStrategy 'ignore'  // Skip PXDs that fail auto-detection

    input:
    tuple val(pxd), path(fetched_dir)

    output:
    tuple val(pxd), path(fetched_dir), path("detected_params.json")

    script:
    """
    # Initialize conda
    ${params.conda_init}
    
    # Parse runAssessor results to detect acquisition type and labeling
    # Pass central_mzml_dir for fast reuse of cached runAssessor results on second run
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/parse_runAssessor.py \\
        --input_dir ${fetched_dir} \\
        --output detected_params.json \\
        --central_mzml_dir ${params.central_mzml_dir} \\
        --pxd ${pxd}

    # Display results
    echo "Detected parameters:"
    cat detected_params.json
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
    
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/determine_taxids.py \\
        --pxd ${pxd} \\
        --fetched_dir ${fetched_dir} \\
        --organism_results ${organism_results} \\
        --llm_results ${llm_results} \\
        ${default_taxid_arg} \\
        --output_mapping taxid_mapping.json \\
        --output_warnings taxid_warnings.json
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
    
    # FetchPXD.py handles all caching logic:
    # 1. Checks if files exist in central_mzml_dir
    # 2. If yes: creates symlink ${pxd} -> central_mzml_dir/PXD and exits (no re-download)
    # 3. If no: downloads and converts files to central_mzml_dir/PXD, then creates symlink
    # This way, empty central_mzml_dir won't cause false cache hits
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/FetchPXD.py \\
        --central_mzml_dir ${params.central_mzml_dir} \
        --PXD ${pxd} \
        ${aria2c_args} \
        ${max_files_arg} \
        --log_file fetch/events.jsonl

    # Clean up original .raw files after conversion to .mzML
    # Keep only .mzML files to save disk space (all downstream processes use only .mzML)
    echo "Cleaning up original .raw files..."
    find ${pxd} -type f -iname "*.raw" -delete
    echo "✓ Original .raw files removed"

    ls -R ${pxd} || true
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
    tuple val(pxd), path(fetched_dir), path(detected_params), path(contaminants_fasta), path(taxid_list_file)

    output:
    tuple val(pxd), path(fetched_dir), path(detected_params), path("organism_results")

    script:
    def peptonizer_container_arg = params.peptonizer_container ? "--peptonizer_container ${params.peptonizer_container}" : ""
    """
    set +e  # Don't exit on errors; we'll handle them
    
    # Initialize conda
    ${params.conda_init}
    
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
    """
}


/* -----------------------
 * PROCESS: aggregate_results
 * --------------------- */
process aggregate_results {

    tag "aggregate-${pxd}"

    publishDir "${params.outdir}/${pxd}", mode: 'copy', overwrite: true

    cache 'deep'

    errorStrategy 'ignore'

    input:
    tuple val(pxd), path(fetched_dir), path(organism_results), path(search_results), path(llm_results), path(taxid_warnings)

    output:
    tuple val(pxd), path("${pxd}_aggregated_results.json"), path("${pxd}_pipeline.json"), path("${pxd}_pipeline_summary.md")

    script:
    """
    # Initialize conda
    ${params.conda_init}
    
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
    """
}
/* -----------------------
 * PROCESS: agentic_metadata_extraction
 * --------------------- */
process agentic_metadata_extraction {

    tag "agentic-${pxd}"

    publishDir "${params.outdir}/${pxd}/agentic_metadata", mode: 'copy', overwrite: true

    cache 'deep'

    errorStrategy 'ignore'  // Continue if metadata extraction fails

    input:
    tuple val(pxd), path(aggregated_results), path(llm_results_dir)

    output:
    tuple val(pxd), path("metadata_extraction_output")

    script:
    """
    # Initialize conda
    ${params.conda_init}

    mkdir -p metadata_extraction_output

    # Ensure both variable names are available inside the task and inherited by conda run.
    export LLM_API_KEY="\${LLM_API_KEY:-\${OPENAI_API_KEY:-}}"
    export OPENAI_API_KEY="\${OPENAI_API_KEY:-\${LLM_API_KEY:-}}"

    # Run unified wrapper: performs agentic extraction and writes SDRF TSV.
    echo "=== Running Agentic Metadata Extraction wrapper for ${pxd} ==="
    conda run -p ${params.meti_env_path} python ${baseDir}/src/python/run_agentic_metadata.py \\
        --input ${aggregated_results} \\
        --outdir metadata_extraction_output \\
        --pride_cache ${baseDir}/pride_survey/pride_cache \\
        --pmc_cache ${baseDir}/pride_survey/pmc_cache || {
        echo "WARNING: Agentic metadata extraction failed for ${pxd} - continuing"
        mkdir -p metadata_extraction_output
    }

    # Non-fatal validation for expected SDRF output from wrapper.
    if [ ! -f "metadata_extraction_output/${pxd}.sdrf.tsv" ]; then
        echo "WARNING: Expected SDRF output missing: metadata_extraction_output/${pxd}.sdrf.tsv"
    fi

    # Verify output
    ls -la metadata_extraction_output/ || echo "No metadata extraction output"
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