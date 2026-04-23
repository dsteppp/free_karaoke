#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# app_install.sh — Универсальный установщик Free Karaoke
# Работает на любом Linux, определяет конфигурацию, создаёт portable-установку
# ─────────────────────────────────────────────────────────────────────────────

set -e

# Обработка прерываний (Ctrl+C)
trap 'echo ""; echo "⚠️  Установка прервана пользователем."; echo "Нажмите Enter для выхода..."; read -r; exit 130' INT TERM

# ─────────────────────────────────────────────────────────────────────────────
# Цвета и форматирование вывода
# ─────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()    { echo -e "${BLUE}ℹ  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}⚠  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }
log_step()    { echo -e "${CYAN}📍 $1${NC}"; }

# Функция обработки ошибок
error_handler() {
    local exit_code=$?
    local line_number=$1
    echo ""
    echo "❌ ═══════════════════════════════════════════════════════"
    echo "❌ ОШИБКА! Скрипт не может продолжить работу."
    echo "❌ Код ошибки: $exit_code"
    echo "❌ Строка: $line_number"
    echo "❌ ═══════════════════════════════════════════════════════"
    echo ""
    echo "❌ Возможные причины:"
    echo "❌   • Нет подключения к интернету"
    echo "❌   • Недостаточно прав доступа"
    echo "❌   • Не установлены системные зависимости"
    echo "❌   • Конфликт версий пакетов"
    echo ""
    echo "Нажмите Enter для закрытия окна..."
    read -r
    exit $exit_code
}

trap 'error_handler $LINENO' ERR

# ─────────────────────────────────────────────────────────────────────────────
# 0. Проверка: запущены ли в терминале
# ─────────────────────────────────────────────────────────────────────────────
if [ ! -t 0 ]; then
    # Не в терминале — пробуем открыть в терминале по умолчанию
    log_warn "Скрипт запущен не в терминале. Открываем терминал..."
    
    TERMINAL_CMD=""
    
    # Пробуем найти терминал
    for term in x-terminal-emulator gnome-terminal konsole xfce4-terminal lxterminal qterminal alacritty kitty xterm; do
        if command -v "$term" &> /dev/null; then
            TERMINAL_CMD="$term"
            break
        fi
    done
    
    if [ -n "$TERMINAL_CMD" ]; then
        # Перезапускаем скрипт в терминале
        SCRIPT_PATH="$(readlink -f "$0")"
        log_info "Открываем $TERMINAL_CMD для установки..."
        
        case "$TERMINAL_CMD" in
            gnome-terminal)
                "$TERMINAL_CMD" -- bash "$SCRIPT_PATH"
                ;;
            konsole)
                "$TERMINAL_CMD" -e bash "$SCRIPT_PATH"
                ;;
            xfce4-terminal|lxterminal|qterminal|alacritty|kitty|xterm)
                "$TERMINAL_CMD" -e bash "$SCRIPT_PATH"
                ;;
            *)
                "$TERMINAL_CMD" -e bash "$SCRIPT_PATH"
                ;;
        esac
        exit 0
    else
        log_error "Не удалось определить терминал. Запустите скрипт вручную из терминала."
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Приветствие
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       Free Karaoke — Универсальный Установщик          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
log_info "Этот скрипт установит Free Karaoke в выбранную вами папку."
log_info "Будет создано:"
echo "   • Виртуальное окружение Python"
echo "   • Все зависимости для работы с аудио и ML"
echo "   • ML-модели для сепарации вокала и транскрипции"
echo "   • Desktop-файл для запуска из меню приложений"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Запрос пути установки
# ─────────────────────────────────────────────────────────────────────────────
log_step "Выбор директории установки"
echo ""
echo "Укажите путь к папке, где будет установлено приложение."
echo "Рекомендуется: \$HOME/free-karaoke или отдельный раздел"
echo ""

# Используем zenity/kdialog или просто read
if command -v zenity &> /dev/null; then
    INSTALL_DIR=$(zenity --file-selection --directory --title="Выберите директорию установки" 2>/dev/null)
    if [ -z "$INSTALL_DIR" ]; then
        log_error "Директория не выбрана. Установка отменена."
        exit 1
    fi
elif command -v kdialog &> /dev/null; then
    INSTALL_DIR=$(kdialog --title "Выберите директорию установки" --getexistingdirectory ~ 2>/dev/null)
    if [ -z "$INSTALL_DIR" ]; then
        log_error "Директория не выбрана. Установка отменена."
        exit 1
    fi
else
    # Ручной ввод с проверкой
    while true; do
        read -p "Введите полный путь к директории установки: " INSTALL_DIR
        
        # Раскрываем ~
        INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"
        
        if [ -z "$INSTALL_DIR" ]; then
            log_error "Путь не может быть пустым"
            continue
        fi
        
        # Проверяем существование родительской директории
        PARENT_DIR="$(dirname "$INSTALL_DIR")"
        if [ ! -d "$PARENT_DIR" ]; then
            log_warn "Родительская директория не существует: $PARENT_DIR"
            read -p "Создать её? (y/n): " CREATE_PARENT
            if [ "$CREATE_PARENT" = "y" ] || [ "$CREATE_PARENT" = "Y" ]; then
                mkdir -p "$PARENT_DIR" || { log_error "Не удалось создать директорию"; continue; }
            else
                continue
            fi
        fi
        
        break
    done
fi

# Нормализуем путь
INSTALL_DIR="$(cd "$(dirname "$INSTALL_DIR")" 2>/dev/null && pwd)/$(basename "$INSTALL_DIR")"
mkdir -p "$INSTALL_DIR"

log_success "Директория установки: $INSTALL_DIR"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 2. Анализ системы
# ─────────────────────────────────────────────────────────────────────────────
log_step "Анализ конфигурации системы"
echo ""

# Определяем дистрибутив
DISTRO=""
PACKAGE_MANAGER=""
if [ -f /etc/os-release ]; then
    source /etc/os-release
    DISTRO="$ID"
    case "$ID" in
        ubuntu|debian|linuxmint|pop)
            PACKAGE_MANAGER="apt"
            ;;
        fedora)
            PACKAGE_MANAGER="dnf"
            ;;
        arch|manjaro|endeavouros)
            PACKAGE_MANAGER="pacman"
            ;;
        opensuse*|suse)
            PACKAGE_MANAGER="zypper"
            ;;
        *)
            PACKAGE_MANAGER="unknown"
            ;;
    esac
    log_info "Дистрибутив: $PRETTY_NAME"
fi

# Определяем GPU
GPU_TYPE="CPU"
GPU_DETAILS=""

if command -v lspci &> /dev/null; then
    if lspci | grep -iE "nvidia" &> /dev/null; then
        GPU_TYPE="NVIDIA"
        GPU_DETAILS=$(lspci | grep -iE "nvidia" | head -1 | sed 's/.*: //')
    elif lspci | grep -iE "radeon|amd.*graphics|advanced micro devices" &> /dev/null; then
        GPU_TYPE="AMD"
        GPU_DETAILS=$(lspci | grep -iE "radeon|amd.*graphics" | head -1 | sed 's/.*: //')
    fi
fi

if [ "$GPU_TYPE" = "NVIDIA" ]; then
    log_success "Обнаружена NVIDIA: $GPU_DETAILS"
elif [ "$GPU_TYPE" = "AMD" ]; then
    log_success "Обнаружена AMD: $GPU_DETAILS"
else
    log_info "GPU не обнаружен — будет использоваться CPU режим"
fi

# Определяем объем RAM
RAM_GB=$(free -g | awk '/^Mem:/{print $2}')
log_info "Оперативная память: ${RAM_GB} GB"

# Проверяем Python
PYTHON_VERSION=""
PYTHON_CMD="python3"
for py in python3.11 python3.12 python3.10 python3; do
    if command -v "$py" &> /dev/null; then
        PYTHON_VERSION=$("$py" --version 2>&1 | cut -d' ' -f2)
        PYTHON_CMD="$py"
        break
    fi
done

if [ -n "$PYTHON_VERSION" ]; then
    log_success "Python: $PYTHON_VERSION ($PYTHON_CMD)"
else
    log_error "Python 3 не найден! Установите Python 3.10-3.12"
    exit 1
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 3. План установки и запрос подтверждения
# ─────────────────────────────────────────────────────────────────────────────
log_step "План установки"
echo ""
echo "Будет выполнено:"
echo "   1. Установка системных зависимостей через $PACKAGE_MANAGER"
echo "   2. Создание виртуального окружения Python в $INSTALL_DIR/.venv"
echo "   3. Установка Python-пакетов (PyTorch под $GPU_TYPE)"
echo "   4. Загрузка ML-моделей (~2 ГБ)"
echo "   5. Создание desktop-файла для запуска"
echo ""

if [ "$PACKAGE_MANAGER" != "unknown" ]; then
    echo "Для установки системных пакетов потребуются права root."
    echo ""
fi

read -p "Продолжить установку? (y/n): " CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    log_error "Установка отменена пользователем"
    echo "Нажмите Enter для закрытия окна..."
    read -r
    exit 1
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 4. Запрос прав sudo и установка системных зависимостей
# ─────────────────────────────────────────────────────────────────────────────
log_step "Установка системных зависимостей"
echo ""

# Списки пакетов
APT_PACKAGES="python3-venv python3-pip curl git ffmpeg libsndfile1 portaudio19-dev yad"
DNF_PACKAGES="python3-devel python3-virtualenv curl git ffmpeg libsndfile portaudio-devel yad"
PACMAN_PACKAGES="python-virtualenv python-pip curl git ffmpeg libsndfile portaudio yad"
ZYPPER_PACKAGES="python3-devel python3-virtualenv curl git ffmpeg libsndfile1 portaudio-devel yad"

install_apt() {
    sudo apt update
    sudo apt install -y $APT_PACKAGES
}

install_dnf() {
    sudo dnf install -y $DNF_PACKAGES
}

# Умная установка для pacman: проверяем наличие пакетов перед установкой
install_pacman() {
    local packages_to_install=()
    local all_packages=($PACMAN_PACKAGES)
    
    log_info "Проверка установленных пакетов..."
    
    for pkg in "${all_packages[@]}"; do
        if ! pacman -Q "$pkg" &> /dev/null; then
            log_info "Пакет $pkg не найден, будет установлен."
            packages_to_install+=("$pkg")
        else
            log_info "Пакет $pkg уже установлен."
        fi
    done
    
    if [ ${#packages_to_install[@]} -eq 0 ]; then
        log_success "Все системные пакеты уже установлены."
        return 0
    fi
    
    log_info "Установка отсутствующих пакетов: ${packages_to_install[*]}"
    sudo pacman -Sy --noconfirm "${packages_to_install[@]}"
}

install_zypper() {
    sudo zypper install -y $ZYPPER_PACKAGES
}

SUDO_AVAILABLE=false
if command -v sudo &> /dev/null; then
    SUDO_AVAILABLE=true
fi

if [ "$SUDO_AVAILABLE" = true ]; then
    log_info "Запрашиваем права суперпользователя..."
    
    case "$PACKAGE_MANAGER" in
        apt)
            install_apt
            ;;
        dnf)
            install_dnf
            ;;
        pacman)
            install_pacman
            ;;
        zypper)
            install_zypper
            ;;
        *)
            log_warn "Неизвестный пакетный менеджер. Пропускаем установку системных пакетов."
            log_info "Если возникнут ошибки, установите вручную: python3-venv, curl, git, ffmpeg"
            ;;
    esac
    
    log_success "Системные зависимости установлены"
else
    log_warn "sudo не доступен. Пропускаем установку системных пакетов."
    log_info "Убедитесь, что установлены: python3-venv, curl, git, ffmpeg"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 5. Проверка / установка uv
# ─────────────────────────────────────────────────────────────────────────────
log_step "Проверка установщика пакетов (uv)"
echo ""

if ! command -v uv &> /dev/null; then
    log_info "Устанавливаем uv (быстрый установщик Python-пакетов)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    log_success "uv установлен"
else
    log_success "uv уже установлен: $(uv --version)"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 6. Создание структуры папок
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание структуры папок"
echo ""

# Создаем только необходимые папки внутри core
mkdir -p "$INSTALL_DIR/core"
mkdir -p "$INSTALL_DIR/core/cache/uv"
mkdir -p "$INSTALL_DIR/core/cache/torch"
mkdir -p "$INSTALL_DIR/core/cache/huggingface"
mkdir -p "$INSTALL_DIR/core/models/audio_separator"
mkdir -p "$INSTALL_DIR/core/models/whisper"
# Папки library, debug_logs, shared создаются программой при первом запуске

log_success "Структура папок создана (все данные внутри core/)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 7. Клонирование файлов программы из репозитория
# ─────────────────────────────────────────────────────────────────────────────
log_step "Загрузка файлов программы"
echo ""

REPO_URL="https://github.com/dsteppp/free_karaoke.git"

# Проверяем, есть ли уже папка core и насколько она полная
CORE_EXISTS=false
if [ -d "$INSTALL_DIR/core" ] && [ -f "$INSTALL_DIR/core/main.py" ] && [ -f "$INSTALL_DIR/core/tasks.py" ]; then
    CORE_EXISTS=true
    log_info "Папка core существует. Проверяем целостность..."
fi

if [ "$CORE_EXISTS" = false ]; then
    log_info "Клонируем репозиторий..."
    if command -v git &> /dev/null; then
        # Используем редирект для предотвращения зависания
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR/tmp_clone" < /dev/null
        cp -r "$INSTALL_DIR/tmp_clone/core/"* "$INSTALL_DIR/core/"
        rm -rf "$INSTALL_DIR/tmp_clone"
        log_success "Файлы загружены из репозитория"
    else
        log_error "git не найден. Установите git или поместите файлы программы рядом со скриптом."
        exit 1
    fi
else
    log_info "Файлы программы уже присутствуют. Пропускаем загрузку."
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 8. Генерация requirements.txt под конфигурацию
# ─────────────────────────────────────────────────────────────────────────────
log_step "Генерация requirements.txt под $GPU_TYPE"
echo ""

cat > "$INSTALL_DIR/core/requirements.txt" << EOF
# АВТОГЕНЕРАЦИЯ ПОД $GPU_TYPE
EOF

if [ "$GPU_TYPE" = "NVIDIA" ]; then
    echo "--extra-index-url https://download.pytorch.org/whl/cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torch==2.6.0+cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchvision==0.21.0+cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchaudio==2.6.0+cu124" >> "$INSTALL_DIR/core/requirements.txt"
    echo "onnxruntime-gpu" >> "$INSTALL_DIR/core/requirements.txt"
elif [ "$GPU_TYPE" = "AMD" ]; then
    echo "--extra-index-url https://download.pytorch.org/whl/rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torch==2.5.1+rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchvision==0.20.1+rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchaudio==2.5.1+rocm6.2" >> "$INSTALL_DIR/core/requirements.txt"
    echo "onnxruntime" >> "$INSTALL_DIR/core/requirements.txt"
else
    echo "--extra-index-url https://download.pytorch.org/whl/cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torch==2.6.0+cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchvision==0.21.0+cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "torchaudio==2.6.0+cpu" >> "$INSTALL_DIR/core/requirements.txt"
    echo "onnxruntime" >> "$INSTALL_DIR/core/requirements.txt"
fi

cat >> "$INSTALL_DIR/core/requirements.txt" << 'EOF'
fastapi>=0.135.0
uvicorn>=0.41.0
starlette>=0.52.0
aiofiles>=25.1.0
python-multipart>=0.0.22
jinja2>=3.0.0
markupsafe>=2.0.0
sqlalchemy>=2.0.48
greenlet>=3.3.0
huey>=2.6.0
pydantic>=2.12.0
pydantic-core>=2.41.0
annotated-types>=0.7.0
typing-extensions>=4.0.0
typing-inspection>=0.4.0
openai-whisper>=20240930
stable-ts>=2.17.0
tiktoken>=0.7.0
ctranslate2>=4.7.0
tokenizers>=0.22.0
audio-separator>=0.41.0
librosa>=0.11.0
soundfile>=0.12.0
pydub>=0.25.0
audioread>=3.1.0
soxr>=1.0.0
samplerate>=0.1.0
resampy>=0.4.0
julius>=0.2.7
av>=16.0.0
numpy>=2.0
scipy>=1.17.0
scikit-learn>=1.8.0
numba>=0.64.0
llvmlite>=0.46.0
einops>=0.8.0
safetensors>=0.7.0
diffq>=0.2.4
rotary-embedding-torch>=0.6.0
tinytag>=2.2.0
mutagen>=1.47.0
lyricsgenius==3.10.1
beautifulsoup4>=4.14.0
soupsieve>=2.8.0
requests>=2.32.0
httpx>=0.28.0
httpcore>=1.0.0
urllib3>=2.6.0
certifi>=2026.0.0
charset-normalizer>=3.4.0
idna>=3.11
h11>=0.16.0
anyio>=4.12.0
huggingface-hub>=1.6.0
hf-xet>=1.3.0
fsspec>=2024.0.0
filelock>=3.0.0
python-dotenv>=1.2.0
pyyaml>=6.0.0
regex>=2026.0.0
tqdm>=4.67.0
packaging>=26.0
click>=8.3.0
rich>=14.3.0
pygments>=2.19.0
six>=1.17.0
decorator>=5.2.0
lazy-loader>=0.5
pooch>=1.9.0
platformdirs>=4.9.0
mpmath>=1.0.0
sympy>=1.13.0
networkx>=3.0.0
threadpoolctl>=3.6.0
joblib>=1.5.0
setuptools>=82.0.0
cffi>=2.0.0
pycparser>=3.0
pillow>=12.0.0
msgpack>=1.1.0
rapidfuzz>=3.9.0
pywebview>=5.0.0
PyQt6>=6.7.0
PyQt6-WebEngine>=6.7.0
PyQt6-WebEngine-Qt6>=6.7.0
qtpy>=2.4.0
psutil>=6.0.0
EOF

log_success "requirements.txt сгенерирован"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 9. Создание виртуального окружения и установка пакетов
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание виртуального окружения Python"
echo ""

VENV_DIR="$INSTALL_DIR/.venv"

if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    log_info "Виртуальное окружение уже существует. Проверяем работоспособность..."
    source "$VENV_DIR/bin/activate"
    if python -c "import sys" 2>/dev/null; then
        log_success "Виртуальное окружение уже существует и работает. Пропускаем создание."
    else
        log_warn "Виртуальное окружение повреждено. Пересоздаем..."
        deactivate 2>/dev/null || true
        rm -rf "$VENV_DIR"
        uv venv "$VENV_DIR" --python "$PYTHON_CMD" --seed
        log_success "Виртуальное окружение пересоздано"
    fi
else
    log_info "Создаём виртуальное окружение..."
    uv venv "$VENV_DIR" --python "$PYTHON_CMD" --seed
    log_success "Виртуальное окружение создано"
fi

source "$VENV_DIR/bin/activate"

# Сохраняем метку архитектуры GPU
echo "$GPU_TYPE" > "$VENV_DIR/.gpu_arch"

log_step "Установка Python-пакетов"
echo ""
log_info "Проверяем наличие ключевых пакетов..."

# Проверяем, установлены ли уже основные пакеты
PACKAGES_INSTALLED=false
if python -c "import torch; import torchaudio; import lyricsgenius; import fastapi" 2>/dev/null; then
    PACKAGES_INSTALLED=true
    log_success "Python-пакеты уже установлены. Пропускаем установку."
else
    log_info "Устанавливаем пакеты через uv (это может занять несколько минут)..."
    if ! uv pip install --index-strategy unsafe-best-match -r "$INSTALL_DIR/core/requirements.txt"; then
        log_error "Ошибка установки Python-пакетов!"
        exit 1
    fi
    log_success "Все пакеты установлены"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 10. Загрузка ML-моделей
# ─────────────────────────────────────────────────────────────────────────────
log_step "Загрузка ML-моделей"
echo ""

# Функция безопасной загрузки с проверкой размера
# $1 — URL, $2 — путь назначения, $3 — имя для вывода, $4 — мин. размер (байты)
download_model() {
    local url="$1" dest="$2" name="$3" min_size="$4"
    
    if [ -f "$dest" ]; then
        local actual_size
        actual_size=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        if (( actual_size >= min_size )); then
            local size_mb
            size_mb=$(awk "BEGIN {printf \"%.1f\", $actual_size / 1048576}")
            log_success "$name — уже есть (${size_mb} MB)"
            return 0
        else
            log_warn "$name — повреждён или неполон — перезагрузка..."
            rm -f "$dest"
        fi
    fi
    
    log_info "Скачиваем $name..."
    if curl -fSL --connect-timeout 15 --retry 3 --retry-delay 5 "$url" -o "$dest"; then
        local final_size
        final_size=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        if (( final_size >= min_size )); then
            local final_mb
            final_mb=$(awk "BEGIN {printf \"%.1f\", $final_size / 1048576}")
            log_success "$name загружен (${final_mb} MB)"
        else
            log_warn "Файл $name слишком мал, возможна ошибка загрузки"
        fi
    else
        log_error "Ошибка загрузки $name"
        return 1
    fi
}

# Kim_Vocal_1.onnx — fallback модель для CPU (~63 MB)
download_model \
    "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_1.onnx" \
    "$INSTALL_DIR/core/models/audio_separator/Kim_Vocal_1.onnx" \
    "Kim_Vocal_1.onnx" \
    50000000

# MDX23C-8KFFT-InstVoc_HQ.ckpt — основная GPU-модель сепарации (~428 MB)
download_model \
    "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/MDX23C-8KFFT-InstVoc_HQ.ckpt" \
    "$INSTALL_DIR/core/models/audio_separator/MDX23C-8KFFT-InstVoc_HQ.ckpt" \
    "MDX23C-8KFFT-InstVoc_HQ.ckpt" \
    200000000

# Whisper medium.pt — модель транскрипции (~1.5 GB)
download_model \
    "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt" \
    "$INSTALL_DIR/core/models/whisper/medium.pt" \
    "Whisper medium" \
    500000000

log_success "ML-модели загружены"
log_info "Модели находятся в $INSTALL_DIR/core/models/"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 11. Настройка токена Genius
# ─────────────────────────────────────────────────────────────────────────────
log_step "Настройка токена Genius"
echo ""

echo "╔══════════════════════════════════════════════════════╗"
echo "║       Free Karaoke — Genius Access Token           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
log_info "Для получения текстов песен нужен токен Genius API."
echo ""
echo "Как получить токен:"
echo "   1. Откройте https://genius.com/api-clients/new"
echo "   2. Войдите в свой аккаунт (или зарегистрируйтесь)"
echo "   3. Заполните форму:"
echo "      • Application name: Free Karaoke (или любое)"
echo "      • Application website: можно оставить пустым"
echo "      • Redirect URI: можно оставить пустым"
echo "   4. Нажмите 'Create Client'"
echo "   5. Скопируйте 'Client Access Token'"
echo ""

GENIUS_TOKEN=""
read -p "Вставьте токен Genius (или нажмите Enter для пропуска): " GENIUS_TOKEN

if [ -z "$GENIUS_TOKEN" ]; then
    log_warn "Токен не введён. Вы сможете добавить его позже в файл .env"
else
    log_success "Токен сохранён"
fi

# Создаём .env файл в папке core на основе шаблона
if [ -f "$INSTALL_DIR/core/.env.example" ]; then
    cp "$INSTALL_DIR/core/.env.example" "$INSTALL_DIR/core/.env"
    log_success "Файл .env создан из шаблона"
else
    cat > "$INSTALL_DIR/core/.env" << EOF
# Free Karaoke Configuration
# Auto-generated by app_install.sh

EOF

    if [ -n "$GENIUS_TOKEN" ]; then
        echo "GENIUS_ACCESS_TOKEN=$GENIUS_TOKEN" >> "$INSTALL_DIR/core/.env"
    else
        echo "# GENIUS_ACCESS_TOKEN=ваш_токен_здесь" >> "$INSTALL_DIR/core/.env"
    fi
    
    # Добавляем APP_PORT по умолчанию
    echo "APP_PORT=8000" >> "$INSTALL_DIR/core/.env"
    
    log_info "Добавьте токен вручную в файл: $INSTALL_DIR/core/.env"
fi

# Если токен был введён — обновляем .env
if [ -n "$GENIUS_TOKEN" ] && [ -f "$INSTALL_DIR/core/.env.example" ]; then
    sed -i "s/GENIUS_ACCESS_TOKEN=.*/GENIUS_ACCESS_TOKEN=$GENIUS_TOKEN/" "$INSTALL_DIR/core/.env"
fi

log_success "Файл .env готов к работе"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 12. Создание .env.cache для изоляции кэшей
# ─────────────────────────────────────────────────────────────────────────────
log_step "Настройка изоляции кэшей"
echo ""

cat > "$INSTALL_DIR/core/.env.cache" << EOF
UV_CACHE_DIR=$INSTALL_DIR/core/cache/uv
TORCH_HOME=$INSTALL_DIR/core/cache/torch
HF_HOME=$INSTALL_DIR/core/cache/huggingface
HUGGINGFACE_HUB_CACHE=$INSTALL_DIR/core/cache/huggingface/hub
TRANSFORMERS_CACHE=$INSTALL_DIR/core/cache/huggingface/hub
XDG_CACHE_HOME=$INSTALL_DIR/core/cache
EOF

# Переменные окружения для Qt WebEngine (критично для отрисовки интерфейса)
# QT_QPA_PLATFORM должен быть установлен ДО запуска приложения — всегда!
echo "QT_QPA_PLATFORM=xcb" >> "$INSTALL_DIR/core/.env.cache"
echo "QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox --disable-gpu-sandbox --disable-dev-shm-usage --disable-http-cache" >> "$INSTALL_DIR/core/.env.cache"

# HSA_OVERRIDE_GFX_VERSION для AMD GPU (и совместимости)
echo "HSA_OVERRIDE_GFX_VERSION=11.0.0" >> "$INSTALL_DIR/core/.env.cache"

log_success "Изоляция кэшей настроена"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 12.5. Проверка наличия APP_PORT в .env
# ─────────────────────────────────────────────────────────────────────────────
if ! grep -q "^APP_PORT=" "$INSTALL_DIR/core/.env" 2>/dev/null; then
    log_info "Добавляем APP_PORT=8000 в файл .env"
    echo "APP_PORT=8000" >> "$INSTALL_DIR/core/.env"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 13. Создание run.sh скрипта (обертка)
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание скрипта запуска"
echo ""

cat > "$INSTALL_DIR/run.sh" << RUNSCRIPT
#!/bin/bash
# Обертка для запуска Free Karaoke
DIR="\$( cd "\$( dirname "\${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Загружаем переменные окружения для Qt WebEngine из .env.cache (критично!)
if [ -f "\$DIR/core/.env.cache" ]; then
    set -a
    source "\$DIR/core/.env.cache"
    set +a
fi

# Принудительно экспортируем переменные для Qt WebEngine ДО запуска приложения
export QT_QPA_PLATFORM="\${QT_QPA_PLATFORM:-xcb}"
export QTWEBENGINE_CHROMIUM_FLAGS="\${QTWEBENGINE_CHROMIUM_FLAGS:---no-sandbox --disable-gpu-sandbox --disable-dev-shm-usage --disable-http-cache}"
export HSA_OVERRIDE_GFX_VERSION="\${HSA_OVERRIDE_GFX_VERSION:-11.0.0}"

exec "\$DIR/core/run.sh" "\$@"
RUNSCRIPT

chmod +x "$INSTALL_DIR/run.sh"

log_success "Скрипт запуска создан: $INSTALL_DIR/run.sh"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 14. Создание desktop-файла
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание desktop-файла"
echo ""

DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/free-karaoke.desktop"

if [ -f "$DESKTOP_FILE" ]; then
    log_info "Desktop-файл уже существует. Пропускаем."
else
    mkdir -p "$DESKTOP_DIR"
    
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Free Karaoke
Comment=Создание караоке из аудиофайлов с помощью нейросетей
Exec=$INSTALL_DIR/run.sh
Icon=audio-x-generic
Terminal=false
Categories=AudioVideo;Audio;Player;
Keywords=karaoke;audio;music;singing;
StartupNotify=true
EOF

    chmod +x "$DESKTOP_FILE"

    # Обновляем базу desktop (если есть)
    if command -v update-desktop-database &> /dev/null; then
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi

    log_success "Desktop-файл создан: $DESKTOP_FILE"
    log_info "Приложение доступно в меню приложений"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 15. Финальная проверка
# ─────────────────────────────────────────────────────────────────────────────
log_step "Финальная проверка"
echo ""

cd "$INSTALL_DIR"
source ".venv/bin/activate"

if python -c "import torch; import torchaudio; import lyricsgenius" 2>/dev/null; then
    log_success "Все проверки пройдены!"
else
    log_warn "Некоторые библиотеки могут отсутствовать, но установка завершена."
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Завершение
# ─────────────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════╗"
echo "║              Установка завершена!                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
log_success "Free Karaoke успешно установлена в: $INSTALL_DIR"
echo ""
echo "Запуск приложения:"
echo "   • Через меню приложений: найдите 'Free Karaoke'"
echo "   • Через терминал: $INSTALL_DIR/run.sh"
echo ""
echo "Дополнительно:"
echo "   • Токен Genius можно изменить в: $INSTALL_DIR/core/.env"
echo "   • Логи находятся в: $INSTALL_DIR/core/debug_logs (создаются при запуске)"
echo "   • Библиотека треков: $INSTALL_DIR/core/library (создается при запуске)"
echo ""
log_info "Спасибо за использование Free Karaoke!"
echo ""
echo "Нажмите Enter для закрытия окна..."
read -r