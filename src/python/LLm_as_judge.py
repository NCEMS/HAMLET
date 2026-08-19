import os
import re
import json
import hashlib
import time
import argparse
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import openai

from deepeval.metrics import GEval
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase, LLMTestCaseParams


#Root directory containing all benchmark inputs and outputs
BASE_DIR = "/Users/fateme/Desktop/Hari_results"
#Directory containing per PXD manuscript folders used as source text
TEST_SET  = os.path.join(BASE_DIR, "test_set")

#Mapping from model name labels to their corresponding extraction output directories
MODEL_EXTRACTION_DIRS = {
    "claude": "/Users/fateme/Desktop/Hari_results/media/volume/bert_training_data_models/llama/codes/extraction_framework/benchmark_data/Final_results/test_claude",
    "gpt":    "/Users/fateme/Desktop/Hari_results/media 3/volume/bert_training_data_models/llama/codes/extraction_framework/benchmark_data/Final_results/test_gpt",
    "gemini": "/Users/fateme/Desktop/Hari_results/media 2/volume/bert_training_data_models/llama/codes/extraction_framework/benchmark_data/Final_results/test_gemini",
    "llama":  "/Users/fateme/Desktop/Hari_results/media 4/volume/bert_training_data_models/llama/codes/extraction_framework/benchmark_data/Final_results/test",
}

#The three specialised extraction agents whose JSON outputs are evaluated
AGENTS = ["BiologicalAgent", "TechnicalAgent", "ExperimentalDesignAgent"]

#LLM used as the judge model via OpenRouter
EVALUATION_MODEL      = "google/gemma-4-31b-it"
OPENROUTER_BASE_URL   = "https://openrouter.ai/api/v1"
MODEL_TEMPERATURE     = 0
#Enable extended thinking mode for the judge model when supported
MODEL_ENABLE_THINKING = True

#Global flag controlling whether the LLM judge is invoked during evaluation
USE_LLM_JUDGE = True
#Set to an integer to restrict evaluation to the first N papers None means all
LIMIT         = None

#File system safe slug for the evaluation model used to name the cache directory
_CACHE_MODEL_SLUG = EVALUATION_MODEL.replace("/", "_").replace(" ", "_")
CACHE_DIR         = os.path.join(BASE_DIR, f".prompt_cache_{_CACHE_MODEL_SLUG}")
#Toggle on or off the disk based response cache
CACHE_ENABLED     = True

#Maximum number of concurrent threads used for LLM judge calls
MAX_WORKERS = 4
#Number of retry attempts before giving up on a single API call
MAX_RETRIES = 3
#Base delay in seconds between successive retry attempts
RETRY_DELAY = 2

#Values longer than this threshold are treated as evidence sentences rather than metadata values
MAX_VALUE_LENGTH = 120

#Thread local storage used to pass per call context into GEval without shared state
_thread_local = threading.local()

#Maps each agent name to the suffix used in its output JSON filenames
AGENT_FILE_SUFFIX = {
    "BiologicalAgent":         "biological",
    "TechnicalAgent":          "technical",
    "ExperimentalDesignAgent": "experimental",
}

#Fields that are intentionally excluded from evaluation because they are ambiguous or out of scope
SKIP_ANNOTATION_FIELDS = {"phenotype", "ethnicity", "mass_analyzer", "technology_type"}

#Fields where the LLM judge must always be called regardless of value content
_ALWAYS_LLM_FIELDS = {"material_type", "acquisition_method"}

#Normalised string representations that indicate a field was not successfully extracted
_NOT_EXTRACTED_VALUES = {"unknown", "n/a", "not available", "none", "null", "na", ""}

def _is_not_extracted(value: str) -> bool:
    """Return True when a value string represents a missing or unextracted result"""
    return value.strip().lower() in _NOT_EXTRACTED_VALUES


#Per agent list of pipeline field names that each agent is responsible for extracting
PIPELINE_FIELDS = {
    "BiologicalAgent": [
        "species", "tissue", "cell_type", "disease_state", "sample_source",
        "age", "anatomic_site_tumor", "BMI", "cell_line", "sex", "strain",
        "material_type", "developmental_stage", "ethnicity",
    ],
    "TechnicalAgent": [
        "acquisition_method", "alkylation_reagent", "alkylation_concentration",
        "cleavage_agent", "collision_energy", "enrichment_method",
        "fractionation_method", "fragmentation_method", "instrument",
        "ionization_type", "labeling", "reduction_reagent", "reduction_concentration",
    ],
    "ExperimentalDesignAgent": [
        "biological_replicate", "technical_replicate", "experimental_design",
        "factor_value", "number_of_fractions", "number_of_technical_replicates",
        "number_of_biological_replicates", "number_of_samples",
    ],
}

#Maps raw JSON field names as produced by agents to the canonical evaluation field names.
#Whenever a raw key appears it is stored under the mapped canonical name.
FIELD_NAME_MAP = {
    "tissue":                          "organ",
    "disease_state":                   "disease",
    "sample_source":                   "material_type",
    "labeling":                        "label",
    "fragmentation_method":            "fragmentation",
    "fractionation_method":            "fractionation",
    "acquisition_method":              "acquisition_method",
    "alkylation_reagent":              "alkylation_reagent",
    "alkylation_concentration":        "alkylation_concentration",
    "reduction_concentration":         "reduction_concentration",
    "enrichment_method":               "enrichment_method",
    "ionization_type":                 "ionization_type",
    "number_of_biological_replicates": "replicates",
    "biological_replicate":            "replicates",
    "number_of_technical_replicates":  "technical_replicates",
    "technical_replicate":             "technical_replicates",
    "number_of_fractions":             "fractions",
    "number_of_samples":               "number_of_samples",
    "experimental_design":             "experimental_design",
}

#Known safe default values for specific fields that do not require explicit mention in the paper
SAFE_DEFAULTS = {
    "disease":              {"normal", "healthy", "no disease", "none", "not applicable", "not diseased"},
    "disease_state":        {"normal", "healthy", "no disease", "none", "not applicable", "not diseased"},
    "developmental_stage":  {"adult", "mature", "neonatal", "embryonic", "fetal", "postnatal",
                             "juvenile", "larval", "seedling", "pupal", "aged"},
    "label":                {"label-free", "lfq", "none", "label free"},
    "labeling":             {"label-free", "lfq", "none", "label free"},
    "fractions":            {"1", "none", "not applicable"},
    "number_of_fractions":  {"1", "none", "not applicable"},
    "replicates":           {"1"},
    "technical_replicates": {"1"},
    "experimental_design":  {"treated vs control", "case vs control", "time course",
                             "dose response", "cross-sectional", "longitudinal"},
}

#Fields where the extracted value is a reagent concentration rather than a name
CONCENTRATION_FIELDS = {"reduction_concentration", "alkylation_concentration"}


#Structured text block defining every metadata field type used in evaluation prompts
_FIELD_DEFINITIONS_TEXT = """\
BIOLOGICAL / SAMPLE FIELD TYPES:
species              : Source organism (e.g. "Homo sapiens", "Mus musculus"). Common names ("human", "mouse") are equivalent to scientific names.
organ                : Tissue or organ of origin (e.g. "liver", "brain cortex", "plasma"). Equivalent to the 'tissue' pipeline field.
cell_type            : Primary cell type or lineage (e.g. "neurons", "fibroblasts").
cell_line            : Name of immortalized cell line (e.g. "HEK293T", "HeLa").
disease              : Disease state or diagnosis (e.g. "breast cancer", "Type 2 diabetes"). "normal" or "healthy" is correct when subjects are healthy controls. Equivalent to the 'disease_state' pipeline field.
sex                  : Donor sex (e.g. "male", "female").
age                  : Age of donor or developmental time point (e.g. "45 years", "E14.5 embryo"). Ranges are acceptable when reported as a range.
developmental_stage  : Developmental stage of source material (e.g. "adult", "embryonic", "early seed development"). Inferable from subject description (e.g. "adult patients" -> "adult").
ethnicity            : Donor ancestry or ethnicity (e.g. "European", "East Asian").
material_type        : Broad material class: "tissue", "cell line", "primary cells", "biofluid", "whole organism", "plasma", "serum", "organoid". Equivalent to the 'sample_source' pipeline field. Must match what was actually used.
strain               : Animal or plant strain (e.g. "BALB/c", "C57BL/6J", "Nipponbare").
BMI                  : Body-Mass Index of donor (kg/m^2).
anatomic_site_tumor  : Anatomical location of the tumor, if applicable (e.g. "left lung lobe", "colon").

TECHNICAL / MS FIELD TYPES:
instrument           : Mass spectrometer make and model (e.g. "Thermo Q-Exactive Plus", "Orbitrap Fusion Lumos"). LC instruments alone are NOT this type.
cleavage_agent       : Protease used for protein digestion (e.g. "trypsin", "Lys-C"). "Trypsin/P" equals "trypsin".
label                : Isobaric or metabolic labeling method applied (e.g. "TMT", "SILAC", "label-free", "iTRAQ"). "label-free" is correct when no isobaric/metabolic labels are used. Equivalent to the 'labeling' pipeline field.
fragmentation        : Fragmentation method for MS/MS (e.g. "HCD", "CID", "ETD"). Equivalent to 'fragmentation_method'.
ptm                  : Post-translational modification studied or enriched for (e.g. "phosphorylation", "ubiquitination").
reduction_reagent    : Chemical used to reduce disulfide bonds (e.g. "DTT", "TCEP", "dithiothreitol").
reduction_concentration : Concentration of the reduction reagent (e.g. "5 mM", "2.5 mM", "10 mM"). Must be a numeric quantity with a unit. The reagent name is extracted separately in the 'reduction_reagent' field, so the concentration value alone (e.g. "2.5 mM" without the reagent name) is COMPLETE and sufficient.
collision_energy     : Collision energy used in MS/MS (e.g. "normalized collision energy 25", "27 eV").
fractionation        : Offline peptide/protein fractionation method applied before LC-MS (e.g. "high-pH reverse-phase fractionation", "strong anion exchange"). Equivalent to 'fractionation_method'.
enrichment_method    : Enrichment protocol applied before MS (e.g. "TiO2 phosphopeptide enrichment", "immunoprecipitation").
acquisition_method   : MS acquisition scheme (e.g. "DDA", "DIA", "data-dependent", "data-independent"). Must be a scheme name, NOT an instrument name. Equivalent to 'acquisition_method'.
alkylation_reagent   : Chemical used for cysteine alkylation (e.g. "iodoacetamide", "IAA", "NEM").
alkylation_concentration : Concentration of the alkylation reagent (e.g. "10 mM", "55 mM", "20 mM"). Must be a numeric quantity with a unit. The reagent name is extracted separately in the 'alkylation_reagent' field, so the concentration value alone (e.g. "10 mM" without the reagent name) is COMPLETE and sufficient.
ionization_type      : Ionization source type (e.g. "electrospray", "nano-ESI", "MALDI"). Can be inferred from instrument model (Q Exactive -> electrospray).
mass_analyzer        : Mass analyzer type used (e.g. "Orbitrap", "TOF", "quadrupole", "ion trap").

EXPERIMENTAL DESIGN FIELD TYPES:
replicates                    : Number of biological replicates (e.g. "3"). "1" is correct when no replication is mentioned. Equivalent to 'number_of_biological_replicates' / 'biological_replicate'.
technical_replicates          : Number of technical replicates per sample (e.g. "2"). Equivalent to 'number_of_technical_replicates' / 'technical_replicate'.
number_of_samples             : Total count of samples processed in the study (e.g. "12").
fractions                     : Number of fractions generated per sample (e.g. "12"). "1" is correct when no fractionation occurred. Equivalent to 'number_of_fractions'.
technology_type               : Broad technology type applied (e.g. "proteomics", "phosphoproteomics").
factor_value                  : Experimental factor or variable under study (e.g. "drug treatment", "cell type", "time point").
experimental_design           : Study design type (e.g. "time course", "cross-sectional", "case-control", "treated vs control").
"""

#Dictionary mapping each canonical field name to its full definition line
FIELD_DEFINITIONS: dict[str, str] = {}
for _line in _FIELD_DEFINITIONS_TEXT.strip().splitlines():
    _stripped = _line.strip()
    if not _stripped or _stripped.endswith(":"):
        continue
    if ":" in _stripped:
        _parts = _stripped.split(":", 1)
        FIELD_DEFINITIONS[_parts[0].strip()] = _stripped

#Set of all known canonical field names in lowercase for type check lookups
_KNOWN_FIELD_TYPES_LOWER: set[str] = set(FIELD_DEFINITIONS.keys())

SAFE_SDRF_OVERRIDE_FIELDS = {
    # Sample/biological fields
    "species":             "organism",
    "organ":               "organism_part",
    "disease":             "disease",
    "cell_type":           "cell_type",
    "cell_line":           "cell_line",
    "sex":                 "sex",
    "age":                 "age",
    "material_type":       "sample_source",
    # Technical fields
    "instrument":          "instrument",
    "label":               "label",
    "precursor_mass_tolerance": "precursor_tolerance",
    "fragment_mass_tolerance":  "fragment_tolerance",
    # Experimental design fields
    "replicates":          "biological_replicate",
    "technical_replicates": "technical_replicate",
    "fractions":           "fraction_identifier",
    "factor_value":        "factor_value",
}


#Full system prompt sent to the judge model on every API call
_STATIC_SYSTEM_PROMPT = """\
You are an expert in proteomics and mass spectrometry experimental metadata.
Your task is to assess the correctness of metadata field values extracted from
proteomics papers, measured against the field definitions provided below.

You will receive two inputs:
  1. A PAPER TEXT message (title + abstract + methods), prepended to the conversation.
  2. An assessment request as a JSON object with a "task" key.

Two task types are supported.

=================================================================
TASK TYPE: "verify"
=================================================================
Determine whether a candidate value is a valid extraction for the
given metadata field, by reading the paper text and applying the
field definitions below.

JSON input fields:
  field_name             -- the metadata field being assessed
  field_definition       -- precise definition of that field
  candidate_value        -- the extracted value to assess (ONE value)
  all_extracted_values   -- ALL values the pipeline extracted for this field
                            (including candidate_value). Use this to judge
                            completeness: if together they cover the full
                            picture described in the paper, each individual
                            value is COMPLETE.

=================================================================
CORE EVALUATION QUESTIONS (answer in order)
=================================================================
1. TYPE CHECK   : Does the candidate value belong to this metadata field's
                  definition? Ask: "Is this the RIGHT CATEGORY OF THING
                  for this field (organism name, tissue, instrument model,
                  method name, numeric count, etc.)?"
                  -- If the value is the right CATEGORY but wrong SPECIFIC
                     ENTITY within that category: TYPE_CORRECT: yes,
                     VALUE_CORRECT: no, VERDICT: low (rule D).
                  -- Only TYPE_CORRECT: no (rule B) when the fundamental
                     nature of the value belongs to a completely different
                     field.

2. SOURCE CHECK : Is the candidate value present in or reasonably inferable
                  from the paper text?
                  -- SAFE DEFAULTS that do NOT require explicit mention:
                     "normal"/"healthy" for disease when subjects are healthy;
                     "adult"/"neonatal"/etc. for developmental_stage when
                     inferable from subject description;
                     "label-free" for label/labeling when no isobaric or
                     metabolic labels are mentioned;
                     "1" for fractions or replicates when paper is silent;
                     standard material_type values inferable from context;
                     abbreviation expansions (IAA = iodoacetamide, HCD =
                     higher-energy collisional dissociation, etc.).
                  -- INFERABLE FIELDS: For material_type and acquisition_method,
                     the value may be reasonably inferable from the experimental
                     context even when not explicitly stated in the paper text.
                  -- If absent AND not a safe default AND not reasonably
                     inferable -> HALLUCINATED: yes (rule A -> VERDICT: low).
                  -- If present but in a different context -> HALLUCINATED: no,
                     VALUE_CORRECT: no (rule D).

3. TRUTH CHECK  : Is the candidate value factually correct and valid for
                  this experiment as described in the paper?
                  -- Synonyms, abbreviations, digit/word swaps ("3"/"three"),
                     common/scientific name swaps ("human"/"Homo sapiens"),
                     and equivalent representations are all CORRECT.

4. COMPLETENESS : Check whether the extraction is complete -- but ALWAYS
                  evaluate completeness against the FULL SET of extracted
                  values (all_extracted_values), NOT against this single
                  candidate value in isolation.

                  SIBLING-VALUE RULE (most important):
                  If all_extracted_values together cover the complete picture
                  described in the paper for this field, then EVERY individual
                  value in that set is VALUE_COMPLETE: yes and VERDICT: high.
                  Do NOT flag a value as incomplete just because it is one of
                  several correct values for the same field.

                  Example: field=material_type, paper uses both "cell line" and
                  "primary cells". If all_extracted_values=["cell line","primary cells"],
                  both are VALUE_COMPLETE: yes -- each is one of the correctly
                  extracted values and together they are exhaustive.

                  Only flag MEDIUM (partial) when the full set of
                  all_extracted_values STILL does not cover the complete picture.

                  Other incompleteness patterns (still apply when the full set
                  is insufficient):
                  -- Subtype drift: value is more specific than what the paper describes.
                  -- Supertype drift: value is broader (e.g. "cells" when paper says "cell line").
                  -- Single channel of a confirmed multi-channel scheme.

                  CONCENTRATION FIELDS EXCEPTION:
                  For reduction_concentration and alkylation_concentration,
                  a concentration value with only the numeric quantity and unit
                  (e.g. "2.5 mM") WITHOUT the reagent name is COMPLETE.

=================================================================
VERDICT RULES
=================================================================
LOW   -- HALLUCINATED, TYPE MISMATCH, or factually INCORRECT.
MEDIUM-- type correct, present, valid, but the FULL SET of
         all_extracted_values still does not cover the complete picture.
HIGH  -- correct type, present/inferable, factually accurate and
         the full set of all_extracted_values is exhaustive (or this
         field only has one correct value).

=================================================================
OUTPUT FORMAT for "verify"
=================================================================
TYPE CHECK:        <one sentence>
SOURCE CHECK:      <one sentence>
TRUTH CHECK:       <one sentence>
COMPLETENESS CHECK:<one sentence -- assess the FULL SET, not just this value>
TYPE_CORRECT:      yes | no
CORRECT_TYPE_NAME: <correct field name if TYPE_CORRECT is no, else NONE>
VALUE_CORRECT:     yes | no
VALUE_COMPLETE:    yes | no
HALLUCINATED:      yes | no
VERDICT:           high | medium | low
CORRECTED_VALUE:   <when VERDICT is medium: the complete/correct full set of
                   values this field should have. When VERDICT is high or low: NONE>

=================================================================
TASK TYPE: "check_missing"
=================================================================
Determine whether the paper text contains information for the specified
metadata field.

JSON input fields:
  field_name       -- the metadata field
  field_definition -- precise definition of that field

OUTPUT FORMAT:
SEARCH:  <one sentence>
FINDING: <one sentence>
VERDICT: high | medium | low
(high = clearly present; medium = inferable; low = absent)

=================================================================
METADATA FIELD DEFINITIONS
=================================================================
""" + _FIELD_DEFINITIONS_TEXT


#GEval criteria string used when judging whether an extracted annotation is correct.
#This is the high level description of what the judge should assess.
_ANNOTATION_GEVAL_CRITERIA = (
    "Assess whether a candidate metadata value is a valid extraction for the "
    "given field, based solely on the paper text and field definitions. "
    "The JSON context includes all_extracted_values -- ALL values the pipeline "
    "extracted for this field. Use this to judge completeness correctly: "
    "if all_extracted_values together cover the complete picture, each individual "
    "value is VALUE_COMPLETE: yes (SIBLING-VALUE RULE). "
    "Only flag MEDIUM when the full set is still insufficient. "
    "Evaluate in order: "
    "(1) TYPE: does it match the field definition in FUNDAMENTAL NATURE? "
    "(2) SOURCE: is it present in or a valid safe default for the paper text? "
    "    IMPORTANT: For material_type and acquisition_method, the value may be "
    "    reasonably inferable from the experimental context. "
    "(3) TRUTH: is it factually correct per the paper and field definition? "
    "(4) COMPLETENESS: apply SIBLING-VALUE RULE first -- assess the full set. "
    "    EXCEPTION: For reduction_concentration and alkylation_concentration, "
    "    a numeric quantity + unit WITHOUT the reagent name IS complete. "
    "HIGH = correct type + present/inferable + factually valid + full set complete. "
    "MEDIUM = correct type + present + valid, but full set still insufficient. "
    "LOW = hallucinated, type mismatch, or factually wrong. "
    "When VERDICT is medium, output CORRECTED_VALUE: <the full correct value set>."
)

#Step by step instructions for GEval when evaluating an extracted annotation
_ANNOTATION_GEVAL_STEPS = [
    "TYPE CHECK: determine the fundamental nature of the value. "
    "If it belongs to a completely different field, set TYPE_CORRECT: no -> VERDICT: low. "
    "If it is the right category but wrong specific entity, TYPE_CORRECT: yes, VALUE_CORRECT: no.",

    "SOURCE CHECK: confirm the candidate value is present in or inferable from the paper. "
    "Safe defaults do NOT require explicit mention. "
    "For material_type and acquisition_method, reasonable inference from context is allowed. "
    "If ABSENT and not a safe default and not inferable: HALLUCINATED: yes -> VERDICT: low.",

    "TRUTH CHECK: assess factual correctness. Synonyms, abbreviations, digit/word swaps, "
    "common/scientific name swaps are CORRECT.",

    "COMPLETENESS CHECK: look at all_extracted_values (the full set of values extracted "
    "for this field). If together they cover the complete picture in the paper, "
    "set VALUE_COMPLETE: yes and VERDICT: high for this candidate -- SIBLING-VALUE RULE. "
    "Only flag MEDIUM if the full set is still missing something. "
    "EXCEPTION: concentration fields missing only the reagent name are COMPLETE.",

    "Output TYPE CHECK / SOURCE CHECK / TRUTH CHECK / COMPLETENESS CHECK, "
    "TYPE_CORRECT (yes/no), CORRECT_TYPE_NAME (field_name or NONE), "
    "VALUE_CORRECT (yes/no), VALUE_COMPLETE (yes/no), "
    "HALLUCINATED (yes/no), VERDICT: high | medium | low, "
    "CORRECTED_VALUE: <full correct value set, or NONE>.",
]

#GEval criteria string used to detect fields that were present in the paper but not extracted
_MISSED_GEVAL_CRITERIA = (
    "Determine whether the paper text contains information for the specified "
    "metadata field. Output VERDICT: high | medium | low. "
    "(high = clearly present; medium = inferable; low = absent)"
)
#Step by step instructions for GEval when checking for missed fields
_MISSED_GEVAL_STEPS = [
    "Search the source text for any mention of the metadata field.",
    "Determine if a valid value is clearly present, inferable, or absent.",
    "Write SEARCH, FINDING and VERDICT: high | medium | low.",
]


class DiskResponseCache:
    """On disk JSON cache for LLM judge responses"""

    def __init__(self, cache_dir: str, enabled: bool = True):
        """Initialise the cache creating the directory if enabled"""
        self._dir     = Path(cache_dir)
        self._enabled = enabled
        self._hits    = 0
        self._misses  = 0
        self._lock    = threading.Lock()
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _make_key(paper_id: str, task: str, field_name: str, primary_value: str) -> str:
        """Compute a deterministic SHA 256 hex key for a given evaluation request"""
        blob = f"{EVALUATION_MODEL}|{paper_id}|{task}|{field_name.lower()}|{primary_value}"
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, paper_id, task, field_name, primary_value):
        """Return the cached response string or None if no cache entry exists"""
        if not self._enabled:
            return None
        key  = self._make_key(paper_id, task, field_name, primary_value)
        path = self._dir / f"{key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                with self._lock:
                    self._hits += 1
                return data.get("response")
            except (json.JSONDecodeError, OSError):
                return None
        with self._lock:
            self._misses += 1
        return None

    def put(self, paper_id, task, field_name, primary_value, response):
        """Write a response to disk under the computed cache key"""
        if not self._enabled:
            return
        key  = self._make_key(paper_id, task, field_name, primary_value)
        path = self._dir / f"{key}.json"
        try:
            path.write_text(
                json.dumps({"key": key, "paper_id": paper_id, "task": task,
                    "field_name": field_name, "primary_value": primary_value,
                    "response": response, "timestamp": time.time(),
                }, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            print(f"  [cache write error] {exc}")

    def stats(self):
        """Return a dictionary summarising cache usage for the current session"""
        n_files = sum(1 for _ in self._dir.glob("*.json")) if self._enabled else 0
        total   = self._hits + self._misses
        return {"enabled": self._enabled, "cache_dir": str(self._dir),
            "cached_responses_on_disk": n_files, "session_hits": self._hits,
            "session_misses": self._misses,
            "session_hit_rate": f"{self._hits/total*100:.1f}%" if total > 0 else "n/a"}


def _build_messages(paper_text: str, entity_context: dict) -> list[dict]:
    """Construct the four turn message list sent to the judge model"""
    return [
        {
            "role": "system",
            "content": [{"type": "text", "text": _STATIC_SYSTEM_PROMPT,
                          "cache_control": {"type": "ephemeral"}}],
        },
        {
            "role": "user",
            "content": [{"type": "text",
                "text": ("PAPER TEXT (title + abstract + methods) -- use as source of truth "
                         "for all SOURCE CHECK and TRUTH CHECK assessments:\n\n" + paper_text),
                "cache_control": {"type": "ephemeral"}}],
        },
        {
            "role": "assistant",
            "content": (
                "Understood. I have read the paper text and will assess all metadata "
                "field values against it using the definitions and rules in my instructions."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(entity_context, indent=2, ensure_ascii=False),
        },
    ]


def _build_openrouter_client() -> openai.OpenAI:
    """Create and return an OpenAI client configured to use the OpenRouter endpoint"""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY environment variable is not set.")
    return openai.OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)


def _extract_text_content(raw_message) -> str:
    """Extract all plain text from an OpenAI compatible response message object"""
    if raw_message is None:
        return ""
    content = getattr(raw_message, "content", None)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text") or "")
            elif hasattr(block, "type") and hasattr(block, "text"):
                if block.type == "text":
                    parts.append(block.text or "")
        return " ".join(parts)
    if isinstance(content, str):
        return content
    return ""


class Gemma4Judge(DeepEvalBaseLLM):
    """LLM judge wrapper that routes evaluation calls through OpenRouter to Gemma 4"""

    def __init__(self):
        """Initialise counters cache and shared state"""
        self._model_name       = EVALUATION_MODEL
        self._client           = None
        self._paper_text: str  = ""
        self._current_paper_id: str = ""
        self._response_cache   = DiskResponseCache(CACHE_DIR, enabled=CACHE_ENABLED)
        self._call_count       = 0
        self._api_call_count   = 0
        self._disk_hit_count   = 0
        self._lock             = threading.Lock()

    def set_paper_context(self, source_text: str, paper_id: str = "") -> None:
        """Store the current paper text and ID so all subsequent calls use it"""
        self._paper_text       = source_text
        self._current_paper_id = paper_id

    def set_entity_context(self, context: dict) -> None:
        """Write per-call evaluation context into thread local storage"""
        _thread_local.current_context = context

    def load_model(self) -> openai.OpenAI:
        """Lazily initialise and return the OpenRouter API client"""
        if self._client is None:
            self._client = _build_openrouter_client()
        return self._client

    def _generate_single(self, paper_text: str, paper_id: str, context: dict) -> str:
        """Execute one judge call with retry logic and disk cache lookup """
        with self._lock:
            self._call_count += 1
            call_num = self._call_count

        task        = context.get("task", "verify")
        field_name  = context.get("field_name", "")
        primary_val = context.get("candidate_value", field_name) if task == "verify" else field_name

        cached = self._response_cache.get(paper_id, task, field_name, primary_val)
        if cached is not None:
            with self._lock:
                self._disk_hit_count += 1
            print(f"  [call {call_num}] DISK CACHE HIT  paper={paper_id!r}  "
                  f"task={task}  field={field_name}  value={primary_val[:40]!r}")
            return cached

        with self._lock:
            self._api_call_count += 1

        messages = _build_messages(paper_text, context)
        all_vals = context.get("all_extracted_values", [])
        print(f"  [call {call_num}] API CALL  paper={paper_id!r}  task={task}  "
              f"field={field_name}  value={primary_val[:40]!r}  "
              f"siblings={all_vals}  "
              f"[sys={len(_STATIC_SYSTEM_PROMPT):,}  paper={len(paper_text):,} chars]")

        extra_body = {"thinking": {"type": "enabled"}} if MODEL_ENABLE_THINKING else {}

        content = ""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.load_model().chat.completions.create(
                    model=self._model_name,
                    messages=messages,
                    temperature=MODEL_TEMPERATURE,
                    max_tokens=16000,
                    extra_body=extra_body if extra_body else None,
                    timeout=300,
                )
                if not response or not getattr(response, "choices", None):
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY * attempt); continue
                    break
                message = response.choices[0].message
                content = _extract_text_content(message)
                if hasattr(response, "usage") and response.usage:
                    u = response.usage
                    ci = ""
                    if hasattr(u, "cache_creation_input_tokens"):
                        ci = (f"  cache_create={u.cache_creation_input_tokens:,}  "
                              f"cache_read={getattr(u, 'cache_read_input_tokens', 0):,}")
                    print(f"  [tokens] prompt={u.prompt_tokens:,}  completion={u.completion_tokens:,}{ci}")
                if content:
                    break
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
            except Exception as exc:
                print(f"  [API ERROR] {type(exc).__name__}: {exc} "
                      f"(attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)

        if content:
            self._response_cache.put(paper_id, task, field_name, primary_val, content)
        print(f"  [response] {content[:200]}...")
        return content

    def generate(self, prompt: str, schema=None):
        """Generate a judge response for the current threa local context"""
        context = getattr(_thread_local, "current_context", None) or {}
        content = self._generate_single(self._paper_text, self._current_paper_id, context)
        if not content:
            content = (
                "TYPE CHECK: Unable to evaluate.\nSOURCE CHECK: N/A\n"
                "TRUTH CHECK: N/A\nCOMPLETENESS CHECK: N/A\n"
                "TYPE_CORRECT: yes\nCORRECT_TYPE_NAME: NONE\n"
                "VALUE_CORRECT: no\nVALUE_COMPLETE: no\n"
                "HALLUCINATED: no\nVERDICT: low\nCORRECTED_VALUE: NONE"
            )
        if schema is not None:
            payload = {"score": 1, "reason": content}
            for attempt in (
                lambda: schema(**payload),
                lambda: schema.model_validate(payload),
                lambda: schema.model_validate_json(json.dumps(payload)),
            ):
                try:
                    return attempt()
                except Exception:
                    continue
            return json.dumps(payload)
        return content

    async def a_generate(self, prompt: str, schema=None) -> str:
        """Async wrapper that delegates to the synchronous generate method"""
        return self.generate(prompt, schema=schema)

    def get_model_name(self) -> str:
        """Return the model identifier string used in API calls"""
        return self._model_name

    def get_cache_stats(self) -> dict:
        """Return a combined summary of disk cache and call count statistics"""
        stats = self._response_cache.stats()
        stats["total_generate_calls"] = self._call_count
        stats["actual_api_calls"]     = self._api_call_count
        stats["disk_cache_hits"]      = self._disk_hit_count
        if self._call_count > 0:
            stats["overall_disk_hit_rate"] = (
                f"{self._disk_hit_count / self._call_count * 100:.1f}%")
        return stats


#Module level singleton holding the shared judge model instance
_judge_model: Gemma4Judge | None = None

def _get_judge_model() -> Gemma4Judge:
    """Return the shared Gemma4Judge singleton, creating it on first call"""
    global _judge_model
    if _judge_model is None:
        _judge_model = Gemma4Judge()
    return _judge_model


def _get_thread_annotation_metric() -> GEval:
    if not hasattr(_thread_local, "annotation_metric"):
        _thread_local.annotation_metric = GEval(
            name="AnnotationJudge",
            criteria=_ANNOTATION_GEVAL_CRITERIA,
            evaluation_steps=_ANNOTATION_GEVAL_STEPS,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT,
                               LLMTestCaseParams.EXPECTED_OUTPUT],
            model=_get_judge_model(), threshold=0.5)
    return _thread_local.annotation_metric


def _get_thread_missed_metric() -> GEval:
    """Return a thread local GEval metric for detecting missed fields"""
    if not hasattr(_thread_local, "missed_metric"):
        _thread_local.missed_metric = GEval(
            name="MissedFieldDetector",
            criteria=_MISSED_GEVAL_CRITERIA,
            evaluation_steps=_MISSED_GEVAL_STEPS,
            evaluation_params=[LLMTestCaseParams.ACTUAL_OUTPUT,
                               LLMTestCaseParams.EXPECTED_OUTPUT],
            model=_get_judge_model(), threshold=0.5)
    return _thread_local.missed_metric


def _field_def_for(field_name: str) -> str:
    fn_lower = field_name.lower()
    for k, v in FIELD_DEFINITIONS.items():
        if k.lower() == fn_lower:
            return v
    return f"Metadata field: {field_name}"


def _parse_type_correct(reason: str) -> bool | None:
    """Extract the correct type yes or no flag from a judge response string returns None when the flag is not present in the response"""
    m = re.search(r"TYPE_CORRECT\s*:\s*(yes|no)\b", reason, re.IGNORECASE)
    return (m.group(1).lower() == "yes") if m else None


def _parse_correct_type_name(reason: str, field_name: str = "") -> str | None:
    fn_lower = field_name.strip().lower()
    def _accept(name):
        n = name.strip().strip("'\"`,.()")
        if n.lower() in _KNOWN_FIELD_TYPES_LOWER and n.lower() != fn_lower:
            return n
        return None
    m = re.search(r"CORRECT_TYPE_NAME\s*:\s*(\S+)", reason, re.IGNORECASE)
    if m:
        val = m.group(1).strip().strip("'\"`,.")
        if val.upper() not in ("NONE", "N/A", "NULL", "SAME", "YES", "NO"):
            result = _accept(val)
            if result:
                return result
    for pat in [r"correct\s+(?:field|type)\s+is\s+([a-z_]+)",
                r"belongs\s+to\s+(?:the\s+)?([a-z_]+)\s+field",
                r"should\s+be\s+(?:labeled\s+as\s+|classified\s+as\s+)?([a-z_]+)"]:
        m2 = re.search(pat, reason, re.IGNORECASE)
        if m2:
            result = _accept(m2.group(1))
            if result:
                return result
    return None


def _parse_yes_no(reason: str, field: str) -> bool | None:
    """Parse a named yes or no flag from a structured judge response string.

    Returns None when the flag is absent.
    """
    m = re.search(rf"{field}\s*:\s*(yes|no)\b", reason, re.IGNORECASE)
    return (m.group(1).lower() == "yes") if m else None


def _clean_corrected_value(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("["):
        try:
            items = json.loads(raw)
            if isinstance(items, list):
                return ", ".join(str(i).strip() for i in items if str(i).strip())
        except (json.JSONDecodeError, ValueError):
            pass
        raw = raw.strip("[]")
        items = [re.sub(r'^["\'\s]+|["\'\s]+$', '', p)
                 for p in re.split(r',\s*', raw)]
        return ", ".join(i for i in items if i)
    return raw


def _parse_corrected_value(reason: str) -> str | None:
    """Extract the CORRECTED_VALUE from a judge response with prose fallbacks"""
    m = re.search(r"CORRECTED_VALUE\s*:\s*(.+?)(?:\n|$)", reason, re.IGNORECASE)
    if m:
        val = m.group(1).strip().strip("'\" `")
        if val and val.upper() not in ("NONE", "N/A", "NULL", "SAME"):
            return _clean_corrected_value(val)
    fallback_patterns = [
        r'(?:paper|study)\s+(?:describes?|uses?|employs?|reports?)\s+(?:a\s+)?(?:specifically\s+)?["\']([^"\']{3,60})["\']',
        r'should\s+be\s+["\']([^"\']{3,60})["\']',
        r'correct\s+value\s+(?:is|should\s+be)\s+["\']([^"\']{3,60})["\']',
    ]
    check_blocks = []
    for block_name in ["COMPLETENESS CHECK", "TRUTH CHECK"]:
        bm = re.search(
            rf"{block_name}\s*:\s*(.+?)(?=TYPE_CORRECT|VALUE_CORRECT|VALUE_COMPLETE|HALLUCINATED|VERDICT|CORRECTED_VALUE|$)",
            reason, re.IGNORECASE | re.DOTALL)
        if bm:
            check_blocks.append(bm.group(1))
    search_text = " ".join(check_blocks) if check_blocks else reason
    for pattern in fallback_patterns:
        fm = re.search(pattern, search_text, re.IGNORECASE)
        if fm:
            val = fm.group(1).strip().strip("'\" `.,;")
            if val and len(val) >= 2 and val.upper() not in ("NONE", "N/A", "NULL"):
                print(f"  [corrected value fallback] Extracted '{val}' from prose")
                return _clean_corrected_value(val)
    return None


def _is_concentration_only(field_name: str, extracted_value: str) -> bool:
    """Return True when a concentration field value contains only a numeric quantity and unit"""
    if field_name.lower() not in CONCENTRATION_FIELDS:
        return False
    conc_pattern = re.compile(
        r"^\s*\d+(?:\.\d+)?\s*(?:m[Mm]|[µu]M|M|mol/[Ll]|mmol/[Ll]|%)\s*$")
    return bool(conc_pattern.match(extracted_value.strip()))


def _norm(s: str) -> str:
    """Normalise a string for deduplication: lowercase, collapse whitespace, unify punctuation"""
    if not s:
        return ""
    s = s.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s.strip().lower())


def _is_evidence_sentence(s: str) -> bool:
    """Return True when a string exceeds the maximum value length threshold"""
    return len(s) > MAX_VALUE_LENGTH


def _flatten_extraction_values(val) -> list[str]:
    """Extract real metadata values from an alternating value evidence list"""
    results: list[str] = []
    if isinstance(val, str):
        s = val.strip()
        if not _is_not_extracted(s) and not _is_evidence_sentence(s):
            results.append(s)
        return results
    if isinstance(val, list):
        for i, item in enumerate(val):
            if i % 2 == 1:
                continue
            if isinstance(item, list):
                s = str(item[0]).strip() if item else ""
            else:
                s = str(item).strip()
            if not _is_not_extracted(s) and not _is_evidence_sentence(s):
                results.append(s)
        return results
    s = str(val).strip()
    if not _is_not_extracted(s) and not _is_evidence_sentence(s):
        results.append(s)
    return results


def _run_geval_semantic(field_name: str,
                        extracted_value: str,
                        all_values_for_field: list[str]) -> dict:
    """Judge one extracted metadata value using the GEval annotation metric"""
    model   = _get_judge_model()
    context = {
        "task":                  "verify",
        "field_name":            field_name,
        "field_definition":      _field_def_for(field_name),
        "candidate_value":       extracted_value,
        "all_extracted_values":  all_values_for_field,
    }
    model.set_entity_context(context)

    expected_str = (
        "Assess the candidate_value against the paper text AND the field definition. "
        "IMPORTANT -- SIBLING-VALUE RULE: all_extracted_values lists ALL values the "
        "pipeline extracted for this field. If together they cover the complete picture "
        "described in the paper, each individual value is VALUE_COMPLETE: yes "
        "and VERDICT: high. Do NOT flag a value as incomplete just because the paper "
        "has multiple correct values for the same field and this is only one of them. "
        "Only flag MEDIUM when the full set of all_extracted_values is still insufficient. "
        "Also assess: correct metadata field (TYPE_CORRECT yes/no), "
        "present/inferable in source (HALLUCINATED yes/no), "
        "factually valid (VALUE_CORRECT yes/no). "
        "When VERDICT is medium, output CORRECTED_VALUE: <the full correct value set>. "
    )
    if field_name.lower() in CONCENTRATION_FIELDS:
        expected_str += (
            "IMPORTANT: concentration field -- reagent name extracted separately. "
            "A value with only numeric quantity + unit is COMPLETE (VALUE_COMPLETE: yes). "
        )
    if field_name.lower() in _ALWAYS_LLM_FIELDS:
        expected_str += (
            "IMPORTANT: value may be reasonably inferable from experimental context "
            "even when not explicitly stated. Do NOT mark as HALLUCINATED solely "
            "because the exact term is absent. "
        )

    sibling_note = (f"  (all extracted values for this field: {all_values_for_field})"
                    if len(all_values_for_field) > 1 else "")
    test_case = LLMTestCase(
        input=(f"Assess field='{field_name}' candidate_value='{extracted_value}'"
               + sibling_note),
        actual_output=(f"field_name: {field_name}\n"
                       f"candidate_value: {extracted_value}\n"
                       f"all_extracted_values: {all_values_for_field}"),
        expected_output=expected_str,
    )

    reason = ""
    score  = None
    try:
        metric = _get_thread_annotation_metric()
        metric.measure(test_case)
        reason = metric.reason or ""
        score  = metric.score
    except RecursionError:
        print(f"  [GEval recursion] {field_name}: '{extracted_value[:40]}' direct API fallback")
        reason = model._generate_single(model._paper_text, model._current_paper_id, context)
    except Exception as exc:
        print(f"  [GEval error] {field_name}: {type(exc).__name__}: {exc}")
        try:
            reason = model._generate_single(model._paper_text, model._current_paper_id, context)
        except Exception as fallback_exc:
            print(f"  [direct fallback also failed] {fallback_exc}")
            return {"verdict": None, "type_mismatch": None, "correct_type": None,
                    "value_correct": None, "value_complete": None, "hallucination": None,
                    "corrected_value": None, "issue_summary": f"GEval error: {exc}",
                    "match_type": "ERROR", "geval_score": None}

    if not reason:
        reason = (
            "TYPE CHECK: Unable to evaluate.\nSOURCE CHECK: N/A\n"
            "TRUTH CHECK: N/A\nCOMPLETENESS CHECK: N/A\n"
            "TYPE_CORRECT: yes\nCORRECT_TYPE_NAME: NONE\n"
            "VALUE_CORRECT: no\nVALUE_COMPLETE: no\n"
            "HALLUCINATED: no\nVERDICT: low\nCORRECTED_VALUE: NONE"
        )

    verdict_match   = re.search(r"VERDICT:\s*(high|medium|low)", reason, re.IGNORECASE)
    verdict         = verdict_match.group(1).lower() if verdict_match else None
    hall_parsed     = _parse_yes_no(reason, "HALLUCINATED")
    is_hallucinated = bool(hall_parsed) if hall_parsed is not None else False

    type_correct_parsed = _parse_type_correct(reason)
    if type_correct_parsed is not None:
        is_mismatch = not type_correct_parsed
    else:
        is_mismatch = (verdict == "low") and not is_hallucinated and bool(
            re.search(r"type mismatch|wrong (?:field|type)|incorrect type|belongs to",
                      reason, re.IGNORECASE))
    correct_type = _parse_correct_type_name(reason, field_name) if is_mismatch else None

    vc_parsed      = _parse_yes_no(reason, "VALUE_CORRECT")
    vcomp_parsed   = _parse_yes_no(reason, "VALUE_COMPLETE")
    value_correct  = vc_parsed if vc_parsed is not None else (
        (verdict in ("high", "medium")) and not is_hallucinated and not is_mismatch)
    value_complete = vcomp_parsed if vcomp_parsed is not None else (
        (verdict == "high") and not is_hallucinated and not is_mismatch)

    if is_hallucinated or is_mismatch:
        value_correct = False
    if is_hallucinated:
        value_complete = False

    #Post processing override: concentration values without the reagent name are still complete
    if (field_name.lower() in CONCENTRATION_FIELDS and value_correct
            and not is_hallucinated and not is_mismatch and not value_complete):
        reagent_incomplete = bool(re.search(
            r"(?:lacks?|missing|without|does not include|omits?)\s+"
            r"(?:the\s+)?(?:reagent|DTT|TCEP|IAA|iodoacetamide|dithiothreitol|"
            r"chemical|compound)\s*(?:name)?", reason, re.IGNORECASE))
        if reagent_incomplete or _is_concentration_only(field_name, extracted_value):
            value_complete = True
            verdict = "high"
            reason += ("\n[POST-PROCESSING OVERRIDE] Concentration field: "
                       "numeric quantity + unit without reagent name IS complete.")

    corrected_value = _parse_corrected_value(reason)

    #Derive a human readable match type label from the parsed flags
    if is_hallucinated:
        match_type = "HALLUCINATED"
    elif is_mismatch:
        match_type = "TYPE_MISMATCH"
    elif verdict == "high":
        match_type = "CORRECT"
    elif verdict == "medium":
        match_type = "PARTIAL"
    else:
        match_type = "NO_MATCH"

    return {"verdict": verdict, "type_mismatch": is_mismatch, "correct_type": correct_type,
            "value_correct": value_correct, "value_complete": value_complete,
            "hallucination": is_hallucinated, "corrected_value": corrected_value,
            "issue_summary": reason, "match_type": match_type, "geval_score": score}


def load_llm_output_json(extraction_dir: str, pxd_id: str,
                         agent: str) -> dict[str, list[str]]:
    """Load one agent's extraction JSON for a given PXD dataset & returns a dict mapping canonical field names to lists of extracted values
    with evidence sentences and sentinel strings stripped out"""
    suffix    = AGENT_FILE_SUFFIX.get(agent, agent.lower())
    agent_dir = os.path.join(extraction_dir, agent)
    if not os.path.exists(agent_dir):
        print(f"    WARNING: agent dir not found: {agent_dir}")
        return {}

    raw_data = None
    for cname in [f"{pxd_id}_{suffix}.json", f"{pxd_id}.json"]:
        path = os.path.join(agent_dir, cname)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw_data = json.load(f)
                print(f"    [{agent}] loaded: {cname}")
                break
            except Exception as e:
                print(f"    WARNING: could not read {path}: {e}")
                return {}
    if raw_data is None:
        for fname in sorted(os.listdir(agent_dir)):
            if fname.startswith(pxd_id) and fname.endswith(".json"):
                path = os.path.join(agent_dir, fname)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                    print(f"    [{agent}] loaded (fallback): {fname}")
                    break
                except Exception as e:
                    print(f"    WARNING: could not read {path}: {e}")
                    return {}
    if raw_data is None:
        print(f"    [{agent}] WARNING: no JSON found for {pxd_id}")
        return {}

    #Build the full set of allowed field names including both raw and mapped forms
    allowed_fields: set[str] = set()
    for fields_list in PIPELINE_FIELDS.values():
        for f in fields_list:
            allowed_fields.add(f)
            allowed_fields.add(FIELD_NAME_MAP.get(f, f))

    parsed: dict[str, list[str]] = {}
    for field, raw_val in raw_data.items():
        if field.startswith("_") or field not in allowed_fields:
            continue
        values = _flatten_extraction_values(raw_val)
        if not values:
            print(f"    [{agent}] {field}: all values are sentinels/evidence -- skipping")
            continue
        mapped = FIELD_NAME_MAP.get(field, field)
        existing = parsed.setdefault(mapped, [])
        for v in values:
            if v not in existing:
                existing.append(v)
        if len(values) > 1:
            print(f"    [{agent}] {field} mapped to {mapped}: "
                  f"{len(values)} values extracted: {values}")
    return parsed


#Column names for the main annotation review CSV
_REVIEW_CSV_FIELDS = [
    "paper_id", "agent", "annotation_type", "extracted_value",
    "all_values_for_field",
    "verdict", "type_mismatch", "correct_type",
    "value_correct", "value_complete", "hallucination",
    "issue_summary", "corrected_value",
]

#Column names for the per paper statistics CSV
_STATS_CSV_FIELDS = [
    "paper_id", "total_extracted",
    "judge_n_correct", "judge_n_hallucinated", "judge_n_mismatch",
    "judge_n_wrong", "judge_n_incomplete", "judge_n_corrected",
    "judge_accuracy",
]

#Column names for the field coverage CSV
_COVERAGE_CSV_FIELDS = [
    "paper_id", "agent", "pipeline_field", "mapped_field",
    "extracted_value", "was_extracted",
]


class _IncrementalCSV:
    """Write CSV rows incrementally to disk flushing after each batch"""

    def __init__(self, path: str, fieldnames: list[str]):
        """Open the output file and write the header row"""
        import csv as _csv
        self._fh     = open(path, "w", newline="", encoding="utf-8")
        self._writer = _csv.DictWriter(self._fh, fieldnames=fieldnames,
                                       quoting=_csv.QUOTE_ALL, extrasaction="ignore")
        self._writer.writeheader()
        self._fh.flush()

    def append_rows(self, rows: list[dict]) -> None:
        """Write a list of row dicts and flush to disk"""
        for row in rows:
            self._writer.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        """Close the underlying file handle"""
        self._fh.close()


def _compute_single_paper_stats(paper_id: str, eval_rows: list[dict]) -> dict:
    """Compute quality category counts and accuracy for one paper's evaluation rows"""
    total = len(eval_rows)
    rec   = {"paper_id": paper_id, "total_extracted": total}
    judged = [r for r in eval_rows if r.get("value_correct") is not None]
    if judged:
        n_correct    = sum(1 for r in eval_rows
                           if r.get("type_mismatch") == False
                           and r.get("value_correct") == True
                           and r.get("value_complete") == True
                           and r.get("hallucination") == False)
        n_halluc     = sum(1 for r in eval_rows if r.get("hallucination"))
        n_mismatch   = sum(1 for r in eval_rows if r.get("type_mismatch"))
        n_wrong      = sum(1 for r in eval_rows
                           if r.get("value_correct") == False
                           and not r.get("hallucination"))
        n_incomplete = sum(1 for r in eval_rows
                           if r.get("value_correct") == True
                           and r.get("value_complete") == False)
        n_corrected  = sum(1 for r in eval_rows if r.get("corrected_value"))
        rec["judge_n_correct"]      = n_correct
        rec["judge_n_hallucinated"] = n_halluc
        rec["judge_n_mismatch"]     = n_mismatch
        rec["judge_n_wrong"]        = n_wrong
        rec["judge_n_incomplete"]   = n_incomplete
        rec["judge_n_corrected"]    = n_corrected
        rec["judge_accuracy"]       = round(n_correct / total, 4) if total > 0 else 0.0
    return rec


def _run_pass(work_items: list[tuple], n_total: int,
              label: str) -> dict[int, dict]:
    """Dispatch a batch of evaluation tasks to the thread pool and collect results"""
    results: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_run_geval_semantic, field, value, siblings):
                (idx, field, value)
            for idx, field, value, siblings in work_items
        }
        for future in as_completed(futures):
            idx, field_name, extracted_value = futures[future]
            try:
                result = future.result()
                results[idx] = result
                if result.get("verdict") is not None:
                    cv_info = (f"  corrected='{result['corrected_value'][:30]}'"
                               if result.get("corrected_value") else "")
                    print(f"      {label}[{idx+1}/{n_total}] {field_name}: "
                          f"'{extracted_value[:40]}' "
                          f"verdict={result['verdict']}  "
                          f"correct={result['value_correct']}  "
                          f"halluc={result['hallucination']}  "
                          f"mismatch={result['type_mismatch']}{cv_info}")
                else:
                    print(f"      {label}[{idx+1}/{n_total}] {field_name}: "
                          f"'{extracted_value[:40]}' ERROR")
            except Exception as exc:
                print(f"      {label}[{idx+1}/{n_total}] {field_name}: "
                      f"'{extracted_value[:40]}' ERROR: {exc}")
                results[idx] = {
                    "verdict": None, "type_mismatch": None, "correct_type": None,
                    "value_correct": None, "value_complete": None, "hallucination": None,
                    "corrected_value": None,
                    "issue_summary": f"Thread error: {exc}",
                    "match_type": "ERROR", "geval_score": None,
                }
    return results


def _is_bad_value(result: dict) -> bool:
    return bool(
        result.get("verdict") == "low"
        or result.get("hallucination")
        or result.get("type_mismatch")
        or result.get("value_correct") == False
    )


def evaluate_paper_with_geval(paper_id: str,
                               eval_rows: list[dict],
                               source_text: str) -> list[dict]:
    """Judge all extracted values for one paper using a two pass evaluation strateg"""
    _get_judge_model().set_paper_context(source_text, paper_id=paper_id)

    #Build the raw (unfiltered) map of all values per field before any quality filtering
    raw_field_values: dict[str, list[str]] = {}
    for row in eval_rows:
        raw_field_values.setdefault(row["annotation_type"], [])
        if row["extracted_value"] not in raw_field_values[row["annotation_type"]]:
            raw_field_values[row["annotation_type"]].append(row["extracted_value"])

    n_total = len(eval_rows)

    print(f"    [judge pass 1] {n_total} values with raw sibling context ...")
    pass1_items = [
        (idx, r["annotation_type"], r["extracted_value"],
         raw_field_values.get(r["annotation_type"], [r["extracted_value"]]))
        for idx, r in enumerate(eval_rows)
    ]
    pass1_results = _run_pass(pass1_items, n_total, "P1 ")

    for idx, row in enumerate(eval_rows):
        r = pass1_results.get(idx, {})
        row["verdict"]         = r.get("verdict")
        row["type_mismatch"]   = r.get("type_mismatch")
        row["correct_type"]    = r.get("correct_type")
        row["value_correct"]   = r.get("value_correct")
        row["value_complete"]  = r.get("value_complete")
        row["hallucination"]   = r.get("hallucination")
        row["corrected_value"] = r.get("corrected_value")
        row["issue_summary"]   = r.get("issue_summary", "")

    #Build a clean sibling map that excludes values judged as low quality in pass 1
    clean_field_values: dict[str, list[str]] = {}
    for idx, row in enumerate(eval_rows):
        r = pass1_results.get(idx, {})
        field = row["annotation_type"]
        clean_field_values.setdefault(field, [])
        if not _is_bad_value(r):
            if row["extracted_value"] not in clean_field_values[field]:
                clean_field_values[field].append(row["extracted_value"])

    #Log any fields where bad values were removed from the sibling context
    for field in raw_field_values:
        raw_set   = set(raw_field_values[field])
        clean_set = set(clean_field_values.get(field, []))
        pruned    = raw_set - clean_set
        if pruned:
            print(f"    [sibling prune] {field}: removed bad values {pruned} "
                  f"from sibling context")

    #Stamp each row with its clean sibling list for the CSV output column
    for row in eval_rows:
        clean_siblings = clean_field_values.get(
            row["annotation_type"], [row["extracted_value"]])
        row["all_values_for_field"] = " | ".join(clean_siblings)
        
    pass2_items = [
        (idx, r["annotation_type"], r["extracted_value"],
         clean_field_values.get(r["annotation_type"], [r["extracted_value"]]))
        for idx, r in enumerate(eval_rows)
        if r.get("verdict") == "medium"
    ]

    if pass2_items:
        print(f"    [judge pass 2] {len(pass2_items)} medium values with clean sibling context ...")
        pass2_results = _run_pass(pass2_items, n_total, "P2 ")

        for idx, row in enumerate(eval_rows):
            if row.get("verdict") != "medium":
                continue
            r2 = pass2_results.get(idx)
            if r2 is None:
                continue
            if r2.get("verdict") is not None:
                row["verdict"]         = r2.get("verdict")
                row["type_mismatch"]   = r2.get("type_mismatch")
                row["correct_type"]    = r2.get("correct_type")
                row["value_correct"]   = r2.get("value_correct")
                row["value_complete"]  = r2.get("value_complete")
                row["hallucination"]   = r2.get("hallucination")
                row["corrected_value"] = r2.get("corrected_value")
                row["issue_summary"]   = r2.get("issue_summary", "")
    else:
        print(f"    [judge pass 2] no medium values found, skipping.")

    return eval_rows


def load_enriched_json_pipeline(input_dir: str, pxd_id: str,
                                agent: str) -> dict[str, list[str]]:
    """Load one agent's pipeline enriched JSON from the integrated_output structure.

    Reads from:
        input_dir/integrated_output/{agent}/temp_0.0/{pxd_id}_PubText_enriched.json

    Each non-private field is a dict like {"resolved": "value", "confidence": ..., "status": "..."}.
    Extracts the "resolved" value, skipping nulls and complex (non-string) resolved values.
    Applies FIELD_NAME_MAP to canonical names.
    """
    enriched_path = os.path.join(
        input_dir, "integrated_output", agent, "temp_0.0",
        f"{pxd_id}_PubText_enriched.json"
    )
    if not os.path.exists(enriched_path):
        print(f"    WARNING: pipeline enriched JSON not found: {enriched_path}")
        return {}

    try:
        with open(enriched_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        print(f"    [{agent}] pipeline loaded: {enriched_path}")
    except Exception as e:
        print(f"    WARNING: could not read {enriched_path}: {e}")
        return {}

    allowed_fields: set[str] = set()
    for fields_list in PIPELINE_FIELDS.values():
        for field in fields_list:
            allowed_fields.add(field)
            allowed_fields.add(FIELD_NAME_MAP.get(field, field))

    parsed: dict[str, list[str]] = {}
    for field, entry in raw_data.items():
        if field.startswith("_"):
            continue
        if field not in allowed_fields:
            continue
        if not isinstance(entry, dict):
            continue
        resolved = entry.get("resolved")
        if resolved is None:
            continue
        # Skip complex resolved values (e.g. modification_site_fractions dicts)
        if not isinstance(resolved, (str, int, float)):
            continue
        value_str = str(resolved).strip()
        if _is_not_extracted(value_str) or _is_evidence_sentence(value_str):
            continue
        mapped = FIELD_NAME_MAP.get(field, field)
        existing = parsed.setdefault(mapped, [])
        if value_str not in existing:
            existing.append(value_str)
    return parsed


def get_manuscript_from_pmc_cache(pxd_id: str, pmc_cache_path: str) -> str:
    """Load publication text for a PXD from the pipeline's PMC cache JSON.

    The PMC cache is a JSON file (or directory with a JSON file) keyed by PXD ID,
    each entry having a 'full_text' key.  Mirrors the logic in run_agentic_metadata.py.
    """
    # Support both a direct JSON file path and a directory containing the cache
    cache_path = Path(pmc_cache_path)
    if cache_path.is_dir():
        # Try common filenames inside the directory
        for candidate in ["pmc_cache.json", "cache.json"]:
            p = cache_path / candidate
            if p.exists():
                cache_path = p
                break
        else:
            # Fall back: try to read directly as if the directory IS the cache file
            print(f"    WARNING: pmc_cache is a directory with no known JSON file: {pmc_cache_path}")
            return ""

    if not cache_path.exists():
        print(f"    WARNING: pmc_cache file not found: {cache_path}")
        return ""

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            pmc_data = json.load(f)
    except Exception as e:
        print(f"    WARNING: could not read pmc_cache {cache_path}: {e}")
        return ""

    pmc_entry = pmc_data.get(pxd_id)
    if not pmc_entry:
        print(f"    WARNING: PXD {pxd_id} not found in pmc_cache")
        return ""

    full_text = pmc_entry.get("full_text", "").strip()
    if not full_text:
        print(f"    WARNING: empty full_text in pmc_cache for {pxd_id}")
        return ""

    # Extract title + abstract + methods sections (same logic as load_manuscript)
    kept_parts = []
    for section in ["TITLE", "ABSTRACT", "METHODS"]:
        pattern = rf"===\s*{section}\s*===(.*?)(?===\s*[A-Z]|\Z)"
        match = re.search(pattern, full_text, re.DOTALL | re.IGNORECASE)
        if match:
            kept_parts.append(f"=== {section} ===\n{match.group(1).strip()}")
    if kept_parts:
        result = "\n\n".join(kept_parts)
        print(f"    PMC cache [{pxd_id}]: {len(full_text):,} chars total, "
              f"using {len(result):,} chars (title + abstract + methods)")
        return result
    print(f"    PMC cache [{pxd_id}]: {len(full_text):,} chars (full text, no sections found)")
    return full_text


def run_pipeline_evaluation(pxd_id: str, input_dir: str,
                             pmc_cache_path: str, out_dir: str,
                             n_runs: int = 1) -> None:
    """Run the LLM judge evaluation for a single PXD from pipeline enriched JSONs.

    input_dir is the metadata_extraction_output directory produced by
    run_agentic_metadata.py (contains integrated_output/{agent}/temp_0.0/).
    Outputs are written to out_dir.
    When n_runs > 1 the judge is run that many times with separate cache contexts
    and a majority-vote consensus is built before writing final outputs.
    """
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n=== LLM Judge: pipeline evaluation for {pxd_id} ===")
    print(f"  Input dir   : {input_dir}")
    print(f"  PMC cache   : {pmc_cache_path}")
    print(f"  Output dir  : {out_dir}")
    print(f"  Judge model : {EVALUATION_MODEL}  (via OpenRouter)")
    print(f"  LLM judge   : {'ENABLED' if USE_LLM_JUDGE else 'DISABLED'}")
    print(f"  Workers     : {MAX_WORKERS}")

    # --- Load manuscript text ---
    source_text = get_manuscript_from_pmc_cache(pxd_id, pmc_cache_path)
    if not source_text:
        print(f"  WARNING: no manuscript text found for {pxd_id} -- proceeding without judge")

    # --- Load extraction JSONs from all three agents ---
    all_predicted: dict[str, dict[str, list[str]]] = {}
    for agent in AGENTS:
        pred = load_enriched_json_pipeline(input_dir, pxd_id, agent)
        if pred:
            all_predicted[agent] = pred

    if not all_predicted:
        print(f"  ERROR: no enriched JSON found for {pxd_id} -- aborting judge evaluation")
        return

    # --- Build coverage rows ---
    coverage_rows = []
    for agent in AGENTS:
        pred = all_predicted.get(agent, {})
        for raw_field in PIPELINE_FIELDS.get(agent, []):
            if raw_field.lower() in SKIP_ANNOTATION_FIELDS:
                continue
            mapped  = FIELD_NAME_MAP.get(raw_field, raw_field)
            values  = pred.get(mapped) or pred.get(raw_field) or []
            display = " | ".join(values) if values else ""
            coverage_rows.append({
                "paper_id":        pxd_id,
                "agent":           agent,
                "pipeline_field":  raw_field,
                "mapped_field":    mapped,
                "extracted_value": display,
                "was_extracted":   bool(values),
            })

    n_extracted = sum(1 for r in coverage_rows if r["was_extracted"])
    print(f"  Fields extracted: {n_extracted}/{len(coverage_rows)}")
    print(f"  Judge runs      : {n_runs}")

    # Check early that there's anything to evaluate
    any_values = any(
        not _is_not_extracted(v)
        for pred in all_predicted.values()
        for vals in pred.values()
        for v in (vals if isinstance(vals, list) else [vals])
    )
    if not any_values:
        print(f"  WARNING: no valid extracted values found for {pxd_id}")
        return

    # --- Run judge N times, building consensus if n_runs > 1 ---
    global CACHE_DIR, _judge_model
    all_runs_eval_rows: list[list[dict]] = []

    for run_idx in range(n_runs):
        run_label = f"run {run_idx + 1}/{n_runs}"
        # Each run gets its own cache dir so fresh API calls are made after run 0.
        # Run 0 reuses the standard pipeline cache; subsequent runs use a per-run slug.
        if run_idx == 0:
            run_cache = os.path.join(out_dir, f".prompt_cache_{_CACHE_MODEL_SLUG}")
        else:
            run_cache = os.path.join(out_dir, f".prompt_cache_{_CACHE_MODEL_SLUG}_run{run_idx}")

        print(f"  [{run_label}] cache: {run_cache}")
        single_rows = _run_single_evaluation(
            pxd_id=pxd_id,
            input_dir=input_dir,
            pmc_cache_path=pmc_cache_path,
            source_text=source_text,
            all_predicted=all_predicted,
            run_cache_dir=run_cache,
        )
        all_runs_eval_rows.append(single_rows)
        print(f"  [{run_label}] got {len(single_rows)} eval rows")

    # Restore primary cache for any subsequent callers
    CACHE_DIR    = os.path.join(out_dir, f".prompt_cache_{_CACHE_MODEL_SLUG}")
    _judge_model = None

    if n_runs > 1:
        print(f"  Computing consensus across {n_runs} runs...")
        eval_rows = _compute_consensus_eval_rows(all_runs_eval_rows)
        print(f"  Consensus: {len(eval_rows)} unique field-value pairs")
    else:
        eval_rows = all_runs_eval_rows[0] if all_runs_eval_rows else []

    # --- Write outputs ---
    import csv as _csv

    review_path   = os.path.join(out_dir, "llm_judge_annotation_review.csv")
    stats_path    = os.path.join(out_dir, "llm_judge_per_paper.csv")
    coverage_path = os.path.join(out_dir, "llm_judge_coverage.csv")
    json_dir      = os.path.join(out_dir, "json_outputs")
    os.makedirs(json_dir, exist_ok=True)

    for path, fieldnames, rows in [
        (review_path,   _REVIEW_CSV_FIELDS,   eval_rows),
        (stats_path,    _STATS_CSV_FIELDS,    [_compute_single_paper_stats(pxd_id, eval_rows)]),
        (coverage_path, _COVERAGE_CSV_FIELDS, coverage_rows),
    ]:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = _csv.DictWriter(fh, fieldnames=fieldnames,
                                     quoting=_csv.QUOTE_ALL, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Written: {path}")

    _write_paper_json(pxd_id, eval_rows, json_dir)
    _write_sdrf_override_json(pxd_id, eval_rows, all_predicted, json_dir)

    per_paper_df = pd.DataFrame([_compute_single_paper_stats(pxd_id, eval_rows)])
    df           = pd.DataFrame(eval_rows)
    plot_results(df, per_paper_df, pxd_id, out_dir)

    stat = per_paper_df.iloc[0]
    print(f"\n  RESULTS: {pxd_id}")
    print(f"    total={stat.get('total_extracted', 0)}  "
          f"correct={stat.get('judge_n_correct', 0)}  "
          f"halluc={stat.get('judge_n_hallucinated', 0)}  "
          f"mismatch={stat.get('judge_n_mismatch', 0)}  "
          f"wrong={stat.get('judge_n_wrong', 0)}  "
          f"incomplete={stat.get('judge_n_incomplete', 0)}")
    acc = stat.get("judge_accuracy")
    if acc is not None:
        print(f"    accuracy={acc:.1%}")

    cache_stats = _get_judge_model().get_cache_stats()
    print("\n  CACHE STATISTICS")
    for k, v in cache_stats.items():
        print(f"    {k:<35} {v}")

    print(f"\n  Output files:")
    print(f"    Review CSV  : {review_path}")
    print(f"    Stats CSV   : {stats_path}")
    print(f"    Coverage CSV: {coverage_path}")
    print(f"    JSON outputs: {json_dir}/{pxd_id}.json")
    print(f"    Plots       : {out_dir}/llm_judge_*.png")


def load_manuscript(pxd_id: str) -> str:
    """Load the manuscript text for a given PXD dataset"""
    path = os.path.join(TEST_SET, pxd_id, "manuscript.txt")
    if not os.path.exists(path):
        print(f"    WARNING: manuscript not found: {path}")
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            full_text = f.read().strip()
        kept_parts = []
        for section in ["TITLE", "ABSTRACT", "METHODS"]:
            pattern = rf"===\s*{section}\s*===(.*?)(?===\s*[A-Z]|\Z)"
            match   = re.search(pattern, full_text, re.DOTALL | re.IGNORECASE)
            if match:
                kept_parts.append(f"=== {section} ===\n{match.group(1).strip()}")
        if kept_parts:
            result = "\n\n".join(kept_parts)
            print(f"    Manuscript: {len(full_text):,} chars total, "
                  f"using {len(result):,} chars (title and abstract and methods)")
            return result
        print(f"    Manuscript: {len(full_text):,} chars (full text, no sections found)")
        return full_text
    except Exception as e:
        print(f"    WARNING: could not read manuscript {path}: {e}")
        return ""


def _parse_checks_to_dict(issue_summary: str) -> dict:
    """Parse the four narrative check lines from an issue summary into a structured dict"""
    keys_out = {
        "TYPE CHECK":        "TYPE_CHECK",
        "SOURCE CHECK":      "SOURCE_CHECK",
        "TRUTH CHECK":       "TRUTH_CHECK",
        "COMPLETENESS CHECK":"COMPLETENESS_CHECK",
    }
    result   = {v: "" for v in keys_out.values()}

    if not issue_summary:
        return result

    structured = re.compile(
        r"^(TYPE_CORRECT|CORRECT_TYPE_NAME|VALUE_CORRECT|VALUE_COMPLETE|"
        r"HALLUCINATED|VERDICT|CORRECTED_VALUE|MATCHED_REFERENCE|"
        r"\[POST-PROCESSING)",
        re.IGNORECASE,
    )

    current_key:  str       = ""
    current_text: list[str] = []

    def _flush():
        if current_key and current_text:
            result[current_key] = " ".join(current_text).strip()

    for line in issue_summary.splitlines():
        stripped = line.strip()
        matched_label = None
        for label, out_key in keys_out.items():
            if re.match(rf"^{label}\s*:", stripped, re.IGNORECASE):
                matched_label = (label, out_key)
                break

        if matched_label:
            _flush()
            label, out_key = matched_label
            text_part = re.sub(rf"^{label}\s*:\s*", "", stripped, flags=re.IGNORECASE)
            current_key  = out_key
            current_text = [text_part] if text_part else []
        elif current_key:
            if structured.match(stripped) or stripped == "":
                _flush()
                current_key  = ""
                current_text = []
            else:
                current_text.append(stripped)

    _flush()
    return result


def _compute_consensus_eval_rows(all_runs: list[list[dict]]) -> list[dict]:
    """Merge eval rows from N judge runs using majority-vote consensus.

    For each (annotation_type, extracted_value) pair:
    - The majority verdict (>N/2) is used.
    - The majority corrected_value (>N/2, ignoring None) is used when available.
    - If corrected_values are spread across runs, no corrected_value is applied.
    """
    if not all_runs:
        return []
    if len(all_runs) == 1:
        return all_runs[0]

    n = len(all_runs)
    threshold = n // 2 + 1  # strict majority

    # Index rows by dedup key across all runs
    from collections import Counter, defaultdict
    key_to_rows: dict[tuple, list[dict]] = defaultdict(list)
    for run in all_runs:
        for row in run:
            key = (row.get("annotation_type", ""), _norm(str(row.get("extracted_value", ""))))
            key_to_rows[key].append(row)

    consensus: list[dict] = []
    for key, rows in key_to_rows.items():
        base = dict(rows[0])  # template from first row

        # Majority verdict
        verdicts = [r.get("verdict") for r in rows if r.get("verdict")]
        if verdicts:
            verdict_counts = Counter(verdicts)
            majority_verdict, count = verdict_counts.most_common(1)[0]
            base["verdict"] = majority_verdict if count >= threshold else verdict_counts.most_common(1)[0][0]

        # Majority per boolean flags
        for flag in ("hallucination", "type_mismatch", "value_correct", "value_complete"):
            vals = [r.get(flag) for r in rows if r.get(flag) is not None]
            if vals:
                true_count = sum(1 for v in vals if v is True or v == "True")
                base[flag] = true_count >= threshold

        # Majority corrected_value (must appear in strict majority, ignoring None)
        corr_vals = [r.get("corrected_value") for r in rows if r.get("corrected_value")]
        if corr_vals:
            corr_counts = Counter(corr_vals)
            top_val, top_count = corr_counts.most_common(1)[0]
            base["corrected_value"] = top_val if top_count >= threshold else None
        else:
            base["corrected_value"] = None

        # Annotate that this came from consensus
        base["consensus_runs"] = n
        base["consensus_votes"] = len(rows)
        consensus.append(base)

    return consensus


def _run_single_evaluation(pxd_id: str, input_dir: str,
                           pmc_cache_path: str, source_text: str,
                           all_predicted: dict, run_cache_dir: str) -> list[dict]:
    """Run one GEval judge pass and return the eval_rows."""
    global CACHE_DIR, _judge_model
    CACHE_DIR    = run_cache_dir
    _judge_model = None  # force re-init with new cache dir

    # Build eval rows
    seen_eval: set[tuple[str, str]] = set()
    eval_rows: list[dict] = []
    for agent in AGENTS:
        pred = all_predicted.get(agent, {})
        for raw_field in PIPELINE_FIELDS.get(agent, []):
            if raw_field.lower() in SKIP_ANNOTATION_FIELDS:
                continue
            mapped = FIELD_NAME_MAP.get(raw_field, raw_field)
            values = pred.get(mapped) or pred.get(raw_field) or []
            for v in values:
                if _is_not_extracted(v):
                    continue
                dedup_key = (mapped, _norm(v))
                if dedup_key in seen_eval:
                    continue
                seen_eval.add(dedup_key)
                eval_rows.append({
                    "paper_id":             pxd_id,
                    "agent":                agent,
                    "annotation_type":      mapped,
                    "extracted_value":      v,
                    "all_values_for_field": "",
                    "verdict":              None,
                    "type_mismatch":        None,
                    "correct_type":         None,
                    "value_correct":        None,
                    "value_complete":       None,
                    "hallucination":        None,
                    "issue_summary":        "",
                    "corrected_value":      None,
                })

    if USE_LLM_JUDGE and source_text:
        eval_rows = evaluate_paper_with_geval(pxd_id, eval_rows, source_text)

    return eval_rows


def _write_paper_json(pxd_id: str, eval_rows: list[dict], json_dir: str) -> None:
    """Write evaluation results for one paper to a JSON file"""
    os.makedirs(json_dir, exist_ok=True)

    entries = []
    for row in eval_rows:
        raw_summary = row.get("issue_summary") or ""
        entries.append({
            "annotation_type": row.get("annotation_type"),
            "extracted_value": row.get("extracted_value"),
            "verdict":         row.get("verdict"),
            "type_mismatch":   row.get("type_mismatch"),
            "value_correct":   row.get("value_correct"),
            "value_complete":  row.get("value_complete"),
            "hallucination":   row.get("hallucination"),
            "corrected_value": row.get("corrected_value"),
            "issue_summary":   _parse_checks_to_dict(raw_summary),
        })

    out = {"paper_id": pxd_id, "annotations": entries}
    path = os.path.join(json_dir, f"{pxd_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"    JSON written: {path}")


def _single_scalar_value(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.lower() in _NOT_EXTRACTED_VALUES:
        return None
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) == 1:
                value = str(parsed[0]).strip()
                return value or None
            return None
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    if " | " in text:
        return None
    return text


def _choose_override_candidate(rows: list[dict]) -> tuple[str | None, str | None, list[str]]:
    high_values = []
    corrected_values = []
    reasons = []

    for row in rows:
        extracted_scalar = _single_scalar_value(row.get("extracted_value"))
        corrected_scalar = _single_scalar_value(row.get("corrected_value"))
        if (
            row.get("verdict") == "high"
            and row.get("value_correct") is True
            and not row.get("hallucination")
            and not row.get("type_mismatch")
            and extracted_scalar
        ):
            high_values.append(extracted_scalar)
            reasons.append("judge_high_confidence")
        if corrected_scalar:
            corrected_values.append(corrected_scalar)

    high_values = sorted(set(high_values))
    corrected_values = sorted(set(corrected_values))

    if len(high_values) == 1:
        return high_values[0], "judge_high_confidence", reasons
    if len(corrected_values) == 1:
        return corrected_values[0], "judge_corrected_value", ["judge_corrected_value"]
    return None, None, []


def _write_sdrf_override_json(pxd_id: str, eval_rows: list[dict], all_predicted: dict[str, dict[str, list[str]]], json_dir: str) -> None:
    os.makedirs(json_dir, exist_ok=True)

    predicted_by_field: dict[str, list[str]] = {}
    for pred in all_predicted.values():
        for field, values in pred.items():
            predicted_by_field.setdefault(field, [])
            for value in values:
                if value not in predicted_by_field[field]:
                    predicted_by_field[field].append(value)

    field_overrides = {}
    for field, builder_field in SAFE_SDRF_OVERRIDE_FIELDS.items():
        rows = [row for row in eval_rows if row.get("annotation_type") == field]
        if not rows:
            continue

        selected_value, selection_source, _ = _choose_override_candidate(rows)
        pipeline_values = predicted_by_field.get(field, [])
        unique_pipeline_values = sorted(set(v for v in pipeline_values if _single_scalar_value(v)))
        apply_override = bool(selected_value) and unique_pipeline_values != [selected_value]

        field_overrides[field] = {
            "builder_field": builder_field,
            "pipeline_values": unique_pipeline_values,
            "selected_value": selected_value,
            "selection_source": selection_source,
            "apply_override": apply_override,
            "judge_rows": [
                {
                    "extracted_value": row.get("extracted_value"),
                    "verdict": row.get("verdict"),
                    "value_correct": row.get("value_correct"),
                    "value_complete": row.get("value_complete"),
                    "hallucination": row.get("hallucination"),
                    "type_mismatch": row.get("type_mismatch"),
                    "corrected_value": row.get("corrected_value"),
                }
                for row in rows
            ],
        }

    out = {
        "paper_id": pxd_id,
        "safe_fields": list(SAFE_SDRF_OVERRIDE_FIELDS.keys()),
        "field_overrides": field_overrides,
    }
    path = os.path.join(json_dir, f"{pxd_id}_sdrf_overrides.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"    SDRF override JSON written: {path}")


def process_model(model_name: str, extraction_dir: str, out_dir: str):
    """Run the full evaluation pipeline for one extraction model"""
    pxd_ids: list[str] = []
    for agent in AGENTS:
        agent_dir = os.path.join(extraction_dir, agent)
        if not os.path.isdir(agent_dir):
            continue
        for fname in os.listdir(agent_dir):
            if fname.endswith(".json"):
                pxd = fname.split("_")[0] if "_" in fname else fname[:-5]
                if pxd not in pxd_ids:
                    pxd_ids.append(pxd)
    pxd_ids = sorted(set(pxd_ids))
    print(f"  Papers discovered: {len(pxd_ids)}")

    if LIMIT and LIMIT < len(pxd_ids):
        pxd_ids = pxd_ids[:LIMIT]
        print(f"  Limit applied: running first {LIMIT} papers: {pxd_ids}")

    n_papers = len(pxd_ids)

    review_csv   = _IncrementalCSV(os.path.join(out_dir, "llm_judge_annotation_review.csv"),
                                   _REVIEW_CSV_FIELDS)
    stats_csv    = _IncrementalCSV(os.path.join(out_dir, "llm_judge_per_paper.csv"),
                                   _STATS_CSV_FIELDS)
    coverage_csv = _IncrementalCSV(os.path.join(out_dir, "llm_judge_coverage.csv"),
                                   _COVERAGE_CSV_FIELDS)

    json_out_dir = os.path.join(out_dir, "json_outputs")
    os.makedirs(json_out_dir, exist_ok=True)

    print()
    print("Output mode: INCREMENTAL -- CSVs and JSON written after each paper.")
    print(f"  Review CSV    : {os.path.join(out_dir, 'llm_judge_annotation_review.csv')}")
    print(f"  Per-paper CSV : {os.path.join(out_dir, 'llm_judge_per_paper.csv')}")
    print(f"  Coverage CSV  : {os.path.join(out_dir, 'llm_judge_coverage.csv')}")
    print(f"  JSON outputs  : {json_out_dir}/")
    print()

    all_rows       = []
    all_cov_rows   = []
    per_file_stats = []

    for paper_idx, pxd_id in enumerate(pxd_ids, 1):
        t_start = time.time()
        print(f"  PAPER [{paper_idx}/{n_papers}]: {pxd_id}")

        source_text = load_manuscript(pxd_id)
        if not source_text:
            print(f"    SKIP: no manuscript text found.")
            continue

        #Load extraction JSONs from all three agents for this paper
        all_predicted: dict[str, dict[str, list[str]]] = {}
        for agent in AGENTS:
            pred = load_llm_output_json(extraction_dir, pxd_id, agent)
            if pred:
                all_predicted[agent] = pred

        if not all_predicted:
            print(f"    SKIP: no extraction JSON found.")
            continue

        #Build one coverage row per agen -field combination
        coverage_rows = []
        for agent in AGENTS:
            pred = all_predicted.get(agent, {})
            for raw_field in PIPELINE_FIELDS.get(agent, []):
                if raw_field.lower() in SKIP_ANNOTATION_FIELDS:
                    continue
                mapped  = FIELD_NAME_MAP.get(raw_field, raw_field)
                values  = pred.get(mapped) or pred.get(raw_field) or []
                display = " | ".join(values) if values else ""
                coverage_rows.append({
                    "paper_id":        pxd_id,
                    "agent":           agent,
                    "pipeline_field":  raw_field,
                    "mapped_field":    mapped,
                    "extracted_value": display,
                    "was_extracted":   bool(values),
                })
        all_cov_rows.extend(coverage_rows)
        coverage_csv.append_rows(coverage_rows)

        n_ext   = sum(1 for r in coverage_rows if r["was_extracted"])
        n_total = len(coverage_rows)
        print(f"    Fields extracted: {n_ext}/{n_total}")

        #Build one eval row per unique canonical field and value combination
        seen_eval: set[tuple[str, str]] = set()
        eval_rows: list[dict] = []

        for agent in AGENTS:
            pred = all_predicted.get(agent, {})
            for raw_field in PIPELINE_FIELDS.get(agent, []):
                if raw_field.lower() in SKIP_ANNOTATION_FIELDS:
                    continue
                mapped = FIELD_NAME_MAP.get(raw_field, raw_field)
                values = pred.get(mapped) or pred.get(raw_field) or []
                for v in values:
                    if _is_not_extracted(v):
                        continue
                    dedup_key = (mapped, _norm(v))
                    if dedup_key in seen_eval:
                        print(f"    [dedup] skip '{v}' for '{mapped}' "
                              f"(already seen from earlier agent or field)")
                        continue
                    seen_eval.add(dedup_key)
                    eval_rows.append({
                        "paper_id":           pxd_id,
                        "agent":              agent,
                        "annotation_type":    mapped,
                        "extracted_value":    v,
                        "all_values_for_field": "",
                        "verdict":            None,
                        "type_mismatch":      None,
                        "correct_type":       None,
                        "value_correct":      None,
                        "value_complete":     None,
                        "hallucination":      None,
                        "issue_summary":      "",
                        "corrected_value":    None,
                    })

        if not eval_rows:
            print(f"    SKIP: no valid extracted values found.")
            continue

        #Count total raw value occurrences across all agents before deduplication
        n_raw = sum(
            len(all_predicted.get(ag, {}).get(FIELD_NAME_MAP.get(f, f))
                or all_predicted.get(ag, {}).get(f)
                or [])
            for ag in AGENTS
            for f in PIPELINE_FIELDS.get(ag, [])
            if f.lower() not in SKIP_ANNOTATION_FIELDS
        )
        print(f"    Evaluation rows: {len(eval_rows)} "
              f"(deduplicated from {n_raw} raw value occurrences)")

        if USE_LLM_JUDGE:
            eval_rows = evaluate_paper_with_geval(pxd_id, eval_rows, source_text)

        review_csv.append_rows(eval_rows)
        _write_paper_json(pxd_id, eval_rows, json_out_dir)

        paper_stat = _compute_single_paper_stats(pxd_id, eval_rows)
        per_file_stats.append(paper_stat)
        stats_csv.append_rows([paper_stat])

        all_rows.extend(eval_rows)

        elapsed = time.time() - t_start
        print(f"\n  PAPER COMPLETE: {pxd_id}  ({elapsed:.1f}s)")
        print(f"    total={paper_stat.get('total_extracted', 0)}  "
              f"correct={paper_stat.get('judge_n_correct', 0)}  "
              f"halluc={paper_stat.get('judge_n_hallucinated', 0)}  "
              f"mismatch={paper_stat.get('judge_n_mismatch', 0)}  "
              f"wrong={paper_stat.get('judge_n_wrong', 0)}  "
              f"incomplete={paper_stat.get('judge_n_incomplete', 0)}  "
              f"corrected={paper_stat.get('judge_n_corrected', 0)}")
        acc = paper_stat.get("judge_accuracy")
        if acc is not None:
            print(f"    accuracy={acc:.1%}")
        print(f"    results written to disk.")

    review_csv.close()
    stats_csv.close()
    coverage_csv.close()

    df           = pd.DataFrame(all_rows)       if all_rows       else pd.DataFrame()
    coverage_df  = pd.DataFrame(all_cov_rows)   if all_cov_rows   else pd.DataFrame()
    per_paper_df = pd.DataFrame(per_file_stats) if per_file_stats else pd.DataFrame()
    return df, coverage_df, per_paper_df


def plot_results(df: pd.DataFrame, per_paper_df: pd.DataFrame,
                 model_name: str, out_dir: str):
    """Generate and save three summary PNG charts from evaluation results"""
    if df.empty or per_paper_df.empty:
        return

    BG, GRID_C, TEXT_C, SUB_C, SPINE_C = "white", "#E5E7EB", "#111827", "#6B7280", "#D1D5DB"
    CLR = dict(correct="#27ae60", hall="#e74c3c", mismatch="#9b59b6",
               wrong="#e67e22", incomplete="#3498db")

    def style_ax(ax):
        """Apply consistent background, grid and spine styling to a matplotlib Axes"""
        ax.set_facecolor(BG)
        ax.yaxis.grid(True, color=GRID_C, lw=0.8, linestyle="--", zorder=0)
        ax.set_axisbelow(True)
        for sp in ["top", "right"]: ax.spines[sp].set_visible(False)
        for sp in ["left", "bottom"]: ax.spines[sp].set_color(SPINE_C)
        ax.tick_params(colors=TEXT_C, labelsize=9)

    required = ["judge_n_correct", "judge_n_hallucinated", "judge_n_mismatch",
                "judge_n_wrong", "judge_n_incomplete"]
    if not all(c in per_paper_df.columns for c in required):
        print("  [plot] skipping -- judge columns missing from per_paper_df")
        return

    names = per_paper_df["paper_id"].tolist()
    x     = np.arange(len(names))
    w     = 0.6

    n_correct    = per_paper_df["judge_n_correct"].fillna(0).values
    n_hall       = per_paper_df["judge_n_hallucinated"].fillna(0).values
    n_mismatch   = per_paper_df["judge_n_mismatch"].fillna(0).values
    n_wrong      = per_paper_df["judge_n_wrong"].fillna(0).values
    n_incomplete = per_paper_df["judge_n_incomplete"].fillna(0).values
    totals       = per_paper_df["total_extracted"].fillna(0).values

    #Stacked bar chart showing annotation quality categories per paper
    fig, ax = plt.subplots(figsize=(max(16, len(names) * 0.7), 7), facecolor=BG)
    style_ax(ax)
    b = np.zeros(len(names))
    for arr, col, lbl in [
        (n_correct,    CLR["correct"],   "Correct"),
        (n_hall,       CLR["hall"],      "Hallucinated"),
        (n_mismatch,   CLR["mismatch"],  "Type Mismatch"),
        (n_wrong,      CLR["wrong"],     "Wrong Value"),
        (n_incomplete, CLR["incomplete"],"Incomplete"),
    ]:
        ax.bar(x, arr, w, bottom=b, label=lbl, color=col,
               edgecolor="white", lw=0.5, alpha=0.92)
        b += arr
    for i, tot in enumerate(totals):
        ax.text(i, b[i] + 0.3, f"n={int(tot)}", ha="center", va="bottom",
                fontsize=7, fontweight="bold", color=TEXT_C)
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8, color=TEXT_C)
    ax.set_ylabel("Number of Annotations", fontsize=11, color=SUB_C)
    ax.set_title(f"{model_name.upper()} Annotation Quality per Paper",
                 fontsize=13, fontweight="bold", color=TEXT_C, pad=12)
    ax.legend(fontsize=9, framealpha=0.9, edgecolor=SPINE_C, loc="upper right")
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "llm_judge_annotation_quality_counts.png"),
                dpi=200, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  Saved: llm_judge_annotation_quality_counts.png")

    if "judge_accuracy" not in per_paper_df.columns:
        return
    acc_vals = per_paper_df["judge_accuracy"].tolist()
    overall  = float(np.mean(acc_vals))
    fig, ax  = plt.subplots(figsize=(max(14, len(names) * 0.55), 6), facecolor=BG)
    style_ax(ax)
    #Colour bars green above 70%, orange above 50%, red below 50%
    bar_colors = ["#27ae60" if v >= 0.7 else "#e67e22" if v >= 0.5 else "#e74c3c"
                  for v in acc_vals]
    bars = ax.bar(x, acc_vals, color=bar_colors, alpha=0.88,
                  edgecolor="white", linewidth=0.8, zorder=3)
    for bar, val in zip(bars, acc_vals):
        ax.text(bar.get_x() + bar.get_width() / 2., bar.get_height() + 0.012,
                f"{val:.2f}", ha="center", va="bottom",
                fontsize=8, fontweight="bold", color=TEXT_C)
    ax.axhline(overall, color="#2471a3", lw=2, linestyle="--",
               label=f"Mean = {overall:.3f}")
    ax.axhline(0.7, color="#e74c3c", lw=1.5, linestyle=":",
               alpha=0.7, label="Threshold = 0.70")
    ax.set_xticks(x)
    ax.set_xticklabels(names, rotation=45, ha="right", fontsize=8, color=TEXT_C)
    ax.set_ylabel("Accuracy (Correct / Total Extracted)", fontsize=11, color=SUB_C)
    ax.set_ylim([0, 1.18])
    ax.set_title(f"{model_name.upper()} LLM Judge Accuracy per Paper",
                 fontsize=13, fontweight="bold", color=TEXT_C, pad=12)
    ax.legend(fontsize=9, framealpha=0.9, edgecolor=SPINE_C)
    ax.text(0.98, 0.97, f"Overall: {overall:.1%}", transform=ax.transAxes,
            ha="right", va="top", fontsize=11, fontweight="bold", color="#27ae60",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#eafaf1",
                      edgecolor="#27ae60", alpha=0.85))
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "llm_judge_accuracy.png"),
                dpi=200, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  Saved: llm_judge_accuracy.png")

    #Aggregate bar chart summing all quality category counts across every paper
    agg_labels = ["Correct", "Hallucinated", "Type Mismatch", "Wrong Value", "Incomplete"]
    agg_vals   = [int(n_correct.sum()), int(n_hall.sum()), int(n_mismatch.sum()),
                  int(n_wrong.sum()), int(n_incomplete.sum())]
    agg_colors = [CLR["correct"], CLR["hall"], CLR["mismatch"], CLR["wrong"], CLR["incomplete"]]
    grand_total = sum(agg_vals)
    fig, ax = plt.subplots(figsize=(10, 6), facecolor=BG)
    style_ax(ax)
    bars5 = ax.bar(agg_labels, agg_vals, color=agg_colors,
                   edgecolor="white", linewidth=1.0, alpha=0.92, zorder=3)
    for bar, val in zip(bars5, agg_vals):
        pct = val / grand_total * 100 if grand_total > 0 else 0
        ax.text(bar.get_x() + bar.get_width() / 2., bar.get_height() + 0.5,
                f"{val}\n({pct:.1f}%)", ha="center", va="bottom",
                fontsize=11, fontweight="bold", color=TEXT_C)
    overall_acc = agg_vals[0] / grand_total * 100 if grand_total > 0 else 0
    ax.set_ylabel("Total Count (all papers)", fontsize=11, color=SUB_C)
    ax.set_title(f"{model_name.upper()} Aggregate Annotation Quality (total = {grand_total})",
                 fontsize=13, fontweight="bold", color=TEXT_C, pad=12)
    ax.text(0.5, 0.97, f"Overall accuracy: {overall_acc:.1f}%",
            transform=ax.transAxes, ha="center", va="top",
            fontsize=12, fontweight="bold", color=CLR["correct"],
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#eafaf1",
                      edgecolor=CLR["correct"], alpha=0.85))
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "llm_judge_aggregate.png"),
                dpi=200, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"  Saved: llm_judge_aggregate.png")


def main():
    """Parse command line arguments and run the full evaluation pipeline"""
    global USE_LLM_JUDGE, LIMIT, MAX_WORKERS, EVALUATION_MODEL, _CACHE_MODEL_SLUG, CACHE_DIR

    parser = argparse.ArgumentParser(
        description="LLM judge evaluation for agentic metadata extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
MODES:
  Pipeline mode (HAMLET integration):
    --pipeline --pxd PXD073162 --input_dir metadata_extraction_output
               --pmc_cache pride_survey/pmc_cache --outdir judge_output

  Benchmark mode (multi-model/multi-paper evaluation):
    --model claude|gpt|gemini|llama
""",
    )

    # ---- mode selection ----
    mode_grp = parser.add_mutually_exclusive_group(required=True)
    mode_grp.add_argument("--pipeline", action="store_true",
                          help="Pipeline mode: evaluate a single PXD from enriched JSONs")
    mode_grp.add_argument("--model", choices=list(MODEL_EXTRACTION_DIRS.keys()),
                          help="Benchmark mode: model to evaluate (claude/gpt/gemini/llama)")

    # ---- pipeline-mode args ----
    parser.add_argument("--pxd", default=None,
                        help="[pipeline] PXD accession to evaluate (e.g. PXD073162)")
    parser.add_argument("--input_dir", default=None,
                        help="[pipeline] Path to metadata_extraction_output directory")
    parser.add_argument("--pmc_cache", default=None,
                        help="[pipeline] Path to PMC cache JSON (or directory containing it)")
    parser.add_argument("--outdir", default=None,
                        help="[pipeline] Output directory for judge results")
    parser.add_argument("--judge_model", default=None,
                        help=f"[pipeline] OpenRouter model name (default: {EVALUATION_MODEL})")
    parser.add_argument("--n_judge_runs", type=int, default=1,
                        help="[pipeline] Run judge N times and use consensus corrections (default: 1)")

    # ---- shared args ----
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM judge API calls")
    parser.add_argument("--limit", type=int, default=None,
                        help="[benchmark] Limit to first N papers")
    parser.add_argument("--workers", type=int, default=None,
                        help=f"Max parallel LLM calls (default: {MAX_WORKERS})")
    args = parser.parse_args()

    if args.no_judge:
        USE_LLM_JUDGE = False
    if args.limit:
        LIMIT = args.limit
    if args.workers:
        MAX_WORKERS = args.workers

    # ---- pipeline mode ----
    if args.pipeline:
        for flag, name in [(args.pxd, "--pxd"), (args.input_dir, "--input_dir"),
                           (args.pmc_cache, "--pmc_cache"), (args.outdir, "--outdir")]:
            if not flag:
                parser.error(f"{name} is required in --pipeline mode")
        if args.judge_model:
            EVALUATION_MODEL  = args.judge_model
            _CACHE_MODEL_SLUG = EVALUATION_MODEL.replace("/", "_").replace(" ", "_")
            CACHE_DIR         = os.path.join(BASE_DIR, f".prompt_cache_{_CACHE_MODEL_SLUG}")
            _judge_model      = None  # force re-init
        run_pipeline_evaluation(args.pxd, args.input_dir, args.pmc_cache, args.outdir,
                                n_runs=args.n_judge_runs)
        return

    # ---- benchmark mode ----
    model_name     = args.model
    extraction_dir = MODEL_EXTRACTION_DIRS[model_name]
    out_dir        = os.path.join(BASE_DIR, "deepeval_SDRF_results_Final_V_text_only3",
                                  f"evaluation_Gemma_{model_name}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"  MODEL          : {model_name.upper()}")
    print(f"  Extraction dir : {extraction_dir}")
    print(f"  Manuscripts    : {TEST_SET}/<PXD>/manuscript.txt")
    print(f"  Output folder  : {out_dir}")
    print(f"  Judge model    : {EVALUATION_MODEL}  (via OpenRouter)")
    print(f"  Temperature    : {MODEL_TEMPERATURE}")
    print(f"  Thinking       : {'ENABLED' if MODEL_ENABLE_THINKING else 'DISABLED'}")
    print(f"  Disk cache     : {'ENABLED' if CACHE_ENABLED else 'DISABLED'}  dir={CACHE_DIR}")
    print(f"  LLM judge      : {'ENABLED' if USE_LLM_JUDGE else 'DISABLED'}")
    print(f"  Limit          : {LIMIT if LIMIT else 'ALL papers'}")
    print(f"  Concurrency    : {MAX_WORKERS} workers")
    print(f"  Max value len  : {MAX_VALUE_LENGTH} chars (longer strings treated as evidence)")
    print()
    print("NOTE: No SDRF or golden files are used.")
    print("      Completeness is judged against the FULL SET of extracted values")
    print("      for each field (SIBLING-VALUE RULE). No value is penalised for")
    print("      being one of several correct extractions.")
    print()

    df, coverage_df, per_paper_df = process_model(model_name, extraction_dir, out_dir)

    if df.empty:
        print("ERROR: No data processed.")
        return

    print(f"\n  Annotation review : {os.path.join(out_dir, 'llm_judge_annotation_review.csv')}")
    print(f"  Total rows        : {len(df)}")

    if not df.empty and "corrected_value" in df.columns:
        medium_df = df[
            (df.get("verdict", pd.Series(dtype=str)) == "medium")
            & df["corrected_value"].notna()
        ]
        if not medium_df.empty:
            print(f"\n  Medium verdicts with corrections: {len(medium_df)}")
            for _, row in medium_df.head(10).iterrows():
                print(f"    {row['annotation_type']}: "
                      f"'{str(row['extracted_value'])[:35]}' "
                      f"corrected to '{str(row['corrected_value'])[:35]}'")

    if not per_paper_df.empty:
        print(f"  Per-paper stats   : {os.path.join(out_dir, 'llm_judge_per_paper.csv')}")

    cache_stats = _get_judge_model().get_cache_stats()
    print("\nCACHE STATISTICS")
    for k, v in cache_stats.items():
        print(f"  {k:<35} {v}")

    print("\nGenerating summary plots...")
    plot_results(df, per_paper_df, model_name, out_dir)

    if not per_paper_df.empty and "judge_accuracy" in per_paper_df.columns:
        print(f"\nLLM Judge mean accuracy: "
              f"{float(per_paper_df['judge_accuracy'].mean()):.1%}")

    print(f"\nFINAL SUMMARY  ({len(per_paper_df)} papers)")
    if not per_paper_df.empty and "judge_accuracy" in per_paper_df.columns:
        for _, stat in per_paper_df.iterrows():
            print(f"  {str(stat['paper_id']):<30} "
                  f"extracted={stat.get('total_extracted', 0)}  "
                  f"correct={stat.get('judge_n_correct', 0)}  "
                  f"halluc={stat.get('judge_n_hallucinated', 0)}  "
                  f"accuracy={stat.get('judge_accuracy', 0):.2f}")

    print(f"\nOutput files:")
    print(f"  Review CSV    : {os.path.join(out_dir, 'llm_judge_annotation_review.csv')}")
    print(f"  Per-paper CSV : {os.path.join(out_dir, 'llm_judge_per_paper.csv')}")
    print(f"  Coverage CSV  : {os.path.join(out_dir, 'llm_judge_coverage.csv')}")
    print(f"  JSON outputs  : {os.path.join(out_dir, 'json_outputs')}/<PXD_ID>.json")
    print(f"  Plots         : {out_dir}/llm_judge_*.png")
    print(f"\nAll outputs saved to: {out_dir}")
    print("\nPIPELINE COMPLETE.")


if __name__ == "__main__":
    main()