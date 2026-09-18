import re

COUNT_FIELDS = {
    "replicates",
    "technical_replicates",
    "number_of_samples",
    "fractions",
}

EVIDENCE_REQUIRED_FIELDS = {
    "instrument",
    "number_of_samples",
    "replicates",
    "technical_replicates",
    "organ",
    "cell_type",
    "disease",
    "enrichment_method",
}

MATERIAL_TYPE_VOCAB = {
    "tissue",
    "cell line",
    "primary cells",
    "biofluid",
    "whole organism",
    "plasma",
    "serum",
    "organoid",
    "cell culture",
}

EXPERIMENTAL_DESIGN_VOCAB = [
    "treated vs control",
    "case vs control",
    "time course",
    "dose response",
    "cross-sectional",
    "longitudinal",
]

CONTRACT_FIELDS = COUNT_FIELDS | {"material_type", "experimental_design"}

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "single": 1, "duplicate": 2, "duplicates": 2,
    "triplicate": 3, "triplicates": 3,
    "quadruplicate": 4, "quadruplicates": 4,
    "quintuplicate": 5, "quintuplicates": 5,
    "sextuplicate": 6, "sextuplicates": 6,
}

_RANGE_RE = re.compile(r"^(\d+)\s*(?:-|to)\s*(\d+)\b")
_N_EQUALS_RE = re.compile(r"\bn\s*=\s*(\d+)\b")
_LEADING_INT_RE = re.compile(
    r"^(?:at\s+least\s+|approximately\s+|about\s+|minimum\s+|>=\s*|~\s*)?(\d+)\b")

_TRAILING_INDEX_RE = re.compile(r"[A-Za-z)]\s*\(?\s*\d+\s*\)?\s*$")

_BIOFLUID_TERMS = {
    "plasma", "serum", "blood", "whole blood", "urine", "saliva", "sweat",
    "bile", "milk", "semen", "csf", "cerebrospinal fluid", "synovial fluid",
    "vitreous humor", "aqueous humor", "amniotic fluid", "lymph", "tear fluid",
}

_WHOLE_ORGANISM_TERMS = {
    "bacteria", "bacterium", "yeast", "e. coli", "escherichia coli",
    "s. cerevisiae", "saccharomyces cerevisiae", "whole organism",
    "whole cells", "whole cell", "microbial culture", "bacterial culture",
    "yeast culture",
}

_MATERIAL_TYPE_SYNONYMS = {
    "cell lines": "cell line",
    "cancer cell lines": "cell line",
    "immortalized cell line": "cell line",
    "immortalised cell line": "cell line",
    "cultured cells": "cell culture",
    "cell cultures": "cell culture",
    "primary cell": "primary cells",
    "primary cell culture": "primary cells",
    "primary cultures": "primary cells",
    "tissues": "tissue",
    "organoids": "organoid",
    "body fluid": "biofluid",
    "biofluids": "biofluid",
    "body fluids": "biofluid",
}

_CELL_SUFFIX_RE = re.compile(
    r"^(.*?)\s+(?:cells?|cell\s+lines?|cell\s+lysates?|cell\s+cultures?|cell\s+pellets?)$")

_GENERIC_CELL_HEADS = {
    "primary", "stem", "immune", "epithelial", "endothelial", "tumor", "tumour",
    "cancer", "blood", "whole", "single", "mammalian", "human", "mouse", "rat",
    "t", "b", "nk", "dendritic", "muscle", "neuronal", "neural", "hematopoietic",
    "haematopoietic", "red", "white", "host", "target", "donor", "patient",
    "cultured", "adherent", "suspension", "living", "intact", "viable",
}

_CELL_LINE_TOKEN_RE = re.compile(r"^(?=.*[a-z])(?=.*\d)[a-z0-9.\-/]{2,}$", re.IGNORECASE)

_MIXED_CASE_RE = re.compile(r"[a-z][A-Z]")

_SPECIES_PREFIXES = {
    "human", "mouse", "murine", "rat", "bovine", "porcine", "canine", "equine",
    "healthy", "patient", "patients", "donor", "donors", "adult", "pooled",
}

_DESIGN_PATTERNS = [
    (re.compile(r"\b(?:time[- ]course|time points?|over time|"
                r"\d+\s*(?:h|hr|hrs|hour|hours|d|day|days|week|weeks|min|minutes)\s+"
                r"(?:and|,|vs)\b)", re.IGNORECASE), "time course"),
    (re.compile(r"\bdose[- ](?:response|dependent)|\bconcentration[- ]series\b",
                re.IGNORECASE), "dose response"),
    (re.compile(r"\blongitudinal\b", re.IGNORECASE), "longitudinal"),
    (re.compile(r"\bcross[- ]sectional\b", re.IGNORECASE), "cross-sectional"),
    (re.compile(r"\b(?:patients?|donors?|subjects?|cohort|healthy|disease[d]?|"
                r"tumou?r|carcinoma|cancer)\b.*\b(?:vs|versus|compared (?:to|with)|control)\b",
                re.IGNORECASE), "case vs control"),
    (re.compile(r"\b(?:vs\.?|versus|compared (?:to|with)|comparison (?:of|between))\b",
                re.IGNORECASE), "treated vs control"),
    (re.compile(r"\b(?:knock[- ]?out|knock[- ]?down|overexpress|treated|treatment|"
                r"mutant|wild[- ]?type|wt|control|untreated|vector)\b",
                re.IGNORECASE), "treated vs control"),
]


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip()


def normalise_count(value):
    text = _clean(value).lower()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return text
    match = _RANGE_RE.match(text)
    if match:
        return f"{int(match.group(1))}-{int(match.group(2))}"
    match = _N_EQUALS_RE.search(text)
    if match:
        return str(int(match.group(1)))
    if _TRAILING_INDEX_RE.search(text):
        return None
    match = _LEADING_INT_RE.match(text)
    if match:
        return str(int(match.group(1)))
    for word, number in _WORD_NUMBERS.items():
        if re.match(rf"^(?:at\s+least\s+|approximately\s+|about\s+)?{word}\b", text):
            return str(number)
    for word, number in _WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", text):
            return str(number)
    return None


def looks_like_cell_line(value) -> bool:
    text = _clean(value)
    if not text:
        return False
    match = _CELL_SUFFIX_RE.match(text)
    head = match.group(1) if match else text
    tokens = [t for t in re.split(r"[\s,;()]+", head) if t]
    if not tokens:
        return False
    head_tokens = [t for t in tokens if t.strip("-/.").lower() not in _GENERIC_CELL_HEADS]
    if not head_tokens:
        return False
    joined = " ".join(head_tokens)
    if re.search(r"[A-Za-z]", joined) and re.search(r"\d", joined):
        return True
    for token in head_tokens:
        bare = token.strip("-/.")
        if not bare:
            continue
        if _CELL_LINE_TOKEN_RE.match(bare):
            return True
        if bare.isupper() and len(bare) >= 3:
            return True
        if _MIXED_CASE_RE.search(bare):
            return True
    return False


def _strip_species_prefix(text: str) -> str:
    tokens = text.split()
    while tokens and tokens[0] in _SPECIES_PREFIXES:
        tokens = tokens[1:]
    return " ".join(tokens)


def normalise_material_type(value, field_index=None):
    raw = _clean(value)
    text = raw.lower()
    if not text:
        return None
    if text in MATERIAL_TYPE_VOCAB:
        return text
    if text in _MATERIAL_TYPE_SYNONYMS:
        return _MATERIAL_TYPE_SYNONYMS[text]
    if text in _BIOFLUID_TERMS:
        return "biofluid"
    if text in _WHOLE_ORGANISM_TERMS:
        return "whole organism"
    stripped = _strip_species_prefix(text)
    if stripped in MATERIAL_TYPE_VOCAB:
        return stripped
    if stripped in _MATERIAL_TYPE_SYNONYMS:
        return _MATERIAL_TYPE_SYNONYMS[stripped]
    if stripped in _BIOFLUID_TERMS:
        return "biofluid"
    if stripped in _WHOLE_ORGANISM_TERMS:
        return "whole organism"
    if re.search(r"\b(?:cell\s+lines?)\b", text):
        return "cell line"
    if _CELL_SUFFIX_RE.match(raw) and looks_like_cell_line(raw):
        return "cell line"
    if _CELL_SUFFIX_RE.match(raw) and _head_matches_field(raw, field_index, "cell_line"):
        return "cell line"
    if re.search(r"\bprimary\s+(?:cells?|cultures?)\b", text):
        return "primary cells"
    if re.search(r"\borganoids?\b", text):
        return "organoid"
    if re.search(r"\bcells?\b", text):
        return None
    if re.search(r"\btissues?\b|\bbiops(?:y|ies)\b", text):
        return "tissue"
    return None


def _head_matches_field(value, field_index, target_field) -> bool:
    if not field_index:
        return False
    match = _CELL_SUFFIX_RE.match(_clean(value))
    head = match.group(1) if match else _clean(value)
    head_tokens = _tokens(head)
    if not head_tokens:
        return False
    for known in field_index.get(target_field, []) or []:
        known_tokens = _tokens(known)
        if known_tokens and known_tokens <= head_tokens:
            return True
    return False


def normalise_experimental_design(value):
    text = _clean(value).lower()
    if not text:
        return None
    for allowed in EXPERIMENTAL_DESIGN_VOCAB:
        if text == allowed or text == allowed.replace(" vs ", " vs. "):
            return allowed
    if text in ("case-control", "case control"):
        return "case vs control"
    if text in ("treated vs. control", "treatment vs control"):
        return "treated vs control"
    for pattern, label in _DESIGN_PATTERNS:
        if pattern.search(text):
            return label
    return None


def check_field_contract(field_name: str, value, field_index=None) -> dict:
    field = (field_name or "").strip().lower()
    text = _clean(value)
    result = {"field": field, "applies": False, "satisfied": None,
              "canonical": None, "reason": ""}
    if not text or field not in CONTRACT_FIELDS:
        return result
    result["applies"] = True

    if field in COUNT_FIELDS:
        canonical = normalise_count(text)
        if canonical is None:
            result["satisfied"] = None
            result["reason"] = (
                f"{field} must be a numeric count; no count could be read from "
                f"'{text[:60]}' -- decide from the paper text")
            return result
        result["satisfied"] = True
        result["canonical"] = canonical
        if canonical != text.lower():
            result["reason"] = (
                f"{field} must be a bare count; '{text[:60]}' reads as {canonical}")
        return result

    if field == "material_type":
        canonical = normalise_material_type(text, field_index)
        if canonical is None:
            result["satisfied"] = None
            result["reason"] = (
                f"material_type takes a broad material class such as "
                f"{sorted(MATERIAL_TYPE_VOCAB)}; '{text[:60]}' maps to none of them "
                f"-- decide from the paper text")
            return result
        result["satisfied"] = True
        result["canonical"] = canonical
        if canonical != text.lower():
            result["reason"] = (
                f"material_type must be a broad class; "
                f"'{text[:60]}' belongs to the class '{canonical}'")
        return result

    canonical = normalise_experimental_design(text)
    if canonical is None:
        result["satisfied"] = False
        result["reason"] = (
            f"experimental_design must be one of {EXPERIMENTAL_DESIGN_VOCAB}; "
            f"'{text[:60]}' is a free-text description")
        return result
    result["satisfied"] = True
    result["canonical"] = canonical
    if canonical != text.lower():
        result["reason"] = (
            f"experimental_design must be a category label; "
            f"'{text[:60]}' maps to '{canonical}'")
    return result


def _tokens(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", _clean(text).lower()))


def infer_destination_field(value, field_name: str, field_index: dict):
    """name the field misplaced value actually belongs to or none"""
    text = _clean(value)
    if not text:
        return None
    field = (field_name or "").strip().lower()
    value_tokens = _tokens(text)
    if not value_tokens or len(value_tokens) > 4:
        candidate_heads = []
    else:
        match = _CELL_SUFFIX_RE.match(text)
        candidate_heads = [value_tokens]
        if match:
            head_tokens = _tokens(match.group(1))
            if head_tokens:
                candidate_heads.append(head_tokens)

    for other_field, other_values in (field_index or {}).items():
        if other_field.strip().lower() == field:
            continue
        for other in other_values:
            other_tokens = _tokens(other)
            if not other_tokens:
                continue
            if all(t.isdigit() for t in other_tokens):
                continue
            if any(other_tokens == head for head in candidate_heads):
                return other_field

    if field != "cell_line" and len(value_tokens) <= 3 and looks_like_cell_line(text):
        return "cell_line"
    return None


def evidence_supports(value, evidence) -> bool:
    value_tokens = _tokens(value)
    evidence_tokens = _tokens(evidence)
    if not value_tokens or not evidence_tokens:
        return False
    return len(value_tokens & evidence_tokens) / len(value_tokens) >= 0.6


TECHNICAL_PROVENANCE_FIELDS = {
    "instrument",
    "mass_analyzer",
    "fragmentation",
    "precursor_mass_tolerance",
    "fragment_mass_tolerance",
    "acquisition_method",
}


def provenance_is_instrument_derived(provenance, field_name=None) -> bool:
    """true when value is read off the raw files rather than claimed about the sample & only the technical fields RunAssessor/meti measures qualify. 
    species, organ, disease and the like are claims about the material and a repository record can name the wrong one crediting those to the instrument hides a scope error. value whose sources disagree is not verified either: which source to believe is what is in question"""
    if not isinstance(provenance, dict):
        return False
    field = (field_name or "").strip().lower()
    if field and field not in TECHNICAL_PROVENANCE_FIELDS:
        return False
    if "DISAGREE" in str(provenance.get("status") or "").upper():
        return False
    return bool(provenance.get("meti_value") or provenance.get("pride_value"))


def provenance_lacks_text_support(provenance) -> bool:
    """true when no llm reading backs the value so the manuscript did not confirm it"""
    if not isinstance(provenance, dict):
        return True
    return not provenance.get("llm_value")


def describe_provenance(provenance) -> str:
    if not isinstance(provenance, dict):
        return ""
    parts = []
    if provenance.get("status"):
        parts.append(f"status={provenance['status']}")
    if provenance.get("meti_value"):
        parts.append(f"runassessor/meti={provenance['meti_value']}")
    if provenance.get("pride_value"):
        parts.append(f"pride={provenance['pride_value']}")
    if provenance.get("llm_value"):
        parts.append(f"llm={provenance['llm_value']}")
    return "; ".join(parts)
