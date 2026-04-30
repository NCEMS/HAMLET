#!/usr/bin/env python3
"""
Determine organism taxids for raw files from multiple sources:
1. organism_id results (Peptonizer2000)
2. LLM extraction results
3. PRIDE metadata

Validates taxids and checks for agreement between sources.
"""

import argparse
import json
import os
import re
from pathlib import Path
from collections import Counter
import pandas as pd


def extract_taxid_from_accession(accession):
    """Extract taxid from NEWT accession (e.g., 'NEWT:36329' -> '36329')"""
    if not accession:
        return None
    match = re.search(r'(NEWT:|taxid:)?(\d+)', str(accession), re.IGNORECASE)
    return match.group(2) if match else None


def is_valid_taxid(taxid):
    """Validate that taxid is a numeric string"""
    if not taxid:
        return False
    return str(taxid).strip().isdigit()


def parse_pride_metadata(fetched_dir, pxd):
    """Parse PRIDE metadata for project-level organism taxid"""
    pride_metadata_file = Path(fetched_dir) / f"{pxd}_PRIDEmetadata.json"
    
    if not pride_metadata_file.exists():
        return None, None
    
    try:
        with open(pride_metadata_file) as f:
            pride_data = json.load(f)
            organisms = pride_data.get("project", {}).get("organisms", [])
            if organisms and len(organisms) > 0:
                accession = organisms[0].get("accession", "")
                taxid = extract_taxid_from_accession(accession)
                if taxid:
                    print(f"Found PRIDE taxid: {taxid}")
                    return taxid, None
    except Exception as e:
        return None, {
            "type": "PRIDE_PARSE_ERROR",
            "message": f"Failed to parse PRIDE metadata: {str(e)}"
        }
    
    return None, None


def parse_llm_results(llm_results_dir):
    """Parse LLM results for per-sample organism taxids"""
    llm_taxids = {}
    warnings = []
    
    if not Path(llm_results_dir).exists() or str(llm_results_dir) == "/dev/null":
        return llm_taxids, warnings
    
    llm_files = list(Path(llm_results_dir).rglob("*_Metadata.json"))
    
    for llm_file in llm_files:
        try:
            with open(llm_file) as f:
                llm_data = json.load(f)
                # LLM results: { "rawfile.raw": { "Characteristics[OrganismTaxid]": ["12345"] } }
                for raw_file, metadata in llm_data.items():
                    if isinstance(metadata, dict):
                        taxid_values = metadata.get("Characteristics[OrganismTaxid]", [])
                        if taxid_values and len(taxid_values) > 0:
                            taxid = str(taxid_values[0]).strip()
                            if is_valid_taxid(taxid):
                                llm_taxids[raw_file] = taxid
                                print(f"LLM taxid for {raw_file}: {taxid}")
                            else:
                                warnings.append({
                                    "type": "INVALID_LLM_TAXID",
                                    "raw_file": raw_file,
                                    "message": f"LLM returned invalid taxid: {taxid_values[0]}"
                                })
        except Exception as e:
            warnings.append({
                "type": "LLM_PARSE_ERROR",
                "file": str(llm_file),
                "message": f"Failed to parse LLM results: {str(e)}"
            })
    
    return llm_taxids, warnings


def parse_organism_id_results(organism_results_dir):
    """Parse organism_id results for per-sample organisms (highest scoring taxid)
    
    OrganismID.py creates peptonizer_result.csv files in nested directory structure:
    organism_results/CasanovoSequence/<raw_file_name>/Peptonizer2000_data/<name>/peptonizer_result.csv
    
    The CSV has columns: taxon_name, taxon_id, score (sorted by score descending)
    """
    organism_taxids = {}
    warnings = []
    
    if not Path(organism_results_dir).exists():
        return organism_taxids, warnings
    
    # Look for peptonizer result CSV files (new format from Peptonizer2000)
    peptonizer_files = list(Path(organism_results_dir).rglob("peptonizer_result.csv"))
    
    for pep_file in peptonizer_files:
        try:
            # Extract raw filename from the directory path
            # Path structure: .../CasanovoSequence/<PXD####_raw_file_name>/Peptonizer2000_data/... (DDA)
            #            or: .../CascadiaSequence/<PXD####_raw_file_name>/Peptonizer2000_data/... (DIA)
            # We need to get the <PXD####_raw_file_name> part and convert to .raw
            parts = pep_file.parts
            raw_file_name = None
            
            for i, part in enumerate(parts):
                if "CasanovoSequence" in part or "CascadiaSequence" in part:
                    # Next part after sequence type is the raw file directory
                    if i + 1 < len(parts):
                        raw_file_name = parts[i + 1]
                        break
            
            if not raw_file_name:
                warnings.append({
                    "type": "ORGANISM_ID_PARSE_ERROR",
                    "file": str(pep_file),
                    "message": f"Failed to extract raw file name from path: {pep_file}"
                })
                continue
            
            # Convert directory name to .raw format
            # Directory name is like: PXD004732_01625b_GF4-TUM_first_pool_30_01_01-3xHCD-1h-R1
            # Raw file should be: 01625b_GF4-TUM_first_pool_30_01_01-3xHCD-1h-R1.raw
            # (strip PXD prefix and add .raw)
            match = re.search(r'PXD\d+_(.*)', raw_file_name)
            if match:
                raw_file = match.group(1) + ".raw"
            else:
                raw_file = raw_file_name + ".raw"
            
            # Parse CSV file
            df = pd.read_csv(pep_file)
            
            if len(df) > 0:
                # Get top result (highest score)
                df_sorted = df.sort_values('score', ascending=False)
                top_result = df_sorted.iloc[0]
                taxid = str(top_result.get("taxon_id", ""))
                
                if is_valid_taxid(taxid):
                    organism_taxids[raw_file] = taxid
                    score = top_result.get("score", "N/A")
                    taxon_name = top_result.get("taxon_name", "unknown")
                    print(f"Organism ID taxid for {raw_file}: {taxid} ({taxon_name}, score: {score})")
                else:
                    warnings.append({
                        "type": "INVALID_ORGANISM_ID_TAXID",
                        "raw_file": raw_file,
                        "message": f"Organism ID returned invalid taxid: {taxid}"
                    })
            else:
                warnings.append({
                    "type": "EMPTY_ORGANISM_ID_RESULTS",
                    "raw_file": raw_file,
                    "message": f"Peptonizer2000 results file is empty: {pep_file}"
                })
                
        except Exception as e:
            warnings.append({
                "type": "ORGANISM_ID_PARSE_ERROR",
                "file": str(pep_file),
                "message": f"Failed to parse organism_id results: {str(e)}"
            })
    
    return organism_taxids, warnings


def determine_file_taxids(mzml_files, organism_taxids, llm_taxids, pride_taxid, default_taxid):
    """Determine taxid for each raw file using priority hierarchy"""
    taxid_mapping = {}
    warnings = []
    
    print(f"\nFound {len(mzml_files)} mzML files to process")
    
    for raw_file in mzml_files:
        print(f"\nDetermining taxid for {raw_file}...")
        
        organism_taxid = organism_taxids.get(raw_file)
        llm_taxid = llm_taxids.get(raw_file)
        
        final_taxid = None
        taxid_source = None
        
        # Check if organism_id and LLM agree (if both present)
        if organism_taxid and llm_taxid:
            if organism_taxid == llm_taxid:
                final_taxid = organism_taxid
                taxid_source = "organism_id+LLM (agreed)"
                print(f"  ✓ Organism ID and LLM agree: {final_taxid}")
            else:
                # Disagreement: try to fall back to PRIDE metadata
                if pride_taxid:
                    final_taxid = pride_taxid
                    taxid_source = "PRIDE (fallback from disagreement)"
                    print(f"  ⚠ DISAGREEMENT: organism_id={organism_taxid}, LLM={llm_taxid}. Using PRIDE fallback: {final_taxid}")
                    warnings.append({
                        "type": "TAXID_DISAGREEMENT_PRIDE_FALLBACK",
                        "raw_file": raw_file,
                        "organism_id_taxid": organism_taxid,
                        "llm_taxid": llm_taxid,
                        "fallback_taxid": pride_taxid,
                        "message": f"Organism ID ({organism_taxid}) and LLM ({llm_taxid}) disagree. Using PRIDE taxid ({pride_taxid}) as fallback."
                    })
                else:
                    warnings.append({
                        "type": "TAXID_DISAGREEMENT",
                        "raw_file": raw_file,
                        "organism_id_taxid": organism_taxid,
                        "llm_taxid": llm_taxid,
                        "message": f"Organism ID ({organism_taxid}) and LLM ({llm_taxid}) disagree. No PRIDE fallback available. Skipping SAGE for this file."
                    })
                    print(f"  ✗ DISAGREEMENT: organism_id={organism_taxid}, LLM={llm_taxid}. No PRIDE fallback.")
                    continue
        elif organism_taxid:
            final_taxid = organism_taxid
            taxid_source = "organism_id"
            print(f"  Using organism_id taxid: {final_taxid}")
        elif llm_taxid:
            final_taxid = llm_taxid
            taxid_source = "LLM"
            print(f"  Using LLM taxid: {final_taxid}")
        elif pride_taxid:
            final_taxid = pride_taxid
            taxid_source = "PRIDE"
            print(f"  Using PRIDE taxid: {final_taxid}")
            warnings.append({
                "type": "USING_PRIDE_TAXID",
                "raw_file": raw_file,
                "message": f"No organism_id or LLM results found. Using PRIDE project-level taxid: {final_taxid}"
            })
        elif default_taxid:
            final_taxid = default_taxid
            taxid_source = "default"
            print(f"  Using default taxid: {final_taxid}")
            warnings.append({
                "type": "USING_DEFAULT_TAXID",
                "raw_file": raw_file,
                "message": f"No organism information found. Using default taxid: {final_taxid}"
            })
        else:
            warnings.append({
                "type": "NO_TAXID_FOUND",
                "raw_file": raw_file,
                "message": "No taxid could be determined. Skipping SAGE for this file."
            })
            print(f"  ✗ No taxid found - skipping SAGE")
            continue
        
        taxid_mapping[raw_file] = {
            "taxid": final_taxid,
            "source": taxid_source
        }
    
    return taxid_mapping, warnings





def main():
    parser = argparse.ArgumentParser(description='Determine organism taxids from multiple sources')
    parser.add_argument('--pxd', required=True, help='PXD identifier')
    parser.add_argument('--fetched_dir', required=True, help='Directory with fetched PXD data')
    parser.add_argument('--organism_results', required=True, help='Directory with organism_id results')
    parser.add_argument('--llm_results', required=True, help='Directory with LLM results')
    parser.add_argument('--default_taxid', help='Default taxid if no valid taxid found')
    parser.add_argument('--output_mapping', default='taxid_mapping.json', help='Output mapping file')
    parser.add_argument('--output_warnings', default='taxid_warnings.json', help='Output warnings file')
    
    args = parser.parse_args()
    
    all_warnings = []
    
    # 1. Parse PRIDE metadata
    pride_taxid, pride_warning = parse_pride_metadata(args.fetched_dir, args.pxd)
    if pride_warning:
        all_warnings.append(pride_warning)
    
    # 2. Parse LLM results
    llm_taxids, llm_warnings = parse_llm_results(args.llm_results)
    all_warnings.extend(llm_warnings)
    
    # 3. Parse organism_id results
    organism_taxids, organism_warnings = parse_organism_id_results(args.organism_results)
    all_warnings.extend(organism_warnings)
    
    # 4. Find all mzML files
    mzml_files = []
    for mzml_path in Path(args.fetched_dir).rglob("*.mzML"):
        raw_name = mzml_path.stem + ".raw"
        mzml_files.append(raw_name)
    
    # 5. Determine taxid for each file
    taxid_mapping, file_warnings = determine_file_taxids(
        mzml_files, organism_taxids, llm_taxids, pride_taxid, args.default_taxid
    )
    all_warnings.extend(file_warnings)
    
    # 6. Write outputs
    print(f"\n=== Final taxid mapping: {len(taxid_mapping)} files ===")
    for raw_file, info in taxid_mapping.items():
        print(f"  {raw_file}: {info['taxid']} (from {info['source']})")
    
    with open(args.output_mapping, "w") as f:
        json.dump({
            "pxd": args.pxd,
            "mappings": taxid_mapping
        }, f, indent=2)
    
    with open(args.output_warnings, "w") as f:
        json.dump({
            "pxd": args.pxd,
            "warnings": all_warnings,
            "summary": {
                "total_warnings": len(all_warnings),
                "files_with_taxid": len(taxid_mapping),
                "files_without_taxid": len(mzml_files) - len(taxid_mapping)
            }
        }, f, indent=2)
    
    print(f"\nGenerated {len(all_warnings)} warnings")
    print(f"Files with taxid: {len(taxid_mapping)}/{len(mzml_files)}")


if __name__ == "__main__":
    main()
