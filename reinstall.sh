#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# reinstall.sh — умная переустановка AI-Karaoke Pro (Adaptive GPU Edition)
# ─────────────────────────────────────────────────────────────────────────────

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$DIR"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     AI-Karaoke Pro — Адаптивная Переустановка        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Предупреждение ────────────────────────────────────────────────────────────
echo "⚠️  Будут удалены и/или перенесены:"
echo "     • .venv          (виртуальное окружение)"
echo "     • models/        (AI-модели)"
echo "     • cache/         (кэши uv, torch, huggingface)"
echo ""
read -p "Продолжить? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Отменено."
    exit 0
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Проверяем / устанавливаем uv
# ─────────────────────────────────────────────────────────────────────────────
echo "🔍 Проверяем uv..."
if ! command -v uv &> /dev/null; then
    echo "   uv не найден. Устанавливаем..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "   ✓ uv $(uv --version)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 2. Создаём внутренние папки кэша
# ─────────────────────────────────────────────────────────────────────────────
echo "📁 Подготовка файловой системы..."
mkdir -p "$DIR/cache/uv" "$DIR/cache/torch" "$DIR/cache/huggingface" "$DIR/models/whisper" "$DIR/library" "$DIR/static"
echo "   ✓ Папки созданы"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 3. Анализ Оборудования (Умный Адаптер)
# ─────────────────────────────────────────────────────────────────────────────
echo "🤖 Сканирование оборудования..."
GPU_TYPE="CPU"
OS_NAME=$(uname -s)

if [ "$OS_NAME" = "Linux" ]; then
    if command -v lspci &> /dev/null; then
        if lspci | grep -iE "nvidia" &> /dev/null; then
            GPU_TYPE="NVIDIA"
        elif lspci | grep -iE "radeon|amd" &> /dev/null; then
            GPU_TYPE="AMD"
        fi
    fi
elif [ "$OS_NAME" = "Darwin" ]; then
    GPU_TYPE="APPLE"
fi
echo "   ✓ Обнаружена платформа: $GPU_TYPE ($OS_NAME)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 4. Создание изоляции и патчей (.env.cache)
# ─────────────────────────────────────────────────────────────────────────────
echo "📌 Настройка среды..."
cat > "$DIR/.env.cache" << EOF
# Автогенерируется reinstall.sh — не редактировать вручную
UV_CACHE_DIR=$DIR/cache/uv
TORCH_HOME=$DIR/cache/torch
HF_HOME=$DIR/cache/huggingface
HUGGINGFACE_HUB_CACHE=$DIR/cache/huggingface/hub
TRANSFORMERS_CACHE=$DIR/cache/huggingface/hub
XDG_CACHE_HOME=$DIR/cache
EOF

if [ "$GPU_TYPE" = "AMD" ]; then
    echo "HSA_OVERRIDE_GFX_VERSION=11.0.0" >> "$DIR/.env.cache"
    echo "   ✓ Инжектирован патч HSA_OVERRIDE_GFX_VERSION=11.0.0 для AMD RDNA3"
fi

set -a; source "$DIR/.env.cache"; set +a
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 5. Очистка кэша от "мусора" других архитектур (Облегчаем вес)
# ─────────────────────────────────────────────────────────────────────────────
echo "🧹 Очистка старых данных и чужих драйверов..."
rm -rf "$DIR/.venv" "$DIR/models"
mkdir -p "$DIR/models/whisper"

if [ "$GPU_TYPE" != "NVIDIA" ]; then
    # Если мы не на NVIDIA, безжалостно удаляем тяжеленные CUDA-драйвера из кэша
    find "$DIR/cache/uv" -name "*nvidia*" -type d -exec rm -rf {} + 2>/dev/null || true
    find "$DIR/cache/uv" -name "*nvidia*" -type f -exec rm -f {} + 2>/dev/null || true
    find "$DIR/cache/uv" -name "*cu12*" -type f -exec rm -f {} + 2>/dev/null || true
fi
echo "   ✓ Кэш оптимизирован под текущее железо"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 6. Создаём .venv
# ─────────────────────────────────────────────────────────────────────────────
echo "🐍 Создаём .venv (Python 3.11)..."
uv venv "$DIR/.venv" --python 3.11 --seed
source "$DIR/.venv/bin/activate"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 7. Установка специфичного тензорного ядра (ДО requirements.txt)
# ─────────────────────────────────────────────────────────────────────────────
echo "🚀 Установка AI-ядра под архитектуру $GPU_TYPE..."

if [ "$GPU_TYPE" = "NVIDIA" ]; then
    uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
    uv pip install onnxruntime-gpu

elif [ "$GPU_TYPE" = "AMD" ]; then
    uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2
    uv pip install onnxruntime-rocm || uv pip install onnxruntime

elif [ "$GPU_TYPE" = "APPLE" ]; then
    uv pip install torch torchvision torchaudio
    uv pip install onnxruntime-silicon || uv pip install onnxruntime

else
    uv pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
    uv pip install onnxruntime
fi
echo "   ✓ AI-ядро установлено!"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 8. Устанавливаем остальные зависимости
# ─────────────────────────────────────────────────────────────────────────────
echo "📦 Устанавливаем остальные пакеты..."
# uv увидит, что torch уже стоит, и НЕ будет его перезаписывать!
uv pip install -r "$DIR/requirements.txt"
echo "   ✓ Все пакеты установлены"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 9. Финальная сборка мусора
# ─────────────────────────────────────────────────────────────────────────────
echo "🧽 Сборка мусора в кэше..."
uv cache clean 2>/dev/null || true
echo "   ✓ Приложение максимально облегчено"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 10. Финальная проверка
# ─────────────────────────────────────────────────────────────────────────────
echo "🎮 Тест аппаратного ускорения..."
python -c "
import torch
if torch.cuda.is_available():
    print(f'   ✓ Ускоритель: {torch.cuda.get_device_name(0)} (CUDA/ROCm)')
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    print('   ✓ Ускоритель: Apple Silicon (MPS)')
else:
    print('   ⚠️  Ускоритель недоступен — будет использован CPU')
"
echo ""

echo "╔══════════════════════════════════════════════════════╗"
echo "║              ✅ Установка завершена!                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "Для запуска: bash run.sh"
echo ""