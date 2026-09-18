#!/bin/bash
# Проверяет, что write_torch_requirements даёт ожидаемый набор строк
# для каждого типа GPU. Запуск: bash releases/lib/test_torch_requirements.sh
set -euo pipefail
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
source "$DIR/torch_requirements.sh"

fail=0

check_contains() {
    local file="$1" needle="$2" label="$3"
    if ! grep -qF -- "$needle" "$file"; then
        echo "FAIL [$label]: ожидалась строка '$needle' в $file"
        fail=1
    fi
}

tmp=$(mktemp)
write_torch_requirements "AMD" "$tmp"
check_contains "$tmp" "torch==2.5.1+rocm6.2" "AMD"
check_contains "$tmp" "rocm6.2" "AMD index"
rm -f "$tmp"

tmp=$(mktemp)
write_torch_requirements "NVIDIA" "$tmp"
check_contains "$tmp" "torch==2.6.0+cu124" "NVIDIA"
check_contains "$tmp" "onnxruntime-gpu" "NVIDIA"
rm -f "$tmp"

tmp=$(mktemp)
write_torch_requirements "HYBRID" "$tmp"
check_contains "$tmp" "torch==2.6.0+cu124" "HYBRID"
rm -f "$tmp"

tmp=$(mktemp)
write_torch_requirements "CPU" "$tmp"
check_contains "$tmp" "torch==2.6.0+cpu" "CPU"
check_contains "$tmp" "onnxruntime" "CPU"
rm -f "$tmp"

if [ "$fail" -eq 0 ]; then
    echo "OK: все проверки write_torch_requirements прошли"
else
    exit 1
fi
