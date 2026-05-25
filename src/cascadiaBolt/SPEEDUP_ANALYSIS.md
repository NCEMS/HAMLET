# CascadiaBolt Speed-up Analysis
**Source:** Cascadia (as distributed in cascadia_env)  
**Hardware:** 2× NVIDIA RTX 6000 Ada (47 GB VRAM each), PyTorch 2.0.1+cu117, pytorch-lightning 1.9.5

---

## Summary

Cascadia's inference pipeline has three separate bottleneck layers: (1) GPU kernel efficiency due to FP32
precision and tiny batch size, (2) unnecessary autograd graph construction during prediction, and
(3) Python-level serial decode loop with no KV-cache. With the available hardware (Ada Lovelace GPUs,
PL 1.9.5, PyTorch 2.0) the realistic speedup potential is **8–20×** with no accuracy loss.

---

## Bottleneck Catalogue

### 1. 🔴 BATCH SIZE 32 — biggest low-hanging fruit (~10–16× raw GPU utilisation)
**File:** `cascadia.py` — `sequence()` argument `-b`/`--batch_size`, default `32`

```python
# Original
parser.add_argument("-b", "--batch_size", type=int, default=32, ...)
```

A batch of 32 spectra leaves the RTX 6000 Ada's tensor cores ~96 % idle. Each spectrum produces a
tensor of shape `(n_peaks, 4)` padded to a fixed size. At 512 spectra per batch the GPU memory
footprint is still well under 1 GB (model ~600 MB + activations). At 1024 it is still comfortably
within the 47 GB VRAM budget.

**Fix:** Default changed to 512. Users on smaller GPUs can pass `-b 128` or `-b 256`.

**Estimated gain:** Near-linear up to GPU memory limit. 512/32 = 16× more work per kernel launch.
Wall-clock gain is typically 10–16× because of DataLoader IO and CPU-side overhead that does not scale.

---

### 2. 🔴 `torch.set_grad_enabled(True)` INSIDE `predict_step` — ~1.5–2× overhead
**File:** `model.py` — `AugmentedSpec2Pep.predict_step()`

```python
def predict_step(self, batch, *args):
    torch.set_grad_enabled(True)   # ← overrides Lightning's built-in no_grad context
    ...
    for i in range(len(sequences[0]) + 1):
        preds, _, _ = self._forward_step(spectra, precursors, cur_sequences)
```

PyTorch Lightning's `Trainer.predict()` runs inside a `torch.no_grad()` context by default. The
explicit `torch.set_grad_enabled(True)` call **re-enables** the autograd engine for the entire
decode loop, forcing PyTorch to allocate and track gradient tensors that are never read. For a
transformer model with 9 encoder and 9 decoder layers this roughly doubles peak activation memory
and adds ~30–50 % to forward-pass time.

Cascadia uses `dropout=0` and does no uncertainty quantification that would require gradients at
prediction time. There is no reason for this call to exist.

**Fix:** Remove the `torch.set_grad_enabled(True)` call and wrap the decode loop explicitly in
`torch.no_grad()` to be defensive regardless of Lightning version.

**Estimated gain:** 1.5–2× speedup; additionally ~2× memory saving on activations which permits
larger batch sizes.

---

### 3. 🔴 FLOAT32 PRECISION — immediate easy win (~1.5–2×)
**File:** `cascadia.py` — `pl.Trainer(...)` call

```python
# Original: no precision argument → defaults to FP32
trainer = pl.Trainer(max_epochs=50, log_every_n_steps=1, accelerator=device, devices=1)
```

The RTX 6000 Ada (Ada Lovelace) has dedicated BF16 tensor cores that execute at **2× the FLOP rate**
of FP32. `precision="bf16"` in pytorch-lightning 1.9.5 runs the forward pass in BF16 while keeping
parameters in FP32 master copies (mixed precision). BF16 has the same 8-bit exponent as FP32 so
there is no overflow risk.

**Fix:** Add `precision="bf16"` when running on a CUDA device that supports BF16.

**Estimated gain:** 1.5–2× throughput on Ada Lovelace.

---

### 4. 🟡 HARD-CODED `devices=1` — prevents dual-GPU inference
**File:** `cascadia.py` — `pl.Trainer(devices=1, ...)`

```python
trainer = pl.Trainer(..., devices=1)
```

Both RTX 6000 Ada GPUs are idle except the first one. Lightning's DDP predict shards the DataLoader
across GPUs automatically.

**Fix:** Add `--devices`/`-d` CLI argument (default `1`; set to `2` or `-1` for both GPUs).

**Estimated gain:** ~1.8× throughput (2 GPUs, ~10 % coordination overhead).

---

### 5. 🟡 NO `torch.compile` — free PyTorch 2.x win (~10–20 %)
**File:** `cascadia.py` — post-checkpoint-load

PyTorch 2.0 `torch.compile` with TorchInductor fuses operations and eliminates Python dispatch
overhead. The `spectrum_encoder` (a `SpectrumTransformerEncoder` with 9 layers) runs exactly once
per batch and has fixed input shapes — an ideal compile target.

**Fix:** After `AugmentedSpec2Pep.load_from_checkpoint(...)`, if `--compile-encoder` is set:
```python
model.spectrum_encoder = torch.compile(
    model.spectrum_encoder, mode="reduce-overhead", dynamic=False
)
```

**Estimated gain:** 10–20 % on encoder; 5–10 % overall (encoder is ~30 % of total wall time in a
single-GPU large-batch run). First batch is slow (~30–60 s) while Inductor compiles.

---

### 6. 🟡 DATALOADER `num_workers=4` — IO not fully pipelined
**File:** `cascadia.py` — `train_dataset.loader(num_workers=4, ...)`

With a batch size of 512 and a fast NVMe drive, 4 workers may bottleneck on HDF5 index reads.
Increasing to 8 workers fully pipelines IO with GPU compute on a 16-core workstation.

**Fix:** Default `--num-workers` raised to `8`; user-configurable via CLI.

**Estimated gain:** 5–15 % end-to-end, depends on disk speed.

---

### 7. 🟢 AUTOREGRESSIVE LOOP WITH FULL RECOMPUTE — hard fix (~2–3× decoder speedup)
**File:** `model.py` — `predict_step()`

```python
for i in range(len(sequences[0]) + 1):
    preds, _, _ = self._forward_step(spectra, precursors, cur_sequences)
    # cur_sequences grows by 1 token per step
```

Each call to `_forward_step` passes `cur_sequences` with all tokens decoded so far to the
`PeptideTransformerDecoder`. The decoder's cross-attention over `cur_sequences` recomputes all
previous token keys/values from scratch every step. For a peptide of length L this is O(L²) attention
work instead of O(L) with a KV-cache.

**Fix:** Implement a KV-cache in `PeptideTransformerDecoder` (from cascadia's bundled depthcharge).
At each decode step, only compute the new token's key/value and append to cached tensors. This
mirrors the KV-cache pattern in production LLM inference.

**Complexity:** High — requires patching the depthcharge `PeptideTransformerDecoder` or replacing
the attention layers with a cache-aware implementation. Deferred to a future CascadiaBolt release.

**Estimated gain:** 2–3× on long peptides (≥ 15 AA); less on short ones.

---

## Combined Estimated Speedup

| Change | Gain | Cumulative |
|--------|------|------------|
| Batch 32 → 512 | 10–16× | 10–16× |
| torch.no_grad() in predict | 1.5–2× | 15–32× |
| BF16 precision | 1.5–2× | 22–64× (capped by IO) |
| Multi-GPU (2 GPUs) | 1.8× | ~35× realistic |
| torch.compile encoder | 1.1–1.2× | ~40× realistic |
| num_workers 4 → 8 | 1.05–1.15× | ~45× realistic |

**Realistic wall-clock improvement with changes 1–4:** **8–20×** (IO-bounded on large files).
