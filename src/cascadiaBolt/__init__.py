"""
cascadiaBolt — performance-optimised fork of Cascadia de novo peptide sequencing.

Base:     Cascadia (as installed in cascadia_env)
Fork:     cascadiaBolt  (src/cascadiaBolt/)
Hardware: 2× NVIDIA RTX 6000 Ada Generation (47 GB VRAM), PyTorch 2.0.1+cu117

Usage (drop-in replacement for `cascadia sequence`):
    conda run -p <cascadia_env_path> python -m cascadiaBolt.cascadia sequence \\
        <spectrum.mzML> <model.ckpt> [options]

Key flags added vs upstream:
    -b / --batch_size    default 512 (upstream: 32)
    -d / --devices       number of GPUs (default 1; set 2 for dual RTX 6000 Ada)
    -n / --num_workers   DataLoader workers (default 8; upstream: 4)
    --compile-encoder    enable torch.compile on spectrum_encoder
"""
