# Aggregated Results JSON Schema

## Overview

The `PXD######_aggregated_results.json` file is the master output of the pipeline, containing all processed data, metadata, and analysis results in a unified JSON structure. This document describes the complete schema with all top-level sections and their contents.

## Top-Level Structure

```
{
  "pxd_id": string,
  "pipeline_version": string,
  "aggregation_timestamp": string (ISO 8601),
  "input_paths": object,
  "runAssessor": object,
  "organism_identification": object,
  "pride_metadata": object,
  "llm_extracted_metadata": object,
  "taxid_warnings": object,
  "processing_summary": object,
  "PTM-shepherd_open_search": object,
  "PTM-shepherd_closed_search": object,
  "SAGE_results": object
}
```

---

## 1. Metadata Fields

### `pxd_id` (string)
- **Description**: PRIDE Project identifier
- **Example**: `"PXD000070"`
- **Format**: PXDXXXXXX

### `pipeline_version` (string)
- **Description**: Version of the pipeline that generated this file
- **Example**: `"1.0"`

### `aggregation_timestamp` (string)
- **Description**: ISO 8601 timestamp of when results were aggregated
- **Example**: `"2026-01-27T20:14:34.819683"`

---

## 2. Input Paths

### `input_paths` (object)

All relative paths used to locate input data during aggregation:

```json
{
  "input_paths": {
    "pxd_dir": "PXD000070",
    "organism_dir": "organism_results",
    "sage_results_dir": "sage_results",
    "llm_results_dir": "llm_results",
    "pride_json_dir": "/data/20250927/pride_json",
    "taxid_warnings": "taxid_warnings.json"
  }
}
```

---

## 3. Run Assessor

### `runAssessor` (object)

Instrument configuration, quantification detection, and data acquisition metadata from `runAssessor` analysis:

```json
{
  "runAssessor": {
    "files": {
      "<absolute_path_to_file.mzML>": {
        "ROIs": {
          "TMT6plex": { /* Reporter ion detection */ },
          "iTRAQ4": { /* Reporter ion detection */ },
          "SILAC_K": { /* Heavy isotope detection */ }
          /* ... other quantification types */
        },
        "instrument_model": {
          "accession": "MS:1002732",
          "name": "Orbitrap Fusion Lumos",
          "rank": 1
        },
        "spectra_stats": {
          "acquisition_type": "DDA",
          "fragmentation_type": "HR_HCD",
          "high_accuracy_precursors": true,
          "n_ms2_spectra": 45563,
          "n_charge_4_precursors": 31328
        },
        "summary": {
          "fragmentation_type": "HR_HCD",
          "labeling": {
            "call": "LFQ",  /* or "TMT6", "iTRAQ4", "SILAC", "none" */
            "scores": { /* Scoring for each quantification type */ }
          }
        }
      }
    },
    "knowledge": {
      "labeling_type": "LFQ",
      "instrument_model": "Orbitrap Fusion Lumos",
      "fragmentation_type": "HCD"
    }
  }
}
```

---

## 4. Organism Identification

### `organism_identification` (object)

Results from Peptonizer2000 de novo sequencing analysis:

```json
{
  "organism_identification": {
    "results": [
      {
        "file_path": "organism_results/CasanovoSequence/.../peptonizer_result.csv",
        "filter_threshold": 70,
        "num_predictions": 1247,
        "columns": ["sequence", "confidence", "organism"],
        "data": [
          {
            "sequence": "PEPTIDESEQUENCE",
            "confidence": 0.95,
            "organism": "Plasmodium falciparum"
          }
          /* ... more predictions */
        ]
      }
    ],
    "summary": {
      "num_files_processed": 6,
      "total_predictions": 7482,
      "filter_thresholds_used": [70, 80]
    }
  }
}
```

**Fields:**
- `results`: Array of Peptonizer2000 outputs per raw file
- `filter_threshold`: Confidence threshold (70, 80, 90 pct)
- `num_predictions`: Number of de novo sequences
- `data`: Full prediction records

---

## 5. PTM-Shepherd Open Search

### `PTM-shepherd_open_search` (object)

Post-translational modifications discovered in pass 1 (open search with ±500 Da tolerance):

```json
{
  "PTM-shepherd_open_search": {
    "file_path": "sage_results/pass1_open_search/global.modsummary.tsv",
    "num_modifications": 163,
    "data": [
      {
        "Modification": "Phosphorylation",
        "Mass Shift": 79.966331,
        "SAGE_Output_PSMs": 170,
        "SAGE_Output_percent_PSMs": 0.065
      },
      {
        "Modification": "Unannotated mass-shift -87.1605",
        "Mass Shift": -87.1605,
        "SAGE_Output_PSMs": 226,
        "SAGE_Output_percent_PSMs": 0.086
      }
      /* ... 161 more modifications */
    ]
  }
}
```

**Fields:**
- `file_path`: Location of TSV file with all modifications
- `num_modifications`: Total unique modifications detected
- `data`: Array of modification records from PTM-Shepherd
  - `Modification`: Name or mass shift description
  - `Mass Shift`: Delta mass in Da
  - `SAGE_Output_PSMs`: Number of PSMs with this modification
  - `SAGE_Output_percent_PSMs`: Percentage of all PSMs

**Note**: Pass 1 runs with **no variable modifications** to enable unbiased PTM discovery. 14 PTMs are typically selected for pass 2.

---

## 6. PTM-Shepherd Closed Search

### `PTM-shepherd_closed_search` (object | null)

Post-translational modifications discovered in pass 2 (closed search with ±20 ppm tolerance, validated PTMs only):

```json
{
  "PTM-shepherd_closed_search": {
    "file_path": "sage_results/pass2_closed_search/global.modsummary.tsv",
    "num_modifications": 26,
    "data": [
      {
        "Modification": "Phosphorylation",
        "Mass Shift": 79.966331,
        "SAGE_Output_PSMs": 2450,
        "SAGE_Output_percent_PSMs": 11.267
      },
      {
        "Modification": "Pyrophosphorylation",
        "Mass Shift": 159.932662,
        "SAGE_Output_PSMs": 1279,
        "SAGE_Output_percent_PSMs": 5.878
      }
      /* ... 24 more modifications */
    ]
  }
}
```

**Key Characteristics**:
- Much smaller modification list (26 vs 163 in pass 1)
- Only validated, high-confidence modifications
- Much higher PSM counts (11.27% phospho vs 0.065% in pass 1)
- **14.4x improvement** for phosphoproteomics

**Note**: Will be `null` if pass 2 fails or is skipped.

---

## 7. SAGE Results

### `SAGE_results` (object)

Comprehensive search engine results for both passes with quantification data for pass 2:

```json
{
  "SAGE_results": {
    "pass1_open_search": {
      "psm_file": "sage_results/pass1_open_search/results.sage.tsv",
      "results_json": "sage_results/pass1_open_search/results.json",
      "num_psms": 261508,
      "num_unique_peptides": 199163,
      "num_unique_proteins": 1067871
    },
    "pass2_closed_search": {
      "psm_file": "sage_results/pass2_closed_search/results.sage.tsv",
      "results_json": "sage_results/pass2_closed_search/results.json",
      "num_psms": 21745,
      "num_unique_peptides": 18448,
      "num_unique_proteins": 135340,
      "quantification": {
        "method": "LFQ",
        "per_file_statistics": {
          "OTPf-IMACDDNL_2010Mar06-02.mzML": {
            "num_psms": 3671,
            "num_unique_peptides": 3406
          },
          /* ... 5 more files */
        },
        "results": [
          {
            "psm_id": 2671,
            "peptide": "GFEVIYMVDPIDEYAVQQLK",
            "proteins": "tr|Q25869|Q25869_PLAFA;tr|Q25882|Q25882_PLAFA;tr|Q25883|Q25883_PLAFA",
            "expmass": 2356.1636,
            "calcmass": 2356.166,
            "charge": 2,
            "peptide_len": 20,
            "missed_cleavages": 0,
            "spectrum_q": 0.0014347202,
            "peptide_q": 0.004538922,
            "protein_q": 0.009947713,
            "ms2_intensity": 34551.438
          }
          /* ... 21,744 more PSM records */
        ]
      }
    }
  }
}
```

#### Pass 1 - Open Search Fields:
- `psm_file`: Path to TSV with all 261K+ PSMs (±500 Da tolerance)
- `num_psms`: Total PSM spectrum matches
- `num_unique_peptides`: Unique sequences
- `num_unique_proteins`: Protein matches (sum of multi-mappings)

#### Pass 2 - Closed Search Fields:

**Basic Metadata:**
- `psm_file`: Path to refined PSM results (±20 ppm, validated PTMs only)
- `num_psms`: High-quality PSMs (21,745)
- `num_unique_peptides`: Validated sequences (18,448)
- `num_unique_proteins`: Protein identifications

**Quantification Section:**

- `method`: `"LFQ"` (Label-Free Quantification)
  - Can also be: `"TMT6"`, `"TMT10"`, `"TMT11"`, `"TMT16"`, `"iTRAQ4"`, `"iTRAQ8"`, `"SILAC"`, or `"LFQ"`

- `per_file_statistics`: Stats grouped by raw file
  - `num_psms`: PSMs in this file
  - `num_unique_peptides`: Unique sequences

- `results`: **Array of all 21,745 PSM records** with these columns:
  - `psm_id`: Unique SAGE PSM identifier
  - `peptide`: Amino acid sequence (may include PTM annotations like `S[+79.96633]`)
  - `proteins`: Protein ID(s) from FASTA (semicolon-separated if multiple)
  - `expmass`: Measured precursor m/z
  - `calcmass`: Calculated precursor m/z
  - `charge`: Precursor charge state
  - `peptide_len`: Number of amino acids
  - `missed_cleavages`: Trypsin missed cleavage count
  - `spectrum_q`: PSM quality score (FDR)
  - `peptide_q`: Peptide-level FDR
  - `protein_q`: Protein-level FDR
  - `ms2_intensity`: LFQ intensity value for quantification

---

## 8. PRIDE Metadata

### `pride_metadata` (object)

Project metadata from PRIDE JSON export:

```json
{
  "pride_metadata": {
    "accession": "PXD000070",
    "title": "Quantitative Proteomics of Phosphorylated Proteins in P. falciparum",
    "organism": {
      "name": "Plasmodium falciparum",
      "taxid": 5833
    },
    "publication": {
      "doi": "10.1074/mcp.M111.010231",
      "pubmed_id": "21965014"
    },
    /* ... additional PRIDE fields */
  }
}
```

---

## 9. LLM Extracted Metadata

### `llm_extracted_metadata` (object | null)

Automatically extracted metadata from publications using LLM:

```json
{
  "llm_extracted_metadata": {
    "file_path": "llm_results/{PXD}_Metadata.json",
    "enrichment_method": "Immobilized metal affinity chromatography (IMAC)",
    "modification_targeted": "Phosphorylation",
    "sample_preparation": "Protein extraction from parasite pellets...",
    "quantification_method": "Label-free",
    "key_findings": "..."
  }
}
```

**Note**: Will be `null` if LLM extraction was not run or API key not configured.

---

## 10. Taxid Warnings

### `taxid_warnings` (object | null)

Warnings and issues encountered during taxid determination:

```json
{
  "taxid_warnings": {
    "potential_contamination": [
      {
        "organism": "Escherichia coli",
        "taxid": 562,
        "confidence": "medium"
      }
    ],
    "multiple_organisms_detected": true,
    "primary_organism": {
      "name": "Plasmodium falciparum",
      "taxid": 5833,
      "confidence": "high"
    }
  }
}
```

---

## 11. Processing Summary

### `processing_summary` (object)

Summary of pipeline execution and data availability:

```json
{
  "processing_summary": {
    "runAssessor_found": true,
    "organism_results_found": true,
    "ptm_shepherd_open_search_found": true,
    "ptm_shepherd_closed_search_found": true,
    "sage_results_found": true,
    "llm_metadata_found": false,
    "pride_metadata_found": true,
    "taxid_warnings_found": true,
    "total_data_files": 7
  }
}
```

---

## Data Access Examples

### Query quantification data for a specific file:

```bash
jq '.SAGE_results.pass2_closed_search.quantification.per_file_statistics."OTPf-IMACDDNL_2010Mar06-02.mzML"' results/PXD000070/PXD000070_aggregated_results.json
```

### Get all phosphorylation PSMs:

```bash
jq '.SAGE_results.pass2_closed_search.quantification.results[] | select(.peptide | contains("[+79.96633]"))' results/PXD000070/PXD000070_aggregated_results.json
```

### Extract LFQ intensities for downstream analysis:

```bash
jq '.SAGE_results.pass2_closed_search.quantification.results | map({peptide, proteins, intensity: .ms2_intensity})' results/PXD000070/PXD000070_aggregated_results.json > intensities.json
```

### Check PTM distribution between passes:

```bash
echo "Pass 1 mods:" && jq '.PTM-shepherd_open_search.num_modifications' results/PXD000070/PXD000070_aggregated_results.json
echo "Pass 2 mods:" && jq '.PTM-shepherd_closed_search.num_modifications' results/PXD000070/PXD000070_aggregated_results.json
```

---

## File Size Considerations

The aggregated JSON can be large, especially for samples with many PSMs:

- **Typical size**: 100-500 MB for phosphoproteomics experiments
- **PXD000070 example**: ~107 MB (21,745 PSMs with full metadata)

**Compression:**
```bash
gzip results/PXD000070/PXD000070_aggregated_results.json
# Reduces to ~10-20 MB typically
```

---

## Two-Pass Workflow Benefits

The aggregated results capture the two-pass SAGE workflow:

| Aspect | Pass 1 (Open) | Pass 2 (Closed) |
|--------|-------------|-----------------|
| **Tolerance** | ±500 Da | ±20 ppm |
| **Mods** | None (unbiased) | Top 14 discovered + quantification |
| **PSMs** | 261,508 | 21,745 |
| **Purpose** | PTM discovery | Validation + quantification |
| **PTM Sensitivity** | Low (0.065% phospho) | High (11.27% phospho) |

This enables **14.4x improvement** in phospho detection for phosphoproteomics samples.

---

## Schema Version History

- **v1.0** (2026-01-27): Initial two-pass schema with full quantification data
  - Split PTM-Shepherd sections
  - Comprehensive pass 2 quantification results
  - Per-file statistics
  - 11 key columns for each PSM
