#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# app_install.sh — Универсальный установщик Free Karaoke
# Работает на любом Linux, определяет конфигурацию, создаёт portable-установку
# Репозиторий: https://github.com/dsteppp/free_karaoke.git
# ─────────────────────────────────────────────────────────────────────────────

# НЕ используем set -e — обрабатываем ошибки вручную для показа пользователю

# Публичный URL репозитория
REPO_URL="https://github.com/dsteppp/free_karaoke.git"
REPO_BRANCH="main"
APP_NAME="Free Karaoke"
DESKTOP_FILE_NAME="free-karaoke.desktop"
INSTALL_DIR_NAME="free-karaoke"

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

# ─────────────────────────────────────────────────────────────────────────────
# Обработка прерывания (Ctrl+C)
# ─────────────────────────────────────────────────────────────────────────────
cleanup() {
    echo ""
    log_warn "Установка прервана пользователем."
    log_info "Очистка временных файлов..."
    if [ -n "$INSTALL_DIR" ] && [ -d "$INSTALL_DIR/tmp_clone" ]; then
        rm -rf "$INSTALL_DIR/tmp_clone"
    fi
    # Оставляем папку установки, чтобы пользователь мог продолжить позже
    echo "Нажмите Enter для выхода..."
    read -r
    exit 130
}

trap cleanup SIGINT SIGTERM
# Обработчик ошибок — не даём окну закрыться
# ─────────────────────────────────────────────────────────────────────────────
error_handler() {
    local exit_code=$?
    local line_number=$1
    echo ""
    log_error "═══════════════════════════════════════════════════════"
    log_error "ОШИБКА! Скрипт не может продолжить работу."
    log_error "Код ошибки: $exit_code"
    log_error "Строка: $line_number"
    log_error "═══════════════════════════════════════════════════════"
    echo ""
    log_error "Возможные причины:"
    log_error "  • Нет подключения к интернету"
    log_error "  • Недостаточно прав доступа"
    log_error "  • Не установлены системные зависимости"
    log_error "  • Неподдерживаемая конфигурация системы"
    echo ""
    read -p "Нажмите Enter, чтобы закрыть окно (или изучите ошибку выше)..."
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
        echo ""
        read -p "Нажмите Enter для закрытия окна..."
        exit 1
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Приветствие
# ─────────────────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       $APP_NAME — Универсальный Установщик          ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
log_info "Этот скрипт установит $APP_NAME в выбранную вами папку."
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
echo "Рекомендуется: \$HOME/$INSTALL_DIR_NAME или отдельный раздел"
echo ""

# Используем zenity/kdialog или просто read
if command -v zenity &> /dev/null; then
    INSTALL_DIR=$(zenity --file-selection --directory --title="Выберите директорию установки" 2>/dev/null)
    if [ -z "$INSTALL_DIR" ]; then
        log_error "Директория не выбрана. Установка отменена."
        echo ""
        read -p "Нажмите Enter для закрытия окна..."
        exit 1
    fi
elif command -v kdialog &> /dev/null; then
    INSTALL_DIR=$(kdialog --title "Выберите директорию установки" --getexistingdirectory ~ 2>/dev/null)
    if [ -z "$INSTALL_DIR" ]; then
        log_error "Директория не выбрана. Установка отменена."
        echo ""
        read -p "Нажмите Enter для закрытия окна..."
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
    echo ""
    read -p "Нажмите Enter для закрытия окна..."
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
    echo ""
    read -p "Нажмите Enter для закрытия окна..."
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
    sudo apt update || true
    # Используем флаги для обработки конфликтов
    sudo apt install -y --fix-broken --force-confdef --force-confold $APT_PACKAGES
}

install_dnf() {
    sudo dnf install -y --allowerasing $DNF_PACKAGES
}

install_pacman() {
    sudo pacman -Sy --noconfirm --needed $PACMAN_PACKAGES
}

install_zypper() {
    sudo zypper install -y --allow-downgrade --auto-agree-with-licenses $ZYPPER_PACKAGES
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

# Создаём только основные папки в директории установки
mkdir -p "$INSTALL_DIR/core"
mkdir -p "$INSTALL_DIR/.venv"

log_success "Структура папок создана"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 7. Клонирование файлов программы из репозитория (идемпотентно)
# ─────────────────────────────────────────────────────────────────────────────
log_step "Загрузка файлов программы"
echo ""

CODE_INSTALLED=false
# Проверяем наличие основных файлов программы
if [ -d "$INSTALL_DIR/core" ] && \
   [ -f "$INSTALL_DIR/core/main.py" ] && \
   [ -f "$INSTALL_DIR/core/api.py" ]; then
    log_info "Файлы программы уже установлены. Пропускаем загрузку."
    CODE_INSTALLED=true
else
    # Если папка core есть, но файлов не хватает — пробуем доустановить
    if [ -d "$INSTALL_DIR/core" ]; then
        log_warn "Папка core существует, но файлы повреждены или отсутствуют. Доустанавливаем..."
    fi
fi

if [ "$CODE_INSTALLED" = false ]; then
    # Создаём папку core если её нет
    mkdir -p "$INSTALL_DIR/core"
    
    # Если скрипт лежит в репозитории — копируем локально
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -d "$SCRIPT_DIR/core" ] && [ -f "$SCRIPT_DIR/core/main.py" ]; then
        log_info "Копируем файлы из локального репозитория..."
        cp -rn "$SCRIPT_DIR/core/"* "$INSTALL_DIR/core/" 2>/dev/null || true
        cp -rn "$SCRIPT_DIR/shared/"* "$INSTALL_DIR/shared/" 2>/dev/null || true
        log_success "Файлы скопированы"
    else
        # Клонируем из публичного репозитория
        log_info "Клонируем репозиторий ($REPO_URL)..."
        if command -v git &> /dev/null; then
            # Клонируем во временную папку
            rm -rf "$INSTALL_DIR/tmp_clone"
            git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" "$INSTALL_DIR/tmp_clone" < /dev/null
            
            # Копируем только недостающие файлы (флаг -n для no-clobber)
            cp -rn "$INSTALL_DIR/tmp_clone/core/"* "$INSTALL_DIR/core/" 2>/dev/null || true
            cp -rn "$INSTALL_DIR/tmp_clone/shared/"* "$INSTALL_DIR/shared/" 2>/dev/null || true
            
            rm -rf "$INSTALL_DIR/tmp_clone"
            log_success "Файлы загружены из репозитория"
        else
            error_handler "git не найден. Установите git или поместите файлы программы рядом со скриптом." 6
        fi
    fi
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
numba==0.62.0
numpy>=2.0
requests
pillow
mutagen
pyyaml
colorama
psutil
setuptools
wheel
EOF

log_success "requirements.txt сгенерирован"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 9. Создание виртуального окружения (идемпотентно)
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание виртуального окружения Python"
echo ""

VENV_INSTALLED=false
if [ -f "$INSTALL_DIR/.venv/bin/activate" ]; then
    # Проверяем, что венв не битый
    if "$INSTALL_DIR/.venv/bin/python" -c "import sys" &>/dev/null; then
        log_info "Виртуальное окружение уже существует и работает. Пропускаем создание."
        VENV_INSTALLED=true
    else
        log_warn "Виртуальное окружение повреждено. Пересоздаём..."
        rm -rf "$INSTALL_DIR/.venv"
    fi
fi

if [ "$VENV_INSTALLED" = false ]; then
    log_info "Создаём виртуальное окружение..."
    "$PYTHON_CMD" -m venv "$INSTALL_DIR/.venv"
    if [ $? -ne 0 ]; then
        error_handler "Не удалось создать виртуальное окружение" 4
    fi
    log_success "Виртуальное окружение создано"
fi

# Активируем окружение
source "$INSTALL_DIR/.venv/bin/activate"
export UV_CACHE_DIR="$INSTALL_DIR/cache/uv"
export TORCH_HOME="$INSTALL_DIR/cache/torch"

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 10. Установка Python-пакетов (идемпотентно через uv)
# ─────────────────────────────────────────────────────────────────────────────
log_step "Установка Python-пакетов"
echo ""

PACKAGES_INSTALLED=false
# Проверяем наличие ключевых пакетов в виртуальном окружении
if [ -f "$INSTALL_DIR/.venv/bin/python" ] && \
   "$INSTALL_DIR/.venv/bin/python" -c "import torch; import audio_separator; import whisper" &>/dev/null; then
    log_info "Python-пакеты уже установлены. Пропускаем установку."
    PACKAGES_INSTALLED=true
fi

if [ "$PACKAGES_INSTALLED" = false ]; then
    log_info "Устанавливаем пакеты через uv (это может занять несколько минут)..."
    
    # Экспортируем переменные для работы с виртуальным окружением
    export VIRTUAL_ENV="$INSTALL_DIR/.venv"
    export PATH="$VIRTUAL_ENV/bin:$PATH"
    
    cd "$INSTALL_DIR/core"
    # Убираем --system, используем явный путь к Python из venv
    if ! uv pip install -r requirements.txt --python "$VIRTUAL_ENV/bin/python"; then
        error_handler "Не удалось установить Python-пакеты. Проверьте логи выше." 5
    fi
    
    log_success "Python-пакеты установлены"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 11. Загрузка ML-моделей (идемпотентно)
# ─────────────────────────────────────────────────────────────────────────────
log_step "Загрузка ML-моделей"
echo ""

MODELS_INSTALLED=false
if [ -f "$INSTALL_DIR/core/models/audio_separator/Kim_Vocal_1.onnx" ] && \
   [ -f "$INSTALL_DIR/core/models/whisper/medium.pt" ]; then
    log_info "ML-модели уже загружены. Пропускаем загрузку."
    MODELS_INSTALLED=true
fi

if [ "$MODELS_INSTALLED" = false ]; then
    log_info "Загружаем модели для сепарации вокала..."

    # Создаём папки моделей внутри core если их нет
    mkdir -p "$INSTALL_DIR/core/models/audio_separator"
    mkdir -p "$INSTALL_DIR/core/models/whisper"

    # Модель для сепарации вокала (Kim_Vocal_1.onnx ~79MB)
    if [ ! -f "$INSTALL_DIR/core/models/audio_separator/Kim_Vocal_1.onnx" ]; then
        log_info "Скачиваем Kim_Vocal_1.onnx..."
        if curl -fSL --connect-timeout 15 --progress-bar --retry 3 --retry-delay 5 "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_1.onnx" \
             -o "$INSTALL_DIR/core/models/audio_separator/Kim_Vocal_1.onnx"; then
            # Проверяем размер файла (должен быть > 50MB)
            MODEL_SIZE=$(stat -c%s "$INSTALL_DIR/core/models/audio_separator/Kim_Vocal_1.onnx" 2>/dev/null); MODEL_SIZE=${MODEL_SIZE:-0}
            if (( MODEL_SIZE > 50000000 )); then
                log_success "Kim_Vocal_1.onnx загружена ($(awk "BEGIN {printf \"%.1f\", $MODEL_SIZE/1048576}") MB)"
            else
                log_warn "Файл Kim_Vocal_1.onnx слишком мал, возможна ошибка загрузки"
                rm -f "$INSTALL_DIR/core/models/audio_separator/Kim_Vocal_1.onnx"
            fi
        else
            log_warn "Не удалось скачать Kim_Vocal_1.onnx (будет загружена при первом запуске)"
        fi
    else
        log_info "Kim_Vocal_1.onnx уже существует. Пропускаем."
    fi

    # Модель Whisper для транскрипции (medium.pt ~769MB)
    if [ ! -f "$INSTALL_DIR/core/models/whisper/medium.pt" ]; then
        log_info "Скачиваем Whisper medium..."
        if curl -fSL --connect-timeout 15 --progress-bar --retry 3 --retry-delay 5 "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt" \
             -o "$INSTALL_DIR/core/models/whisper/medium.pt"; then
            # Проверяем размер файла (должен быть > 500MB)
            MODEL_SIZE=$(stat -c%s "$INSTALL_DIR/core/models/whisper/medium.pt" 2>/dev/null); MODEL_SIZE=${MODEL_SIZE:-0}
            if (( MODEL_SIZE > 500000000 )); then
                log_success "Whisper medium загружена ($(awk "BEGIN {printf \"%.1f\", $MODEL_SIZE/1048576}") MB)"
            else
                log_warn "Файл Whisper medium слишком мал, возможна ошибка загрузки"
                rm -f "$INSTALL_DIR/core/models/whisper/medium.pt"
            fi
        else
            log_warn "Не удалось скачать Whisper medium (будет загружена при первом запуске)"
        fi
    else
        log_info "Whisper medium уже существует. Пропускаем."
    fi

    log_success "ML-модели загружены"
fi

# Больше не создаём символьные ссылки — модели теперь хранятся прямо в core/models
log_info "Модели находятся в $INSTALL_DIR/core/models/"

echo ""
# ─────────────────────────────────────────────────────────────────────────────
# 12. Запрос токена Genius (идемпотентно)
# ─────────────────────────────────────────────────────────────────────────────
log_step "Настройка токена Genius"
echo ""

TOKEN_INSTALLED=false
if [ -f "$INSTALL_DIR/core/.env" ] && grep -q "GENIUS_ACCESS_TOKEN=" "$INSTALL_DIR/core/.env"; then
    log_info "Токен Genius уже настроен. Пропускаем."
    TOKEN_INSTALLED=true
fi

if [ "$TOKEN_INSTALLED" = false ]; then
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║       $APP_NAME — Genius Access Token           ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    log_info "Для получения текстов песен нужен токен Genius API."
    echo ""
    echo "Как получить токен:"
    echo "   1. Откройте https://genius.com/api-clients/new"
    echo "   2. Войдите в свой аккаунт (или зарегистрируйтесь)"
    echo "   3. Заполните форму:"
    echo "      • Application name: $APP_NAME (или любое)"
    echo "      • Application website: можно оставить пустым"
    echo "      • Redirect URI: можно оставить пустым"
    echo "   4. Нажмите 'Create Client'"
    echo "   5. Скопируйте 'Client Access Token'"
    echo ""
    
    while true; do
        read -p "Вставьте токен Genius (или нажмите Enter для пропуска): " GENIUS_TOKEN
        
        if [ -z "$GENIUS_TOKEN" ]; then
            log_warn "Токен не введён. Вы сможете добавить его позже в файл .env"
            GENIUS_TOKEN="your_token_here"
            break
        fi
        
        # Простейшая валидация
        if [[ "$GENIUS_TOKEN" =~ ^[A-Za-z0-9_-]+$ ]] && [ ${#GENIUS_TOKEN} -gt 20 ]; then
            log_success "Токен принят"
            break
        else
            log_warn "Токен выглядит некорректно. Попробуйте ещё раз."
        fi
    done
    
    # Создаём .env файл в папке core
    cat > "$INSTALL_DIR/core/.env" << EOF
# $APP_NAME Configuration
GENIUS_ACCESS_TOKEN=$GENIUS_TOKEN
MODEL_PATH=$INSTALL_DIR/core/models
CACHE_PATH=$INSTALL_DIR/core/cache
LIBRARY_PATH=$INSTALL_DIR/core/library
DEBUG_PATH=$INSTALL_DIR/core/debug_logs
EOF
    
    log_success "Файл .env создан в $INSTALL_DIR/core/.env"
fi

# Создаём .env.cache если нет
if [ ! -f "$INSTALL_DIR/core/.env.cache" ]; then
    cat > "$INSTALL_DIR/core/.env.cache" << EOF
# Cache configuration
UV_CACHE_DIR=$INSTALL_DIR/core/cache/uv
TORCH_HOME=$INSTALL_DIR/core/cache/torch
HF_HOME=$INSTALL_DIR/core/cache/huggingface
HUGGINGFACE_HUB_CACHE=$INSTALL_DIR/core/cache/huggingface/hub
TRANSFORMERS_CACHE=$INSTALL_DIR/core/cache/huggingface/hub
XDG_CACHE_HOME=$INSTALL_DIR/core/cache
EOF
    # Добавляем переменную для AMD GPU
    if [ "$GPU_TYPE" = "AMD" ]; then
        echo "HSA_OVERRIDE_GFX_VERSION=11.0.0" >> "$INSTALL_DIR/core/.env.cache"
    fi
    log_success "Файл .env.cache создан в $INSTALL_DIR/core/.env.cache"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 13. Создание run.sh
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание скрипта запуска"
echo ""

RUN_SCRIPT_INSTALLED=false
if [ -f "$INSTALL_DIR/run.sh" ]; then
    log_info "Скрипт запуска уже существует. Пропускаем."
    RUN_SCRIPT_INSTALLED=true
fi

if [ "$RUN_SCRIPT_INSTALLED" = false ]; then
    cat > "$INSTALL_DIR/run.sh" << 'RUNEOF'
#!/bin/bash
# Запуск Free Karaoke

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Загружаем переменные окружения из .env.cache и .env
if [ -f "$SCRIPT_DIR/core/.env.cache" ]; then
    set -a
    source "$SCRIPT_DIR/core/.env.cache"
    set +a
fi

if [ -f "$SCRIPT_DIR/core/.env" ]; then
    set -a
    source "$SCRIPT_DIR/core/.env"
    set +a
fi

# Функция проверки и запроса токена Genius
check_genius_token() {
    # Проверяем, есть ли токен и не является ли он заглушкой
    if [ -z "$GENIUS_ACCESS_TOKEN" ] || [[ "$GENIUS_ACCESS_TOKEN" == *"ваш_токен"* ]] || [[ "$GENIUS_ACCESS_TOKEN" == "your_token_here" ]]; then
        
        # Если запущены в терминале (есть stdin)
        if [ -t 0 ]; then
            echo ""
            echo "╔══════════════════════════════════════════════════════╗"
            echo "║       Free Karaoke — Требуется токен Genius         ║"
            echo "╚══════════════════════════════════════════════════════╝"
            echo ""
            echo "Для работы с текстами песен необходим токен Genius API."
            echo ""
            echo "Как получить токен:"
            echo "  1. Откройте: https://genius.com/api-clients/new"
            echo "  2. Войдите в аккаунт (или зарегистрируйтесь)"
            echo "  3. Заполните форму и создайте клиент"
            echo "  4. Скопируйте 'Client Access Token'"
            echo ""
            
            while true; do
                read -p "Вставьте токен и нажмите Enter (или нажмите Ctrl+C для выхода): " GENIUS_TOKEN
                
                if [ -n "$GENIUS_TOKEN" ] && [[ "$GENIUS_TOKEN" =~ ^[A-Za-z0-9_-]+$ ]]; then
                    # Сохраняем токен в .env
                    echo "GENIUS_ACCESS_TOKEN=$GENIUS_TOKEN" > "$SCRIPT_DIR/core/.env"
                    export GENIUS_ACCESS_TOKEN="$GENIUS_TOKEN"
                    echo ""
                    echo "✅ Токен сохранён в $SCRIPT_DIR/core/.env"
                    echo ""
                    break
                else
                    echo "❌ Неверный формат токена. Попробуйте ещё раз."
                fi
            done
        else
            # Запуск из GUI (Desktop файл) - нет терминала
            # Используем графический диалог или открытие файла
            
            MSG="Для работы Free Karaoke необходим токен Genius API.\n\nСейчас будет открыт файл конфигурации (.env).\nВставьте полученный токен (GENIUS_ACCESS_TOKEN=...) и сохраните файл.\nПосле этого запустите программу снова."
            
            # Попытка использовать zenity для уведомления
            if command -v zenity &> /dev/null; then
                zenity --warning --title="Требуется настройка Free Karaoke" --text="$MSG" --width=450 2>/dev/null || true
            elif command -v kdialog &> /dev/null; then
                kdialog --sorry "$MSG" --title "Требуется настройка Free Karaoke" 2>/dev/null || true
            elif command -v notify-send &> /dev/null; then
                notify-send "Free Karaoke: Требуется токен" "$MSG" 2>/dev/null || true
            fi
            
            # Открываем файл .env в редакторе по умолчанию
            echo "📝 Открытие файла конфигурации для ввода токена..."
            
            if command -v xdg-open &> /dev/null; then
                xdg-open "$SCRIPT_DIR/core/.env" &
            elif command -v gnome-text-editor &> /dev/null; then
                gnome-text-editor "$SCRIPT_DIR/core/.env" &
            elif command -v kate &> /dev/null; then
                kate "$SCRIPT_DIR/core/.env" &
            elif command -v mousepad &> /dev/null; then
                mousepad "$SCRIPT_DIR/core/.env" &
            elif command -v geany &> /dev/null; then
                geany "$SCRIPT_DIR/core/.env" &
            else
                # Если ничего не нашли, пробуем через переменные окружения
                ${EDITOR:-nano} "$SCRIPT_DIR/core/.env" 2>/dev/null || echo "❌ Не удалось открыть редактор. Откройте файл вручную: $SCRIPT_DIR/core/.env"
            fi
            
            echo ""
            echo "⚠️  Программа остановлена."
            echo "   1. Вставьте токен в открывшийся файл."
            echo "   2. Сохраните файл."
            echo "   3. Запустите Free Karaoke повторно."
            echo ""
            
            # Завершаем скрипт, чтобы пользователь сохранил файл и перезапустил
            exit 0
        fi
    fi
}

# Выполняем проверку токена
check_genius_token

# Активируем виртуальное окружение
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
else
    echo "❌ Виртуальное окружение не найдено!"
    echo "Запустите установку заново."
    exit 1
fi

# Экспортируем пути (теперь все пути внутри core)
export MODEL_PATH="${MODEL_PATH:-$SCRIPT_DIR/core/models}"
export CACHE_PATH="${CACHE_PATH:-$SCRIPT_DIR/core/cache}"
export LIBRARY_PATH="${LIBRARY_PATH:-$SCRIPT_DIR/core/library}"

# PyTorch ROCm fix для AMD
if [ "$HSA_OVERRIDE_GFX_VERSION" ]; then
    export HSA_OVERRIDE_GFX_VERSION="$HSA_OVERRIDE_GFX_VERSION"
fi

# Запускаем приложение
echo "🚀 Запуск Free Karaoke..."
exec python "$SCRIPT_DIR/core/main.py" "$@"
RUNEOF
    
    chmod +x "$INSTALL_DIR/run.sh"
    log_success "Скрипт запуска создан: $INSTALL_DIR/run.sh"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 14. Создание desktop-файла (идемпотентно)
# ─────────────────────────────────────────────────────────────────────────────
log_step "Создание desktop-файла"
echo ""

DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

DESKTOP_INSTALLED=false
if [ -f "$DESKTOP_DIR/$DESKTOP_FILE_NAME" ]; then
    log_info "Desktop-файл уже существует. Пропускаем."
    DESKTOP_INSTALLED=true
fi

if [ "$DESKTOP_INSTALLED" = false ]; then
    cat > "$DESKTOP_DIR/$DESKTOP_FILE_NAME" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=$APP_NAME
Comment=Создание караоке-версий песен с помощью ИИ
Exec=$INSTALL_DIR/run.sh
Icon=audio-x-generic
Terminal=false
Categories=AudioVideo;Audio;
Keywords=karaoke;music;audio;ai;
StartupNotify=true
EOF
    
    chmod +x "$DESKTOP_DIR/$DESKTOP_FILE_NAME"
    log_success "Desktop-файл создан: $DESKTOP_DIR/$DESKTOP_FILE_NAME"
fi

# Обновляем базу desktop-файлов
if command -v update-desktop-database &> /dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 15. Финальная проверка
# ─────────────────────────────────────────────────────────────────────────────
log_step "Финальная проверка"
echo ""

ERRORS=0

if [ ! -f "$INSTALL_DIR/.venv/bin/activate" ]; then
    log_error "Виртуальное окружение не найдено"
    ERRORS=$((ERRORS + 1))
fi

if [ ! -f "$INSTALL_DIR/run.sh" ]; then
    log_error "Скрипт запуска не найден"
    ERRORS=$((ERRORS + 1))
fi

if [ ! -f "$DESKTOP_DIR/$DESKTOP_FILE_NAME" ]; then
    log_error "Desktop-файл не создан"
    ERRORS=$((ERRORS + 1))
fi

if [ $ERRORS -eq 0 ]; then
    log_success "Все проверки пройдены!"
else
    log_warn "Обнаружено ошибок: $ERRORS"
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Завершение
# ─────────────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════╗"
echo "║              Установка завершена!                    ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
log_success "$APP_NAME успешно установлена в: $INSTALL_DIR"
echo ""
echo "Запуск приложения:"
echo "   • Через меню приложений: найдите '$APP_NAME'"
echo "   • Через терминал: $INSTALL_DIR/run.sh"
echo ""
echo "Дополнительно:"
echo "   • Токен Genius можно изменить в: $INSTALL_DIR/core/.env"
echo "   • Логи находятся в: $INSTALL_DIR/core/debug_logs (создаются при запуске)"
echo "   • Библиотека треков: $INSTALL_DIR/core/library (создается при запуске)"
echo ""
log_info "Спасибо за использование $APP_NAME!"
echo ""
read -p "Нажмите Enter для закрытия окна..."

exit 0
