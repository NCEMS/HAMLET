#!/usr/bin/env python3
"""
Parse PTM-Shepherd's global.modsummary.tsv file to extract validated PTMs
for use in a closed search pass.

Filters out:
- "Unannotated mass-shift" entries
- Isotopic peak errors
- Low abundance PTMs (optional threshold)

Outputs PTM names and mass shifts suitable for SAGE variable_mods configuration.
"""

import os
import pandas as pd
import argparse
import json
import sys

from unimod_utils import load_unimod_index, match_unimod_by_mass, unimod_allowed_residues_and_terms


def parse_modsummary(modsummary_path, min_psms=10, min_percent=0.005, max_ptm_classes=3):
    """
    Parse global.modsummary.tsv and extract validated PTMs.
    
    Filters modifications by percentage threshold and applies a class limit.
    
    Args:
        modsummary_path: Path to global.modsummary.tsv from PTM-Shepherd
        min_psms: Unused (kept for API compatibility); filtering is percent-based
        min_percent: Minimum percentage of PSMs to consider a PTM validated (default 0.5%)
        max_ptm_classes: Maximum number of PTM classes to return, ordered by PSM count
        
    Returns:
        List of dicts with 'name', 'mass_shift', 'psms', 'percent' keys, sorted by PSM count descending
    """
    df = pd.read_csv(modsummary_path, sep="\t")
    
    # Filter criteria
    candidates = []
    
    for _, row in df.iterrows():
        mod_name = str(row['Modification']).strip()
        mass_shift = float(row['Mass Shift'])
        psms = int(row['SAGE_Output_PSMs'])
        percent = float(row['SAGE_Output_percent_PSMs'])
        
        # Skip filtering criteria
        if mod_name.startswith("Unannotated mass-shift"):
            continue
        if "Isotopic peak" in mod_name or "isotopic peak" in mod_name:
            continue
        if mod_name in ["None", "nan"]:
            continue
        
        # Filter by percentage threshold only (percentage-based, not absolute PSM count)
        if percent < min_percent:
            continue
            
        candidates.append({
            'name': mod_name,
            'mass_shift': mass_shift,
            'psms': psms,
            'percent': percent
        })
    
    # Sort by PSM count descending and apply class limit
    candidates.sort(key=lambda x: x['psms'], reverse=True)
    validated_ptms = candidates[:max_ptm_classes]
    
    return validated_ptms


def convert_to_sage_mods_from_unimod(
    validated_ptms,
    unimod_xml_path: str,
    unimod_tol: float = 0.01,
    fixed_percent: float = 95.0,
):
    """Convert validated PTMs to SAGE static_mods + variable_mods using Unimod specificity.

    Output:
      static_mods: dict[str, float]
      variable_mods: dict[str, list[float]]  (SAGE variable_mods format)

    Rules:
    - Only include PTMs that have a Unimod match within unimod_tol.
    - Use Unimod specificity to route mods to residues and/or termini.
    - If percent >= fixed_percent and the specificity is 'Anywhere' on a residue OR Any N-term/C-term,
      suggest it as static_mods (single mass per key). Otherwise put it in variable_mods.

    Notes:
    - For termini: SAGE variable_mods uses '[' (N-term) and ']' (C-term).
      SAGE static_mods commonly uses '^' (N-term) and '$' (C-term).
    """

    unimod = load_unimod_index(unimod_xml_path)

    static_mods = {}
    variable_mods = {}

    for ptm in validated_ptms:
        name = ptm['name']
        mass = float(ptm['mass_shift'])
        percent = float(ptm.get('percent', 0.0))

        # Skip extreme masses that are almost certainly artifacts.
        if abs(mass) > 1000:
            print(f"  Warning: Skipping extreme mass PTM '{name}' ({mass:+.6f} Da)")
            continue

        match = match_unimod_by_mass(unimod, mass_shift=mass, tolerance_da=unimod_tol)
        if match is None:
            print(f"  Warning: PTM '{name}' ({mass:+.6f} Da) not found in Unimod within ±{unimod_tol} Da; skipping")
            continue

        # Include hidden specificities to allow mods like Diethylation that are marked as hidden in Unimod
        residues, terms = unimod_allowed_residues_and_terms(unimod, match.record_id, include_hidden=True)
        if not residues and not terms:
            print(f"  Warning: Unimod match for '{name}' (UniMod:{match.record_id}) has no usable specificity; skipping")
            continue

        # Enrich PTM record (used downstream by orchestrator for class limiting / reporting)
        ptm['unimod_id'] = f"UniMod:{match.record_id}"
        ptm['unimod_name'] = match.full_name or match.code_name

        is_fixed = percent >= fixed_percent

        for res in sorted(residues):
            if is_fixed:
                if res in static_mods and abs(static_mods[res] - mass) > 1e-6:
                    print(f"  Warning: static_mods collision for residue '{res}': keeping {static_mods[res]:+.6f}, ignoring {mass:+.6f}")
                else:
                    static_mods[res] = mass
            else:
                variable_mods.setdefault(res, [])
                if mass not in variable_mods[res]:
                    variable_mods[res].append(mass)

        for term in sorted(terms):
            if term == "N-term":
                if is_fixed:
                    static_key = "^"
                    if static_key in static_mods and abs(static_mods[static_key] - mass) > 1e-6:
                        print(f"  Warning: static_mods collision for '{static_key}': keeping {static_mods[static_key]:+.6f}, ignoring {mass:+.6f}")
                    else:
                        static_mods[static_key] = mass
                else:
                    variable_mods.setdefault("[", [])
                    if mass not in variable_mods["["]:
                        variable_mods["["].append(mass)
            elif term == "C-term":
                if is_fixed:
                    static_key = "$"
                    if static_key in static_mods and abs(static_mods[static_key] - mass) > 1e-6:
                        print(f"  Warning: static_mods collision for '{static_key}': keeping {static_mods[static_key]:+.6f}, ignoring {mass:+.6f}")
                    else:
                        static_mods[static_key] = mass
                else:
                    variable_mods.setdefault("]", [])
                    if mass not in variable_mods["]"]:
                        variable_mods["]"].append(mass)

    return static_mods, variable_mods


def main():
    parser = argparse.ArgumentParser(
        description="Parse PTM-Shepherd global.modsummary.tsv to extract validated PTMs"
    )
    parser.add_argument(
        "modsummary",
        help="Path to global.modsummary.tsv from PTM-Shepherd"
    )
    parser.add_argument(
        "--min-psms",
        type=int,
        default=10,
        help="Unused (kept for compatibility); filtering uses percentage only"
    )
    parser.add_argument(
        "--min-percent",
        type=float,
        default=0.005,
        help="Minimum percent of PSMs to validate a PTM (default: 0.005 = 0.5%)"
    )
    parser.add_argument(
        "--max-ptm-classes",
        type=int,
        default=3,
        help="Maximum number of PTM classes to return (default: 3)"
    )
    parser.add_argument(
        "--output-json",
        help="Output validated PTMs to JSON file"
    )
    parser.add_argument(
        "--sage-mods",
        action="store_true",
        help="Output in SAGE variable_mods format"
    )

    parser.add_argument(
        "--unimod-xml",
        default=None,
        help="Path to Unimod tables XML (default: assets/unimod/unimod_tables.xml)"
    )
    parser.add_argument(
        "--unimod-tol",
        type=float,
        default=0.01,
        help="Unimod mass matching tolerance in Da (default: 0.01)"
    )
    parser.add_argument(
        "--fixed-percent",
        type=float,
        default=95.0,
        help="If PTM-Shepherd percent >= this, suggest as static_mods (default: 95.0)"
    )
    
    args = parser.parse_args()
    
    # Parse modsummary with percentage-based filtering and class limit
    print(f"\n[PTM Discovery] Filtering modsummary with min_percent={args.min_percent*100:.1f}%, max_classes={args.max_ptm_classes}")
    validated_ptms = parse_modsummary(
        args.modsummary,
        min_psms=args.min_psms,
        min_percent=args.min_percent,
        max_ptm_classes=args.max_ptm_classes
    )
    
    if not validated_ptms:
        print("[PTM Discovery] No PTMs passed filtering criteria; proceeding without PTM discovery")
    else:
        print(f"[PTM Discovery] Found {len(validated_ptms)} validated PTMs (filtered & limited to top {args.max_ptm_classes}):")
        for ptm in validated_ptms:
            print(f"  {ptm['name']:50s} {ptm['mass_shift']:+10.6f} Da  "
                  f"({ptm['psms']:4d} PSMs, {ptm['percent']:5.2f}%)")
    
    # Output results
    if args.sage_mods:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        default_unimod = os.path.abspath(os.path.join(script_dir, '..', '..', 'assets', 'unimod', 'unimod_tables.xml'))
        unimod_xml = args.unimod_xml or default_unimod

        static_mods, sage_variable_mods = convert_to_sage_mods_from_unimod(
            validated_ptms,
            unimod_xml_path=unimod_xml,
            unimod_tol=args.unimod_tol,
            fixed_percent=args.fixed_percent,
        )
        print("\nSAGE variable_mods format:")
        print(json.dumps(sage_variable_mods, indent=2))

        if static_mods:
            print("\nSAGE static_mods suggestions:")
            print(json.dumps(static_mods, indent=2))
        
        if args.output_json:
            with open(args.output_json, 'w') as f:
                json.dump({
                    'static_mods': static_mods,
                    'variable_mods': sage_variable_mods,
                    'validated_ptms': validated_ptms
                }, f, indent=2)
            print(f"\nWrote mods JSON to: {args.output_json}")
    elif args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(validated_ptms, f, indent=2)
        print(f"\nWrote validated PTMs to: {args.output_json}")


if __name__ == "__main__":
    main()
