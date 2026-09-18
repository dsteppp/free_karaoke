#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# repair_env.sh — переустанавливает ML-рантайм (torch/torchvision/torchaudio/
# onnxruntime) под текущее железо БЕЗ полной переустановки приложения.
#
# Когда это нужно: приложение перестало запускаться или обрабатывать треки
# после ОБНОВЛЕНИЯ СИСТЕМЫ (ROCm, CUDA-драйвер, Mesa) на rolling-release
# дистрибутиве (Arch/Manjaro и т.п.) — venv продолжает нести старую сборку
# torch, несовместимую с новым системным GPU-стеком.
#
# Запуск: ./repair_env.sh [путь_к_установке]
# Если путь не указан — используется директория, где лежит этот скрипт.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
INSTALL_DIR="${1:-$DIR}"

if [ ! -d "$INSTALL_DIR/.venv" ]; then
    echo "❌ Не найден venv в $INSTALL_DIR/.venv"
    echo "   Укажите путь к установке: ./repair_env.sh /путь/к/Free_Karaoke"
    exit 1
fi

if [ ! -f "$DIR/lib/torch_requirements.sh" ]; then
    echo "❌ Не найден $DIR/lib/torch_requirements.sh"
    echo "   repair_env.sh должен лежать рядом с папкой lib/ (releases/lib/)."
    exit 1
fi
source "$DIR/lib/torch_requirements.sh"

echo "╔══════════════════════════════════════════════════════╗"
echo "║   Free Karaoke — восстановление ML-рантайма           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Установка: $INSTALL_DIR"
echo ""

# ── 1. Определяем текущее железо (та же логика, что в установщике) ─────────
GPU_TYPE="CPU"
if command -v lspci &>/dev/null; then
    N=$(lspci 2>/dev/null | grep -ciE 'nvidia' || true); N=${N:-0}
    A=$(lspci 2>/dev/null | grep -ciE 'radeon|amd.*graphics' || true); A=${A:-0}
    if [ "$N" -gt 0 ] && [ "$A" -gt 0 ]; then
        GPU_TYPE="HYBRID"
    elif [ "$N" -gt 0 ]; then
        GPU_TYPE="NVIDIA"
    elif [ "$A" -gt 0 ]; then
        GPU_TYPE="AMD"
    fi
fi
echo "🎮 Определённое железо: $GPU_TYPE"
echo ""

# ── 2. Активируем venv ──────────────────────────────────────────────────────
source "$INSTALL_DIR/.venv/bin/activate"

# ── 3. Удаляем старые ML-пакеты ─────────────────────────────────────────────
echo "🗑️  Удаление текущих torch/torchvision/torchaudio/onnxruntime*..."
PIP_CMD="pip"
command -v uv &>/dev/null && PIP_CMD="uv pip"
$PIP_CMD uninstall -y torch torchvision torchaudio onnxruntime onnxruntime-gpu 2>/dev/null || true

# ── 4. Генерируем свежий requirements под текущее железо ───────────────────
tmp_req=$(mktemp)
write_torch_requirements "$GPU_TYPE" "$tmp_req"
echo ""
echo "📦 Будут установлены:"
cat "$tmp_req"
echo ""

# ── 5. Устанавливаем ─────────────────────────────────────────────────────────
if command -v uv &>/dev/null; then
    uv pip install --prerelease=allow --index-strategy unsafe-best-match -r "$tmp_req"
else
    pip install --extra-index-url "$(grep 'extra-index-url' "$tmp_req" | awk '{print $2}')" -r <(grep -v 'extra-index-url' "$tmp_req")
fi
rm -f "$tmp_req"

echo ""
echo "✅ ML-рантайм переустановлен под $GPU_TYPE."
echo "   Проверка: python -c \"import torch; print(torch.__version__)\""
echo "   Запустите приложение: $INSTALL_DIR/run.sh"
