# Bug Report: Incorrect Organism in SDRF for PXD073162

**Date:** 2026-07-01  
**Dataset:** PXD073162 (*Styela clava* thyroglobulin-like IP-MS study)  
**Symptom:** `characteristics[organism]` in the generated SDRF is `homo sapiens` instead of `Styela clava`

---

## Expected vs Actual

| Field | Expected | Actual |
|---|---|---|
| `characteristics[organism]` | `Styela clava` | `homo sapiens` |

---

## Root Cause

There are **two independent issues** that compound to produce the wrong result.

### Issue 1 — PRIDE organism data is at the wrong path in `_get_pride_organisms()` (agentic-metadata submodule)

`integration_agent.py` contains:

```python
def _get_pride_organisms(self, data: dict) -> list[dict]:
    organisms = data.get("pride_metadata", {}).get("organisms", [])
```

The PRIDE organisms list is stored at `pride_metadata.project.organisms` in the HAMLET aggregated results JSON, but the integration agent reads from `pride_metadata.organisms` (top level). That key is always an empty list in our JSON structure.

**Evidence:**
```python
pride_meta.get("organisms", [])          # → []   (what the agent reads)
pride_meta.get("project", {}).get("organisms", [])  # → [{"name": "Styela clava", "accession": "NEWT:7725", ...}]
```

Because `_get_pride_organisms()` returns `[]`, `pride_single` is `None` for the `species` field. The v2.5.1 majority-vote logic in `resolve_field()` only fires when all three sources (LLM, tool, PRIDE) are present. With PRIDE absent, it falls through to the simple two-source `DISAGREE` path where the tool value (Peptonizer) wins by default.

### Issue 2 — Peptonizer identifies Homo sapiens as the dominant taxonomic signal, but that does not define the SDRF sample organism

PXD073162 is an IP-MS experiment on *Styela clava* adult endostyle tissue, and both PRIDE/project metadata and the publication context indicate *Styela clava* as the study/sample organism. Peptonizer scores reflect dominant spectral/taxonomic signal, which can diverge from submitted sample organism metadata:

| Species | Peptonizer score |
|---|---|
| **Homo sapiens** | **0.9999** |
| Mus musculus | 0.7520 |
| Bos taurus | 0.3968 |
| *Styela clava* | 0.1004 |

The Homo sapiens Peptonizer result should therefore be treated as tool-level taxonomic evidence (or a potential search-space/database ambiguity), not as the authoritative SDRF `characteristics[organism]` value when PRIDE and publication/sample metadata agree on *Styela clava*.

---

## What Happened Step-by-Step

1. `organism_id` (Peptonizer) → `Homo sapiens` (score 0.9999) → taxid 9606 written to `taxid_mapping.json`
2. Integration agent resolves `species` field:
   - **Tool value** (`_get_top_organism`): `Homo sapiens`, score 0.9999
   - **LLM value**: `Styela clava`, score 0.5
   - **PRIDE value** (`_get_pride_organisms`): `None` ← bug: reads wrong JSON path
3. `pride_single = None` → majority vote skipped
4. Two-source `DISAGREE` → tool (METI) wins → `resolved = "Homo sapiens"`
5. `sdrf_builder.py` writes `homo sapiens` to `characteristics[organism]`

### What the majority vote *would have* decided (if PRIDE were correctly read)

- Tool: `Homo sapiens`
- LLM: `Styela clava`
- PRIDE: `Styela clava`

→ Status: `DISAGREE_TOOL_OUTVOTED` — LLM + PRIDE agree, tool is the outlier → **resolved = `Styela clava`** ✓

---

## Fix Required

### Fix 1 — `integration_agent.py` in `agentic-metadata` submodule (upstream)

`_get_pride_organisms()` needs to also check `pride_metadata.project.organisms`:

```python
def _get_pride_organisms(self, data: dict) -> list[dict]:
    pride_meta = data.get("pride_metadata") or {}
    # HAMLET stores organisms under pride_metadata.project.organisms
    organisms = pride_meta.get("organisms") or (pride_meta.get("project") or {}).get("organisms", [])
```

This should be raised as a bug with the upstream `agentic-metadata` repo (CompOmics/agentic-metadata) since the submodule is responsible for reading the METI JSON structure.

### Fix 2 — Consider a structural normalisation in `aggregate_results.py` (HAMLET)

Alternatively, HAMLET's `aggregate_results.py` could hoist `pride_metadata.project.organisms` up to `pride_metadata.organisms` when building the aggregated JSON, making it consistent with what the integration agent expects. This is a HAMLET-side fix and doesn't require an upstream change.

### Fix 3 — Long-term: separate sample/study organism from detected spectral organism

For SDRF `characteristics[organism]`, prioritize PRIDE + publication/sample metadata when they agree, and treat `organism_id` output as supporting or conflict-detection evidence rather than the default winner. This is especially important for IP-MS, affinity purification workflows, recombinant expression contexts, mixed-species samples, antibody-based workflows, and non-model organism studies.

---

## Files Investigated

| File | Role |
|---|---|
| `results/PXD073162/PXD073162_aggregated_results.json` | Source of truth — confirmed `pride_metadata.project.organisms = [Styela clava]`, `pride_metadata.organisms = []` |
| `results/PXD073162/taxid_mapping.json` | All 4 files mapped to taxid 9606 (Homo sapiens) via `organism_id` source |
| `results/PXD073162/organism_results/` | Peptonizer scores: Homo sapiens 0.9999, Styela clava 0.1004 |
| `results/PXD073162/agentic_metadata/metadata_extraction_output/integrated_output/BiologicalAgent/temp_0.0/PXD073162_PubText_enriched.json` | `species.resolved = "Homo sapiens"`, `status = "DISAGREE"`, `sources.pride = null` |
| `src/agentic-metadata/agents/integration_agent.py` | `_get_pride_organisms()` at line 321 reads wrong JSON path |
