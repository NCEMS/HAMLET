"""Pure protocol-derived modification detection for SDRF rendering."""

import re


def parse_protocol_modifications(protocol_text: str, alkylation_reagent: str | None) -> list[dict[str, object]]:
    """Return ordered unique protocol modifications in the legacy SDRF shape."""
    modifications: list[dict[str, object]] = []
    seen: set[int] = set()

    def add(uid: int, name: str, residues: str, modification_type: str) -> None:
        if uid not in seen:
            seen.add(uid)
            modifications.append({
                "uid": uid,
                "name": name,
                "residues": residues,
                "mod_type": modification_type,
            })

    if re.search(r"carbamidomethyl", protocol_text, re.I):
        add(4, "Carbamidomethyl", "C", "Fixed")
    elif alkylation_reagent in ("iodoacetamide", "chloroacetamide"):
        add(4, "Carbamidomethyl", "C", "Fixed")
    if re.search(r"\bTMT\b|\bTMTpro\b", protocol_text, re.I):
        add(730, "TMT6plex", "K", "Fixed")
    if re.search(r"\biTRAQ\b", protocol_text, re.I):
        add(214, "iTRAQ4plex", "K", "Fixed")
    if re.search(r"oxidation", protocol_text, re.I):
        add(35, "Oxidation", "M", "Variable")
    if re.search(r"\bacetyl\b.*\bn.?term|n.?term.*\bacetyl\b", protocol_text, re.I):
        add(1, "Acetyl", "K", "Variable")
    if re.search(r"phospho(?:rylation)?", protocol_text, re.I):
        add(21, "Phospho", "STY", "Variable")
    if re.search(r"deamid", protocol_text, re.I):
        add(7, "Deamidation", "NQ", "Variable")

    methyl_k = r"\blysines?\b|\bLys\b(?!\s*-?\s*C\b)|[\(\[]\s*K\s*[\)\]]|\bon\s+K\b"
    methyl_r = r"\barginines?\b|\bArg\b|[\(\[]\s*R\s*[\)\]]|\bon\s+R\b"
    residues = ""
    for match in re.finditer(r"\bmethylat\w*", protocol_text, re.I):
        window = protocol_text[max(0, match.start() - 60): match.end() + 60]
        if re.search(methyl_k, window, re.I):
            residues += "K"
        if re.search(methyl_r, window, re.I):
            residues += "R"
    residues = "".join(sorted(set(residues)))
    if residues:
        add(34, "Methyl", residues, "Variable")
    return modifications