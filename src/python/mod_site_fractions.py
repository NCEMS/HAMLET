#!/usr/bin/env python3
"""Compute modification site fractions from a search_results.tsv-like table.

Goal
- Use unique stripped peptide sequences.
- For each modification, compute:
    fraction = (# modified sites) / (# potential sites)
  where potential sites are defined by Unimod residue/terminus specificity.

This script is designed to work with both SAGE and DIA-NN-derived TSVs.
It attempts to locate a "modified peptide" column automatically.

Output
- A TSV with one row per modification.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

from unimod_utils import (
    load_unimod_index,
    match_unimod_by_mass,
    unimod_allowed_residues_and_terms,
)


AA_RE = re.compile(r"[A-Z]")

# Examples handled:
#   ACD[+57.02146]EF
#   [ +42.010565]ACDE
#   AC(UniMod:4)DE
#   (UniMod:1)ACDE  (rare)
MASS_BRACKET_RE = re.compile(r"\[\s*([+-]?(?:\d+\.?\d*|\d*\.\d+))\s*\]")
RES_MASS_RE = re.compile(r"([A-Z])\[\s*([+-]?(?:\d+\.?\d*|\d*\.\d+))\s*\]")
UNI_RES_RE = re.compile(r"([A-Z])\(UniMod:(\d+)\)")
UNI_ANY_RE = re.compile(r"\(UniMod:(\d+)\)")


@dataclass(frozen=True)
class ModKey:
    kind: str  # 'unimod' or 'mass'
    value: str  # unimod id as str, or rounded mass string


@dataclass
class ModDef:
    key: ModKey
    mass: Optional[float] = None
    unimod_id: Optional[int] = None
    name: Optional[str] = None
    allowed_residues: Set[str] = None  # type: ignore[assignment]
    allowed_terms: Set[str] = None  # {'N-term','C-term'}


def _strip_to_letters(seq: str) -> str:
    return "".join(ch for ch in seq if "A" <= ch <= "Z")


def strip_mods_modified_peptide(modified: str) -> str:
    """Best-effort strip of modification markup to get the bare AA sequence."""
    if not modified:
        return ""
    # Remove bracket masses and Unimod annotations, keep letters.
    # This is intentionally permissive to support multiple encodings.
    return _strip_to_letters(modified)


def choose_modified_peptide_column(header: List[str]) -> str:
    """Pick the best column likely to contain modifications."""
    # Prefer SAGE-style
    for c in ["peptide", "Modified.Peptide", "modified_peptide", "modified_peptide_sequence"]:
        if c in header:
            return c
    # DIA-NN: sometimes modified sequence exists
    for c in ["diann_modified_sequence", "Modified.Sequence", "ModifiedSequence", "Modified sequence"]:
        if c in header:
            return c
    # Fall back to peptide
    if "peptide" in header:
        return "peptide"
    raise ValueError("Could not find a peptide column to parse")


def choose_stripped_column(header: List[str]) -> Optional[str]:
    for c in ["diann_stripped_sequence", "Stripped.Sequence", "stripped_sequence", "peptide"]:
        if c in header:
            return c
    return None


def open_tsv_rows(path: str) -> Tuple[object, List[str], Iterable[Dict[str, str]]]:
    """Open a TSV and return (file_handle, header, row_iter).

    The caller is responsible for closing the returned file handle.
    """
    f = open(path, "r", newline="")
    reader = csv.DictReader(f, delimiter="\t")
    header = list(reader.fieldnames or [])
    return f, header, reader


def parse_modified_events(modified: str) -> Tuple[str, List[Tuple[int, Optional[str], Optional[str], Optional[float], Optional[int]]]]:
    """Parse a modified peptide string.

    Returns
      stripped_sequence,
      events: list of (position, residue, term, mass_shift, unimod_id)

    Position conventions:
      - residue mods: 0-based index in stripped sequence
      - N-term: position = -1, term='N-term'
      - C-term: position = len(stripped), term='C-term'
    """
    if modified is None:
        modified = ""

    stripped = strip_mods_modified_peptide(modified)
    events: List[Tuple[int, Optional[str], Optional[str], Optional[float], Optional[int]]] = []

    # Detect N-term bracket mass like "[+42.0106]PEPTIDE"
    m0 = MASS_BRACKET_RE.match(modified.strip())
    if m0 and modified.strip().startswith("["):
        try:
            mass = float(m0.group(1))
            events.append((-1, None, "N-term", mass, None))
        except ValueError:
            pass

    # Detect Unimod tag at N-term like "(UniMod:1)PEPTIDE"
    u0 = UNI_ANY_RE.match(modified.strip())
    if u0 and modified.strip().startswith("("):
        try:
            uid = int(u0.group(1))
            events.append((-1, None, "N-term", None, uid))
        except ValueError:
            pass

    # Walk through string to map residue-index and capture inline mods.
    idx = -1
    i = 0
    s = modified
    while i < len(s):
        ch = s[i]
        if "A" <= ch <= "Z":
            idx += 1
            # Bracket mass after residue: A[+15.99]
            if i + 1 < len(s) and s[i + 1] == "[":
                m = MASS_BRACKET_RE.match(s, i + 1)
                if m:
                    try:
                        mass = float(m.group(1))
                        events.append((idx, ch, None, mass, None))
                    except ValueError:
                        pass
                    i = m.end()
                    continue
            # Unimod after residue: A(UniMod:35)
            if i + 1 < len(s) and s[i + 1] == "(":
                m = UNI_ANY_RE.match(s, i + 1)
                if m:
                    try:
                        uid = int(m.group(1))
                        events.append((idx, ch, None, None, uid))
                    except ValueError:
                        pass
                    i = m.end()
                    continue
        i += 1

    # Detect C-term bracket mass like "PEPTIDE[+xx]" (no residue preceding)
    s_strip = s.strip()
    if s_strip.endswith("]"):
        # find last bracket
        last_open = s_strip.rfind("[")
        if last_open != -1 and last_open > s_strip.rfind(")"):
            m = MASS_BRACKET_RE.match(s_strip, last_open)
            if m and m.end() == len(s_strip):
                try:
                    mass = float(m.group(1))
                    events.append((len(stripped), None, "C-term", mass, None))
                except ValueError:
                    pass

    # Detect C-term unimod like "PEPTIDE(UniMod:xxx)" (rare)
    if s_strip.endswith(")"):
        last_open = s_strip.rfind("(UniMod:")
        if last_open != -1:
            m = UNI_ANY_RE.match(s_strip, last_open)
            if m and m.end() == len(s_strip):
                try:
                    uid = int(m.group(1))
                    events.append((len(stripped), None, "C-term", None, uid))
                except ValueError:
                    pass

    return stripped, events


def resolve_mod_def(
    unimod_index,
    residue: Optional[str],
    term: Optional[str],
    mass_shift: Optional[float],
    unimod_id: Optional[int],
    tol_da: float,    include_hidden: bool = True,) -> ModDef:
    if unimod_id is not None:
        residues, terms = unimod_allowed_residues_and_terms(unimod_index, unimod_id, include_hidden=include_hidden)
        rec = unimod_index.mods_by_id.get(unimod_id)
        name = None
        mass = None
        if rec is not None:
            name = rec.full_name or rec.code_name
            mass = rec.mono_mass
        return ModDef(
            key=ModKey("unimod", str(unimod_id)),
            mass=mass,
            unimod_id=unimod_id,
            name=name,
            allowed_residues=set(residues),
            allowed_terms=set(terms),
        )

    if mass_shift is None:
        # Shouldn't happen, but guard.
        key = ModKey("mass", "0.0")
        return ModDef(key=key, mass=0.0, allowed_residues=set(), allowed_terms=set())

    match = match_unimod_by_mass(
        unimod_index,
        mass_shift=mass_shift,
        tolerance_da=tol_da,
        residue=residue,
        term=term,
    )
    if match is not None:
        residues, terms = unimod_allowed_residues_and_terms(unimod_index, match.record_id, include_hidden=include_hidden)
        rec = unimod_index.mods_by_id.get(match.record_id)
        name = None
        if rec is not None:
            name = rec.full_name or rec.code_name
        return ModDef(
            key=ModKey("unimod", str(match.record_id)),
            mass=mass_shift,
            unimod_id=match.record_id,
            name=name,
            allowed_residues=set(residues),
            allowed_terms=set(terms),
        )

    # Unknown mod: fall back to observed residue/term only.
    key = ModKey("mass", f"{mass_shift:+.5f}")
    allowed_res = set([residue]) if residue else set()
    allowed_terms = set([term]) if term else set()
    return ModDef(
        key=key,
        mass=mass_shift,
        unimod_id=None,
        name=None,
        allowed_residues=allowed_res,
        allowed_terms=allowed_terms,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute modification site fractions from search_results.tsv")
    ap.add_argument("--results", required=True, help="Path to search_results.tsv (or legacy results.sage.tsv)")
    ap.add_argument("--out", required=True, help="Output TSV path")
    ap.add_argument(
        "--unimod-xml",
        default=None,
        help="Path to assets/unimod/unimod_tables.xml (default: inferred from repo)",
    )
    ap.add_argument("--unimod-tol", type=float, default=0.01, help="Unimod mass tolerance (Da)")
    ap.add_argument(
        "--include-hidden-mods",
        type=lambda x: x.lower() in ("true", "1", "yes"),
        default=True,
        help="Include hidden Unimod specificities when resolving modifications (default: True)",
    )
    args = ap.parse_args()

    # Some result tables contain very large fields (e.g., long protein lists).
    # Raise the CSV parser limit to avoid _csv.Error: field larger than field limit.
    try:
        csv.field_size_limit(sys.maxsize)
    except OverflowError:
        csv.field_size_limit(10**7)

    results_path = os.path.abspath(args.results)
    if not os.path.exists(results_path):
        raise FileNotFoundError(results_path)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_unimod = os.path.abspath(os.path.join(script_dir, "..", "..", "assets", "unimod", "unimod_tables.xml"))
    unimod_xml = os.path.abspath(args.unimod_xml or default_unimod)

    unimod = load_unimod_index(unimod_xml)

    f, header, rows = open_tsv_rows(results_path)
    try:
        modified_col = choose_modified_peptide_column(header)
        stripped_col = choose_stripped_column(header)

        unique_peptides: Set[str] = set()
        residue_counts: Counter[str] = Counter()
        peptide_count = 0

        # Dedup: for each stripped peptide, keep a set of (mod_key, position)
        events_by_stripped: Dict[str, Set[Tuple[ModKey, int]]] = defaultdict(set)

        mod_defs: Dict[ModKey, ModDef] = {}
        modified_sites_by_mod: Counter[ModKey] = Counter()
        peptides_with_mod: Dict[ModKey, Set[str]] = defaultdict(set)

        for row in rows:
            modified = (row.get(modified_col) or "").strip()

            if stripped_col and stripped_col in row and row.get(stripped_col):
                stripped = strip_mods_modified_peptide(str(row.get(stripped_col)))
            else:
                stripped = strip_mods_modified_peptide(modified)

            if not stripped:
                continue

            # Track unique peptides and residue counts once per stripped sequence
            if stripped not in unique_peptides:
                unique_peptides.add(stripped)
                peptide_count += 1
                residue_counts.update(stripped)

            # Parse events from modified string
            _, events = parse_modified_events(modified)
            # If the modified column doesn't include modifications, try an alternate column if present.
            if not events:
                for alt in ["diann_modified_sequence", "Modified.Sequence", "Modified.Peptide"]:
                    if alt in row and row.get(alt) and alt != modified_col:
                        alt_modified = str(row.get(alt)).strip()
                        _, alt_events = parse_modified_events(alt_modified)
                        if alt_events:
                            events = alt_events
                            break

            for pos, res, term, mass, uid in events:
                mod_def = resolve_mod_def(unimod, res, term, mass, uid, tol_da=args.unimod_tol, include_hidden=args.include_hidden_mods)
                mod_defs.setdefault(mod_def.key, mod_def)

                key = mod_def.key
                event = (key, pos)
                if event in events_by_stripped[stripped]:
                    continue
                events_by_stripped[stripped].add(event)
                modified_sites_by_mod[key] += 1
                peptides_with_mod[key].add(stripped)
    finally:
        try:
            f.close()
        except Exception:
            pass

    # Compute denominators (potential sites) from global residue counts.
    out_rows: List[Dict[str, str]] = []
    for key, mod in mod_defs.items():
        potential = 0
        if mod.allowed_residues:
            potential += sum(residue_counts.get(r, 0) for r in mod.allowed_residues)
        if mod.allowed_terms:
            if "N-term" in mod.allowed_terms:
                potential += peptide_count
            if "C-term" in mod.allowed_terms:
                potential += peptide_count

        modified_sites = int(modified_sites_by_mod.get(key, 0))
        frac = (modified_sites / potential) if potential else 0.0

        out_rows.append(
            {
                "mod_key": f"{key.kind}:{key.value}",
                "unimod_id": str(mod.unimod_id) if mod.unimod_id is not None else "",
                "mod_name": mod.name or "",
                "mass_shift": f"{mod.mass:+.6f}" if mod.mass is not None else "",
                "allowed_residues": "".join(sorted(mod.allowed_residues or set())),
                "allowed_terms": ";".join(sorted(mod.allowed_terms or set())),
                "unique_peptides": str(peptide_count),
                "peptides_with_mod": str(len(peptides_with_mod.get(key, set()))),
                "modified_sites": str(modified_sites),
                "potential_sites": str(int(potential)),
                "fraction_modified": f"{frac:.6f}",
            }
        )

    # Filter out trivial modifications (those with no potential sites to modify)
    # These have fraction_modified = 0.0 and carry no meaningful information
    valid_rows = [r for r in out_rows if int(r["potential_sites"]) > 0]
    
    if len(out_rows) != len(valid_rows):
        skipped = len(out_rows) - len(valid_rows)
        print(f"Skipped {skipped} modifications with no potential sites (trivial results)")
    
    # Sort by fraction desc then modified sites desc
    valid_rows.sort(key=lambda r: (float(r["fraction_modified"]), int(r["modified_sites"])), reverse=True)

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "mod_key",
                "unimod_id",
                "mod_name",
                "mass_shift",
                "allowed_residues",
                "allowed_terms",
                "unique_peptides",
                "peptides_with_mod",
                "modified_sites",
                "potential_sites",
                "fraction_modified",
            ],
            delimiter="\t",
        )
        writer.writeheader()
        writer.writerows(valid_rows)

    print(f"Wrote mod-site fractions: {out_path}")
    print(f"Unique peptides: {peptide_count}")
    print(f"Mods observed: {len(out_rows)} (reported: {len(valid_rows)} non-trivial)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
