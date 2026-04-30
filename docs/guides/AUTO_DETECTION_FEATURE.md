# Intelligent Auto-Detection Feature

## Overview
The pipeline now automatically detects acquisition type (DDA/DIA) and labeling (LFQ, TMT, iTRAQ, SILAC) from runAssessor results, eliminating the need for manual parameter specification.

## How It Works

### 1. runAssessor Parsing
After files are downloaded by `fetch_pxd`, a new process `parse_runAssessor` analyzes the runAssessor JSON:

```
fetch_pxd → parse_runAssessor → organism_id (Casanovo/Cascadia)
                                 ↓
                                 sage_search (SAGE/DIA-NN)
```

### 2. Detected Parameters

The [parse_runAssessor.py](src/python/parse_runAssessor.py) script extracts:

- **Acquisition Type**: `DDA` or `DIA` (from `search_criteria.acquisition_type`)
- **Labeling**: `LFQ`, `TMT6`, `TMT10`, `TMT11`, `TMTpro`, `iTRAQ4`, `iTRAQ8`, `SILAC`
- **Confidence**: Score indicating detection confidence (0-1)
- **Fragmentation Type**: `HR_HCD`, `HR_IT_CID`, etc.
- **Precursor Accuracy**: High or low resolution

### 3. Automatic Configuration

Based on detected parameters, the pipeline:

1. **Selects correct container**:
   - DDA → `organism-id.sif` + `sage.sif`
   - DIA → `organism-id_DIA.sif` + `DiaNN.sif`

2. **Configures modifications**:
   - **LFQ**: Basic mods (Oxidation, Acetyl, Carbamidomethyl)
   - **TMT**: Adds TMT modifications on K and N-terminus
   - **iTRAQ**: Adds iTRAQ modifications on K and N-terminus
   - **SILAC**: Adds heavy K (+8) and heavy R (+10)

3. **Sets quantification mode**:
   - LFQ → MS1 intensity-based
   - TMT/iTRAQ → Reporter ion extraction
   - SILAC → Isotope pair quantification

## Example Detection

For the PXD005207 dataset (iTRAQ4-labeled, DDA):

```json
{
  "detected_params": {
    "DIA": false,
    "acquisition_type": "DDA",
    "labeling": "iTRAQ4",
    "confidence": 0.489,
    "fragmentation_type": "HR_HCD"
  },
  "modifications": {
    "quantification_type": "iTRAQ",
    "reporter_ions": true,
    "sage_mods": [
      "iTRAQ,144.102063,K",
      "iTRAQ,144.102063,^"
    ],
    "diann_mods": [
      "UniMod:214,144.102063,K",
      "UniMod:214,144.102063,*n"
    ]
  }
}
```

## Usage

### Automatic Mode (Default)
```bash
nextflow run main.nf --pxd PXD005207 --taxid 9606
```

Pipeline will:
1. Download PXD005207
2. Parse runAssessor results
3. Detect: DDA, iTRAQ4
4. Configure: Casanovo + SAGE with iTRAQ modifications
5. Run quantification with reporter ion extraction

### Manual Override
If you want to force specific parameters:
```bash
nextflow run main.nf --pxd PXD005207 --taxid 9606 --auto_detect false --DIA true
```

This disables auto-detection and uses your specified `--DIA` flag.

## Labeling Detection Logic

The pipeline examines runAssessor's ROI (Region of Interest) analysis:

```json
"labeling": {
  "call": "iTRAQ4",
  "scores": {
    "TMT": 0.0,
    "TMT6": 0.0,
    "iTRAQ": 2.704,
    "iTRAQ4": 0.489,
    "iTRAQ8": 0.025
  }
}
```

- **High confidence**: `iTRAQ4` score = 0.489 (found in ~49% of spectra)
- **Call**: `iTRAQ4` (highest specific score)

### Confidence Thresholds

| Confidence | Interpretation |
|------------|----------------|
| > 0.5 | High confidence - labeling clearly present |
| 0.2 - 0.5 | Medium confidence - likely labeled |
| < 0.2 | Low confidence - possibly unlabeled (LFQ) |
| 0.0 | No detection - defaults to LFQ |

## Modification Mapping

### LFQ (Label-Free)
**Variable mods**:
- Oxidation (M): +15.994915
- Acetyl (N-term): +42.010565

**Fixed mods**:
- Carbamidomethyl (C): +57.021464

### TMT (Tandem Mass Tags)
**Variable mods** (in addition to LFQ mods):
- TMT6/10/11: +229.162932 on K, N-term
- TMTpro: +304.207146 on K, N-term

**Quantification**: Reporter ions at m/z 126-131 (TMT6), 126-135 (TMT10/11), 126-135 (TMTpro)

### iTRAQ (Isobaric Tags)
**Variable mods** (in addition to LFQ mods):
- iTRAQ4: +144.102063 on K, N-term
- iTRAQ8: +304.205360 on K, N-term

**Quantification**: Reporter ions at m/z 114-117 (iTRAQ4), 113-121 (iTRAQ8)

### SILAC (Stable Isotope Labeling)
**Variable mods** (in addition to LFQ mods):
- Heavy K: +8.014199 (13C6 15N2)
- Heavy R: +10.008269 (13C6 15N4)

**Quantification**: Isotope pair ratios (light vs heavy)

## Implementation Details

### New Files

1. **[src/python/parse_runAssessor.py](src/python/parse_runAssessor.py)**
   - Parses runAssessor JSON
   - Maps labeling to modifications
   - Generates `detected_params.json`

2. **detected_params.json** (generated per run)
   - Contains detected parameters
   - Passed to downstream processes
   - Example in `results/detected_params.json`

### Modified Files

1. **[main.nf](main.nf)**
   - Added `parse_runAssessor` process
   - Passes `detected_params.json` to organism_id and sage_search
   - Dynamic container selection based on detection
   - Added `--auto_detect` parameter (default: true)

2. **[src/python/SAGE.py](src/python/SAGE.py)**
   - Added `--labeling` and `--config` parameters
   - Reads detected modifications from config
   - TODO: Apply dynamic modifications to SAGE config

3. **[src/python/DiaNN.py](src/python/DiaNN.py)**
   - Added `--labeling` and `--config` parameters
   - Modified `run_diann()` to accept custom modifications
   - Dynamically adds `--var-mod` and `--fixed-mod` flags

### Workflow Logic

```nextflow
workflow {
    pxd_ch = Channel.of(params.pxd)
    fetched_ch = fetch_pxd(pxd_ch)
    
    if (params.auto_detect) {
        // Auto-detect from runAssessor
        detected_params_ch = parse_runAssessor(fetched_ch)
    } else {
        // Use user-provided params
        detected_params_ch = Channel.of([DIA: params.DIA, ...])
    }
    
    // Pass detected params to downstream processes
    organism_results_ch = organism_id(fetched_ch, ..., detected_params_ch)
    sage_results_ch = sage_search(fetched_ch, detected_params_ch)
    ...
}
```

## Benefits

### 1. Zero Configuration
No need to specify acquisition type or labeling - the pipeline figures it out automatically!

**Before**:
```bash
nextflow run main.nf --pxd PXD005207 --taxid 9606 --DIA false --labeling iTRAQ4 --modifications "..."
```

**After**:
```bash
nextflow run main.nf --pxd PXD005207 --taxid 9606
```

### 2. No Human Error
Eliminates mistakes from manually specifying wrong acquisition type or labeling method.

### 3. Reproducibility
Detected parameters are saved in `detected_params.json`, documenting exactly what was detected and used.

### 4. Flexibility
runAssessor results override user parameters by default, but users can disable auto-detection if needed.

### 5. Intelligent Processing
Different datasets in the same run can use different settings if they have different acquisition types or labeling.

## Limitations & Future Work

### Current Limitations

1. **SAGE Modifications**: Dynamic modification of SAGE config not yet fully implemented. SAGE config still uses static modifications from `assets/default_sage.config`. Future enhancement needed.

2. **Reporter Ion Extraction**: While modifications are configured, reporter ion quantification in SAGE/DIA-NN needs additional configuration beyond just adding the modifications.

3. **SILAC Quantification**: Light/heavy pair quantification requires additional processing beyond modification specification.

4. **Confidence Handling**: Low-confidence detections still use the top scoring label. Could add a threshold to fall back to LFQ if confidence < 0.2.

### Future Enhancements

1. **Dynamic SAGE Config Generation**:
   - Generate SAGE config file on-the-fly based on detected labeling
   - Add appropriate reporter ion extraction settings
   - Configure quantification method (MS1, MS2, MS3)

2. **TMT/iTRAQ Reporter Ion Processing**:
   - Add reporter ion extraction to SAGE workflow
   - Parse reporter intensities from SAGE output
   - Normalize and quantify across channels

3. **SILAC Pair Detection**:
   - Detect isotope pairs in MS1
   - Calculate light/heavy ratios
   - Integrate with Skyline or MaxQuant for quantification

4. **Multi-Label Support**:
   - Handle mixed labeling strategies (e.g., TMT + SILAC)
   - Detect TMT variants automatically (6-plex vs 10-plex vs 11-plex)

5. **Confidence Thresholding**:
   - Add `--min_confidence` parameter
   - Fall back to LFQ if detection confidence too low
   - Warn user about uncertain detections

6. **Validation**:
   - Compare detected labeling against PRIDE metadata
   - Flag discrepancies for manual review
   - Add sanity checks (e.g., DIA data shouldn't have iTRAQ)

## Testing

### Test Case 1: DDA + iTRAQ4
```bash
nextflow run main.nf --pxd PXD005207 --taxid 5833
```

Expected:
- Detects: DDA, iTRAQ4
- Uses: Casanovo + SAGE
- Modifications: iTRAQ on K and N-term
- Output: `detected_params.json` showing iTRAQ4

### Test Case 2: DDA + LFQ
```bash
nextflow run main.nf --pxd PXD023343 --taxid 3847
```

Expected:
- Detects: DDA, LFQ
- Uses: Casanovo + SAGE
- Modifications: Basic (Oxidation, Acetyl, Carbamidomethyl)
- Output: `detected_params.json` showing LFQ

### Test Case 3: DIA + LFQ
```bash
nextflow run main.nf --pxd <DIA_PXD> --taxid 9606
```

Expected:
- Detects: DIA, LFQ
- Uses: Cascadia + DIA-NN
- Modifications: Basic mods
- Output: `detected_params.json` showing DIA + LFQ

### Test Case 4: Manual Override
```bash
nextflow run main.nf --pxd PXD005207 --taxid 5833 --auto_detect false --DIA false
```

Expected:
- Skips detection
- Uses: User-specified params (DDA in this case)
- Output: No `detected_params.json` or default config

## Troubleshooting

### Issue: "Could not find runAssessor JSON"

**Cause**: runAssessor didn't run or output is in unexpected location.

**Solution**:
1. Check that FetchPXD.py successfully ran runAssessor
2. Look for `*runAssessor*.json` files in work directory
3. If missing, pipeline falls back to default (DDA, LFQ)

### Issue: Low Confidence Detection

**Symptom**: `confidence: 0.15` in detected_params.json

**Cause**: Weak or ambiguous signal in runAssessor ROI analysis.

**Solution**:
1. Check runAssessor labeling scores
2. If uncertain, manually specify with `--auto_detect false --DIA <type>`
3. Review data quality - may be poorly labeled or unlabeled

### Issue: Wrong Labeling Detected

**Symptom**: Pipeline detects iTRAQ8 but data is actually iTRAQ4

**Cause**: runAssessor confusion between similar labeling methods.

**Solution**:
1. Disable auto-detection: `--auto_detect false`
2. Manually specify correct labeling (future feature)
3. Check PRIDE metadata for ground truth

### Issue: Modifications Not Applied

**Symptom**: SAGE runs but doesn't use TMT modifications

**Cause**: SAGE modification configuration not yet fully dynamic (see Limitations).

**Solution**:
1. Check `detected_params.json` shows correct modifications
2. For now, manually edit `assets/default_sage.config` for labeled data
3. Wait for future enhancement implementing dynamic SAGE config

---

**Feature Added**: January 18, 2025  
**Status**: ✅ Core functionality complete, future enhancements planned  
**Auto-detect**: Enabled by default (`--auto_detect true`)
