# Taxid Determination Feature

## Overview

The pipeline now includes intelligent taxid determination for SAGE/DIA-NN searches. Instead of using a hardcoded taxid value, the pipeline determines the appropriate organism taxid for each raw file by combining information from multiple sources.

## Sources of Taxid Information

The `determine_taxids` process extracts taxid values from three sources (in priority order):

1. **organism_id results** (Peptonizer2000)
   - Extracts the highest-scoring taxid for each raw file
   - Most reliable source as it's directly inferred from the peptide data

2. **LLM extraction results**
   - Parses `Characteristics[OrganismTaxid]` from publication metadata
   - Provides taxid when explicitly stated in the publication

3. **PRIDE metadata**
   - Parses `organisms[0].accession` field
   - Extracts taxid from NEWT taxonomy format (e.g., "NEWT:9606")
   - Fallback when organism_id and LLM don't provide taxids

## Validation Logic

### Per-File Validation

For each raw file, the pipeline:

1. Extracts taxid from organism_id if available
2. Extracts taxid from LLM if available
3. Checks for agreement between organism_id and LLM
   - If both exist and disagree → skip file with warning
   - If both agree → use the agreed taxid
   - If only one exists → use that one
4. Falls back to PRIDE metadata if neither organism_id nor LLM provide taxid
5. Uses default taxid (from config) if no valid taxid found

### Bulk Mode Consensus

When `--sage_per_sample false` (default), the pipeline:

1. Validates taxid for each file individually
2. Checks that all files with taxids have the same value
3. If consensus exists → use consensus taxid for bulk SAGE run
4. If no consensus → generate warning

## Configuration Parameters

```bash
--sage_per_sample <boolean>  # Run SAGE per-sample (true) or bulk (false, default)
--taxid <string>             # Default taxid to use if no valid taxid determined (default: null)
```

When `--taxid null`, files without valid taxids will skip SAGE search with a warning.

## Warning Types

The pipeline generates warnings in `taxid_warnings.json` for:

1. **no_organism_id**: No organism_id results found for file
2. **no_llm_results**: No LLM results found for project
3. **invalid_organism_taxid**: organism_id taxid is not valid numeric string
4. **invalid_llm_taxid**: LLM taxid is not valid numeric string
5. **disagreement**: organism_id and LLM taxids disagree
6. **no_valid_taxid**: No valid taxid from any source
7. **using_default**: Using default taxid from config
8. **consensus_check**: Bulk mode consensus validation results

## Output Files

### taxid_mapping.json

Maps each raw file to its determined taxid:

```json
{
  "sage_per_sample": false,
  "consensus_taxid": "9606",
  "mappings": {
    "file1.raw": {
      "taxid": "9606",
      "source": "organism_id+llm"
    },
    "file2.raw": {
      "taxid": "9606",
      "source": "organism_id"
    }
  }
}
```

### taxid_warnings.json

Records warnings and validation issues:

```json
{
  "pxd": "PXD000001",
  "sage_per_sample": false,
  "consensus_taxid": "9606",
  "warnings": [
    {
      "file": "file3.raw",
      "type": "no_llm_results",
      "message": "No LLM results available for this project"
    }
  ]
}
```

## Integration with SAGE

The `sage_search` process:

1. Reads `taxid_mapping.json`
2. Filters mzML files to only those with valid taxids
3. In bulk mode: uses consensus taxid for all files
4. In per-sample mode: runs SAGE separately for each taxid group (TODO)
5. Skips files without valid taxids

## Aggregated Results

The `aggregate_results` process includes:

- `taxid_warnings` section with all warnings
- Full traceability of taxid determination for each file

## Example Usage

### Bulk mode with automatic taxid determination:
```bash
nextflow run main.nf \
  --pxd_csv PXDs.csv \
  --num_pxds 5 \
  --sage_per_sample false \
  --taxid null
```

### With fallback taxid:
```bash
nextflow run main.nf \
  --pxd PXD000001 \
  --taxid 9606  # Use human if no valid taxid determined
```

### Per-sample mode (future):
```bash
nextflow run main.nf \
  --pxd_csv PXDs.csv \
  --sage_per_sample true
```

## Testing

To test the taxid determination feature:

1. Run pipeline on datasets with mixed organism sources
2. Check `taxid_mapping.json` for correct taxid extraction
3. Check `taxid_warnings.json` for validation warnings
4. Verify SAGE runs with appropriate taxid values

## Future Enhancements

- [ ] Implement per-sample SAGE mode with different taxids
- [ ] Add support for multi-organism projects
- [ ] Validate taxids against NCBI taxonomy database
- [ ] Support for mixed DDA/DIA datasets with different organisms
