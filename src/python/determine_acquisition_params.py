#!/usr/bin/env python3
"""
Determine acquisition parameters (DIA vs DDA, labeling type) for a PRIDE dataset.

Integrates three evidence sources with a priority-based decision:
  1. LLM Comment[AcquisitionMethod] from GPT_Extraction output  (highest priority)
  2. runAssessor study_metadata.json (isolation-window detection)
  3. PRIDE metadata dataProcessingProtocol text scan
  4. DDA/LFQ fallback with explicit WARNING

Also accepts --output for the Nextflow work-dir copy, and writes a persistent copy
to spectral_files/<PXD>/detected_params.json so subsequent runs skip recomputation.
"""

import json
import argparse
import os
import glob
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# DIA keyword detection
# ---------------------------------------------------------------------------

DIA_KEYWORDS = re.compile(
    r'\b(dia|directdia|direct-dia|swath|diann|dia-nn|spectronaut|data[- ]?independent)\b',
    re.IGNORECASE,
)

def _text_is_dia(text: str) -> bool:
    """Return True if the text contains a DIA acquisition keyword."""
    return bool(DIA_KEYWORDS.search(text))


# ---------------------------------------------------------------------------
# Source loaders
# ---------------------------------------------------------------------------

def load_runAssessor_json(directory, central_mzml_dir=None, pxd=None):
    """
    Find and parse the runAssessor study_metadata.json.

    Returns parsed dict on success, None if not found.
    """
    # Prefer central storage path
    if central_mzml_dir and pxd:
        central_path = os.path.join(central_mzml_dir, pxd, 'runAssessor', 'study_metadata.json')
        if os.path.exists(central_path):
            print(f"✓ Found runAssessor results in central storage: {central_path}")
            with open(central_path) as f:
                return json.load(f)

    # Fallback: search input_dir
    for pattern in ["**/study_metadata.json", "**/*runAssessor*.json", "**/*assessor*.json"]:
        matches = list(Path(directory).glob(pattern))
        if matches:
            print(f"  Found runAssessor JSON: {matches[0]}")
            with open(matches[0]) as f:
                return json.load(f)

    return None


def load_llm_metadata(llm_results_dir, pxd):
    """
    Find and parse the GPT_Extraction Metadata JSON.

    GPT_Extraction writes to: <llm_results_dir>/<MODEL>/<pxd>_Metadata.json
    Returns dict (file→fields) on success, None if not found or empty.
    """
    if not llm_results_dir or not os.path.isdir(llm_results_dir):
        return None

    # Search for <pxd>_Metadata.json anywhere under llm_results_dir
    pattern = os.path.join(llm_results_dir, '**', f'{pxd}_Metadata.json')
    matches = glob.glob(pattern, recursive=True)

    if not matches:
        # Fallback: any *_Metadata.json (in case PXD casing differs)
        pattern_any = os.path.join(llm_results_dir, '**', '*_Metadata.json')
        matches = glob.glob(pattern_any, recursive=True)

    if not matches:
        print(f"  No LLM Metadata JSON found in: {llm_results_dir}")
        return None

    metadata_path = matches[0]
    print(f"  Found LLM Metadata JSON: {metadata_path}")

    try:
        with open(metadata_path) as f:
            content = f.read().strip()
        if not content or content == '{}':
            return None
        data = json.loads(content)
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"  WARNING: Could not parse LLM Metadata JSON ({metadata_path}): {exc}")
        return None


def load_pride_metadata(central_mzml_dir, pxd):
    """
    Load PRIDE project metadata JSON from central storage.
    Returns dict on success, None if not found.
    """
    if not central_mzml_dir or not pxd:
        return None
    pride_path = os.path.join(central_mzml_dir, pxd, f'{pxd}_PRIDEmetadata.json')
    if not os.path.exists(pride_path):
        return None
    try:
        with open(pride_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Acquisition type determination (priority order)
# ---------------------------------------------------------------------------

def determine_acquisition_type(runAssessor_data, llm_data, pride_data):
    """
    Determine DIA vs DDA using three evidence sources in priority order.

    Returns (acquisition_type: str, source: str, evidence: str)
    """

    # ---- Priority 1: LLM Comment[AcquisitionMethod] ----
    if llm_data and isinstance(llm_data, dict):
        dia_votes = 0
        dda_votes = 0
        for file_key, fields in llm_data.items():
            if not isinstance(fields, dict):
                continue
            raw_acq = fields.get('Comment[AcquisitionMethod]', '')
            # LLM output wraps all values in lists; flatten to string for matching
            if isinstance(raw_acq, list):
                acq_value = ' '.join(str(v) for v in raw_acq)
            else:
                acq_value = str(raw_acq) if raw_acq else ''
            if not acq_value.strip():
                continue
            if _text_is_dia(acq_value):
                dia_votes += 1
                print(f"    LLM DIA signal in '{file_key}': '{acq_value}'")
            else:
                dda_votes += 1

        if dia_votes > 0:
            evidence = f"LLM Comment[AcquisitionMethod] ({dia_votes} file(s) indicate DIA)"
            print(f"  → DIA determined from LLM metadata ({evidence})")
            return 'DIA', 'llm_metadata', evidence
        elif dda_votes > 0:
            evidence = f"LLM Comment[AcquisitionMethod] ({dda_votes} file(s) indicate DDA)"
            print(f"  → DDA determined from LLM metadata ({evidence})")
            return 'DDA', 'llm_metadata', evidence

    # ---- Priority 2: runAssessor isolation-window result ----
    if runAssessor_data:
        # Handle both direct and aggregated formats
        ra = runAssessor_data.get('runAssessor', runAssessor_data)
        files = ra.get('files', {})
        if files:
            first_file = next(iter(files.values()))
            spectra_stats = first_file.get('spectra_stats', {})
            acq_type = spectra_stats.get('acquisition_type', '')
            if acq_type:
                evidence = f"runAssessor spectra_stats.acquisition_type = '{acq_type}'"
                print(f"  → {acq_type} determined from runAssessor ({evidence})")
                return acq_type, 'runAssessor', evidence

        # Check search_criteria fallback
        search_criteria = ra.get('search_criteria', {})
        acq_type = search_criteria.get('acquisition_type', '')
        if acq_type:
            evidence = f"runAssessor search_criteria.acquisition_type = '{acq_type}'"
            print(f"  → {acq_type} determined from runAssessor ({evidence})")
            return acq_type, 'runAssessor', evidence

    # ---- Priority 3: PRIDE metadata text scan ----
    if pride_data:
        project = pride_data.get('project', pride_data)
        fields_to_scan = [
            project.get('dataProcessingProtocol', ''),
            project.get('title', ''),
            project.get('projectDescription', ''),
        ]
        for field_text in fields_to_scan:
            if field_text and _text_is_dia(field_text):
                evidence = f"PRIDE metadata text scan (matched DIA keyword in project metadata)"
                print(f"  → DIA determined from PRIDE metadata ({evidence})")
                return 'DIA', 'pride_metadata', evidence

    # ---- Priority 4: DDA fallback ----
    print("  WARNING: No acquisition type evidence found. Falling back to DDA/LFQ.")
    print("    Sources checked: LLM metadata, runAssessor, PRIDE metadata.")
    print("    This may be wrong — check the data manually if results are unexpected.")
    return 'DDA', 'fallback', 'No evidence found; defaulting to DDA'


# ---------------------------------------------------------------------------
# runAssessor labeling extraction (unchanged from parse_runAssessor.py)
# ---------------------------------------------------------------------------

def extract_runAssessor_params(runAssessor_data):
    """
    Extract labeling, fragmentation, and other parameters from runAssessor output.
    Acquisition type is intentionally NOT extracted here — use determine_acquisition_type().
    """
    ra = runAssessor_data.get('runAssessor', runAssessor_data)
    files = ra.get('files', {})
    search_criteria = ra.get('search_criteria', {})

    fragmentation_type = 'HR_HCD'
    high_accuracy_precursors = 'true'
    labeling = 'LFQ'
    labeling_scores = {}

    if files:
        first_file = next(iter(files.values()))
        spectra_stats = first_file.get('spectra_stats', {})
        summary = first_file.get('summary', {})

        if 'fragmentation_type' in spectra_stats:
            fragmentation_type = spectra_stats['fragmentation_type']
        if 'high_accuracy_precursors' in spectra_stats:
            high_accuracy_precursors = str(spectra_stats['high_accuracy_precursors'])

        labeling_info = summary.get('labeling', {})
        if 'call' in labeling_info:
            labeling = labeling_info['call']
        labeling_scores = labeling_info.get('scores', {})
    else:
        fragmentation_type = search_criteria.get('fragmentation_type', fragmentation_type)
        high_accuracy_precursors = search_criteria.get('high_accuracy_precursors', high_accuracy_precursors)
        labeling = search_criteria.get('labeling', labeling)

    confidence = 0.0
    if labeling_scores:
        if labeling != 'LFQ':
            confidence = max(labeling_scores.values())
        else:
            confidence = 1.0 - max(labeling_scores.values())

    return {
        'labeling': labeling,
        'fragmentation_type': fragmentation_type,
        'high_accuracy_precursors': str(high_accuracy_precursors),
        'confidence': confidence,
        'labeling_scores': labeling_scores,
    }


# ---------------------------------------------------------------------------
# Modification mapping (unchanged from parse_runAssessor.py)
# ---------------------------------------------------------------------------

def map_labeling_to_modifications(labeling):
    config = {
        'sage_mods': [],
        'diann_mods': [],
        'reporter_ions': False,
        'quantification_type': 'LFQ'
    }

    common_sage = []
    common_diann = [
        "UniMod:35,15.994915,M",
        "UniMod:1,42.010565,*n",
        "UniMod:7,0.984016,N",
        "UniMod:7,0.984016,Q",
        "UniMod:21,79.966331,S",
        "UniMod:21,79.966331,T",
        "UniMod:21,79.966331,Y",
        "UniMod:28,-17.026549,Qn",
        "UniMod:27,-18.010565,En",
    ]
    fixed_sage = []
    fixed_diann = ["UniMod:4,57.021464,C"]

    if labeling == 'LFQ':
        config['sage_mods'] = common_sage + fixed_sage
        config['diann_mods'] = common_diann + fixed_diann

    elif 'TMT' in labeling:
        config['reporter_ions'] = True
        config['quantification_type'] = 'TMT'
        tmt_mass = 304.207146 if 'TMTpro' in labeling else 229.162932
        config['sage_mods'] = common_sage + fixed_sage + [
            f"TMT,{tmt_mass},K", f"TMT,{tmt_mass},^"
        ]
        config['diann_mods'] = common_diann + fixed_diann + [
            f"UniMod:737,{tmt_mass},K", f"UniMod:737,{tmt_mass},*n"
        ]

    elif 'iTRAQ' in labeling:
        config['reporter_ions'] = True
        config['quantification_type'] = 'iTRAQ'
        itraq_mass = 304.205360 if 'iTRAQ8' in labeling else 144.102063
        config['sage_mods'] = common_sage + fixed_sage + [
            f"iTRAQ,{itraq_mass},K", f"iTRAQ,{itraq_mass},^"
        ]
        config['diann_mods'] = common_diann + fixed_diann + [
            f"UniMod:214,{itraq_mass},K", f"UniMod:214,{itraq_mass},*n"
        ]

    elif labeling == 'SILAC':
        config['quantification_type'] = 'SILAC'
        config['sage_mods'] = common_sage + fixed_sage + [
            "SILAC_K,8.014199,K", "SILAC_R,10.008269,R"
        ]
        config['diann_mods'] = common_diann + fixed_diann + [
            "UniMod:259,8.014199,K", "UniMod:267,10.008269,R"
        ]

    return config


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Determine acquisition parameters (DIA/DDA, labeling) from multiple evidence sources'
    )
    parser.add_argument('--input_dir', required=True,
                        help='PXD directory (used to search for runAssessor JSON if not in central storage)')
    parser.add_argument('--output', required=True,
                        help='Output path for detected_params.json (Nextflow work dir)')
    parser.add_argument('--central_mzml_dir',
                        help='spectral_files/ root directory')
    parser.add_argument('--pxd',
                        help='PXD accession ID')
    parser.add_argument('--llm_results_dir',
                        help='Directory containing GPT_Extraction output (llm_results/)')
    args = parser.parse_args()

    # ---- Skip-if-exists: reuse persistent copy from spectral_files ----
    if args.central_mzml_dir and args.pxd:
        central_output = os.path.join(args.central_mzml_dir, args.pxd, 'detected_params.json')
        if os.path.exists(central_output):
            print(f"✓ Using cached detected_params.json from spectral_files: {central_output}")
            import shutil
            shutil.copy2(central_output, args.output)
            return
    else:
        central_output = None

    # ---- Load evidence sources ----
    print("Loading evidence sources...")

    print("  [1/3] runAssessor study_metadata.json")
    runAssessor_data = load_runAssessor_json(args.input_dir, args.central_mzml_dir, args.pxd)
    if runAssessor_data:
        print(f"    ✓ Loaded")
    else:
        print(f"    ✗ Not found")

    print("  [2/3] LLM Metadata JSON")
    llm_data = load_llm_metadata(args.llm_results_dir, args.pxd) if args.llm_results_dir else None
    if llm_data:
        print(f"    ✓ Loaded ({len(llm_data)} file entries)")
    else:
        print(f"    ✗ Not found or empty")

    print("  [3/3] PRIDE metadata")
    pride_data = load_pride_metadata(args.central_mzml_dir, args.pxd)
    if pride_data:
        print(f"    ✓ Loaded")
    else:
        print(f"    ✗ Not found")

    # ---- Determine acquisition type ----
    print("\nDetermining acquisition type...")
    acquisition_type, acq_source, acq_evidence = determine_acquisition_type(
        runAssessor_data, llm_data, pride_data
    )

    # ---- Extract labeling and other params from runAssessor ----
    if runAssessor_data:
        ra_params = extract_runAssessor_params(runAssessor_data)
    else:
        print("  WARNING: No runAssessor data; defaulting labeling to LFQ")
        ra_params = {
            'labeling': 'LFQ',
            'fragmentation_type': 'HR_HCD',
            'high_accuracy_precursors': 'true',
            'confidence': 0.0,
            'labeling_scores': {},
        }

    # ---- Build output config ----
    mod_config = map_labeling_to_modifications(ra_params['labeling'])

    config = {
        'detected_params': {
            'DIA': acquisition_type == 'DIA',
            'acquisition_type': acquisition_type,
            'acquisition_source': acq_source,
            'acquisition_evidence': acq_evidence,
            'labeling': ra_params['labeling'],
            'fragmentation_type': ra_params['fragmentation_type'],
            'high_accuracy_precursors': ra_params['high_accuracy_precursors'],
            'confidence': ra_params['confidence'],
        },
        'modifications': mod_config,
        'labeling_scores': ra_params['labeling_scores'],
    }

    # ---- Write output ----
    with open(args.output, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"\n✅ detected_params.json written to: {args.output}")

    # Also persist to spectral_files for future reruns
    if central_output:
        import shutil
        os.makedirs(os.path.dirname(central_output), exist_ok=True)
        shutil.copy2(args.output, central_output)
        print(f"✅ Persisted detected_params.json to spectral_files: {central_output}")

    # ---- Summary ----
    print(f"\nDetected parameters:")
    print(f"  Acquisition type : {acquisition_type} (source: {acq_source})")
    print(f"  Labeling         : {ra_params['labeling']} (confidence: {ra_params['confidence']:.2f})")
    print(f"  Fragmentation    : {ra_params['fragmentation_type']}")
    print(f"  High-acc precurs : {ra_params['high_accuracy_precursors']}")


if __name__ == '__main__':
    main()
