"""Declarative SDRF column rules shared by renderers and provenance output."""

from dataclasses import dataclass
from typing import Literal


SdrfNamespace = Literal["characteristics", "comment", "factor value", "core"]


@dataclass(frozen=True)
class MappingRule:
    """Maps a logical field to one standards-compliant SDRF column."""

    field: str
    header: str
    namespace: SdrfNamespace
    scope: Literal["study", "sample", "assay", "file"]
    required: bool = False
    cardinality: Literal["one", "many"] = "one"
    formatter: str = "plain"
    source_precedence: tuple[str, ...] = ()


# This is intentionally data, not renderer control flow. The builder migrates
# fields to this registry incrementally while retaining stable output ordering.
SDRF_MAPPING_RULES: tuple[MappingRule, ...] = (
    MappingRule("source_name", "source name", "core", "sample", required=True),
    MappingRule("organism", "characteristics[organism]", "characteristics", "sample", required=True, source_precedence=("biological_agent", "pride")),
    MappingRule("organism_part", "characteristics[organism part]", "characteristics", "sample", required=True, source_precedence=("biological_agent", "pride")),
    MappingRule("disease", "characteristics[disease]", "characteristics", "sample", required=True, source_precedence=("biological_agent", "pride")),
    MappingRule("cell_type", "characteristics[cell type]", "characteristics", "sample"),
    MappingRule("cell_line", "characteristics[cell line]", "characteristics", "sample"),
    MappingRule("cellosaurus_accession", "characteristics[cellosaurus accession]", "characteristics", "sample"),
    MappingRule("biological_replicate", "characteristics[biological replicate]", "characteristics", "sample", required=True),
    MappingRule("sex", "characteristics[sex]", "characteristics", "sample", required=True),
    MappingRule("age", "characteristics[age]", "characteristics", "sample", required=True),
    MappingRule("treatment", "characteristics[treatment]", "characteristics", "sample"),
    MappingRule("enrichment", "characteristics[enrichment process]", "characteristics", "sample"),
    MappingRule("assay_name", "assay name", "core", "assay", required=True),
    MappingRule("technology_type", "technology type", "core", "assay", required=True),
    MappingRule("acquisition", "comment[proteomics data acquisition method]", "comment", "assay", required=True, formatter="cv", source_precedence=("runassessor", "aggregate")),
    MappingRule("label", "comment[label]", "comment", "assay", cardinality="many", formatter="cv", source_precedence=("technical_agent", "runassessor", "aggregate")),
    MappingRule("instrument", "comment[instrument]", "comment", "assay", required=True, formatter="cv", source_precedence=("runassessor", "technical_agent", "aggregate")),
    MappingRule("cleavage_agent", "comment[cleavage agent details]", "comment", "study", required=True, formatter="cv"),
    MappingRule("fraction_identifier", "comment[fraction identifier]", "comment", "assay", required=True),
    MappingRule("technical_replicate", "comment[technical replicate]", "comment", "assay", required=True),
    MappingRule("dissociation", "comment[dissociation method]", "comment", "assay", required=True, formatter="cv", source_precedence=("runassessor", "technical_agent", "aggregate")),
    MappingRule("factor_value", "factor value[experimental design]", "factor value", "sample"),
    MappingRule("modification", "comment[modification parameters]", "comment", "assay", cardinality="many", formatter="cv"),
    MappingRule("precursor_tolerance", "comment[precursor mass tolerance]", "comment", "study"),
    MappingRule("fragment_tolerance", "comment[fragment mass tolerance]", "comment", "study"),
    MappingRule("reduction_reagent", "comment[reduction reagent]", "comment", "study"),
    MappingRule("alkylation_reagent", "comment[alkylation reagent]", "comment", "study"),
    MappingRule("ms2_analyzer", "comment[ms2 mass analyzer]", "comment", "assay"),
    MappingRule("ms1_scan_range", "comment[ms1 scan range]", "comment", "study"),
    MappingRule("collision_energy", "comment[collision energy]", "comment", "study"),
    MappingRule("data_file", "comment[data file]", "comment", "file", required=True),
    MappingRule("sdrf_version", "comment[sdrf version]", "comment", "study", required=True),
    MappingRule("annotation_tool", "comment[sdrf annotation tool]", "comment", "study", required=True),
    MappingRule("factor_disease", "factor value[disease]", "factor value", "sample", required=True),
    MappingRule("factor_organism_part", "factor value[organism part]", "factor value", "sample"),
)


def flatten_internal_header(column: str) -> str:
    """Convert renderer-only indexed multi-value keys into SDRF headers."""
    if column.startswith("comment[modification parameters]#"):
        return "comment[modification parameters]"
    if column.startswith("comment[label]#"):
        return "comment[label]"
    return column


def source_precedence_for(field: str) -> tuple[str, ...]:
    """Return a field-specific policy, or let the resolver use its default."""
    for rule in SDRF_MAPPING_RULES:
        if rule.field == field and rule.source_precedence:
            return rule.source_precedence
    return ()


def rule_for_header(header: str) -> MappingRule | None:
    """Return the mapping rule for a rendered SDRF header."""
    return next((rule for rule in SDRF_MAPPING_RULES if rule.header == header), None)


def render_columns(included_fields: set[str], cardinalities: dict[str, int]) -> list[str]:
    """Build ordered renderer keys from explicit resolved-field presence only."""
    columns: list[str] = []
    for rule in SDRF_MAPPING_RULES:
        if rule.field not in included_fields:
            continue
        if rule.cardinality == "many":
            for index in range(max(1, cardinalities.get(rule.field, 0))):
                columns.append(f"{rule.header}#{index}")
        else:
            columns.append(rule.header)
    return columns