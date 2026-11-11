#!/bin/bash

lease_organism_gpu() {
    local count="$1" lock_dir="$2" gpu lock_fd
    local -a devices
    if [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
        IFS=',' read -r -a devices <<< "$CUDA_VISIBLE_DEVICES"
    else
        for ((gpu=0; gpu<count; gpu++)); do devices+=("$gpu"); done
    fi
    if ((count < 1 || ${#devices[@]} < 1)); then
        echo "ERROR: No GPU devices available for organism identification" >&2
        return 1
    fi
    lock_dir="$lock_dir/$(hostname)"
    mkdir -p "$lock_dir"
    while true; do
        for gpu in "${devices[@]:0:count}"; do
            exec {lock_fd}>"$lock_dir/gpu-${gpu}.lock"
            if flock -n "$lock_fd"; then
                export CUDA_VISIBLE_DEVICES="$gpu"
                echo "Leased organism-ID GPU $gpu"
                return 0
            fi
            exec {lock_fd}>&-
        done
        sleep 2
    done
}
