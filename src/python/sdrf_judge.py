import os
import re
import json
import hashlib
import time
import argparse
import threading
import tempfile
import shutil
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


#root directory containing one folder per PXD dataset plus text file
DEFAULT_BASE_DIR = "/Users/fateme/Desktop/hamlet_sdrfs"
BASE_DIR = os.environ.get("HAMLET_SDRF_JUDGE_BASE_DIR", DEFAULT_BASE_DIR)

#directory containing per PXD manuscript text 
TEXT_FILES_DIR = os.path.join(BASE_DIR, "text_files")

#evaluation input for every PXD dataset is a single SDRF file:
#each SDRF is a tab separated table with one row per sample or run and columns
#named characteristics[...], comment[...], factor value[...]. Columns may be repeated (several comment[modification parameters] columns)
SDRF_SUFFIX = ".sdrf.tsv"

#maps an SDRF column header to the canonical evaluation field name. Columns not listed here are ignored (ids, accessions, data files,sdrf bookkeeping). Any "factor value[...]" column is handled generically below.
SDRF_COLUMN_MAP = {
    "characteristics[organism]":                    "species",
    "characteristics[organism part]":               "organ",
    "characteristics[disease]":                      "disease",
    "characteristics[cell type]":                    "cell_type",
    "characteristics[cell line]":                    "cell_line",
    "characteristics[strain]":                       "strain",
    "characteristics[biological replicate]":         "replicates",
    "characteristics[sex]":                          "sex",
    "characteristics[age]":                          "age",
    "characteristics[enrichment process]":           "enrichment_method",
    "technology type":                               "technology_type",
    "comment[proteomics data acquisition method]":   "acquisition_method",
    "comment[label]":                                "label",
    "comment[instrument]":                           "instrument",
    "comment[cleavage agent details]":               "cleavage_agent",
    "comment[fraction identifier]":                  "fractions",
    "comment[technical replicate]":                  "technical_replicates",
    "comment[dissociation method]":                  "fragmentation",
    "comment[modification parameters]":              "modification",
    "comment[precursor mass tolerance]":             "precursor_mass_tolerance",
    "comment[fragment mass tolerance]":              "fragment_mass_tolerance",
    "comment[reduction reagent]":                    "reduction_reagent",
    "comment[alkylation reagent]":                   "alkylation_reagent",
    "comment[ms2 mass analyzer]":                    "mass_analyzer",
}

#category label attached to each canonical field (used for the "agent" column in the output CSVs and for grouping in the plots)
FIELD_CATEGORY = {
    "species": "Biological", "organ": "Biological", "cell_type": "Biological",
    "cell_line": "Biological", "disease": "Biological", "sex": "Biological",
    "age": "Biological", "strain": "Biological",
    "acquisition_method": "Technical", "label": "Technical", "instrument": "Technical",
    "cleavage_agent": "Technical", "fragmentation": "Technical", "modification": "Technical",
    "precursor_mass_tolerance": "Technical", "fragment_mass_tolerance": "Technical",
    "reduction_reagent": "Technical", "alkylation_reagent": "Technical",
    "mass_analyzer": "Technical", "enrichment_method": "Technical",
    "technology_type": "Technical",
    "fractions": "ExperimentalDesign", "technical_replicates": "ExperimentalDesign",
    "replicates": "ExperimentalDesign", "factor_value": "ExperimentalDesign",
}

#LLM used as the judge model via OpenRouter
EVALUATION_MODEL      = "google/gemma-4-31b-it"
OPENROUTER_BASE_URL   = "https://openrouter.ai/api/v1"
MODEL_TEMPERATURE     = 0
#enable extended thinking mode for the judge model when supported
MODEL_ENABLE_THINKING = True

USE_LLM_JUDGE = True

LIMIT         = None

_CACHE_MODEL_SLUG = EVALUATION_MODEL.replace("/", "_").replace(" ", "_")
CACHE_DIR         = os.path.join(BASE_DIR, f".prompt_cache_{_CACHE_MODEL_SLUG}")

CACHE_ENABLED     = True

MAX_WORKERS = 4

MAX_RETRIES = 3

RETRY_DELAY = 2

#values longer than this threshold are treated as evidence sentences rather than metadata values
MAX_VALUE_LENGTH = 120

_thread_local = threading.local()

SKIP_ANNOTATION_FIELDS = {"phenotype", "ethnicity", "technology_type"}

_ALWAYS_LLM_FIELDS = {"material_type", "acquisition_method", "enrichment_method"}


_CONTEXT_SENSITIVE_FIELDS = {"cell_line", "cell_type", "organ", "material_type", "species"}

PROMPT_VERSION = "v7"

_NOT_EXTRACTED_VALUES = {"unknown", "n/a", "not available", "none", "null", "na", ""}

def _is_not_extracted(value: str) -> bool:
    return value.strip().lower() in _NOT_EXTRACTED_VALUES


_DEGENERATE_PATTERN = re.compile(r"(- a[- ]){10,}")
_DEGENERATE_UNICODE_PATTERN = re.compile(
    r"[\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff\u3000-\u9fff\uac00-\ud7af"
    r"\u1100-\u11ff\uf900-\ufaff]{3,}[- a-z0-9]{0,5}"
    r"[\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff\u3000-\u9fff\uac00-\ud7af"
    r"\u1100-\u11ff\uf900-\ufaff]{3,}"
)

def _garble_score(text: str) -> int:
    """count small-model token-corruption artifacts (stray capital S doubled words)"""
    glued    = len(re.findall(r"[a-z]S\b", text))              
    isolated = len(re.findall(r"(?:^|\s)S(?=\s)", text))       
    runs     = len(re.findall(r"\bS{2,}\b", text))             
    doubled  = len(re.findall(r"\b(\w{3,})\s+\1\b", text, re.IGNORECASE))  
    return glued + isolated + runs + doubled


def _is_degenerate_response(text: str) -> bool:
    if not text or len(text) < 100:
        return False
    if _DEGENERATE_PATTERN.search(text):
        return True
    repeated_fragments = re.findall(r"((?:- a){5,})", text)
    if len(repeated_fragments) >= 3:
        return True
    if _DEGENERATE_UNICODE_PATTERN.search(text):
        tail = text[len(text)//2:]
        if len(set(tail)) < 30 and len(tail) > 200:
            return True
    unique_ratio = len(set(text[-500:])) / max(len(text[-500:]), 1) if len(text) > 500 else 1.0
    if unique_ratio < 0.05 and len(text) > 500:
        return True
    if len(text) > 150 and _garble_score(text) >= 6:
        return True
    return False


def _sanitize_reason(text: str) -> str:
    """clean small-model token corruption so parsed output columns stay tidy"""
    if not text:
        return text
    text = text.replace("\r", "\n")
    text = re.sub(r"([a-z])S\b", r"\1", text)               
    text = re.sub(r"(?:^|(?<=\s))S(?=\s|$)", "", text)      
    text = re.sub(r"\bS{2,}\b", "", text)                  
    text = re.sub(r"\b(\w{2,})(\s+\1\b)+", r"\1", text, flags=re.IGNORECASE)  
    lines, prev_blank = [], False
    for ln in text.split("\n"):
        ln = re.sub(r"[ \t]{2,}", " ", ln).rstrip()
        blank = (ln.strip() == "")
        if blank and prev_blank:
            continue
        lines.append(ln)
        prev_blank = blank
    return "\n".join(lines).strip()


def _truncate_degenerate_tail(text: str) -> str:
    m = _DEGENERATE_PATTERN.search(text)
    if m:
        truncated = text[:m.start()].rstrip()
        if truncated:
            return truncated
    for pattern in [r"(?:- a[- ]){5,}", r"(?:same|kind|one|person|little|bouncy|ability)(?:- a){3,}"]:
        m2 = re.search(pattern, text)
        if m2:
            truncated = text[:m2.start()].rstrip()
            if truncated:
                return truncated
    return text


#known safe default values for specific fields that do not require explicit mention in the paper
SAFE_DEFAULTS = {
    "disease":              {"normal", "healthy", "no disease", "disease free", "disease-free", "none", "not applicable", "not diseased"},
    "disease_state":        {"normal", "healthy", "no disease", "disease free", "disease-free", "none", "not applicable", "not diseased"},
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

#fields where the extracted value is a reagent concentration rather than a name
CONCENTRATION_FIELDS = {"reduction_concentration", "alkylation_concentration"}


#structured text block defining every metadata field type used in evaluation prompts
_FIELD_DEFINITIONS_TEXT = """\
BIOLOGICAL / SAMPLE FIELD TYPES:
species              : Source organism (e.g. "Homo sapiens", "Mus musculus"). Common names ("human", "mouse") are equivalent to scientific names.
organ                : Tissue or organ of origin (e.g. "liver", "brain cortex", "plasma"). Equivalent to the 'tissue' pipeline field. Must refer to the tissue from which the ACTUAL MS SAMPLE was derived, not tissues mentioned in unrelated validation assays or binding experiments.
cell_type            : Primary cell type or lineage (e.g. "neurons", "fibroblasts"). Must refer to the cell type of the ACTUAL MS SAMPLE, not cell types mentioned in unrelated validation assays, transfection experiments, or binding studies.
cell_line            : Name of immortalized cell line (e.g. "HEK293T", "HeLa"). CRITICAL: must be the cell line from which the ACTUAL PROTEOMICS / MS SAMPLE was derived. Cell lines mentioned ONLY in the context of unrelated validation assays, transfection experiments, binding assays, co-immunoprecipitation controls, or in-vitro functional tests (e.g. "HEK293T cells were transfected to validate receptor binding") are NOT the MS sample source and should be marked HALLUCINATED: yes, VERDICT: low. To determine the correct cell line, identify which biological material was actually lysed, digested, and analysed by mass spectrometry.
disease              : Disease state or diagnosis (e.g. "breast cancer", "Type 2 diabetes"). "normal", "healthy", "no disease" and "disease free"/"disease-free" are all equivalent safe defaults and are CORRECT when the subjects are healthy / not part of a disease study, even if that exact phrase is not written in the text. Equivalent to the 'disease_state' pipeline field.
sex                  : Donor sex (e.g. "male", "female").
age                  : Age of the donor/animal FOR THE MS SAMPLE that was analysed (e.g. "45 years", "P30", "30", "E14.5"). A single reported value that matches a time point actually used for the mass-spec sample is COMPLETE and correct. Do NOT demand that the value enumerate every age or developmental time point mentioned anywhere in the paper -- only the age(s) of the analysed sample matter.
developmental_stage  : Developmental stage of source material (e.g. "adult", "embryonic", "early seed development"). Inferable from subject description (e.g. "adult patients" -> "adult").
ethnicity            : Donor ancestry or ethnicity (e.g. "European", "East Asian").
material_type        : Broad material class: "tissue", "cell line", "primary cells", "biofluid", "whole organism", "plasma", "serum", "organoid". Equivalent to the 'sample_source' pipeline field. Must match what was actually used FOR THE MS EXPERIMENT.
strain               : Animal or plant strain (e.g. "BALB/c", "C57BL/6J", "Nipponbare").
BMI                  : Body-Mass Index of donor (kg/m^2).
anatomic_site_tumor  : Anatomical location of the tumor, if applicable (e.g. "left lung lobe", "colon").

TECHNICAL / MS FIELD TYPES:
instrument           : Mass spectrometer make and model (e.g. "Thermo Q-Exactive Plus", "Orbitrap Fusion Lumos"). LC instruments alone are NOT this type.
cleavage_agent       : Protease used for protein digestion (e.g. "trypsin", "Lys-C"). "Trypsin/P" equals "trypsin".
label                : Isobaric, metabolic or chemical labeling method applied (e.g. "TMT", "SILAC", "iTRAQ", "dimethyl", "label-free"). "label-free" is correct ONLY when the paper describes NO isobaric labels (TMT/iTRAQ) AND NO metabolic/chemical labels (SILAC, heavy/light amino acids such as 13C/15N arginine or lysine, dimethyl). If the paper describes ANY such labeling (e.g. SILAC / heavy and light labeling), then "label-free" is INCORRECT (VERDICT: low) -- the correct value is that labeling method. Equivalent to the 'labeling' pipeline field.
fragmentation        : Fragmentation method for MS/MS (e.g. "HCD", "CID", "ETD"). Equivalent to 'fragmentation_method'.
ptm                  : Post-translational modification studied or enriched for (e.g. "phosphorylation", "ubiquitination").
reduction_reagent    : Chemical used to reduce disulfide bonds (e.g. "DTT", "TCEP", "dithiothreitol").
reduction_concentration : Concentration of the reduction reagent (e.g. "5 mM", "2.5 mM", "10 mM"). Must be a numeric quantity with a unit. The reagent name is extracted separately in the 'reduction_reagent' field, so the concentration value alone (e.g. "2.5 mM" without the reagent name) is COMPLETE and sufficient.
collision_energy     : Collision energy used in MS/MS (e.g. "normalized collision energy 25", "27 eV").
fractionation        : Offline peptide/protein fractionation method applied before LC-MS (e.g. "high-pH reverse-phase fractionation", "strong anion exchange"). Equivalent to 'fractionation_method'.
enrichment_method    : Enrichment / affinity-capture protocol applied before MS (e.g. "TiO2 phosphopeptide enrichment", "immunoprecipitation", "streptavidin pull-down"). INFERABLE from context: proximity-biotinylation / BioID / APEX / TurboID or any biotin-based labeling implies a "streptavidin pull-down" (streptavidin/avidin capture of biotinylated proteins); a phospho study implies phospho-enrichment. Do NOT mark as hallucinated just because the exact phrase is absent when the enrichment is clearly implied.
acquisition_method   : MS acquisition scheme (e.g. "DDA", "DIA", "data-dependent", "data-independent"). Must be a scheme name, NOT an instrument name. Equivalent to 'acquisition_method'.
alkylation_reagent   : Chemical used for cysteine alkylation (e.g. "iodoacetamide", "IAA", "NEM").
alkylation_concentration : Concentration of the alkylation reagent (e.g. "10 mM", "55 mM", "20 mM"). Must be a numeric quantity with a unit. The reagent name is extracted separately in the 'alkylation_reagent' field, so the concentration value alone (e.g. "10 mM" without the reagent name) is COMPLETE and sufficient.
ionization_type      : Ionization source type (e.g. "electrospray", "nano-ESI", "MALDI"). Can be inferred from instrument model (Q Exactive -> electrospray).
mass_analyzer        : Mass analyzer type used (e.g. "Orbitrap", "TOF", "quadrupole", "ion trap").
precursor_mass_tolerance : Mass tolerance window applied to PRECURSOR (MS1) ions during the database search (e.g. "4.5 ppm", "10 ppm", "0.05 Da"). This is DISTINCT from the fragment / product-ion (MS2) tolerance. A value that actually corresponds to the FRAGMENT-ion tolerance reported in the paper is WRONG for this field (VERDICT: low, CORRECT_TYPE_NAME: fragment_mass_tolerance). Papers often state both, e.g. "4.5 ppm for precursor ions and 20 ppm for fragment ions" -- only the precursor number (4.5 ppm here) is correct for this field.
fragment_mass_tolerance  : Mass tolerance window applied to FRAGMENT / product (MS2) ions during the database search (e.g. "20 ppm", "0.02 Da", "0.5 Da"). DISTINCT from the precursor (MS1) tolerance. A value that actually corresponds to the precursor tolerance is WRONG for this field (VERDICT: low, CORRECT_TYPE_NAME: precursor_mass_tolerance).
modification         : A peptide/protein modification searched, either fixed or variable, with its target residue(s), e.g. "Carbamidomethyl (C)", "Oxidation (M)", "Deamidation (NQ)", "Acetyl (K)". Judge each modification INDEPENDENTLY of the others. THE PAPER TEXT IS THE ONLY REFERENCE. A modification is CORRECT (VERDICT: high) ONLY when its name -- or an unambiguous synonym (e.g. "carbamidomethylation" == "Carbamidomethyl") -- is EXPLICITLY written in the paper text. Do NOT infer a modification from sample-preparation reagents: naming an alkylation reagent such as iodoacetamide, chloroacetamide or NEM does NOT by itself make "Carbamidomethyl (C)" / "NEM (C)" correct unless the modification name itself ALSO appears in the text. If the modification name is NOT explicitly present in the text, it is UNSUPPORTED and must be marked HALLUCINATED: yes, VERDICT: low. Set CORRECTED_VALUE to another modification ONLY if that modification's name is literally written in the paper text; otherwise CORRECTED_VALUE: NONE. Never invent or infer a replacement modification (including "Carbamidomethyl (C)") that is not literally named in the text.

EXPERIMENTAL DESIGN FIELD TYPES:
replicates                    : Number of biological replicates (e.g. "3"). "1" is correct when no replication is mentioned. Equivalent to 'number_of_biological_replicates' / 'biological_replicate'.
technical_replicates          : Number of technical replicates per sample (e.g. "2"). Equivalent to 'number_of_technical_replicates' / 'technical_replicate'.
number_of_samples             : Total count of samples processed in the study (e.g. "12").
fractions                     : Number of fractions generated per sample (e.g. "12"). "1" is correct when no fractionation occurred. Equivalent to 'number_of_fractions'.
technology_type               : Broad technology type applied (e.g. "proteomics", "phosphoproteomics").
factor_value                  : The experimental factor / variable under study, whose value mirrors an underlying characteristic (e.g. factor value[disease], factor value[genotype]). Judge it BY THE SAME RULES as that characteristic, including its safe defaults -- e.g. a disease factor of "disease free"/"healthy"/"normal" is CORRECT. A factor_value legitimately DUPLICATES the value of another field; do NOT penalise it for that, and do NOT require the factor to vary across samples (SDRF records it even for uniform studies).
experimental_design           : Study design type (e.g. "time course", "cross-sectional", "case-control", "treated vs control").
"""

#dictionary mapping each canonical field name to its full definition line
FIELD_DEFINITIONS: dict[str, str] = {}
for _line in _FIELD_DEFINITIONS_TEXT.strip().splitlines():
    _stripped = _line.strip()
    if not _stripped or _stripped.endswith(":"):
        continue
    if ":" in _stripped:
        _parts = _stripped.split(":", 1)
        FIELD_DEFINITIONS[_parts[0].strip()] = _stripped

#set of all known canonical field names in lowercase for type check lookups
_KNOWN_FIELD_TYPES_LOWER: set[str] = set(FIELD_DEFINITIONS.keys())


#full system prompt sent to the judge model on every API call
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

                  CRITICAL -- EXPERIMENTAL CONTEXT RULE:
                  Proteomics papers often describe MULTIPLE experimental
                  systems. Metadata values must refer to the biological
                  material that was ACTUALLY ANALYSED BY MASS SPECTROMETRY,
                  not to materials mentioned in unrelated contexts such as:
                  - Transfection / expression host cells for construct
                    validation (e.g. HEK293T transfected to test receptor
                    binding is NOT the MS sample)
                  - In-vitro binding assays or cell-shape assays
                  - Co-immunoprecipitation validation experiments
                  - Cell lines used only for cloning or protein production
                  A value that appears in the paper but ONLY in such an
                  unrelated context is HALLUCINATED for the purpose of
                  describing the MS experiment: HALLUCINATED: yes,
                  VERDICT: low.
                  To identify the MS sample, look for phrases like:
                  "analysed by mass spectrometry", "LC-MS/MS", "proteomics
                  experiment", "streptavidin pull-down ... analysed by
                  tandem-mass spectrometry", or the sample preparation
                  workflow that directly feeds into the MS instrument.

                  -- SAFE DEFAULTS that do NOT require explicit mention:
                     "normal"/"healthy"/"no disease"/"disease free" for disease
                     when subjects are healthy or not part of a disease study
                     (these are all equivalent -- accept regardless of exact wording);
                     "adult"/"neonatal"/etc. for developmental_stage when
                     inferable from subject description;
                     "label-free" for label/labeling ONLY when NO isobaric
                     (TMT/iTRAQ) AND NO metabolic/chemical labeling (SILAC,
                     heavy/light 13C/15N amino acids, dimethyl) is mentioned;
                     if any such labeling IS described, "label-free" is WRONG;
                     "1" for fractions or replicates when paper is silent;
                     standard material_type values inferable from context;
                     abbreviation expansions (IAA = iodoacetamide, HCD =
                     higher-energy collisional dissociation, etc.).
                  -- INFERABLE FIELDS: For material_type and acquisition_method,
                     the value may be reasonably inferable from the experimental
                     context even when not explicitly stated in the paper text.
                  -- MODIFICATIONS ARE EXPLICIT-ONLY: A modification is correct
                     ONLY when its name (or an unambiguous synonym) is EXPLICITLY
                     written in the paper text. Do NOT infer a modification from
                     sample-prep reagents: naming iodoacetamide, chloroacetamide
                     or NEM does NOT make Carbamidomethyl (C) / NEM (C) correct
                     unless the modification name itself also appears in the text.
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
         Also LOW when the value is from an UNRELATED experimental
         context (e.g. a cell line used only for transfection/validation,
         not for the MS experiment).
MEDIUM-- type correct, present, valid, but the FULL SET of
         all_extracted_values still does not cover the complete picture.
HIGH  -- correct type, present/inferable, factually accurate and
         the full set of all_extracted_values is exhaustive (or this
         field only has one correct value).

=================================================================
FIELD-SPECIFIC RULES (apply on top of the four checks above)
=================================================================
CELL LINE / CELL TYPE / ORGAN (EXPERIMENTAL CONTEXT):
   These fields describe the biological source of the MS SAMPLE.
   Papers frequently mention cell lines (e.g. HEK293T, HeLa, COS-7)
   for UNRELATED purposes such as transient transfection to validate
   constructs, binding assays, cell-shape assays, or reporter assays.
   If a cell line appears ONLY in such a validation/assay context and
   was NOT the material that was lysed and analysed by mass spectrometry,
   it is WRONG for the cell_line field: HALLUCINATED: yes, VERDICT: low.
   Carefully trace which biological material underwent the proteomics
   workflow (lysis, digestion, LC-MS/MS).

MASS TOLERANCE (precursor_mass_tolerance vs fragment_mass_tolerance):
   These are two DIFFERENT fields. Papers commonly report both, e.g.
   "4.5 ppm for precursor ions and 20 ppm for fragment ions". If the
   candidate_value for precursor_mass_tolerance is actually the paper's
   FRAGMENT tolerance (e.g. "20 ppm" here), it is WRONG:
   VALUE_CORRECT: no, VERDICT: low, CORRECT_TYPE_NAME: fragment_mass_tolerance.
   The mirror rule applies to fragment_mass_tolerance. Match the number to
   the correct ion type in the paper before accepting it.

LABEL:
   "label-free" is correct ONLY when no isobaric/metabolic/chemical labeling
   is described. If the paper describes SILAC, heavy/light amino-acid labeling
   (13C/15N arginine/lysine), dimethyl, TMT or iTRAQ, then a candidate of
   "label-free"/"label free sample" is WRONG (VERDICT: low); the correct value
   is the labeling method actually used (e.g. "SILAC").

MODIFICATION:
   Judge each modification value INDEPENDENTLY. THE PAPER TEXT IS THE ONLY
   REFERENCE. A modification is CORRECT (VERDICT: high) ONLY when its name --
   or an unambiguous synonym (e.g. "carbamidomethylation" == "Carbamidomethyl")
   -- is EXPLICITLY written in the paper text.
   Do NOT infer a modification from sample-preparation reagents: naming an
   alkylation reagent such as iodoacetamide, chloroacetamide or NEM does NOT by
   itself make "Carbamidomethyl (C)" / "NEM (C)" correct unless the modification
   name itself ALSO appears in the text.
   If the modification name is NOT explicitly present in the text, it is
   UNSUPPORTED: HALLUCINATED: yes, VERDICT: low. Set CORRECTED_VALUE to another
   modification ONLY if that modification's name is literally written in the
   text; otherwise CORRECTED_VALUE: NONE. Never invent or infer "Carbamidomethyl
   (C)" (or any modification) that is not literally named in the text.

ENRICHMENT_METHOD:
   Inferable from context -- proximity biotinylation / BioID / APEX / TurboID
   imply "streptavidin pull-down". Do not mark as hallucinated when the
   enrichment is clearly implied even if the literal phrase is absent.

AGE:
   The value is the age of the source animal/donor. If the numeric value
   matches ANY age or developmental time point reported for the animals used in
   the study (e.g. "30" matches "P30 mice" / postnatal day 30), it is CORRECT
   and COMPLETE -- the paper does not need to restate it specifically for the MS
   sample. Do NOT set CORRECTED_VALUE to a list of every age or developmental
   stage mentioned in the paper; a single matching value is sufficient.

FACTOR_VALUE:
   A factor_value mirrors some characteristic (disease, genotype, treatment,
   cell type, time point, ...). Judge it BY THE SAME RULES as that underlying
   characteristic, including that field's safe defaults -- e.g. a disease factor
   of "disease free"/"healthy"/"normal" is CORRECT (healthy default). Do NOT
   require that the factor actually varies across samples: SDRF records the
   factor value even for a uniform study, so a single/duplicated value is fine.
   Never mark it wrong merely for duplicating another annotation type or for not
   being a "real" contrast.

=================================================================
OUTPUT FORMAT for "verify"
=================================================================
TYPE CHECK:        <one sentence>
SOURCE CHECK:      <one sentence -- MUST state whether the value comes from the
                    MS experiment context or from an unrelated assay>
TRUTH CHECK:       <one sentence>
COMPLETENESS CHECK:<one sentence -- assess the FULL SET, not just this value>
TYPE_CORRECT:      yes | no
CORRECT_TYPE_NAME: <correct field name if TYPE_CORRECT is no, else NONE>
VALUE_CORRECT:     yes | no
VALUE_COMPLETE:    yes | no
HALLUCINATED:      yes | no
VERDICT:           high | medium | low
CORRECTED_VALUE:   <ALWAYS provide the correct value(s) when VERDICT is
                    medium OR low, but ONLY if the correct value is
                    explicitly stated in the paper text.
                    For medium: the complete/correct full set of values
                    from the paper.
                    For low: the factually correct value from the paper
                    that should replace this wrong/hallucinated extraction.
                    For type mismatches: the correct value for the CORRECT
                    field if identifiable in the text, or NONE.
                    CRITICAL: NEVER invent, assume, or suggest a corrected
                    value that does not appear in the paper text. If the
                    paper does not mention a correct replacement, output NONE.
                    When VERDICT is high: NONE>

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


#GEval criteria string used when judging whether an extracted annotation is correct
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
    "    CRITICAL -- EXPERIMENTAL CONTEXT RULE: For cell_line, cell_type, organ, "
    "    and similar biological fields, the value MUST describe the material that "
    "    was ACTUALLY ANALYSED by mass spectrometry. Values that appear in the "
    "    paper ONLY in unrelated contexts (transfection hosts, binding assay cell "
    "    lines, validation experiments) are HALLUCINATED for the MS experiment. "
    "(3) TRUTH: is it factually correct per the paper and field definition? "
    "(4) COMPLETENESS: apply SIBLING-VALUE RULE first -- assess the full set. "
    "    EXCEPTION: For reduction_concentration and alkylation_concentration, "
    "    a numeric quantity + unit WITHOUT the reagent name IS complete. "
    "HIGH = correct type + present/inferable + factually valid + full set complete. "
    "MEDIUM = correct type + present + valid, but full set still insufficient. "
    "LOW = hallucinated, type mismatch, factually wrong, OR from wrong experimental context. "
    "CORRECTED_VALUE is MANDATORY when VERDICT is medium OR low: "
    "provide the factually correct value(s) that should have been extracted "
    "based on what the paper actually says. For medium: the complete set. "
    "For low: the correct replacement value from the paper. "
    "CRITICAL: CORRECTED_VALUE must ONLY contain values that are explicitly "
    "present in or directly stated by the paper text. NEVER invent, assume, "
    "or suggest values that do not appear in the text -- if the paper does not "
    "mention a correct replacement, set CORRECTED_VALUE: NONE. "
    "Only output CORRECTED_VALUE: NONE when VERDICT is high."
)

#step by step instructions for GEval when evaluating an extracted annotation
_ANNOTATION_GEVAL_STEPS = [
    "TYPE CHECK: determine the fundamental nature of the value. "
    "If it belongs to a completely different field, set TYPE_CORRECT: no -> VERDICT: low. "
    "If it is the right category but wrong specific entity, TYPE_CORRECT: yes, VALUE_CORRECT: no.",

    "SOURCE CHECK: confirm the candidate value is present in or inferable from the paper. "
    "Safe defaults do NOT require explicit mention. "
    "For material_type and acquisition_method, reasonable inference from context is allowed. "
    "CRITICAL -- EXPERIMENTAL CONTEXT: for cell_line, cell_type, organ, and material_type, "
    "verify the value refers to the ACTUAL MS/proteomics sample, NOT to cell lines or "
    "materials mentioned only in unrelated validation assays, transfection experiments, "
    "binding assays, or functional tests. A cell line used only for transfection to test "
    "receptor binding is NOT the MS sample source -- mark it HALLUCINATED: yes, VERDICT: low. "
    "For modifications: a modification is correct ONLY if its name (or an unambiguous "
    "synonym) is EXPLICITLY written in the paper text. Do NOT infer a modification from "
    "sample-prep reagents -- naming iodoacetamide/chloroacetamide/NEM does NOT make "
    "Carbamidomethyl (C)/NEM (C) correct unless the modification name itself is in the text. "
    "If the modification name is absent from the text: HALLUCINATED: yes -> VERDICT: low, "
    "and do NOT suggest it as a CORRECTED_VALUE. "
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
    "CORRECTED_VALUE: MANDATORY when verdict is medium or low -- provide the "
    "factually correct value(s) from the paper. For medium: the complete set "
    "of values. For low: the correct replacement value that should have been "
    "extracted. CRITICAL: ONLY use values explicitly stated in the paper text. "
    "NEVER invent or assume a corrected value that does not appear in the text. "
    "If the paper does not mention a correct replacement, output CORRECTED_VALUE: NONE. "
    "Only NONE when verdict is high.",
]

#GEval criteria string used to detect fields that were present in the paper but not extracted
_MISSED_GEVAL_CRITERIA = (
    "Determine whether the paper text contains information for the specified "
    "metadata field. Output VERDICT: high | medium | low. "
    "(high = clearly present; medium = inferable; low = absent)"
)
#step by step instructions for GEval when checking for missed fields
_MISSED_GEVAL_STEPS = [
    "Search the source text for any mention of the metadata field.",
    "Determine if a valid value is clearly present, inferable, or absent.",
    "Write SEARCH, FINDING and VERDICT: high | medium | low.",
]


class DiskResponseCache:

    def __init__(self, cache_dir: str, enabled: bool = True):
        """initialise the cache creating the directory if enabled"""
        self._dir     = Path(cache_dir)
        self._enabled = enabled
        self._hits    = 0
        self._misses  = 0
        self._lock    = threading.Lock()
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _make_key(paper_id: str, task: str, field_name: str, primary_value: str) -> str:
        """compute a deterministic SHA 256 hex key for a given evaluation request"""
        blob = (f"{EVALUATION_MODEL}|{PROMPT_VERSION}|{paper_id}|{task}|"
                f"{field_name.lower()}|{primary_value}")
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def get(self, paper_id, task, field_name, primary_value):
        """return the cached response string or None if no cache entry exists"""
        if not self._enabled:
            return None
        key  = self._make_key(paper_id, task, field_name, primary_value)
        path = self._dir / f"{key}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                response = data.get("response")
                if response and _is_degenerate_response(response):
                    print(f"  [cache evict] removing cached degenerate response: {key[:16]}...")
                    try:
                        path.unlink()
                    except OSError:
                        pass
                    with self._lock:
                        self._misses += 1
                    return None
                with self._lock:
                    self._hits += 1
                return response
            except (json.JSONDecodeError, OSError):
                return None
        with self._lock:
            self._misses += 1
        return None

    def put(self, paper_id, task, field_name, primary_value, response):
        """write a response to disk under the computed cache key"""
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
        """return a dictionary summarising cache usage for the current session"""
        n_files = sum(1 for _ in self._dir.glob("*.json")) if self._enabled else 0
        total   = self._hits + self._misses
        return {"enabled": self._enabled, "cache_dir": str(self._dir),
            "cached_responses_on_disk": n_files, "session_hits": self._hits,
            "session_misses": self._misses,
            "session_hit_rate": f"{self._hits/total*100:.1f}%" if total > 0 else "n/a"}


def _build_messages(paper_text: str, entity_context: dict) -> list[dict]:
    """construct the four turn message list sent to the judge model"""
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
                "field values against it using the definitions and rules in my instructions. "
                "I will pay special attention to distinguishing the actual MS/proteomics "
                "sample from cell lines or materials used only in validation assays."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(entity_context, indent=2, ensure_ascii=False),
        },
    ]


def _build_openrouter_client() -> openai.OpenAI:
    """create and return an OpenAI client configured to use the OpenRouter endpoint"""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENROUTER_API_KEY environment variable is not set.")
    return openai.OpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL)


def _extract_text_content(raw_message) -> str:
    """extract all plain text from an OpenAI compatible response message object"""
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
        """initialise counters cache and shared state"""
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
        """store the current paper text and ID so all subsequent calls use it"""
        self._paper_text       = source_text
        self._current_paper_id = paper_id

    def set_entity_context(self, context: dict) -> None:
        """write per call evaluation context into thread local storage"""
        _thread_local.current_context = context

    def load_model(self) -> openai.OpenAI:
        """lazily initialise and return the OpenRouter API client"""
        if self._client is None:
            self._client = _build_openrouter_client()
        return self._client

    def _generate_single(self, paper_text: str, paper_id: str, context: dict) -> str:
        """execute one judge call with retry logic and disk cache lookup """
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
                if content and _is_degenerate_response(content):
                    print(f"  [DEGENERATE RESPONSE] attempt {attempt}/{MAX_RETRIES} "
                          f"-- repetitive/garbled output detected, retrying...")
                    content = ""
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY * attempt)
                    continue
                if content:
                    break
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
            except Exception as exc:
                print(f"  [API ERROR] {type(exc).__name__}: {exc} "
                      f"(attempt {attempt}/{MAX_RETRIES})")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)

        if content and not _is_degenerate_response(content):
            content = _sanitize_reason(content)
            self._response_cache.put(paper_id, task, field_name, primary_val, content)
        elif content:
            print(f"  [DEGENERATE] not caching degenerate response")
            content = ""
        print(f"  [response] {content[:200]}...")
        return content

    def generate(self, prompt: str, schema=None):
        """generate a judge response for the current thread local context"""
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
        return self.generate(prompt, schema=schema)

    def get_model_name(self) -> str:
        """return the model identifier string used in API calls"""
        return self._model_name

    def get_cache_stats(self) -> dict:
        """return a combined summary of disk cache and call count statistics"""
        stats = self._response_cache.stats()
        stats["total_generate_calls"] = self._call_count
        stats["actual_api_calls"]     = self._api_call_count
        stats["disk_cache_hits"]      = self._disk_hit_count
        if self._call_count > 0:
            stats["overall_disk_hit_rate"] = (
                f"{self._disk_hit_count / self._call_count * 100:.1f}%")
        return stats

_judge_model: Gemma4Judge | None = None

def _get_judge_model() -> Gemma4Judge:
    """return the shared Gemma4Judge singleton, creating it on first call"""
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
    """return a thread local GEval metric for detecting missed fields"""
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
    """extract the correct type yes or no flag from a judge response string returns None when the flag is not present in the response"""
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
    """parse a named yes or no flag from a structured judge response string"""
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
    """extract the CORRECTED_VALUE from a judge response with prose fallbacks"""
    m = re.search(r"CORRECTED_VALUE\s*:\s*(.+?)(?:\n|$)", reason, re.IGNORECASE)
    if m:
        val = m.group(1).strip().strip("'\" `")
        if val and val.upper() not in ("NONE", "N/A", "NULL", "SAME"):
            return _clean_corrected_value(val)
    fallback_patterns = [
        r'(?:correct\s+value\s+(?:is|should\s+be)\s+)["\']([^"\']{2,80})["\']',
        r'(?:should\s+(?:have\s+been|be)\s+)["\']([^"\']{2,80})["\']',
        r'(?:paper|study)\s+(?:describes?|uses?|employs?|reports?)\s+(?:a\s+)?(?:specifically\s+)?["\']([^"\']{3,60})["\']',
        r'correct\s+(?:label|labeling|value)\s+(?:is|would\s+be)\s+["\']?([^"\'",\n]{2,60})["\']?',
    ]
    check_blocks = []
    for block_name in ["TRUTH CHECK", "SOURCE CHECK", "COMPLETENESS CHECK"]:
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

    #additional fallback: for label field, try to extract the labeling method mentioned as the correct one in the judges reasoning
    label_patterns = [
        r'(?:correct\s+value\s+is\s+(?:the\s+)?(?:labeling\s+method\s+)?)'
        r'(?:actually\s+used[,:]?\s+)?["\']?(\w[\w\s/-]{1,40})["\']?',
        r'(?:uses?|describes?|employs?)\s+(?:metabolic\s+labeling\s+\()?'
        r'(SILAC|TMT\d*|iTRAQ\d*|dimethyl)(?:\))?',
        r'(?:labeling\s+method\s+(?:actually\s+)?used\s+(?:is|was)\s+)'
        r'["\']?(\w[\w\s/-]{1,40})["\']?',
    ]
    for pattern in label_patterns:
        fm = re.search(pattern, reason, re.IGNORECASE)
        if fm:
            val = fm.group(1).strip().strip("'\" `.,;()")
            if val and len(val) >= 2 and val.upper() not in (
                "NONE", "N/A", "NULL", "LABEL", "LABEL FREE", "LABEL-FREE",
                "THE", "IS", "WAS", "NO", "YES",
            ):
                print(f"  [corrected value fallback-label] Extracted '{val}' from prose")
                return _clean_corrected_value(val)
    return None


def _is_concentration_only(field_name: str, extracted_value: str) -> bool:
    """return True when a concentration field value contains only a numeric quantity and unit"""
    if field_name.lower() not in CONCENTRATION_FIELDS:
        return False
    conc_pattern = re.compile(
        r"^\s*\d+(?:\.\d+)?\s*(?:m[Mm]|[µu]M|M|mol/[Ll]|mmol/[Ll]|%)\s*$")
    return bool(conc_pattern.match(extracted_value.strip()))


def _norm(s: str) -> str:
    """normalise a string for deduplication: lowercase, collapse whitespace, unify punctuation"""
    if not s:
        return ""
    s = s.replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    s = s.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", s.strip().lower())


def _is_evidence_sentence(s: str) -> bool:
    """return True when a string exceeds the maximum value length threshold"""
    return len(s) > MAX_VALUE_LENGTH


def _flatten_extraction_values(val) -> list[str]:
    """extract real metadata values from an alternating value evidence list"""
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


#generic words inside a modification string that are NOT the modifications own name and must not be used to claim the modification is present in the text.
_MOD_NAME_STOPWORDS = {
    "acid", "derivative", "label", "labeled", "labelled", "residue", "residues",
    "modification", "modified", "protein", "peptide", "terminal", "terminus",
    "fixed", "variable", "cysteine", "methionine", "site", "group", "heavy", "light",
}


def _modification_named_in_text(mod_value: str, paper_text: str) -> bool:
    """True only when the modification's OWN name (not a reagent) is explicitly in the text & modifications are judged against the paper text alone: a reagent such as
    iodoacetamide does NOT count as the modification 'Carbamidomethyl' being present. matching is stem-based (first 6 chars) so 'Carbamidomethyl' matches 'carbamidomethylation' and 'Deamidated' matches 'deamidation'"""
    if not mod_value or not paper_text:
        return False
    core = re.sub(r"\([^)]*\)", " ", mod_value)          
    core = re.sub(r"[^a-zA-Z]+", " ", core).lower()
    tokens = [t for t in core.split() if len(t) >= 5 and t not in _MOD_NAME_STOPWORDS]
    if not tokens:
        return False
    pl = paper_text.lower()
    for t in tokens:
        stem = t[:6] if len(t) > 6 else t
        if stem in pl:
            return True
    return False


def _run_geval_semantic(field_name: str,
                        extracted_value: str,
                        all_values_for_field: list[str]) -> dict:
    """judge one extracted metadata value using the GEval annotation metric"""
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
        "CORRECTED_VALUE is MANDATORY when VERDICT is medium or low: "
        "provide the factually correct value(s) from the paper that should have "
        "been extracted. For medium: the complete set of values the field should "
        "have. For low: the correct replacement value based on the paper. "
        "CRITICAL: CORRECTED_VALUE must ONLY contain values explicitly present "
        "in the paper text. NEVER invent or assume values that the paper does "
        "not state -- if no correct replacement exists in the text, set "
        "CORRECTED_VALUE: NONE. "
        "Only output CORRECTED_VALUE: NONE when VERDICT is high. "
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

    fn = field_name.lower()
    if fn in _CONTEXT_SENSITIVE_FIELDS:
        expected_str += (
            "CRITICAL -- EXPERIMENTAL CONTEXT: this field describes the biological "
            "source of the ACTUAL MS/proteomics sample. Papers often mention cell lines "
            "(e.g. HEK293T, HeLa, COS-7) for UNRELATED purposes such as transient "
            "transfection to validate constructs, binding assays, cell-shape assays, or "
            "reporter assays. If the candidate value (e.g. a cell line name) appears in "
            "the paper ONLY in such an unrelated validation/assay context and was NOT the "
            "material that was lysed, digested, and analysed by mass spectrometry, then "
            "it is WRONG: HALLUCINATED: yes, VERDICT: low. Carefully trace which biological "
            "material actually underwent the proteomics workflow (lysis, digestion, LC-MS/MS). "
        )

    if fn in ("precursor_mass_tolerance", "fragment_mass_tolerance"):
        other = ("fragment_mass_tolerance" if fn == "precursor_mass_tolerance"
                 else "precursor_mass_tolerance")
        ion   = "precursor (MS1)" if fn == "precursor_mass_tolerance" else "fragment (MS2)"
        expected_str += (
            f"IMPORTANT: this is the {ion} mass tolerance. Papers often report BOTH a "
            f"precursor and a fragment tolerance. Match the candidate number to the "
            f"correct ion type in the paper. If the value is actually the OTHER ion "
            f"type's tolerance, it is WRONG: VALUE_CORRECT: no, VERDICT: low, "
            f"CORRECT_TYPE_NAME: {other}. "
        )
    if fn in ("label", "labeling"):
        expected_str += (
            "IMPORTANT: 'label-free'/'label free sample' is correct ONLY when NO "
            "isobaric (TMT/iTRAQ) and NO metabolic/chemical labeling (SILAC, heavy/light "
            "13C/15N amino acids, dimethyl) is described. If the paper describes such "
            "labeling, 'label-free' is WRONG (VERDICT: low) and the correct value is the "
            "labeling method used. When verdict is low, you MUST set CORRECTED_VALUE to "
            "the actual labeling method described in the paper (e.g. 'SILAC', 'TMT', etc.). "
        )
    if fn == "modification":
        expected_str += (
            "IMPORTANT: judge THIS modification independently of its siblings. "
            "The paper text is the ONLY reference. A modification is CORRECT "
            "(VERDICT: high) ONLY when its name -- or an unambiguous synonym "
            "(e.g. 'carbamidomethylation' == 'Carbamidomethyl') -- is EXPLICITLY "
            "written in the paper text. Do NOT infer a modification from sample-prep "
            "reagents: naming iodoacetamide, chloroacetamide or NEM does NOT make "
            "'Carbamidomethyl (C)' / 'NEM (C)' correct unless the modification name "
            "itself also appears in the text. If the modification name is NOT explicitly "
            "in the text, it is UNSUPPORTED: HALLUCINATED: yes, VERDICT: low. "
            "Set CORRECTED_VALUE to another modification ONLY if that modification's name "
            "is literally written in the paper text; otherwise CORRECTED_VALUE: NONE. "
            "Never invent or infer 'Carbamidomethyl (C)' (or any modification) that is "
            "not literally named in the text. "
        )
    if fn == "age":
        expected_str += (
            "IMPORTANT: if the value matches ANY age / developmental time point reported for "
            "the animals in the study (e.g. '30' == P30 mice), it is CORRECT and COMPLETE -- "
            "the paper need not restate it for the MS sample. Do NOT set CORRECTED_VALUE to a "
            "list of every age/stage mentioned in the paper; a single matching value suffices. "
        )
    if fn == "factor_value":
        expected_str += (
            "IMPORTANT: judge this factor_value by the SAME rules as the characteristic it "
            "mirrors, including that field's safe defaults (e.g. a disease factor of "
            "'disease free'/'healthy'/'normal' is CORRECT). It may duplicate another field's "
            "value and need not vary across samples -- do NOT penalise it for either. "
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

    if not reason or _is_degenerate_response(reason):
        if reason and _is_degenerate_response(reason):
            truncated = _truncate_degenerate_tail(reason)
            verdict_in_truncated = re.search(r"VERDICT:\s*(high|medium|low)", truncated, re.IGNORECASE)
            if verdict_in_truncated:
                print(f"  [DEGENERATE TRUNCATION] salvaged response up to degenerate tail")
                reason = truncated
            else:
                print(f"  [DEGENERATE RESPONSE] replacing garbled output with safe fallback")
                reason = (
                    "TYPE CHECK: Unable to evaluate (degenerate model output).\n"
                    "SOURCE CHECK: N/A\n"
                    "TRUTH CHECK: N/A\nCOMPLETENESS CHECK: N/A\n"
                    "TYPE_CORRECT: yes\nCORRECT_TYPE_NAME: NONE\n"
                    "VALUE_CORRECT: no\nVALUE_COMPLETE: no\n"
                    "HALLUCINATED: no\nVERDICT: low\nCORRECTED_VALUE: NONE"
                )
        else:
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

    #post processing override: concentration values without the reagent name are still complete
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

    corrected_value = None
    if verdict in ("medium", "low"):
        corrected_value = _parse_corrected_value(reason)
        if corrected_value and (_is_degenerate_response(corrected_value)
                                or re.search(r"(- a[- ]){3,}", corrected_value)
                                or len(corrected_value) > 200):
            print(f"  [corrected value rejected] garbled or too long: '{corrected_value[:60]}...'")
            corrected_value = None


    if fn == "modification":
        paper_text = _get_judge_model()._paper_text
        if not _modification_named_in_text(extracted_value, paper_text):
            if verdict in ("high", "medium") or value_correct or not is_hallucinated:
                print(f"  [modification guard] '{extracted_value[:40]}' not named in text "
                      f"-> forcing hallucinated/low")
            verdict         = "low"
            value_correct   = False
            value_complete  = False
            is_hallucinated = True
        if corrected_value and not _modification_named_in_text(corrected_value, paper_text):
            print(f"  [modification guard] dropping corrected_value "
                  f"'{corrected_value[:40]}' (not named in text)")
            corrected_value = None

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


def _sdrf_column_to_field(header: str) -> str | None:
    h = header.strip().lower()
    if h in SDRF_COLUMN_MAP:
        return SDRF_COLUMN_MAP[h]
    if h.startswith("factor value["):
        return "factor_value"
    return None


def _parse_ontology_term(value: str) -> str:
    """return the human readable name (NT=) from an SDRF ontology-encoded value"""
    if "NT=" not in value:
        return value.strip()
    parts = {}
    for chunk in value.split(";"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip().upper()] = v.strip()
    name = parts.get("NT", value).strip()
    target = parts.get("TA", "").strip()
    if target:
        return f"{name} ({target})"
    return name


def _parse_sdrf_value(field: str, raw: str) -> list[str]:
    """normalise one raw SDRF cell into a list of clean canonical values"""
    if raw is None:
        return []
    s = raw.strip()
    if _is_not_extracted(s):
        return []
    #sdrf label values are written as "label free sample" / "TMT6plex sample" etc
    if field in ("label", "labeling"):
        s = re.sub(r"\s+sample$", "", s, flags=re.IGNORECASE).strip()
        return [s] if s and not _is_not_extracted(s) else []
    #ontology encoded fields keep only the readable term (+ target residue)
    if "NT=" in s:
        s = _parse_ontology_term(s)
    return [s] if s and not _is_not_extracted(s) else []


def load_sdrf(pxd_root: str, pxd_id: str) -> dict[str, list[str]]:
    """load one dataset's SDRF file into {canonical_field: [unique values]}"""
    import csv as _csv
    path = os.path.join(pxd_root, f"{pxd_id}{SDRF_SUFFIX}")
    if not os.path.isfile(path):
        print(f"    WARNING: SDRF not found: {path}")
        return {}

    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            rows = list(_csv.reader(f, delimiter="\t"))
    except Exception as e:
        print(f"    WARNING: could not read SDRF {path}: {e}")
        return {}

    if len(rows) < 2:
        print(f"    WARNING: SDRF has no data rows: {path}")
        return {}

    header = rows[0]
    data_rows = [r for r in rows[1:] if any(c.strip() for c in r)]
    print(f"    loaded SDRF: {os.path.basename(path)}  "
          f"({len(data_rows)} sample rows, {len(header)} columns)")

    col_fields = [_sdrf_column_to_field(h) for h in header]
    ignored = sorted({header[i].strip() for i, cf in enumerate(col_fields)
                      if cf is None and header[i].strip()})
    if ignored:
        print(f"    SDRF columns ignored (ids/bookkeeping): {ignored}")

    parsed: dict[str, list[str]] = {}
    seen:   dict[str, set[str]]  = {}
    for row in data_rows:
        for i, cf in enumerate(col_fields):
            if cf is None or i >= len(row):
                continue
            for v in _parse_sdrf_value(cf, row[i]):
                bucket = parsed.setdefault(cf, [])
                seen_set = seen.setdefault(cf, set())
                key = _norm(v)
                if key and key not in seen_set:
                    seen_set.add(key)
                    bucket.append(v)

    for field, values in parsed.items():
        if len(values) > 1:
            print(f"    [{field}]: {len(values)} distinct value(s): {values}")
    return parsed


#column names for the main annotation review CSV
_REVIEW_CSV_FIELDS = [
    "paper_id", "agent", "annotation_type", "extracted_value",
    "all_values_for_field",
    "verdict", "type_mismatch", "correct_type",
    "value_correct", "value_complete", "hallucination",
    "issue_summary", "corrected_value",
]

#column names for the per paper statistics CSV
_STATS_CSV_FIELDS = [
    "paper_id", "total_extracted",
    "judge_n_correct", "judge_n_hallucinated", "judge_n_mismatch",
    "judge_n_wrong", "judge_n_incomplete", "judge_n_corrected",
    "judge_accuracy",
]

#column names for the field coverage CSV
_COVERAGE_CSV_FIELDS = [
    "paper_id", "agent", "pipeline_field", "mapped_field",
    "extracted_value", "was_extracted",
]


class _IncrementalCSV:

    def __init__(self, path: str, fieldnames: list[str]):
        import csv as _csv
        self._fh     = open(path, "w", newline="", encoding="utf-8")
        self._writer = _csv.DictWriter(self._fh, fieldnames=fieldnames,
                                       quoting=_csv.QUOTE_ALL, extrasaction="ignore")
        self._writer.writeheader()
        self._fh.flush()

    def append_rows(self, rows: list[dict]) -> None:
        for row in rows:
            self._writer.writerow(row)
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _compute_single_paper_stats(paper_id: str, eval_rows: list[dict]) -> dict:
    """compute quality category counts and accuracy for one papers evaluation rows"""
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
    """judge all extracted values for one paper using a two pass evaluation strategy"""
    _get_judge_model().set_paper_context(source_text, paper_id=paper_id)

    #build the raw (unfiltered) map of all values per field before any quality filtering
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

    #build a clean sibling map that excludes values judged as low quality in pass 1
    clean_field_values: dict[str, list[str]] = {}
    for idx, row in enumerate(eval_rows):
        r = pass1_results.get(idx, {})
        field = row["annotation_type"]
        clean_field_values.setdefault(field, [])
        if not _is_bad_value(r):
            if row["extracted_value"] not in clean_field_values[field]:
                clean_field_values[field].append(row["extracted_value"])

    #log any fields where bad values were removed from the sibling context
    for field in raw_field_values:
        raw_set   = set(raw_field_values[field])
        clean_set = set(clean_field_values.get(field, []))
        pruned    = raw_set - clean_set
        if pruned:
            print(f"    [sibling prune] {field}: removed bad values {pruned} "
                  f"from sibling context")

    #stamp each row with its clean sibling list for the CSV output column
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


def _extract_text_from_json_obj(obj) -> str:
    parts: list[str] = []
    if isinstance(obj, dict):
        for v in obj.values():
            parts.append(_extract_text_from_json_obj(v))
    elif isinstance(obj, list):
        for v in obj:
            parts.append(_extract_text_from_json_obj(v))
    elif isinstance(obj, str):
        parts.append(obj)
    else:
        parts.append(str(obj))
    return "\n".join(p for p in parts if p)


def _read_text_file(path: str) -> str:
    """read a manuscript file that may be plain text or JSON"""
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    is_json = path.lower().endswith(".json") or raw[:1] in ("{", "[")
    if is_json:
        try:
            obj = json.loads(raw)
            text = _extract_text_from_json_obj(obj).strip()
            if text:
                return text
        except (json.JSONDecodeError, ValueError):
            pass
    return raw


def _extract_sections_or_full(full_text: str, label: str) -> str:
    kept_parts = []
    for section in ["TITLE", "ABSTRACT", "METHODS"]:
        pattern = rf"===\s*{section}\s*===(.*?)(?===\s*[A-Z]|\Z)"
        match   = re.search(pattern, full_text, re.DOTALL | re.IGNORECASE)
        if match:
            kept_parts.append(f"=== {section} ===\n{match.group(1).strip()}")
    if kept_parts:
        result = "\n\n".join(kept_parts)
        print(f"    {label}: {len(full_text):,} chars total, "
              f"using {len(result):,} chars (title and abstract and methods)")
        return result
    print(f"    {label}: {len(full_text):,} chars (full text, no sections found)")
    return full_text


def load_manuscript_from_pmc_cache(pxd_id: str, pmc_cache_path: str) -> str:
    cache_path = Path(pmc_cache_path)
    if cache_path.is_dir():
        for candidate in ["pmc_cache.json", "cache.json"]:
            p = cache_path / candidate
            if p.exists():
                cache_path = p
                break
        else:
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

    full_text = str(pmc_entry.get("full_text", "")).strip()
    if not full_text:
        print(f"    WARNING: empty full_text in pmc_cache for {pxd_id}")
        return ""

    return _extract_sections_or_full(full_text, f"PMC cache [{pxd_id}]")


def load_manuscript(pxd_id: str) -> str:
    base = os.path.join(TEXT_FILES_DIR, pxd_id)
    candidates: list[str] = []

    if os.path.isfile(base):
        candidates.append(base)
    for ext in (".txt", ".json", ".md", ".text"):
        candidates.append(base + ext)
    candidates += [
        os.path.join(base, "manuscript.txt"),
        os.path.join(base, f"{pxd_id}.txt"),
        os.path.join(base, f"{pxd_id}_PubText.txt"),
        os.path.join(base, f"{pxd_id}_PubText.json"),
        os.path.join(base, f"{pxd_id}.json"),
    ]
    if os.path.isdir(base):
        for f in sorted(os.listdir(base)):
            if f.lower().endswith((".txt", ".json", ".md", ".text")):
                candidates.append(os.path.join(base, f))

    path = next((c for c in candidates if os.path.isfile(c)), None)
    if path is None:
        print(f"    WARNING: manuscript not found for {pxd_id} under {base}")
        return ""

    try:
        full_text = _read_text_file(path)
    except Exception as e:
        print(f"    WARNING: could not read manuscript {path}: {e}")
        return ""

    if not full_text:
        print(f"    WARNING: manuscript is empty: {path}")
        return ""

    return _extract_sections_or_full(full_text, f"Manuscript ({os.path.basename(path)})")


def _evaluate_one_pxd(pxd_id: str, pxd_root: str, source_text: str, out_dir: str):
    review_path   = os.path.join(out_dir, "llm_judge_annotation_review.csv")
    stats_path    = os.path.join(out_dir, "llm_judge_per_paper.csv")
    coverage_path = os.path.join(out_dir, "llm_judge_coverage.csv")
    json_out_dir  = os.path.join(out_dir, "json_outputs")
    os.makedirs(json_out_dir, exist_ok=True)

    predicted = load_sdrf(pxd_root, pxd_id)
    if not predicted:
        print(f"    SKIP: no SDRF metadata found for {pxd_id}.")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    eval_fields = [f for f in predicted if f.lower() not in SKIP_ANNOTATION_FIELDS]
    eval_fields.sort(key=lambda f: (FIELD_CATEGORY.get(f, "Other"), f))

    coverage_rows = []
    for field in eval_fields:
        values = predicted.get(field, [])
        coverage_rows.append({
            "paper_id": pxd_id,
            "agent": FIELD_CATEGORY.get(field, "Other"),
            "pipeline_field": field,
            "mapped_field": field,
            "extracted_value": " | ".join(values) if values else "",
            "was_extracted": bool(values),
        })

    seen_eval = set()
    eval_rows = []
    n_raw = 0
    for field in eval_fields:
        for v in predicted.get(field, []):
            n_raw += 1
            if _is_not_extracted(v):
                continue
            dedup_key = (field, _norm(v))
            if dedup_key in seen_eval:
                continue
            seen_eval.add(dedup_key)
            eval_rows.append({
                "paper_id": pxd_id,
                "agent": FIELD_CATEGORY.get(field, "Other"),
                "annotation_type": field,
                "extracted_value": v,
                "all_values_for_field": "",
                "verdict": None,
                "type_mismatch": None,
                "correct_type": None,
                "value_correct": None,
                "value_complete": None,
                "hallucination": None,
                "issue_summary": "",
                "corrected_value": None,
            })

    print(f"    Evaluation rows: {len(eval_rows)} (deduplicated from {n_raw} value occurrences)")
    if USE_LLM_JUDGE and eval_rows:
        eval_rows = evaluate_paper_with_geval(pxd_id, eval_rows, source_text)

    review_csv = _IncrementalCSV(review_path, _REVIEW_CSV_FIELDS)
    coverage_csv = _IncrementalCSV(coverage_path, _COVERAGE_CSV_FIELDS)
    stats_csv = _IncrementalCSV(stats_path, _STATS_CSV_FIELDS)
    try:
        coverage_csv.append_rows(coverage_rows)
        review_csv.append_rows(eval_rows)
        _write_paper_json(pxd_id, eval_rows, json_out_dir)
        paper_stat = _compute_single_paper_stats(pxd_id, eval_rows)
        stats_csv.append_rows([paper_stat])
    finally:
        review_csv.close()
        coverage_csv.close()
        stats_csv.close()

    df = pd.DataFrame(eval_rows) if eval_rows else pd.DataFrame()
    coverage_df = pd.DataFrame(coverage_rows) if coverage_rows else pd.DataFrame()
    per_paper_df = pd.DataFrame([paper_stat]) if eval_rows else pd.DataFrame()
    return df, coverage_df, per_paper_df


def run_single_sdrf_evaluation(
    pxd_id: str,
    sdrf_path: str,
    pmc_cache_path: str,
    out_dir: str,
    workers: int | None = None,
    use_llm_judge: bool = True,
):
    global USE_LLM_JUDGE, MAX_WORKERS, CACHE_DIR, _judge_model

    USE_LLM_JUDGE = use_llm_judge
    if workers:
        MAX_WORKERS = workers

    out_dir_path = Path(out_dir)
    out_dir_path.mkdir(parents=True, exist_ok=True)
    CACHE_DIR = str(out_dir_path / f".prompt_cache_{_CACHE_MODEL_SLUG}")
    _judge_model = None

    source_text = load_manuscript_from_pmc_cache(pxd_id, pmc_cache_path)
    if not source_text:
        raise RuntimeError(f"No manuscript text found for {pxd_id} in pmc_cache {pmc_cache_path}")

    sdrf_src = Path(sdrf_path).resolve()
    if not sdrf_src.exists():
        raise FileNotFoundError(f"SDRF file not found: {sdrf_src}")

    expected_name = f"{pxd_id}{SDRF_SUFFIX}"
    temp_ctx = None
    if sdrf_src.name == expected_name:
        pxd_root = str(sdrf_src.parent)
    else:
        temp_ctx = tempfile.TemporaryDirectory(prefix=f"sdrf_judge_{pxd_id}_")
        temp_root = Path(temp_ctx.name)
        shutil.copy2(sdrf_src, temp_root / expected_name)
        pxd_root = str(temp_root)

    try:
        df, _, per_paper_df = _evaluate_one_pxd(pxd_id, pxd_root, source_text, str(out_dir_path))
    finally:
        if temp_ctx is not None:
            temp_ctx.cleanup()

    if df.empty:
        return None

    plot_results(df, per_paper_df, "HAMLET", str(out_dir_path))

    if per_paper_df.empty:
        return None
    return per_paper_df.iloc[0].to_dict()


def _parse_checks_to_dict(issue_summary: str) -> dict:
    """parse the four narrative check lines from an issue summary into a structured dict"""
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


def _write_paper_json(pxd_id: str, eval_rows: list[dict], json_dir: str) -> None:
    """write evaluation results for one paper to a JSON file"""
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


def discover_pxd_ids(base_dir: str) -> list[str]:
    skip = {"text_files", "__pycache__"}
    ids: list[str] = []
    for name in sorted(os.listdir(base_dir)):
        full = os.path.join(base_dir, name)
        if not os.path.isdir(full):
            continue
        if name in skip or name.startswith("."):
            continue
        if os.path.isfile(os.path.join(full, f"{name}{SDRF_SUFFIX}")):
            ids.append(name)
    return ids


def process_all(out_dir: str):
    """Run the full evaluation pipeline across every PXD dataset under BASE_DIR"""
    pxd_ids = discover_pxd_ids(BASE_DIR)
    print(f"  Papers discovered: {len(pxd_ids)}  {pxd_ids}")

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

        pxd_root = os.path.join(BASE_DIR, pxd_id)

        source_text = load_manuscript(pxd_id)
        if not source_text:
            print(f"    SKIP: no manuscript text found.")
            continue

        predicted = load_sdrf(pxd_root, pxd_id)
        if not predicted:
            print(f"    SKIP: no SDRF metadata found.")
            continue

        #Evaluation-eligible fields => canonical fields present in the SDRF
        eval_fields = [f for f in predicted
                       if f.lower() not in SKIP_ANNOTATION_FIELDS]
        eval_fields.sort(key=lambda f: (FIELD_CATEGORY.get(f, "Other"), f))

        coverage_rows = []
        for field in eval_fields:
            values  = predicted.get(field, [])
            display = " | ".join(values) if values else ""
            coverage_rows.append({
                "paper_id":        pxd_id,
                "agent":           FIELD_CATEGORY.get(field, "Other"),
                "pipeline_field":  field,
                "mapped_field":    field,
                "extracted_value": display,
                "was_extracted":   bool(values),
            })
        all_cov_rows.extend(coverage_rows)
        coverage_csv.append_rows(coverage_rows)

        n_ext   = sum(1 for r in coverage_rows if r["was_extracted"])
        print(f"    Fields with a value: {n_ext}/{len(coverage_rows)}")

        #build one eval row per unique canonical field and value combination
        seen_eval: set[tuple[str, str]] = set()
        eval_rows: list[dict] = []
        n_raw = 0

        for field in eval_fields:
            for v in predicted.get(field, []):
                n_raw += 1
                if _is_not_extracted(v):
                    continue
                dedup_key = (field, _norm(v))
                if dedup_key in seen_eval:
                    print(f"    [dedup] skip '{v}' for '{field}' (already seen)")
                    continue
                seen_eval.add(dedup_key)
                eval_rows.append({
                    "paper_id":           pxd_id,
                    "agent":              FIELD_CATEGORY.get(field, "Other"),
                    "annotation_type":    field,
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

        print(f"    Evaluation rows: {len(eval_rows)} "
              f"(deduplicated from {n_raw} value occurrences)")

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
    if df.empty or per_paper_df.empty:
        return

    BG, GRID_C, TEXT_C, SUB_C, SPINE_C = "white", "#E5E7EB", "#111827", "#6B7280", "#D1D5DB"
    CLR = dict(correct="#27ae60", hall="#e74c3c", mismatch="#9b59b6",
               wrong="#e67e22", incomplete="#3498db")

    def style_ax(ax):
        """apply consistent background, grid and spine styling to a matplotlib axes"""
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

    #stacked bar chart showing annotation quality categories per paper
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

    #aggregate bar chart summing all quality category counts across every paper
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
    global USE_LLM_JUDGE, LIMIT, MAX_WORKERS

    parser = argparse.ArgumentParser(
        description="LLM judge evaluation over the hamlet_sdrfs datasets "
                    "using manuscript text as source of truth and the per-dataset "
                    "SDRF (.sdrf.tsv) file as the extraction being judged")
    parser.add_argument("--pipeline", action="store_true", help="Pipeline mode: evaluate one final SDRF")
    parser.add_argument("--pxd", default=None, help="[pipeline] PXD accession")
    parser.add_argument("--sdrf", default=None, help="[pipeline] Path to final SDRF TSV")
    parser.add_argument("--pmc_cache", default=None, help="[pipeline] Path to pmc cache JSON (or dir)")
    parser.add_argument("--outdir", default=None, help="[pipeline] Output directory")
    parser.add_argument("--no-judge", action="store_true", help="Skip LLM judge")
    parser.add_argument("--limit", type=int, default=None, help="Limit to first N papers")
    parser.add_argument("--workers", type=int, default=None,
                        help=f"Max parallel LLM calls (default: {MAX_WORKERS})")
    args = parser.parse_args()

    if args.no_judge:
        USE_LLM_JUDGE = False
    if args.limit:
        LIMIT = args.limit
    if args.workers:
        MAX_WORKERS = args.workers

    if args.pipeline:
        for flag, name in [(args.pxd, "--pxd"), (args.sdrf, "--sdrf"), (args.pmc_cache, "--pmc_cache"), (args.outdir, "--outdir")]:
            if not flag:
                parser.error(f"{name} is required in --pipeline mode")

        stats = run_single_sdrf_evaluation(
            pxd_id=args.pxd,
            sdrf_path=args.sdrf,
            pmc_cache_path=args.pmc_cache,
            out_dir=args.outdir,
            workers=args.workers,
            use_llm_judge=not args.no_judge,
        )
        if stats:
            print(f"Post-judge complete for {args.pxd}: accuracy={float(stats.get('judge_accuracy', 0)):.1%}")
        else:
            print(f"Post-judge completed for {args.pxd} with no evaluable rows.")
        return

    out_dir = os.path.join(BASE_DIR, "llm_judge_results")
    os.makedirs(out_dir, exist_ok=True)

    print(f"  Base dir       : {BASE_DIR}")
    print(f"  Manuscripts    : {TEXT_FILES_DIR}/<PXD>")
    print(f"  SDRF input     : <PXD>/<PXD>{SDRF_SUFFIX}")
    print(f"  Output folder  : {out_dir}")
    print(f"  Judge model    : {EVALUATION_MODEL}  (via OpenRouter)")
    print(f"  Prompt version : {PROMPT_VERSION}")
    print(f"  Temperature    : {MODEL_TEMPERATURE}")
    print(f"  Thinking       : {'ENABLED' if MODEL_ENABLE_THINKING else 'DISABLED'}")
    print(f"  Disk cache     : {'ENABLED' if CACHE_ENABLED else 'DISABLED'}  dir={CACHE_DIR}")
    print(f"  LLM judge      : {'ENABLED' if USE_LLM_JUDGE else 'DISABLED'}")
    print(f"  Limit          : {LIMIT if LIMIT else 'ALL papers'}")
    print(f"  Concurrency    : {MAX_WORKERS} workers")
    print(f"  Max value len  : {MAX_VALUE_LENGTH} chars (longer strings treated as evidence)")
    print()
    print("NOTE: The SDRF file is the extraction being judged; the manuscript text")
    print("      is the source of truth. Completeness is judged against the FULL SET")
    print("      of values for each field (SIBLING-VALUE RULE), so no value is")
    print("      penalised for being one of several correct extractions.")
    print()

    df, coverage_df, per_paper_df = process_all(out_dir)

    if df.empty:
        print("ERROR: No data processed.")
        return

    print(f"\n  Annotation review : {os.path.join(out_dir, 'llm_judge_annotation_review.csv')}")
    print(f"  Total rows        : {len(df)}")

    if not df.empty and "corrected_value" in df.columns:
        corrected_df = df[df["corrected_value"].notna() & (df["corrected_value"] != "")]
        if not corrected_df.empty:
            print(f"\n  Verdicts with corrections: {len(corrected_df)}")
            for _, row in corrected_df.head(20).iterrows():
                print(f"    [{row.get('verdict', '?')}] {row['annotation_type']}: "
                      f"'{str(row['extracted_value'])[:35]}' "
                      f"-> corrected to '{str(row['corrected_value'])[:50]}'")

    if not per_paper_df.empty:
        print(f"  Per-paper stats   : {os.path.join(out_dir, 'llm_judge_per_paper.csv')}")

    cache_stats = _get_judge_model().get_cache_stats()
    print("\nCACHE STATISTICS")
    for k, v in cache_stats.items():
        print(f"  {k:<35} {v}")

    print("\nGenerating summary plots...")
    plot_results(df, per_paper_df, "HAMLET", out_dir)

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

