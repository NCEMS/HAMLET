# Problem PXDs

## PXD001725 - PRIDE RAW files rejected by ThermoRawFileParser

**Status:** Blocked pending an alternative RAW-to-mzML conversion route or replacement source files.

**Observed:** 2026-09-15 during an uncapped (`--max_raw_files 0`) fetch.

### Scope

- PRIDE selected 30 downloadable RAW files.
- Five existing mzML files validate successfully.
- The remaining 25 RAW files download from PRIDE but do not convert.

### Error

`ThermoRawFileParser 2.0.0.0` exits with status `1` for each affected RAW:

```text
Native Thermo API reported the following error - RAW file is likely corrupted
Message: CRC failed [file revision #: 66]
```

### Evidence

- Refresh downloads completed through aria2c with `OK` status.
- For `130708_M98_002.raw`, the refreshed local file matches PRIDE's declared size: `2,397,477,363` bytes.
- Remote-versus-local 64 KiB ranges matched at offsets 0, 1 GiB, and 2 GiB.
- All 25 refreshed RAW files failed conversion; none produced a new mzML.

### Impact

RunAssessor consumes mzML input only. It can process the five valid existing mzML files, but the uncapped PXD inventory is incomplete, so HAMLET correctly stops before downstream stages rather than silently analyzing a subset.

### Required Fix

Use and validate an alternative converter that supports these RAW revision-66 files (for example a containerized ProteoWizard route), or obtain verified mzML/replacement RAW files from the data provider. Do not relax the selected-inventory completion check for this PXD.

---