"""Pure protocol parsing helpers used by the SDRF evidence adapters."""

import re
from typing import Any


CLEAVAGE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"chymotrypsin", re.I), "NT=Chymotrypsin;AC=MS:1001306"),
    (re.compile(r"lys[\s\-]?c\b", re.I), "NT=Lys-C;AC=MS:1001309"),
    (re.compile(r"asp[\s\-]?n\b", re.I), "NT=Asp-N;AC=MS:1001303"),
    (re.compile(r"glu[\s\-]?c\b", re.I), "NT=Glu-C;AC=MS:1001917"),
    (re.compile(r"trypsin", re.I), "NT=Trypsin;AC=MS:1001251"),
)


def _format_tolerance(value: object, unit: str) -> str | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        match = re.search(r"([-+]?\d+(?:\.\d+)?)", str(value))
        if not match:
            return None
        number = float(match.group(1))
    return f"{int(number) if number.is_integer() else number:g} {unit}"


def parse_mass_tolerances(search_criteria: dict[str, Any], protocol_text: str) -> tuple[str | None, str | None]:
    """Prefer structured RunAssessor tolerances, then parse protocol text."""
    tolerances = search_criteria.get("tolerances", {}) if isinstance(search_criteria, dict) else {}
    if isinstance(tolerances, dict):
        items = [(str(key), value) for key, value in tolerances.items()]

        def pick(kind: str) -> str | None:
            for key in (
                f"recommended overall {kind} tolerance (ppm)",
                f"recommended_overall_{kind}_tolerance_ppm",
            ):
                value = _format_tolerance(tolerances.get(key), "ppm")
                if value:
                    return value
            for key, value in items:
                lowered = key.lower()
                if kind not in lowered or "tolerance" not in lowered:
                    continue
                unit = "Da" if " da" in lowered or "(da" in lowered or lowered.endswith("_da") or " dalton" in lowered else "mmu" if "mmu" in lowered else "ppm"
                formatted = _format_tolerance(value, unit)
                if formatted:
                    return formatted
            return None

        precursor, fragment = pick("precursor"), pick("fragment")
        if precursor or fragment:
            return precursor, fragment

    def parse(patterns: tuple[str, ...]) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, protocol_text, re.I)
            if match:
                return f"{match.group(1)} {match.group(2)}"
        return None

    return (
        parse((r"(\d+(?:\.\d+)?)\s*(ppm|Da|mmu)\s*for\s*precursor", r"precursor[^.]{0,80}?(\d+(?:\.\d+)?)\s*(ppm|Da|mmu)")),
        parse((r"(\d+(?:\.\d+)?)\s*(ppm|Da|mmu)\s*for\s*fragment", r"fragment[^.]{0,80}?(\d+(?:\.\d+)?)\s*(ppm|Da|mmu)")),
    )


def parse_cleavage_agent(*texts: str) -> str | None:
    for text in texts:
        for pattern, value in CLEAVAGE_PATTERNS:
            if pattern.search(text):
                return value
    return None


def parse_reduction_reagent(*texts: str) -> str | None:
    for text in texts:
        if re.search(r"dithiothreitol|\bDTT\b", text, re.I):
            return "dithiothreitol"
        if re.search(r"\bTCEP\b|tris\(2-carboxyethyl\)phosphine", text, re.I):
            return "tris(2-carboxyethyl)phosphine"
        if re.search(r"beta-mercaptoethanol|\b2-ME\b|\bBME\b", text, re.I):
            return "beta-mercaptoethanol"
    return None


def parse_alkylation_reagent(*texts: str) -> str | None:
    for text in texts:
        if re.search(r"iodoacetamide|\bIAA\b", text, re.I):
            return "iodoacetamide"
        if re.search(r"chloroacetamide|\bCAA\b|2-chloroacetamide", text, re.I):
            return "chloroacetamide"
        if re.search(r"N-ethylmaleimide|\bNEM\b", text, re.I):
            return "N-ethylmaleimide"
    return None


def parse_scan_range(text: str) -> str | None:
    normalized = text.replace("\xad", "-").replace("\u2013", "-")
    match = re.search(r"(\d{3,4})\s*[-to]+\s*(\d{3,4})\s*m/?z", normalized, re.I)
    if not match:
        match = re.search(r"m/?z\s*(?:range\s*of\s*)?(\d{3,4})\s*[-to]+\s*(\d{3,4})", normalized, re.I)
    if match:
        return f"{match.group(1)}m/z-{match.group(2)}m/z"
    match = re.search(r"m/?z\s*(?:range\s*of\s*)?(\d{7,8})\b", normalized, re.I)
    if match:
        value = match.group(1)
        split_at = 3 if len(value) == 7 else 4
        return f"{value[:split_at]}m/z-{value[split_at:]}m/z"
    return None


def parse_collision_energy(text: str) -> str | None:
    for pattern, unit in (
        (r"\bNCE\)?[\s]*(?:of\s+)?(\d+(?:\.\d+)?)%?", "NCE"),
        (r"normalized collision energy[^)]*?(\d+(?:\.\d+)?)%", "NCE"),
        (r"collision energy[^)]*?(\d+(?:\.\d+)?)\s*eV", "eV"),
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return f"{match.group(1)} {unit}"
    return None