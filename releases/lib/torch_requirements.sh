#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# torch_requirements.sh — единственный источник версий PyTorch/ONNX Runtime
# по типу GPU. Используется app_install.sh, alternative_app_install.sh и
# repair_env.sh — чтобы не дублировать версии в нескольких файлах.
#
# При обновлении версий (например, когда PyTorch выпустит колёса под новый
# ROCm) правится ТОЛЬКО этот файл.
# ─────────────────────────────────────────────────────────────────────────────

# write_torch_requirements <GPU_TYPE> <output_file>
# GPU_TYPE: NVIDIA | HYBRID | AMD | CPU
# Дописывает строки в output_file (не перезаписывает — вызывающий скрипт сам
# решает, создавать файл заново или дополнять).
write_torch_requirements() {
    local gpu_type="$1"
    local out="$2"

    case "$gpu_type" in
        NVIDIA|HYBRID)
            echo "--extra-index-url https://download.pytorch.org/whl/cu124" >> "$out"
            echo "torch==2.6.0+cu124" >> "$out"
            echo "torchvision==0.21.0+cu124" >> "$out"
            echo "torchaudio==2.6.0+cu124" >> "$out"
            echo "onnxruntime-gpu" >> "$out"
            ;;
        AMD)
            echo "--extra-index-url https://download.pytorch.org/whl/rocm6.2" >> "$out"
            echo "torch==2.5.1+rocm6.2" >> "$out"
            echo "torchvision==0.20.1+rocm6.2" >> "$out"
            echo "torchaudio==2.5.1+rocm6.2" >> "$out"
            echo "onnxruntime" >> "$out"
            ;;
        *)
            echo "--extra-index-url https://download.pytorch.org/whl/cpu" >> "$out"
            echo "torch==2.6.0+cpu" >> "$out"
            echo "torchvision==0.21.0+cpu" >> "$out"
            echo "torchaudio==2.6.0+cpu" >> "$out"
            echo "onnxruntime" >> "$out"
            ;;
    esac
}
