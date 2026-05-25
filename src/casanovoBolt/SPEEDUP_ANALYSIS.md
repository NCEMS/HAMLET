# CasanovoBolt Speed-up Analysis
**Source:** Casanovo v5.1.2  
**Hardware:** 2× NVIDIA RTX 6000 Ada (47 GB VRAM each), PyTorch 2.10.0+cu128  

---

## Summary

Casanovo's inference bottleneck is its **autoregressive beam-search decoder loop** combined with **full re-computation of the decoder's attention at every step**. Secondary bottlenecks are precision (float32), CPU↔GPU round-trips in `_finish_beams`, and serial Python loops. With the available hardware (Ada Lovelace GPUs, PyTorch 2.10), the realistic speedup potential is **3–6×** with no accuracy loss, and **up to ~10×** with BF16 mixed precision and `torch.compile`.

---

## Bottleneck Catalogue

### 1. 🔴 NO KV-CACHE IN DECODER — biggest win (~2–3×)
**File:** `denovo/model.py` — `beam_search_decode()` and `_get_topk_beams()`

Every decoder call in the main loop re-computes attention over the **entire token history from scratch**:
```python
active_scores = self.decoder(
    tokens=active_tokens,   # grows by 1 token each step
    precursors=active_precursors,
    memory=active_memories,
    memory_key_padding_mask=active_mem_masks,
)
```
At step N, the decoder processes tokens 0..N even though tokens 0..N-1 were already processed at step N-1. This makes decode time O(L²) in sequence length instead of O(L).

**Fix:** Implement a KV-cache in `PeptideDecoder` (and the underlying `AnalyteTransformerDecoder` from depthcharge). At each step, only compute the new token's key/value and append to a cached list. This is the same pattern used by all production LLM inference engines (vLLM, HuggingFace's `use_cache=True`).

**Complexity:** High — requires modifying the depthcharge `AnalyteTransformerDecoder` or patching it in `casanovoBolt/denovo/transformers.py`. The depthcharge encoder already computes memory once (not per-step), so only the decoder needs the cache.

**Estimated gain:** 2–3× throughput on long peptides (e.g., 20–50 AAs), less on short ones.

---

### 2. 🔴 FLOAT32 PRECISION — immediate easy win (~1.5–2×)
**File:** `config.yaml` line 177, `denovo/model_runner.py` `initialize_trainer()`

Default: `precision: "32-true"`. RTX 6000 Ada has excellent BF16 tensor core support (2× FLOPS vs FP32).

```yaml
precision: "32-true"   # current
precision: "bf16-mixed" # change to this
```

BF16 mixed-precision runs the forward/backward pass in BF16 but keeps master weights in FP32. For inference this is almost transparent.

**Fix:** Change `config.yaml` default and add a BF16 config file. Optionally add `--precision bf16-mixed` as a CLI flag.

**Complexity:** Trivial (one config line). 

**Risk:** Negligible accuracy impact on inference. BF16 has the same exponent range as FP32 (wider than FP16), avoiding overflow issues.

**Estimated gain:** 1.5–2× on RTX 6000 Ada.

---

### 3. 🔴 CPU ROUND-TRIP IN `_finish_beams()` — every decode step (~10–20% overhead)
**File:** `denovo/model.py` — `_finish_beams()`, lines ~507–515

```python
recalc_mzs = self.tokenizer.calculate_precursor_ions(
    padded_sequences.cpu(),        # GPU → CPU transfer
    charges_to_check.cpu()
).to(device, dtype=torch.float64)  # CPU → GPU transfer
```

This is called **every decode step** for **every active beam**. The tokenizer's `calculate_precursor_ions` runs on CPU. For a batch of 1024 spectra with 100 decode steps, this is 100 × CPU/GPU transfers.

**Fix option A:** Re-implement precursor ion mass calculation in pure PyTorch using the `token_masses` buffer that already lives on GPU:
```python
# All tensors already on GPU — no transfer needed
seq_lengths = (padded_sequences != 0).sum(dim=1)
neutral_masses = (token_masses[padded_sequences] * (padded_sequences != 0)).sum(dim=1)
# add water: 18.010565
neutral_masses += 18.010565
recalc_mzs = (neutral_masses / charges_to_check.double()) + 1.007276
```
This avoids the CPU round-trip entirely and is vectorized.

**Fix option B:** Use the existing `_cumulative_masses` buffer (already on GPU) instead of recalculating from scratch. The incremental mass update in `_get_topk_beams()` is already there — unify the logic.

**Complexity:** Medium. Need to verify mass calculation correctness against the tokenizer reference.

**Estimated gain:** 10–20% on typical workloads.

---

### 4. 🟡 PYTHON LOOP IN `_finish_beams()` — per-step Python overhead
**File:** `denovo/model.py` — `_finish_beams()`, lines ~490–499

```python
for i, beam_idx in enumerate(idx):
    seq = tokens[beam_idx, : step + 1]
    if seq[-1] == self.stop_token:
        seq = seq[:-1]
    sequences_to_check.append(seq)
```

This builds a Python list of variable-length tensors at every decode step. It then pads them manually. With 1024 spectra × 1 beam this is ~1024 Python iterations per decode step × 100 steps = ~100k Python iterations total.

**Fix:** Vectorize with masking. The stop-token removal can be done with a boolean mask:
```python
# Vectorized: shape (n_beams, step+1)
seq_block = tokens[idx, : step + 1]
# mask out the stop token if it appears at position `step`
last_is_stop = (seq_block[:, -1] == self.stop_token)
seq_lengths = torch.where(last_is_stop,
                           torch.full_like(last_is_stop, step, dtype=torch.long),
                           torch.full_like(last_is_stop, step + 1, dtype=torch.long))
```
Then pass `seq_block` and `seq_lengths` directly to the vectorized mass calculation.

**Complexity:** Medium — tied to fix #3 above.

**Estimated gain:** 5–15% on large batches.

---

### 5. 🟡 TENSOR CLONES IN `_get_topk_beams()` — memory bandwidth
**File:** `denovo/model.py` — `_get_topk_beams()`, lines ~735–745

```python
tokens_new = tokens.clone()   # full copy of (B*S, L) tensor
scores_new = scores.clone()   # full copy of (B*S, L, V) tensor — large!
```

`scores` has shape `(batch * beams, max_length, vocab_size)` = `(1024, 101, ~30)` ≈ 3M float32 per batch. Cloned every step. 100 steps = 300M floats moved per batch.

**Fix:** Use `torch.scatter_` in-place or restructure the index gather to avoid the clone. The final writes via `tokens_new[:, :step, :] = ...` and `scores_new[:, :step+1, :, :] = ...` rewrite the entire cloned tensor anyway, so the clone is only needed to avoid aliasing during the gather. Can be replaced with a pre-allocated output buffer.

**Complexity:** Medium.

**Estimated gain:** 5–10% (memory-bandwidth bound on large batches).

---

### 6. 🟡 `torch.compile` NOT USED — free PyTorch 2.x win
**File:** `denovo/model_runner.py` — `initialize_model()`

PyTorch 2.x `torch.compile` with the TorchInductor backend can fuse operations and reduce Python overhead significantly. The encoder (which runs once per batch) is an ideal candidate.

**Fix:**
```python
# In initialize_model(), after loading:
import torch
self.model.encoder = torch.compile(self.model.encoder, mode="reduce-overhead")
# Do NOT compile the decoder yet (KV-cache refactor needed first)
```

`mode="reduce-overhead"` is best for inference with fixed-shape inputs.

**Complexity:** Very low (2 lines of code).  
**Risk:** First batch is slow (compilation), subsequent batches faster. May cause issues with dynamic shapes in beam search — test carefully.

**Estimated gain:** 10–30% on encoder, less impact overall since decoder dominates.

---

### 7. 🟡 MULTI-GPU INFERENCE NOT ENABLED
**File:** `denovo/model_runner.py` — `initialize_trainer()`, line ~275

For inference (`train=False`), the trainer is hardcoded to `devices=1`:
```python
trainer_cfg = dict(
    accelerator=self.config.accelerator,
    devices=1,    # ← always 1 for inference
    ...
)
```

With 2× RTX 6000 Ada, you could split the input files across both GPUs.

**Fix:** For inference, allow `devices=2` (or `devices="auto"`) using `DDPStrategy`. This requires the predict DataLoader to shard data per device. Lightning handles this natively with `DataParallel` or `DDP` predict mode.

**Complexity:** Medium — need to ensure output file writing is coordinated (already using `MztabWriter`, need to check thread safety).

**Estimated gain:** ~1.8× throughput (not quite 2× due to overhead).

---

### 8. 🟢 PREDICT BATCH SIZE — easy tuning
**File:** `config.yaml` line 26

Current default: `predict_batch_size: 1024`. With 47 GB VRAM each, and the model being ~200 MB, you could potentially push this to **4096–8192** for a linear throughput increase. The limiting factor is the `scores` tensor which is `(B, L, V, S)` = `(4096, 101, 30, 1)` ≈ ~50M floats ≈ 200 MB in FP32 or ~100 MB in BF16 — well within 47 GB.

**Fix:** Benchmark `predict_batch_size: 2048`, `4096`, `8192`.

**Complexity:** Zero (config change only).

**Estimated gain:** Near-linear up to GPU memory limit. 4× batch size = ~3–4× throughput.

---

### 9. 🟢 PRECISION IN `_finish_beams()` — unnecessary float64
**File:** `denovo/model.py` — `_finish_beams()`, lines ~520–540

Mass calculations are done in `float64`:
```python
recalc_neutral_masses = (recalc_mzs - 1.007276) * charges_to_check.double()
```

For PPM-level mass accuracy at m/z ~1000, float32 has precision of ~0.0001 Da (~0.1 ppm), well within the 50 ppm tolerance. Using float64 for GPU operations is ~2× slower on most CUDA hardware.

**Fix:** Change to float32 after verifying precision is sufficient. With 50 ppm tolerance and typical peptide masses, float32 is more than adequate.

**Complexity:** Low.

**Estimated gain:** 5–15% in `_finish_beams`.

---

## Priority Implementation Plan

| Priority | Change | Complexity | Estimated Gain | Risk |
|----------|--------|------------|----------------|------|
| 1 | **Increase `predict_batch_size`** to 4096–8192 | Zero | 3–4× | None |
| 2 | **BF16 mixed precision** (`precision: "bf16-mixed"`) | Trivial | 1.5–2× | Very low |
| 3 | **torch.compile on encoder** | Very low | 10–30% (encoder) | Low |
| 4 | **GPU-native mass calc** (remove CPU round-trip in `_finish_beams`) | Medium | 10–20% | Medium |
| 5 | **Vectorize `_finish_beams` Python loop** | Medium | 5–15% | Medium |
| 6 | **Multi-GPU inference** (devices=2) | Medium | ~1.8× | Medium |
| 7 | **KV-cache in decoder** | High | 2–3× | High |
| 8 | **In-place ops in `_get_topk_beams`** | Medium | 5–10% | Low |
| 9 | **Float32 for mass tol checks** | Low | 5–15% | Very low |

### Realistic Combined Gain Estimate

Combining items 1–3 (zero/trivial/low effort):
- Batch 4096 + BF16 + compile ≈ **4–6× speedup over baseline**

Adding items 4–6 (medium effort):
- **6–9× speedup total**

Adding the KV-cache (high effort, changes the core decoder):
- **10–15× speedup total**

---

## Files in casanovoBolt to Modify

| File | Changes Needed |
|------|---------------|
| `config.yaml` | `predict_batch_size: 4096`, `precision: "bf16-mixed"` |
| `denovo/model_runner.py` | `torch.compile` encoder; allow `devices>1` for inference |
| `denovo/model.py` | GPU mass calc in `_finish_beams`; vectorize Python loop; in-place ops in `_get_topk_beams`; KV-cache (later) |
| `denovo/transformers.py` | KV-cache in `PeptideDecoder` (later) |

---

## Notes

- The **KV-cache** change requires modifying the `AnalyteTransformerDecoder` from the `depthcharge` library (or monkey-patching it in casanovoBolt). This is the highest-value but also highest-risk change.
- **BF16 + large batch** are safe to start with and require essentially no code changes.
- All changes in casanovoBolt are isolated — the installed `casanovo_env` package is untouched.
