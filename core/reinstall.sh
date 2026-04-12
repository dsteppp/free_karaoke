#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# reinstall.sh — Умный Адаптивный Инсталлятор AI-Karaoke Pro (С памятью)
# ─────────────────────────────────────────────────────────────────────────────

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$DIR"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║     AI-Karaoke Pro — Адаптивная Переустановка        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 0. Проверяем Python 3.11
# ─────────────────────────────────────────────────────────────────────────────
if ! command -v python3.11 &> /dev/null; then
    echo "❌ Python 3.11 не найден!"
    echo ""
    echo "   Проект требует именно Python 3.11 (не 3.12+)."
    echo "   Установите его через менеджер пакетов вашей системы:"
    echo ""
    echo "   Arch/Manjaro:  sudo pacman -S python311 или yay -S python311"
    echo "   Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    echo "   Fedora:        sudo dnf install python3.11"
    echo "   openSUSE:      sudo zypper install python311"
    echo ""
    echo "   Или через deadsnakes PPA (Ubuntu):"
    echo "     sudo add-apt-repository ppa:deadsnakes/ppa"
    echo "     sudo apt install python3.11 python3.11-venv"
    exit 1
fi
echo "   ✓ Python 3.11: $(python3.11 --version)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Проверяем / устанавливаем uv
# ─────────────────────────────────────────────────────────────────────────────
echo "🔍 Проверяем установщик (uv)..."
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi
echo "   ✓ uv $(uv --version)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 2. Создание структуры папок
# ─────────────────────────────────────────────────────────────────────────────
echo "📁 Подготовка файловой системы..."
mkdir -p "$DIR/cache/uv" "$DIR/cache/torch" "$DIR/cache/huggingface" "$DIR/models/whisper" "$DIR/library" "$DIR/static"
echo "   ✓ Структура папок готова"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 3. Проверяем / напоминаем про .env
# ─────────────────────────────────────────────────────────────────────────────
if [ ! -f "$DIR/.env" ]; then
    echo "⚠️  Файл .env не найден!"
    if [ -f "$DIR/.env.example" ]; then
        echo "📋 Найден шаблон .env.example — скопируй его и заполни токены:"
        echo "   cp .env.example .env"
        echo "   Затем открой .env и вставь свои ключи (инструкция внутри)"
    else
        echo "📋 Создай файл .env с токенами Genius и HuggingFace"
        echo "   (см. документацию проекта)"
    fi
    echo ""
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. Анализ оборудования
# ─────────────────────────────────────────────────────────────────────────────
echo "🤖 Сканирование шины оборудования..."
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
echo "   ✓ Обнаружена аппаратная платформа: $GPU_TYPE ($OS_NAME)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 4. Настройка песочницы (.env.cache)
# ─────────────────────────────────────────────────────────────────────────────
echo "📌 Настройка окружения..."
cat > "$DIR/.env.cache" << EOF
UV_CACHE_DIR=$DIR/cache/uv
TORCH_HOME=$DIR/cache/torch
HF_HOME=$DIR/cache/huggingface
HUGGINGFACE_HUB_CACHE=$DIR/cache/huggingface/hub
TRANSFORMERS_CACHE=$DIR/cache/huggingface/hub
XDG_CACHE_HOME=$DIR/cache
EOF

if [ "$GPU_TYPE" = "AMD" ]; then
    echo "HSA_OVERRIDE_GFX_VERSION=11.0.0" >> "$DIR/.env.cache"
fi

set -a; source "$DIR/.env.cache"; set +a
echo "   ✓ Окружение изолировано"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 5. Генерация requirements.txt
# ─────────────────────────────────────────────────────────────────────────────
echo "📝 Генерация requirements.txt под $GPU_TYPE..."

cat > "$DIR/requirements.txt" << EOF
# АВТОГЕНЕРАЦИЯ ПОД $GPU_TYPE
EOF

if [ "$GPU_TYPE" = "NVIDIA" ]; then
    echo "--extra-index-url https://download.pytorch.org/whl/cu124" >> "$DIR/requirements.txt"
    echo "torch" >> "$DIR/requirements.txt"
    echo "torchvision" >> "$DIR/requirements.txt"
    echo "torchaudio" >> "$DIR/requirements.txt"
    echo "onnxruntime" >> "$DIR/requirements.txt"

elif [ "$GPU_TYPE" = "AMD" ]; then
    echo "--extra-index-url https://download.pytorch.org/whl/rocm6.2" >> "$DIR/requirements.txt"
    echo "torch==2.5.1+rocm6.2" >> "$DIR/requirements.txt"
    echo "torchvision==0.20.1+rocm6.2" >> "$DIR/requirements.txt"
    echo "torchaudio==2.5.1+rocm6.2" >> "$DIR/requirements.txt"
    echo "onnxruntime" >> "$DIR/requirements.txt"

elif [ "$GPU_TYPE" = "APPLE" ]; then
    echo "torch" >> "$DIR/requirements.txt"
    echo "torchvision" >> "$DIR/requirements.txt"
    echo "torchaudio" >> "$DIR/requirements.txt"
    echo "onnxruntime-silicon; sys_platform == 'darwin' and platform_machine == 'arm64'" >> "$DIR/requirements.txt"

else
    echo "--extra-index-url https://download.pytorch.org/whl/cpu" >> "$DIR/requirements.txt"
    echo "torch==2.5.1+cpu" >> "$DIR/requirements.txt"
    echo "torchvision==0.20.1+cpu" >> "$DIR/requirements.txt"
    echo "torchaudio==2.5.1+cpu" >> "$DIR/requirements.txt"
    echo "onnxruntime" >> "$DIR/requirements.txt"
fi

cat >> "$DIR/requirements.txt" << 'EOF'
fastapi==0.135.1
uvicorn==0.41.0
starlette==0.52.1
aiofiles==25.1.0
python-multipart==0.0.22
jinja2
markupsafe
sqlalchemy==2.0.48
greenlet==3.3.2
huey==2.6.0
pydantic==2.12.5
pydantic-core==2.41.5
annotated-types==0.7.0
typing-extensions
typing-inspection==0.4.2
openai-whisper
stable-ts
tiktoken
ctranslate2==4.7.1
tokenizers==0.22.2
audio-separator==0.41.1
librosa==0.11.0
soundfile==0.12.1
pydub==0.25.1
audioread==3.1.0
soxr==1.0.0
samplerate==0.1.0
resampy==0.4.3
julius==0.2.7
av==16.1.0
numpy==2.4.3
scipy==1.17.1
scikit-learn==1.8.0
numba==0.64.0
llvmlite==0.46.0
einops==0.8.2
safetensors==0.7.0
diffq==0.2.4
rotary-embedding-torch==0.6.5
tinytag==2.2.0
mutagen==1.47.0
lyricsgenius==3.10.1
beautifulsoup4==4.14.3
soupsieve==2.8.3
requests==2.32.5
httpx==0.28.1
httpcore==1.0.9
urllib3==2.6.3
certifi==2026.2.25
charset-normalizer==3.4.5
idna==3.11
h11==0.16.0
anyio==4.12.1
huggingface-hub==1.6.0
hf-xet==1.3.2
fsspec
filelock
python-dotenv==1.2.2
pyyaml==6.0.3
regex==2026.2.28
tqdm==4.67.3
packaging==26.0
click==8.3.1
rich==14.3.3
pygments==2.19.2
six==1.17.0
decorator==5.2.1
lazy-loader==0.5
pooch==1.9.0
platformdirs==4.9.4
mpmath
sympy
networkx
threadpoolctl==3.6.0
joblib==1.5.3
setuptools==82.0.1
cffi==2.0.0
pycparser==3.0
pillow==12.1.1
msgpack==1.1.2
rapidfuzz==3.9.0
pywebview==5.0.5
PyQt6==6.7.0
PyQt6-WebEngine==6.7.0
qtpy
psutil
EOF
echo "   ✓ Манифест готов"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 6. Умная очистка (Только при смене железа)
# ─────────────────────────────────────────────────────────────────────────────
ARCH_MARKER="$DIR/.venv/.gpu_arch"
PREV_GPU=""

if [ -f "$ARCH_MARKER" ]; then
    PREV_GPU=$(cat "$ARCH_MARKER")
fi

if [ -d "$DIR/.venv" ] && [ "$PREV_GPU" = "$GPU_TYPE" ]; then
    echo "♻️  Железо не менялось ($GPU_TYPE). Используем кэш и текущее окружение..."
else
    echo "⚠️  Обнаружена смена железа (или первая установка)!"
    echo "🧹 Удаляем старое окружение, чтобы избежать конфликтов..."
    rm -rf "$DIR/.venv"
    
    # Чистим кэши других видеокарт только при смене железа
    if [ "$GPU_TYPE" != "NVIDIA" ]; then
        find "$DIR/cache/uv" -name "*nvidia*" -exec rm -rf {} + 2>/dev/null || true
        find "$DIR/cache/uv" -name "*cu11*" -exec rm -rf {} + 2>/dev/null || true
        find "$DIR/cache/uv" -name "*cu12*" -exec rm -rf {} + 2>/dev/null || true
    fi
    if [ "$GPU_TYPE" != "AMD" ]; then
        find "$DIR/cache/uv" -name "*rocm*" -exec rm -rf {} + 2>/dev/null || true
    fi
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 7. Создание .venv и Установка
# ─────────────────────────────────────────────────────────────────────────────
if [ ! -d "$DIR/.venv" ]; then
    echo "🐍 Создаём новое виртуальное окружение..."
    uv venv "$DIR/.venv" --python 3.11 --seed
    echo "$GPU_TYPE" > "$ARCH_MARKER"
fi

source "$DIR/.venv/bin/activate"

echo "📦 Проверка и доустановка зависимостей (инкрементно)..."
uv pip install --index-strategy unsafe-best-match -r "$DIR/requirements.txt"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 8. Финальная проверка работоспособности
# ─────────────────────────────────────────────────────────────────────────────
echo "🎮 Тест аппаратного ускорения PyTorch..."
python -c "
import torch
if torch.cuda.is_available():
    print(f'   ✓ Движок подключен: {torch.cuda.get_device_name(0)} (CUDA/ROCm)')
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    print('   ✓ Движок подключен: Apple Silicon (MPS)')
else:
    print('   ⚠️  Ускоритель не найден — fallback на CPU')
"
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              ✅ СИСТЕМА ГОТОВА К БОЮ!                 ║"
echo "╚══════════════════════════════════════════════════════╝"
echo "Для запуска используй: bash run.sh"
echo ""