#!/usr/bin/env python3

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class UnimodMod:
    record_id: str
    full_name: str
    code_name: str
    mono_mass: float


@dataclass(frozen=True)
class UnimodSpecificity:
    one_letter: str
    position: str
    hidden: bool


@dataclass(frozen=True)
class UnimodIndex:
    mods_by_id: Dict[str, UnimodMod]
    specificity_by_mod_id: Dict[str, List[UnimodSpecificity]]


def _as_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    return str(value).strip() in {"1", "true", "True", "yes", "Y"}


def load_unimod_index(unimod_xml_path: str) -> UnimodIndex:
    """Load a lightweight index from the local Unimod tables XML.

    Expected file: assets/unimod/unimod_tables.xml

    Only reads:
    - <modifications_row ... record_id=... mono_mass=... full_name=... code_name=...>
    - <positions_row ... record_id=... position=...>
    - <specificity_row ... mod_key=... one_letter=... position_key=... hidden=...>
    """

    if not os.path.exists(unimod_xml_path):
        raise FileNotFoundError(f"Unimod XML not found: {unimod_xml_path}")

    tree = ET.parse(unimod_xml_path)
    root = tree.getroot()
    
    # Handle namespace in the XML
    ns = {"um": "http://www.unimod.org/xmlns/schema/unimod_tables_1"}
    # Try with namespace first, then without if that fails
    modifications_rows = root.findall(".//um:modifications_row", ns)
    if not modifications_rows:
        # Fallback for files without namespace
        modifications_rows = root.findall(".//modifications_row")
    
    positions_rows = root.findall(".//um:positions_row", ns)
    if not positions_rows:
        positions_rows = root.findall(".//positions_row")
    
    specificity_rows = root.findall(".//um:specificity_row", ns)
    if not specificity_rows:
        specificity_rows = root.findall(".//specificity_row")

    # Build positions lookup: position_key -> human-readable label
    position_by_id: Dict[str, str] = {}
    for row in positions_rows:
        record_id = row.get("record_id")
        position = row.get("position")
        if record_id and position:
            position_by_id[record_id] = position

    mods_by_id: Dict[str, UnimodMod] = {}
    for row in modifications_rows:
        record_id = row.get("record_id")
        if not record_id:
            continue
        full_name = row.get("full_name") or ""
        code_name = row.get("code_name") or ""
        mono_mass_raw = row.get("mono_mass")
        if mono_mass_raw is None:
            continue
        try:
            mono_mass = float(mono_mass_raw)
        except ValueError:
            continue
        mods_by_id[record_id] = UnimodMod(
            record_id=record_id,
            full_name=full_name,
            code_name=code_name,
            mono_mass=mono_mass,
        )

    specificity_by_mod_id: Dict[str, List[UnimodSpecificity]] = {}
    for row in specificity_rows:
        mod_key = row.get("mod_key")
        one_letter = row.get("one_letter")
        position_key = row.get("position_key")
        if not mod_key or not one_letter or not position_key:
            continue
        position = position_by_id.get(position_key, "")
        hidden = _as_bool(row.get("hidden"))
        specificity_by_mod_id.setdefault(mod_key, []).append(
            UnimodSpecificity(one_letter=one_letter, position=position, hidden=hidden)
        )

    return UnimodIndex(mods_by_id=mods_by_id, specificity_by_mod_id=specificity_by_mod_id)


def _norm_residue_token(token: str) -> str:
    return token.strip()


def unimod_allowed_residues_and_terms(index: UnimodIndex, mod_id: str, include_hidden: bool = False) -> Tuple[Set[str], Set[str]]:
    """Return (residues, terms) where residues are AA one-letter codes and terms are {'N-term','C-term'}.

    Only considers specificity rows with positions we can interpret generically:
    - Anywhere
    - Any N-term
    - Any C-term

    Other Unimod positions (Protein N-term, etc.) are ignored here.
    """

    mod_id = str(mod_id)

    residues: Set[str] = set()
    terms: Set[str] = set()

    for spec in index.specificity_by_mod_id.get(mod_id, []):
        if spec.hidden and not include_hidden:
            continue

        pos = (spec.position or "").strip()
        one = _norm_residue_token(spec.one_letter)

        if pos == "Anywhere":
            if len(one) == 1 and one.isalpha() and one.isupper():
                residues.add(one)
        elif pos == "Any N-term":
            terms.add("N-term")
        elif pos == "Any C-term":
            terms.add("C-term")
        else:
            # Positions like Protein N-term are not safely computable without protein context.
            continue

    return residues, terms


def match_unimod_by_mass(
    index: UnimodIndex,
    mass_shift: float,
    tolerance_da: float = 0.01,
    residue: Optional[str] = None,
    term: Optional[str] = None,
) -> Optional[UnimodMod]:
    """Find the best Unimod match by mono_mass within tolerance.

    If residue is provided, prefers mods whose specificity includes that residue.
    If term is provided ('N-term' or 'C-term'), prefers mods that allow that term.

    Returns the closest-mass match after preference filtering.
    """

    candidates: List[UnimodMod] = []
    for mod in index.mods_by_id.values():
        if abs(mod.mono_mass - mass_shift) <= tolerance_da:
            candidates.append(mod)

    if not candidates:
        return None

    def score(mod: UnimodMod) -> Tuple[int, float]:
        # Lower score is better.
        prefer = 1
        if residue is not None:
            allowed_res, _allowed_terms = unimod_allowed_residues_and_terms(index, mod.record_id)
            if residue in allowed_res:
                prefer = 0
        if term is not None:
            _allowed_res, allowed_terms = unimod_allowed_residues_and_terms(index, mod.record_id)
            if term in allowed_terms:
                prefer = 0
        return (prefer, abs(mod.mono_mass - mass_shift))

    candidates.sort(key=score)
    return candidates[0]
