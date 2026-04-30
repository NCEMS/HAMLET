# LLM-Assisted Metadata Extraction Integration

## Overview

Added optional LLM-powered metadata extraction from scientific publications to supplement automated parameter detection. The LLM analyzes publication text (title, abstract, methods, results) and raw file names to extract SDRF-format metadata.

## New Components

### 1. Container: `llm-extraction.sif`
- **Base**: Ubuntu 24.04 with Python 3.11
- **Dependencies**: OpenAI API (v1.58.1), pandas, numpy
- **Purpose**: Extract publication text and call LLM for metadata extraction

### 2. Python Scripts
- **GetTextcsvs.py**: Extracts publication text from PMC JSON database
  - Input: PXD IDs, database path
  - Output: JSON files with publication sections (TITLE, ABSTRACT, METHODS, etc.)
  
- **GPT_Extraction.py**: Calls OpenAI API to extract SDRF metadata
  - Input: Publication text JSON, prompt file
  - Output: Per-raw-file SDRF metadata in JSON format
  - Uses multiprocessing for batch processing

### 3. Prompt: `BaselinePrompt.txt`
- Comprehensive SDRF extraction instructions
- Defines allowed metadata categories (Characteristics, Comment, FactorValue)
- Two-round verification process for accuracy

## Pipeline Integration

### Workflow
```
fetch_pxd
    ├─> parse_runAssessor (auto-detect)
    └─> llm_extraction (optional)
             ├─> GetTextcsvs.py (extract publication text)
             └─> GPT_Extraction.py (LLM extraction)
                     ↓
              aggregate_results (combines all outputs)
```

### Parameters (nextflow.config)
```groovy
run_llm_extraction = false              // Enable/disable LLM extraction
pride_database_path = "/path/to/data"   // Path to PMC JSON database
llm_prompt_file = "src/BaselinePrompt.txt"  // Path to extraction prompt
llm_workers = 1                         // API calls per PXD (keep low for rate limits)
```

## Setup Instructions

### 1. Build the Container
```bash
cd containers/
sudo singularity build llm-extraction.sif llm-extraction.def
```

### 2. Set OpenAI API Key
```bash
export OPENAI_API_KEY="your-api-key-here"
```
**Important**: The pipeline requires `OPENAI_API_KEY` to be set as an environment variable.

### 3. Configure Database Path
Update `nextflow.config` with your local database path:
```groovy
pride_database_path = "/your/path/to/pmc_json"
```

The database should contain files in format: `{PXD}_*.json`

## Usage

### Enable LLM Extraction
```bash
# Process multiple PXDs with LLM extraction
nextflow run main.nf \
    --pxd_csv PXDs.csv \
    --run_llm_extraction true \
    --max_raw_files 2 \
    -resume
```

### Without LLM Extraction (Default)
```bash
# Standard pipeline without LLM
nextflow run main.nf --pxd_csv PXDs.csv -resume
```

## Output Structure

### LLM Results Directory
```
results/
└── {PXD}/
    └── llm_results/
        ├── {PXD}_PubText.txt          # Formatted publication text
        ├── {PXD}_PubText.json         # Publication text JSON
        ├── PubText.json               # Master publication text
        └── {MODEL}/                   # e.g., gpt-5-mini-2025-08-07/
            └── {PXD}_Metadata.json    # Extracted SDRF metadata
```

### Aggregated JSON
The final `{PXD}_aggregated_results.json` now includes:
```json
{
    "pxd_id": "PXD000070",
    "llm_extracted_metadata": {
        "filename1.raw": {
            "Source Name": ["..."],
            "Characteristics[Organism]": ["..."],
            "Comment[Instrument]": ["..."],
            ...
        },
        "filename2.raw": {...}
    },
    "processing_summary": {
        "llm_metadata_found": true,
        ...
    }
}
```

## Error Handling

The LLM extraction process is fault-tolerant:
- **Missing API Key**: Warns and creates empty JSON, pipeline continues
- **Missing Publication**: Warns and creates empty JSON, pipeline continues
- **API Failures**: Catches errors, creates empty JSON, pipeline continues
- **Process Failure**: `errorStrategy 'ignore'` ensures other PXDs continue processing

## Resource Management

### Process Limits
- **CPUs**: 2 per PXD (light processing, API-bound)
- **Memory**: 8 GB (for loading publication text)
- **maxForks**: 3 (limits parallel API calls to avoid rate limits)

### API Rate Limiting
- `llm_workers = 1`: Processes one raw file at a time per PXD
- Nextflow `maxForks = 3`: Maximum 3 PXDs calling API simultaneously
- Adjust based on your OpenAI API rate limits

## Testing

### Quick Test (2 raw files per PXD)
```bash
nextflow run main.nf \
    --pxd_csv PXDs.csv \
    --num_pxds 2 \
    --max_raw_files 2 \
    --run_llm_extraction true \
    -resume
```

### Verify Results
```bash
# Check LLM extraction ran
ls -la results/PXD*/llm_results/

# Check aggregated output includes LLM data
cat results/PXD000070/PXD000070_aggregated_results.json | jq '.llm_extracted_metadata'
```

## Cost Considerations

OpenAI API charges per token. Estimate costs:
- **Average publication**: ~5,000-15,000 tokens (input)
- **Metadata extraction**: ~2,000-5,000 tokens (output)
- **Cost estimate**: $0.01-0.05 per PXD (varies by model and publication length)

Use `gpt-4o-mini` for cost-effective extraction or `gpt-4` for maximum accuracy.

## Troubleshooting

### API Key Not Found
```bash
# Set the environment variable
export OPENAI_API_KEY="sk-..."

# Verify it's set
echo $OPENAI_API_KEY
```

### Publication Not Found
Check that PMC JSON files exist in the database directory:
```bash
ls -la /home/ians/HAMLET/data/20250927/pmc_json/PXD000070_*.json
```

### Rate Limit Errors
Reduce parallel API calls:
```groovy
// In nextflow.config
llm_workers = 1
process {
    withName: llm_extraction {
        maxForks = 2  // Reduce from 3 to 2
    }
}
```

## Future Enhancements

Potential improvements:
1. **Prompt tuning**: Optimize prompt for specific metadata categories
2. **Local LLMs**: Add support for local models (Llama, Mistral)
3. **Caching**: Cache LLM results to avoid re-extraction
4. **Validation**: Compare LLM vs runAssessor results for consistency
5. **Active learning**: Use high-confidence extractions to improve model

## Files Modified

| File | Changes |
|------|---------|
| `containers/llm-extraction.def` | **NEW** - Container with OpenAI library |
| `src/python/GetTextcsvs.py` | **NEW** - Publication text extraction |
| `src/python/GPT_Extraction.py` | **NEW** - LLM API integration |
| `src/BaselinePrompt.txt` | **NEW** - SDRF extraction instructions |
| `nextflow.config` | Added LLM parameters and process config |
| `main.nf` | Added `llm_extraction` process, updated workflow |
| `src/python/aggregate_results.py` | Added LLM results loading |

## Complete Integration Summary

The LLM extraction feature:
- ✅ Runs optionally in parallel with other processes
- ✅ Fails gracefully without affecting pipeline
- ✅ Integrated into aggregated JSON output
- ✅ Configurable via parameters
- ✅ Resource-managed to avoid API rate limits
- ✅ Ready for production use
