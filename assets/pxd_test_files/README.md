# Test PXD Files

This directory contains curated PXD test sets for HAMLET pipeline validation and testing.

## Available Test Sets

- **ConsolidatedTestPXDs.csv** (142 PXDs)
  - Union of all test PXDs from the repository
  - Recommended for comprehensive testing
  - Includes successful and challenging datasets

- **GoldStandardSDRFs.csv** (101 PXDs)
  - High-quality datasets with validated SDRF files
  - Best for production validation and benchmarking
  - Organized by acquisition type and organism

- **PXDs.csv** (12 PXDs)
  - General purpose test set
  - Good mix of DDA and DIA datasets
  - Suitable for standard testing workflows

- **PXDsTest.csv** (2 PXDs)
  - Minimal quick test set
  - Fast validation of pipeline execution
  - Recommended for CI/CD integration

- **PXDsingle.csv** (1 PXD)
  - Single PXD for debugging specific issues
  - Minimal resource requirements
  - PXD034195

- **PXDfail.csv** (5 PXDs)
  - Known problematic datasets
  - Used for testing error handling
  - Includes timeout/resource scenarios

## Usage

```bash
# Quick test with 2 PXDs
nextflow run main.nf --pxd_csv assets/pxd_test_files/PXDsTest.csv -resume

# Comprehensive test with all test PXDs
nextflow run main.nf --pxd_csv assets/pxd_test_files/ConsolidatedTestPXDs.csv --num_pxds 20 -resume

# Gold standard validation
nextflow run main.nf --pxd_csv assets/pxd_test_files/GoldStandardSDRFs.csv --num_pxds 10 -resume
```

## CSV Format

All files follow the same format:
```
PXDs
PXDxxxxxx
PXDxxxxxx
...
```

The first column must contain `PXDxxxxxx` identifiers. The pipeline extracts all entries matching the pattern.

## Adding New Test Sets

1. Create a new CSV file following the format above
2. Ensure all PXD IDs are valid (format: `PXDxxxxxx`)
3. Document the purpose and characteristics in this README
4. Test with a small subset before committing
