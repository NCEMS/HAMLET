"""
CascadiaBolt — performance-optimised fork of Cascadia.
Base: Cascadia (as installed in cascadia_env).
Fork: cascadiaBolt (src/cascadiaBolt/)
Hardware target: 2× NVIDIA RTX 6000 Ada Generation (47 GB VRAM), PyTorch 2.0.1+cu117

Changes vs upstream Cascadia:
  1. Default batch size 32 → 512  (see CHANGES.md Change 1)
  2. BF16 mixed precision when GPU + BF16 supported  (Change 2)
  3. torch.no_grad() in predict_step (Change 3, in model.py)
  4. Multi-GPU inference via --devices / -d argument  (Change 4)
  5. Optional torch.compile on spectrum_encoder  (Change 5)
  6. DataLoader num_workers 4 → 8 (configurable)  (Change 6)
"""

# ── stdlib / third-party imports identical to upstream ──────────────────────
from cascadia.depthcharge.data.spectrum_datasets import AnnotatedSpectrumDataset
from cascadia.depthcharge.data.preprocessing import scale_to_unit_norm, scale_intensity
from cascadia.depthcharge.tokenizers import PeptideTokenizer
import torch
import numpy as np
import pytorch_lightning as pl
import os
import sys
import argparse
from lightning.pytorch import loggers as pl_loggers
from cascadia.utils import write_results
from cascadia.augment import augment_spectra
from datetime import datetime
import warnings
import json
warnings.filterwarnings('ignore')

# ── Use CascadiaBolt's patched model (no_grad fix) ───────────────────────────
from .model import AugmentedSpec2Pep


def sequence():
    parser = argparse.ArgumentParser()
    parser.add_argument("spectrum_file")
    parser.add_argument("model", type=str,
                        help="A path to a trained Cascadia model checkpoint.")
    parser.add_argument("-o", "--outfile", type=str, default='cascadia_results',
                        help="Output file for inference.")
    parser.add_argument("-t", "--score_threshold", type=float, default=0.8,
                        help="Score threshold for Cascadia predictions.")

    # ── CascadiaBolt Change 1: default batch_size 32 → 512 ──────────────────
    parser.add_argument("-b", "--batch_size", type=int, default=512,
                        help="Number of spectra per batch. Default: 512 (up from upstream 32). "
                             "Reduce to 128/256 if you encounter OOM on smaller GPUs.")

    parser.add_argument("-w", "--width", type=int, default=2,
                        help="Number of adjacent scans to use when constructing each augmented spectrum.")
    parser.add_argument("-c", "--max_charge", type=int, default=4,
                        help="Maximum precursor charge state to consider")
    parser.add_argument("-p", "--modifications", type=str, default='mskb',
                        help="A path to a json file containing a list of the PTMs to consider.")

    # ── CascadiaBolt Change 4: multi-GPU support ─────────────────────────────
    parser.add_argument("-d", "--devices", type=int, default=1,
                        help="Number of GPUs to use for inference. 1 = single GPU (default), "
                             "2 = both RTX 6000 Ada GPUs, -1 = all available GPUs.")

    # ── CascadiaBolt Change 6: configurable DataLoader workers ───────────────
    parser.add_argument("-n", "--num_workers", type=int, default=8,
                        help="DataLoader worker processes. Default: 8 (up from upstream 4).")

    # ── CascadiaBolt Change 5: optional torch.compile on encoder ─────────────
    parser.add_argument("--compile-encoder", action="store_true",
                        help="Apply torch.compile(mode='reduce-overhead') to the spectrum encoder "
                             "for an additional 10–20 %% speedup after a one-time ~60 s compile "
                             "cost on the first batch. Requires PyTorch 2.0+.")

    args = parser.parse_args(args=sys.argv[2:])

    spectrum_file = args.spectrum_file
    model_ckpt_path = args.model
    results_file = args.outfile
    batch_size = args.batch_size
    score_threshold = args.score_threshold
    augmentation_width = args.width
    max_charge = args.max_charge
    mods = args.modifications
    n_devices = args.devices
    num_workers = args.num_workers
    compile_encoder = args.compile_encoder

    temp_path = os.getcwd() + '/cascadia_' + datetime.now().strftime("%m-%d-%H:%M:%S")
    os.mkdir(temp_path)
    train_index_filename = temp_path + "/index.hdf5"

    print("Augmenting spectra from:", spectrum_file)
    asf_file, isolation_window_size, cycle_time = augment_spectra(
        spectrum_file, temp_path, max_charge=max_charge
    )

    if mods == 'mskb':
        tokenizer = PeptideTokenizer.from_massivekb(
            reverse=False, replace_isoleucine_with_leucine=True
        )
    else:
        with open('ptms.json', 'r') as f:
            proforma = json.load(f)
        tokenizer = PeptideTokenizer.from_proforma(
            proforma, reverse=False, replace_isoleucine_with_leucine=True
        )

    train_dataset = AnnotatedSpectrumDataset(
        tokenizer, asf_file, index_path=train_index_filename,
        preprocessing_fn=[scale_intensity(scaling="root"), scale_to_unit_norm]
    )
    # ── CascadiaBolt Change 6: num_workers configurable ──────────────────────
    train_loader = train_dataset.loader(
        batch_size=batch_size, num_workers=num_workers, pin_memory=True
    )

    if os.path.exists(asf_file):
        os.remove(asf_file)

    model = AugmentedSpec2Pep.load_from_checkpoint(
        model_ckpt_path,
        d_model=512,
        n_layers=9,
        n_head=8,
        dim_feedforward=1024,
        dropout=0,
        rt_width=2,
        tokenizer=tokenizer,
        max_charge=10,
    )

    # ── CascadiaBolt Change 5: optional torch.compile on encoder ─────────────
    if compile_encoder:
        try:
            model.spectrum_encoder = torch.compile(
                model.spectrum_encoder,
                mode="reduce-overhead",
                dynamic=False,
            )
            print("[cascadiaBolt] spectrum_encoder compiled with torch.compile "
                  "(first batch will be slow ~30-60 s while Inductor compiles)")
        except Exception as e:
            print(f"[cascadiaBolt] torch.compile unavailable, falling back to eager: {e}")

    print("Running inference on augmented spectra from:", spectrum_file)
    if torch.cuda.is_available():
        device = 'gpu'
        print('GPU found')
    else:
        device = 'cpu'
        n_devices = 1  # multi-GPU only makes sense on CUDA
        print('No GPU found - running inference on cpu')

    # ── CascadiaBolt Change 2: BF16 mixed precision ───────────────────────────
    # pytorch_lightning 1.9.x uses precision="bf16" (not "bf16-mixed") for BF16.
    # BF16 has the same 8-bit exponent as FP32, so there is no overflow risk on
    # typical peptide scoring. Ada Lovelace tensor cores run BF16 at ~2× the
    # FLOP rate of FP32.
    if device == 'gpu' and torch.cuda.is_bf16_supported():
        precision = "bf16"
        print("[cascadiaBolt] Using BF16 mixed precision")
    else:
        precision = 32

    # ── CascadiaBolt Change 4: respect --devices for inference ───────────────
    # PL 1.9.5 DDP predict shards the DataLoader across GPUs automatically.
    # n_devices=-1 tells Lightning to use all available GPUs.
    trainer = pl.Trainer(
        max_epochs=50,
        log_every_n_steps=1,
        accelerator=device,
        devices=n_devices,
        precision=precision,
    )

    preds = trainer.predict(model, dataloaders=train_loader)

    print("Writing results to:", results_file + '.ssl')

    write_results(
        preds, results_file, spectrum_file,
        isolation_window_size, score_threshold,
        augmentation_width * cycle_time
    )

    os.remove(train_index_filename)
    os.rmdir(temp_path)

    return parser


def train():
    print("train", sys.argv)
    parser = argparse.ArgumentParser()
    parser.add_argument("train_spectrum_file")
    parser.add_argument("val_spectrum_file")
    parser.add_argument("-m", "--model", type=str, required=False,
                        help="A path to a Cascadia model checkpoint to fine tune.")
    parser.add_argument("-b", "--batch_size", type=int, default=32,
                        help="Number of spectra to include in a batch.")
    parser.add_argument("-w", "--width", type=int, default=2,
                        help="Number of adjacent scans to use when constructing each augmented spectrum.")
    parser.add_argument("-c", "--max_charge", type=int, default=4,
                        help="Maximum precursor charge state to consider.")
    parser.add_argument("-e", "--max_epochs", type=int, default=10,
                        help="Maximum number of training epochs.")
    parser.add_argument("-lr", "--learning_rate", type=float, default=1e-5,
                        help="Learning rate for model training.")
    parser.add_argument("-p", "--modifications", type=str, default='mskb',
                        help="A path to a json file containing a list of the PTMs to consider.")

    args = parser.parse_args(args=sys.argv[2:])

    train_spectrum_file = args.train_spectrum_file
    val_spectrum_file = args.val_spectrum_file
    model_ckpt_path = args.model
    batch_size = args.batch_size
    augmentation_width = args.width
    max_charge = args.max_charge
    max_epochs = args.max_epochs
    lr = args.learning_rate
    mods = args.modifications

    if torch.cuda.is_available():
        device = 'gpu'
        print('GPU found')
    else:
        device = 'cpu'
        print("No GPU Available - training on CPU will be extremely slow!")

    print("Training on spectra from:", train_spectrum_file)
    print("Validating on spectra from:", val_spectrum_file)

    ckpt_path = os.getcwd() + '/checkpoint_' + datetime.now().strftime("%m-%d-%H:%M:%S")
    os.mkdir(ckpt_path)
    train_index_filename = ckpt_path + "/train_gpu.hdf5"
    val_index_filename = ckpt_path + "/val_gpu.hdf5"

    if os.path.exists(train_index_filename):
        os.remove(train_index_filename)
    if os.path.exists(val_index_filename):
        os.remove(val_index_filename)

    if mods == 'mskb':
        tokenizer = PeptideTokenizer.from_massivekb(
            reverse=False, replace_isoleucine_with_leucine=True
        )
    else:
        with open(mods, 'r') as f:
            proforma = json.load(f)
        tokenizer = PeptideTokenizer.from_proforma(
            proforma, reverse=False, replace_isoleucine_with_leucine=True
        )

    if '.hdf5' in train_spectrum_file:
        train_dataset = AnnotatedSpectrumDataset(
            tokenizer, index_path=train_spectrum_file,
            preprocessing_fn=[scale_intensity(scaling="root"), scale_to_unit_norm]
        )
        val_dataset = AnnotatedSpectrumDataset(
            tokenizer, index_path=val_spectrum_file,
            preprocessing_fn=[scale_intensity(scaling="root"), scale_to_unit_norm]
        )
    else:
        train_dataset = AnnotatedSpectrumDataset(
            tokenizer, train_spectrum_file, index_path=train_index_filename,
            preprocessing_fn=[scale_intensity(scaling="root"), scale_to_unit_norm]
        )
        val_dataset = AnnotatedSpectrumDataset(
            tokenizer, val_spectrum_file, index_path=val_index_filename,
            preprocessing_fn=[scale_intensity(scaling="root"), scale_to_unit_norm]
        )

    train_loader = train_dataset.loader(
        batch_size=batch_size, num_workers=10, pin_memory=True, shuffle=True
    )
    val_loader = val_dataset.loader(batch_size=batch_size, num_workers=10, pin_memory=True)

    tb_logger = pl_loggers.TensorBoardLogger(save_dir="logs/")
    ckpt_callback = pl.callbacks.ModelCheckpoint(
        dirpath=ckpt_path,
        filename="Cascadia-{epoch}-{step}",
        monitor="Val Pep. Acc.",
        mode='max',
        save_top_k=2
    )
    trainer = pl.Trainer(
        max_epochs=max_epochs,
        logger=tb_logger,
        log_every_n_steps=10000,
        val_check_interval=10000,
        check_val_every_n_epoch=None,
        callbacks=[ckpt_callback],
        accelerator=device,
        devices=1
    )
    trainer.fit(model, train_loader, val_loader)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=['sequence', 'train'],
                        help='Which command to call')
    args = parser.parse_args(args=sys.argv[1:2])
    mode = args.mode

    if mode == 'sequence':
        sequence()
    elif mode == 'train':
        train()


if __name__ == '__main__':
    main()
