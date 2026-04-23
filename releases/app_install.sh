#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# app_install.sh — Универсальный установщик AI-Karaoke Pro
# Работает на любом Linux, определяет конфигурацию, создаёт portable-установку
# Репозиторий: https://github.com/ai-karaoke-pro/ai-karaoke-pro
# ─────────────────────────────────────────────────────────────────────────────

set -e

# Публичный URL репозитория
REPO_URL="https://github.com/ai-karaoke-pro/ai-karaoke-pro.git"
REPO_BRANCH="main"

# ─────────────────────────────────────────────────────────────────────────────
# Цвета и форматирование вывода
# ─────────────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }
log_success() { echo -e "${GREEN}✅ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}⚠️  $1${NC}"; }
log_error()   { echo -e "${RED}❌ $1${NC}"; }
log_step()    { echo -e "${CYAN}📍 $1${NC}"; }

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
echo "║     AI-Karaoke Pro — Универсальный Установщик        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
log_info "Этот скрипт установит AI-Karaoke Pro в выбранную вами папку."
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
echo "Рекомендуется: \$HOME/ai-karaoke-pro или отдельный раздел"
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
    exit 1
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 4. Запрос прав sudo и установка системных зависимостей
# ─────────────────────────────────────────────────────────────────────────────
log_step "Установка системных зависимостей"
echo ""

# Список пакетов для разных дистрибутивов
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

install_pacman() {
    sudo pacman -Sy --noconfirm $PACMAN_PACKAGES
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

mkdir -p "$INSTALL_DIR/core"
mkdir -p "$INSTALL_DIR/cache/uv"
mkdir -p "$INSTALL_DIR/cache/torch"
mkdir -p "$INSTALL_DIR/cache/huggingface"
mkdir -p "$INSTALL_DIR/models/audio_separator"
mkdir -p "$INSTALL_DIR/models/whisper"
mkdir -p "$INSTALL_DIR/library"
mkdir -p "$INSTALL_DIR/debug_logs"
mkdir -p "$INSTALL_DIR/shared/formats"

log_success "Структура папок создана"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 7. Клонирование файлов программы из репозитория
# ─────────────────────────────────────────────────────────────────────────────
log_step "Загрузка файлов программы"
echo ""

# Если скрипт лежит в репозитории — копируем локально
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$SCRIPT_DIR/core" ]; then
    log_info "Копируем файлы из локального репозитория..."
    cp -r "$SCRIPT_DIR/core/"* "$INSTALL_DIR/core/"
    cp -r "$SCRIPT_DIR/shared/"* "$INSTALL_DIR/shared/" 2>/dev/null || true
    log_success "Файлы скопированы"
else
    # Клонируем из публичного репозитория
    log_info "Клонируем репозиторий ($REPO_URL)..."
    if command -v git &> /dev/null; then
        git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR/tmp_clone"
        cp -r "$INSTALL_DIR/tmp_clone/core/"* "$INSTALL_DIR/core/"
        cp -r "$INSTALL_DIR/tmp_clone/shared/"* "$INSTALL_DIR/shared/" 2>/dev/null || true
        rm -rf "$INSTALL_DIR/tmp_clone"
        log_success "Файлы загружены из репозитория"
    else
        log_error "git не найден. Установите git или поместите файлы программы рядом со скриптом."
        exit 1
    fi
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 8. Генерация requirements.txt под конфигурацию
# ─────────────────────────────────────────────────────────────────────────────
log_step "Генерация manifests под $GPU_TYPE"
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

log_success "requirements.txt сгенерирован"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 9. Создание виртуального окружения и установка пакетов
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание виртуального окружения"
echo ""

uv venv "$INSTALL_DIR/.venv" --python "$PYTHON_CMD" --seed
source "$INSTALL_DIR/.venv/bin/activate"

echo "$GPU_TYPE" > "$INSTALL_DIR/.venv/.gpu_arch"

log_success "Виртуальное окружение создано"
echo ""

log_step "Установка Python-пакетов"
echo ""
log_info "Это может занять несколько минут..."
echo ""

uv pip install --index-strategy unsafe-best-match -r "$INSTALL_DIR/core/requirements.txt"

log_success "Все пакеты установлены"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 10. Загрузка ML-моделей
# ─────────────────────────────────────────────────────────────────────────────
log_step "Загрузка ML-моделей"
echo ""

download_model() {
    local url="$1" dest="$2" name="$3" min_size="$4"
    
    if [ -f "$dest" ]; then
        local actual_size
        actual_size=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        if [ "$actual_size" -ge "$min_size" ]; then
            local size_mb
            size_mb=$(awk "BEGIN {printf \"%.1f\", $actual_size / 1048576}")
            log_success "$name — уже есть (${size_mb} MB)"
            return 0
        else
            log_warn "$name — повреждён — перезагрузка..."
            rm -f "$dest"
        fi
    fi
    
    log_info "Загрузка $name..."
    if curl -fSL --connect-timeout 15 --retry 3 --retry-delay 5 "$url" -o "$dest"; then
        local final_size
        final_size=$(stat -c%s "$dest" 2>/dev/null || echo 0)
        local final_mb
        final_mb=$(awk "BEGIN {printf \"%.1f\", $final_size / 1048576}")
        log_success "$name готова (${final_mb} MB)"
    else
        log_warn "$name — ошибка загрузки (будет скачана при первом использовании)"
        rm -f "$dest"
        return 1
    fi
}

# MDX23C
download_model \
    "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/MDX23C-8KFFT-InstVoc_HQ.ckpt" \
    "$INSTALL_DIR/models/audio_separator/MDX23C-8KFFT-InstVoc_HQ.ckpt" \
    "MDX23C (сепарация вокала)" \
    200000000

# Kim_Vocal_1 (CPU fallback)
download_model \
    "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_1.onnx" \
    "$INSTALL_DIR/models/audio_separator/Kim_Vocal_1.onnx" \
    "Kim_Vocal_1 (CPU fallback)" \
    50000000

# Whisper medium
download_model \
    "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt" \
    "$INSTALL_DIR/models/whisper/medium.pt" \
    "Whisper medium (транскрипция)" \
    500000000

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 11. Запрос токена Genius
# ─────────────────────────────────────────────────────────────────────────────
log_step "Настройка доступа к Genius"
echo ""

echo "╔══════════════════════════════════════════════════════╗"
echo "║       AI-Karaoke Pro — Genius Access Token           ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Для поиска текстов песен нужен токен Genius API."
echo ""
echo "Как получить токен:"
echo "  1. Откройте: https://genius.com/api-clients/new"
echo "  2. Войдите в аккаунт (или зарегистрируйтесь)"
echo "  3. Заполните форму:"
echo "     • Application name: AI-Karaoke Pro (или любое)"
echo "     • Application website: можно оставить пустым"
echo "     • Redirect URI: можно оставить пустым"
echo "  4. Нажмите 'Create application'"
echo "  5. Скопируйте 'Client Access Token'"
echo ""
echo "Токен будет сохранён в: $INSTALL_DIR/core/.env"
echo ""

while true; do
    read -p "Вставьте токен и нажмите Enter (или нажмите Enter для пропуска): " GENIUS_TOKEN
    
    if [ -z "$GENIUS_TOKEN" ]; then
        log_warn "Токен не введён. Вы сможете добавить его позже в файл .env"
        break
    fi
    
    # Проверяем формат токена (должен начинаться с букв/цифр)
    if [[ "$GENIUS_TOKEN" =~ ^[A-Za-z0-9_-]+$ ]]; then
        break
    else
        log_error "Неверный формат токена. Попробуйте ещё раз."
    fi
done

# Создаём .env файл
cat > "$INSTALL_DIR/core/.env" << EOF
# AI-Karaoke Pro Configuration
# Auto-generated by app_install.sh

EOF

if [ -n "$GENIUS_TOKEN" ]; then
    echo "GENIUS_ACCESS_TOKEN=$GENIUS_TOKEN" >> "$INSTALL_DIR/core/.env"
    log_success "Токен сохранён"
else
    echo "# GENIUS_ACCESS_TOKEN=ваш_токен_здесь" >> "$INSTALL_DIR/core/.env"
    log_info "Добавьте токен вручную в файл: $INSTALL_DIR/core/.env"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 12. Создание .env.cache для изоляции кэшей
# ─────────────────────────────────────────────────────────────────────────────
log_step "Настройка изоляции кэшей"
echo ""

cat > "$INSTALL_DIR/core/.env.cache" << EOF
UV_CACHE_DIR=$INSTALL_DIR/cache/uv
TORCH_HOME=$INSTALL_DIR/cache/torch
HF_HOME=$INSTALL_DIR/cache/huggingface
HUGGINGFACE_HUB_CACHE=$INSTALL_DIR/cache/huggingface/hub
TRANSFORMERS_CACHE=$INSTALL_DIR/cache/huggingface/hub
XDG_CACHE_HOME=$INSTALL_DIR/cache
EOF

if [ "$GPU_TYPE" = "AMD" ]; then
    echo "HSA_OVERRIDE_GFX_VERSION=11.0.0" >> "$INSTALL_DIR/core/.env.cache"
fi

log_success "Изоляция кэшей настроена"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 13. Создание run.sh скрипта
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание скрипта запуска"
echo ""

cat > "$INSTALL_DIR/run.sh" << 'RUNSCRIPT'
#!/bin/bash
# Запуск AI-Karaoke Pro

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$DIR"

# Загружаем переменные окружения
if [ -f "$DIR/core/.env.cache" ]; then
    set -a
    source "$DIR/core/.env.cache"
    set +a
fi

if [ -f "$DIR/core/.env" ]; then
    set -a
    source "$DIR/core/.env"
    set +a
fi

# Активируем venv
source "$DIR/.venv/bin/activate"

# PyTorch ROCm fix
export HSA_OVERRIDE_GFX_VERSION=11.0.0

# Запускаем
python "$DIR/core/launcher.py"
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
mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_DIR/ai-karaoke-pro.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=AI-Karaoke Pro
Comment=Создание караоке из аудиофайлов с помощью нейросетей
Exec=$INSTALL_DIR/run.sh
Icon=audio-x-generic
Terminal=false
Categories=AudioVideo;Audio;Player;
Keywords=karaoke;audio;music;singing;
StartupNotify=true
EOF

chmod +x "$DESKTOP_DIR/ai-karaoke-pro.desktop"

# Обновляем базу desktop (если есть)
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

log_success "Desktop-файл создан: $DESKTOP_DIR/ai-karaoke-pro.desktop"
log_info "Приложение доступно в меню приложений"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 15. Финальная проверка
# ─────────────────────────────────────────────────────────────────────────────
log_step "Финальная проверка"
echo ""

cd "$INSTALL_DIR"
source ".venv/bin/activate"

python -c "
import torch
import torchaudio

print(f'   PyTorch:    {torch.__version__}')
print(f'   torchaudio: {torchaudio.__version__}')

if torch.cuda.is_available():
    device_name = torch.cuda.get_device_name(0)
    print(f'   ✓ GPU: {device_name} (CUDA)')
elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
    print('   ✓ GPU: Apple Silicon (MPS)')
else:
    print('   ℹ️  Режим CPU')

print()
print('   ✓ Все библиотеки работают корректно')
"

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Завершение
# ─────────────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════╗"
echo "║          ✅ УСТАНОВКА ЗАВЕРШЕНА УСПЕШНО!              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "📁 Директория установки: $INSTALL_DIR"
echo ""
echo "🚀 Запуск приложения:"
echo "   $INSTALL_DIR/run.sh"
echo ""
echo "📎 Или найдите 'AI-Karaoke Pro' в меню приложений"
echo ""
echo "📝 Для изменения настроек отредактируйте:"
echo "   $INSTALL_DIR/core/.env"
echo ""
log_success "Приятного использования!"
echo ""

# Не закрываем окно — ждём подтверждения от пользователя
echo "╔══════════════════════════════════════════════════════╗"
echo "║         Нажмите Enter для завершения                 ║"
echo "╚══════════════════════════════════════════════════════╝"
read -p ""