#!/usr/bin/env python3
"""
gpu-watch — GPU monitor that works when nvidia-smi fails (NVML mismatch).
Reads via PyTorch CUDA. Run with:  conda run -n casanovo_env python gpu-watch.py
Or loop:  watch -n 2 "conda run -n casanovo_env python gpu-watch.py -n 1"
"""

import argparse
import os
import time

RESET = "\033[0m";  BOLD = "\033[1m";  GREEN = "\033[92m"
YELLOW = "\033[93m"; CYAN = "\033[96m"; BLUE = "\033[94m"
RED = "\033[91m";   DIM = "\033[2m"


def bar(used, total, width=32):
    frac = min(used / total, 1.0) if total > 0 else 0
    filled = int(frac * width)
    color = GREEN if frac < 0.6 else YELLOW if frac < 0.85 else RED
    return f"{color}{'█' * filled}{'░' * (width - filled)}{RESET}"


def get_gpu_info():
    # Try pynvml first (works if driver is consistent)
    try:
        import pynvml
        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(n):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            mem  = pynvml.nvmlDeviceGetMemoryInfo(h)
            temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            pwr  = pynvml.nvmlDeviceGetPowerUsage(h) / 1000
            pwrl = pynvml.nvmlDeviceGetEnforcedPowerLimit(h) / 1000
            procs = pynvml.nvmlDeviceGetComputeRunningProcesses(h)
            gpus.append(dict(idx=i, name=name, util_gpu=util.gpu,
                             mem_used=mem.used/1024**3, mem_total=mem.total/1024**3,
                             temp=temp, power=pwr, power_limit=pwrl,
                             n_procs=len(procs), source="pynvml"))
        pynvml.nvmlShutdown()
        return gpus
    except Exception:
        pass

    # Fallback: PyTorch CUDA (memory only — no SM util without NVML)
    try:
        import torch
        if not torch.cuda.is_available():
            return []
        gpus = []
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            gpus.append(dict(
                idx=i, name=p.name,
                util_gpu=None,
                mem_used=torch.cuda.memory_allocated(i) / 1024**3,
                mem_reserved=torch.cuda.memory_reserved(i) / 1024**3,
                mem_total=p.total_memory / 1024**3,
                temp=None, power=None, power_limit=None, n_procs=None,
                source="torch.cuda"))
        return gpus
    except Exception:
        return []


def render_once():
    gpus = get_gpu_info()
    now = time.strftime("%a %b %d %H:%M:%S %Y")
    src = gpus[0]["source"] if gpus else "none"
    print(f"{BOLD}gpu-watch{RESET}  {DIM}[{now}]  source: {src}{RESET}")
    print(f"{DIM}nvidia-smi broken (NVML mismatch 580.126→580.159) — reboot to fix permanently{RESET}\n")

    if not gpus:
        print(f"{RED}No GPU data available.{RESET}")
        return

    for g in gpus:
        u_gpu  = g.get("util_gpu")
        mu     = g["mem_used"]
        mt     = g["mem_total"]
        mr     = g.get("mem_reserved")

        print(f"  {BOLD}{CYAN}GPU {g['idx']}{RESET}  {g['name']}")

        if u_gpu is not None:
            uc = GREEN if u_gpu < 60 else YELLOW if u_gpu < 85 else RED
            print(f"    GPU util  {bar(u_gpu, 100)}  {uc}{u_gpu:3d}%{RESET}")
        else:
            print(f"    GPU util  {DIM}N/A (needs NVML — SM utilisation unavailable){RESET}")

        print(f"    Mem alloc {bar(mu, mt)}  {BLUE}{mu:.2f}{RESET} / {mt:.1f} GB")
        if mr is not None:
            print(f"    Mem rsvd  {bar(mr, mt)}  {DIM}{mr:.2f} GB{RESET}")

        if g.get("temp") is not None:
            tc = GREEN if g["temp"] < 70 else YELLOW if g["temp"] < 85 else RED
            print(f"    Temp  {tc}{g['temp']}°C{RESET}   Power {g['power']:.0f} / {g['power_limit']:.0f} W   Procs {g['n_procs']}")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-d", "--delay", type=float, default=2.0)
    ap.add_argument("-n", "--count", type=int, default=0)
    args = ap.parse_args()
    i = 0
    while True:
        i += 1
        print("\033[H\033[2J", end="")  # clear screen
        render_once()
        if args.count and i >= args.count:
            break
        try:
            time.sleep(args.delay)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    main()
