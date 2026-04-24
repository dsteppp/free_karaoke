#!/bin/bash

# ==============================================================================
# Free Karaoke Android APK Builder
# Версия: 6.2 (Fixed Spec Version Parameter)
# ==============================================================================
# Исправление v6.2:
# Добавлен обязательный параметр 'version = 0.1' в шаблон buildozer.spec.
# Без него сборка завершается ошибкой валидации конфигурации.
# ==============================================================================

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Глобальные переменные
LOG_FILE=""
BUILD_ROOT=""
REPO_URL="https://github.com/dsteppp/free_karaoke.git"
REQUIRED_PYTHON_VER="3.11"
CMAKE_VERSION="3.24.3"
CMAKE_DIR=""

# ------------------------------------------------------------------------------
# Функции логирования
# ------------------------------------------------------------------------------
log() {
    local msg="$1"
    local level="${2:-INFO}"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local colored_msg=""

    case "$level" in
        ERROR)   colored_msg="${RED}ERROR: $msg${NC}" ;;
        SUCCESS) colored_msg="${GREEN}SUCCESS: $msg${NC}" ;;
        WARN)    colored_msg="${YELLOW}WARN: $msg${NC}" ;;
        *)       colored_msg="${BLUE}INFO: $msg${NC}" ;;
    esac

    echo -e "$colored_msg"

    if [ -n "$LOG_FILE" ]; then
        echo "[$timestamp] $level: $msg" >> "$LOG_FILE"
    fi
}

log_error_exit() {
    log "$1" "ERROR"
    echo ""
    read -p "Нажмите Enter для выхода..."
    exit 1
}

# Обработчик ошибок (Trap)
trap 'last_line=$LINENO; log "Критическая ошибка на строке $last_line. Проверьте логи." "ERROR"; read -p "Нажмите Enter для выхода..."; exit 1' ERR

# ------------------------------------------------------------------------------
# Шаг 0: Принудительный запуск в терминале
# ------------------------------------------------------------------------------
if [ -z "${TERM:-}" ] || [ "$TERM" == "dumb" ]; then
    TERMINALS=("gnome-terminal" "konsole" "xfce4-terminal" "xterm" "alacritty" "kitty" "roxterm" "mate-terminal")
    FOUND_TERM=""
    SCRIPT_PATH="$(readlink -f "$0")"

    for t in "${TERMINALS[@]}"; do
        if command -v "$t" &> /dev/null; then
            FOUND_TERM="$t"
            break
        fi
    done

    if [ -n "$FOUND_TERM" ]; then
        case "$FOUND_TERM" in
            gnome-terminal) gnome-terminal -- "$SCRIPT_PATH" ;;
            konsole) konsole -e "$SCRIPT_PATH" ;;
            xfce4-terminal) xfce4-terminal -e "$SCRIPT_PATH" ;;
            xterm) xterm -e "$SCRIPT_PATH" ;;
            alacritty|kitty) $FOUND_TERM -e "$SCRIPT_PATH" ;;
            *) $FOUND_TERM -e "$SCRIPT_PATH" ;;
        esac
        exit 0
    else
        echo "Ошибка: Не найден эмулятор терминала."
        echo "Запустите скрипт вручную из терминала командой: bash $0"
        read -p "Нажмите Enter..."
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# Шаг 1: Инициализация и выбор директории
# ------------------------------------------------------------------------------
clear
echo "=============================================="
echo "  Free Karaoke Android APK Builder v6.2     "
echo "=============================================="
echo ""
log "Добро пожаловать! Этот скрипт создаст APK файл."
log "Требуется Python версии $REQUIRED_PYTHON_VER."
log "Скрипт автоматически загрузит совместимую версию CMake."
log "Все файлы будут загружены и собраны в указанной вами папке."
echo ""

while true; do
    read -p "Введите полный путь к папке для сборки (например, /home/user/apk_build): " BUILD_ROOT

    if [ -z "$BUILD_ROOT" ]; then
        log "Путь не может быть пустым." "ERROR"
        continue
    fi

    if mkdir -p "$BUILD_ROOT"/{src,logs,output,env,tools} 2>/dev/null; then
        break
    else
        log "Не удалось создать директорию $BUILD_ROOT. Проверьте права доступа." "ERROR"
    fi
done

LOG_FILE="$BUILD_ROOT/logs/build_script.log"
: > "$LOG_FILE" # Очистка лога

log "Директория сборки: $BUILD_ROOT"
log "Лог файл: $LOG_FILE"
echo ""

# ------------------------------------------------------------------------------
# Шаг 2: Проверка Python 3.11 (ЖЕСТКОЕ ТРЕБОВАНИЕ)
# ------------------------------------------------------------------------------
log "Проверка наличия Python $REQUIRED_PYTHON_VER..."

PYTHON_BIN=""

if command -v python3.11 &> /dev/null; then
    PYTHON_BIN="python3.11"
    log "Найден Python 3.11: $(which python3.11)" "SUCCESS"
else
    log "Python $REQUIRED_PYTHON_VER НЕ найден в системе." "ERROR"
    echo ""
    echo "Для успешной сборки требуется именно Python 3.11."
    echo "Пожалуйста, установите его, используя команды для вашего дистрибутива:"
    echo ""
    
    if command -v yay &> /dev/null; then
        echo -e "${GREEN}Arch Linux (yay):${NC}"
        echo "  yay -S python311 python311-pip python311-virtualenv"
        echo ""
    elif command -v pacman &> /dev/null; then
        echo -e "${GREEN}Arch Linux (pacman):${NC}"
        echo "  sudo pacman -S python311 python311-pip python311-virtualenv"
        echo ""
    elif command -v apt &> /dev/null; then
        echo -e "${GREEN}Debian/Ubuntu:${NC}"
        echo "  sudo apt update"
        echo "  sudo apt install python3.11 python3.11-venv python3.11-dev"
        echo ""
    elif command -v dnf &> /dev/null; then
        echo -e "${GREEN}Fedora:${NC}"
        echo "  sudo dnf install python3.11 python3.11-pip python3.11-devel"
        echo ""
    elif command -v zypper &> /dev/null; then
        echo -e "${GREEN}OpenSUSE:${NC}"
        echo "  sudo zypper install python3.11 python3.11-pip python3.11-devel"
        echo ""
    else
        echo "Установите Python 3.11 любым доступным способом."
        echo ""
    fi
    
    log_error_exit "Скрипт не может продолжить работу без Python 3.11."
fi

# ------------------------------------------------------------------------------
# Шаг 3: Установка системных зависимостей (Без CMake!)
# ------------------------------------------------------------------------------
log "Проверка и установка системных зависимостей..."
log "Примечание: Системный CMake будет проигнорирован в пользу изолированной версии."

PKG_MANAGER=""
INSTALL_CMD=""

if command -v yay &> /dev/null; then
    PKG_MANAGER="yay"
    INSTALL_CMD="yay -S --noconfirm --needed"
    log "Обнаружен: yay (Arch/AUR)"
elif command -v pacman &> /dev/null; then
    PKG_MANAGER="pacman"
    INSTALL_CMD="sudo pacman -S --noconfirm --needed"
    log "Обнаружен: pacman (Arch)"
elif command -v apt &> /dev/null; then
    PKG_MANAGER="apt"
    INSTALL_CMD="sudo apt install -y"
    log "Обнаружен: apt (Debian/Ubuntu)"
elif command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
    INSTALL_CMD="sudo dnf install -y"
    log "Обнаружен: dnf (Fedora)"
elif command -v zypper &> /dev/null; then
    PKG_MANAGER="zypper"
    INSTALL_CMD="sudo zypper install -y"
    log "Обнаружен: zypper (OpenSUSE)"
else
    log_error_exit "Не удалось определить менеджер пакетов."
fi

PACKAGES=()

if [[ "$PKG_MANAGER" == "pacman" || "$PKG_MANAGER" == "yay" ]]; then
    PACKAGES=(
        git zip unzip jdk-openjdk 
        libffi openssl zlib gcc base-devel autoconf automake libtool 
        pkgconf libglvnd gstreamer gst-plugins-base gst-plugins-good 
        ninja wget
    )
elif [[ "$PKG_MANAGER" == "apt" ]]; then
    PACKAGES=(
        git zip unzip openjdk-17-jdk 
        libffi-dev libssl-dev zlib1g-dev gcc build-essential 
        autoconf automake libtool pkg-config libgl1-mesa-dev 
        gstreamer1.0-dev gstreamer1.0-plugins-base gstreamer1.0-plugins-good 
        ninja-build wget python3.11-dev
    )
elif [[ "$PKG_MANAGER" == "dnf" ]]; then
    PACKAGES=(
        git zip unzip java-17-openjdk-devel 
        libffi-devel openssl-devel zlib-devel gcc gcc-c++ make 
        autoconf automake libtool pkg-config mesa-libGL-devel 
        gstreamer1-devel gstreamer1-plugins-base-devel gstreamer1-plugins-good 
        ninja-build wget python3.11-devel
    )
else
    PACKAGES=(
        git zip unzip java-17-openjdk-devel 
        libffi-devel libopenssl-devel zlib-devel gcc make 
        autoconf automake libtool pkg-config Mesa-libGL-devel 
        gstreamer-devel gstreamer-plugins-base-devel gstreamer-plugins-good 
        ninja wget python3.11-devel
    )
fi

log "Требуемые пакеты: ${PACKAGES[*]}"
read -p "Продолжить установку зависимостей? (требуется sudo/root) (y/n): " CONFIRM
if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    log_error_exit "Установка отменена пользователем."
fi

log "Запуск установки пакетов..."
if ! $INSTALL_CMD "${PACKAGES[@]}"; then
    log "Некоторые пакеты не удалось установить. Попробуйте установить их вручную." "WARN"
fi

# Проверка Java
if ! command -v java &> /dev/null; then
    log_error_exit "Java не найдена после установки. Сборка невозможна."
fi

export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
log "JAVA_HOME установлен: $JAVA_HOME"

# ------------------------------------------------------------------------------
# Шаг 4: Подготовка изолированного CMake
# ------------------------------------------------------------------------------
log "Настройка изолированной среды CMake $CMAKE_VERSION..."
CMAKE_DIR="$BUILD_ROOT/tools/cmake-$CMAKE_VERSION-linux-x86_64"

if [ ! -d "$CMAKE_DIR" ]; then
    log "Загрузка CMake $CMAKE_VERSION..."
    CMAKE_TARBALL="cmake-$CMAKE_VERSION-linux-x86_64.tar.gz"
    CMAKE_URL="https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/$CMAKE_TARBALL"
    
    cd "$BUILD_ROOT/tools"
    if ! wget --show-progress "$CMAKE_URL" -O "$CMAKE_TARBALL"; then
        log_error_exit "Не удалось загрузить CMake. Проверьте соединение."
    fi
    
    log "Распаковка CMake..."
    tar -xzf "$CMAKE_TARBALL"
    rm "$CMAKE_TARBALL"
    
    if [ ! -d "$CMAKE_DIR" ]; then
        log_error_exit "Ошибка распаковки CMake. Директория не найдена."
    fi
else
    log "Изолированный CMake уже найден." "SUCCESS"
fi

export PATH="$CMAKE_DIR/bin:$PATH"
CMAKE_CHECK=$("$CMAKE_DIR/bin/cmake" --version | head -n 1)
log "Активирован CMake: $CMAKE_CHECK" "SUCCESS"

# ------------------------------------------------------------------------------
# Шаг 5: Работа с репозиторием
# ------------------------------------------------------------------------------
log "Подготовка исходного кода..."

PROJECT_DIR="$BUILD_ROOT/src/project_src"

if [ -d "$PROJECT_DIR/.git" ]; then
    log "Репозиторий найден. Обновление..."
    cd "$PROJECT_DIR"
    git fetch --all
    git reset --hard origin/main || git reset --hard origin/master
    git pull
else
    log "Клонирование репозитория..."
    rm -rf "$PROJECT_DIR"
    git clone "$REPO_URL" "$PROJECT_DIR" || log_error_exit "Ошибка клонирования."
fi

cd "$PROJECT_DIR"
log "Код готов в: $PROJECT_DIR"

# ------------------------------------------------------------------------------
# Шаг 6: Python окружение (на базе Python 3.11) и Buildozer
# ------------------------------------------------------------------------------
log "Настройка виртуального окружения на Python $REQUIRED_PYTHON_VER..."
cd "$BUILD_ROOT"

ENV_PYTHON="$BUILD_ROOT/env/bin/python"

if [ -d "env" ]; then
    if ! "$ENV_PYTHON" -c "pass" 2>/dev/null; then
        log "Окружение повреждено, пересоздание..."
        rm -rf env
        $PYTHON_BIN -m venv env
    else
        EXISTING_VER=$("$ENV_PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        if [ "$EXISTING_VER" != "$REQUIRED_PYTHON_VER" ]; then
            log "Версия Python в окружении ($EXISTING_VER) не совпадает с требуемой ($REQUIRED_PYTHON_VER). Пересоздание..."
            rm -rf env
            $PYTHON_BIN -m venv env
        fi
    fi
else
    $PYTHON_BIN -m venv env
fi

source env/bin/activate

log "Обновление pip..."
pip install --upgrade pip setuptools wheel

log "Установка Cython и зависимостей..."
pip install "Cython<3.0" requests packaging

log "Установка Buildozer (из git)..."
pip install --upgrade "git+https://github.com/kivy/buildozer.git"

# ------------------------------------------------------------------------------
# Шаг 7: УМНАЯ ОЧИСТКА (Smart Cleanup) - КРИТИЧЕСКИЙ ЭТАП
# ------------------------------------------------------------------------------
log "Глубокая очистка кэша сборки для предотвращения конфликтов..."

# 1. Полное удаление кэша сборки (build-*)
BUILD_CACHE_DIRS=("$PROJECT_DIR/.buildozer/android/platform/build-"*)
for dir in "${BUILD_CACHE_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        log "Удаление старого кэша сборки: $dir"
        rm -rf "$dir"
    fi
done

# 2. Очистка временной директории приложения
APP_BUILD_DIR="$PROJECT_DIR/.buildozer/android/app"
if [ -d "$APP_BUILD_DIR" ]; then
    log "Очистка временной копии приложения..."
    rm -rf "$APP_BUILD_DIR"
fi

# 3. Удаление старых APK
BIN_DIR="$PROJECT_DIR/bin"
if [ -d "$BIN_DIR" ]; then
    rm -f "$BIN_DIR"/*.apk 2>/dev/null || true
fi

# 4. Принудительное удаление main.py и buildozer.spec перед генерацией
rm -f "$PROJECT_DIR/main.py"
rm -f "$PROJECT_DIR/buildozer.spec"

log "Очистка завершена. Готово к модификации." "SUCCESS"

# ------------------------------------------------------------------------------
# Шаг 8: Создание buildozer.spec (Атомарная запись)
# ------------------------------------------------------------------------------
log "Создание нового buildozer.spec с нуля..."

SPEC_FILE="$PROJECT_DIR/buildozer.spec"

# Записываем весь файл целиком, чтобы избежать дубликатов
# ДОБАВЛЕНО: version = 0.1
cat > "$SPEC_FILE" << 'SPEC_EOF'
[app]
title = Free Karaoke
version = 0.1
package.name = freekaraoke
package.domain = org.freekaraoke
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf,wav,mp3
orientation = landscape
osx.python_version = 3.11
min_android_version = 7.0
android.api = 33
android.ndk = 25b
android.permissions = INTERNET, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, ACCESS_FINE_LOCATION, RECORD_AUDIO, MODIFY_AUDIO_SETTINGS
requirements = python3,kivy==2.3.0,requests,chardet,mutagen,pillow,pyjnius
android.accept_all_licenses = True
android.add_args = --orientation=sensorLandscape
[buildozer]
log_level = 2
warn_on_root = 1
SPEC_EOF

log "buildozer.spec создан." "SUCCESS"

# ------------------------------------------------------------------------------
# Шаг 9: Патчинг кода и создание main.py
# ------------------------------------------------------------------------------
log "Внедрение заглушек для ML функций и создание точки входа..."

# Экспорт переменной для Python
export PROJECT_DIR

python3 << 'PYEOF'
import os
import re

project_dir = os.environ.get('PROJECT_DIR', '.')
warn_func_code = '''
def show_android_warning(title="Внимание"):
    from kivy.utils import platform
    if platform == "android":
        from kivy.uix.popup import Popup
        from kivy.uix.label import Label
        from kivy.clock import Clock
        def _show(*args):
            popup = Popup(title=title,
                          content=Label(text="Эта функция требует работы нейросетей и доступна только в Desktop версии."),
                          size_hint=(0.8, 0.3))
            popup.open()
        Clock.schedule_once(_show, 0)
        return True
    return False
'''

target_files = []
for root, dirs, files in os.walk(project_dir):
    if "env" in root or ".buildozer" in root or "__pycache__" in root or "bin" in root:
        continue
    for f in files:
        if f.endswith(".py"):
            target_files.append(os.path.join(root, f))

app_class_name = "FreeKaraokeApp"
found_class = False

core_main_path = os.path.join(project_dir, "core", "main.py")
if os.path.exists(core_main_path):
    try:
        with open(core_main_path, 'r', encoding='utf-8') as f:
            content = f.read()
            match = re.search(r'class\s+(\w+App)\s*\([^)]*App[^)]*\):', content)
            if match:
                app_class_name = match.group(1)
                found_class = True
                print(f"Найден главный класс приложения: {app_class_name}")
            else:
                match = re.search(r'class\s+(\w+)\s*\(App\):', content)
                if match:
                    app_class_name = match.group(1)
                    found_class = True
                    print(f"Найден главный класс (простой поиск): {app_class_name}")
    except Exception as e:
        print(f"Предупреждение: Не удалось прочитать core/main.py: {e}")

if not found_class:
    print("Предупреждение: Класс не найден. Используется: FreeKaraokeApp")

# Патчинг файлов
for fpath in target_files:
    try:
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        modified = False
        
        if any(x in fpath for x in ["main.py", "app.py", "main_window.py"]):
            if "from kivy.utils import platform" not in content:
                content = "from kivy.utils import platform\n" + content
                modified = True
            
            if "def show_android_warning" not in content:
                content += "\n" + warn_func_code
                modified = True
            
            if "class App" in content or "class MainApp" in content:
                if "Config.set('graphics', 'orientation')" not in content:
                    if "from kivy.config import Config" in content:
                        content = content.replace(
                            "from kivy.config import Config",
                            "from kivy.config import Config\nConfig.set('graphics', 'orientation', 'sensorLandscape')"
                        )
                        modified = True
                    elif "import kivy" in content:
                         content = content.replace(
                             "import kivy",
                             "import kivy\nfrom kivy.config import Config\nConfig.set('graphics', 'orientation', 'sensorLandscape')"
                         )
                         modified = True

        ml_keywords = ["separate", "transcribe", "rescan", "fix_library", "process_ml", "on_load_track", "on_rescan", "on_fix"]
        
        lines = content.split('\n')
        new_lines = []
        
        for line in lines:
            new_lines.append(line)
            match = re.match(r'^(\s*)def\s+(\w+).*:', line)
            if match:
                func_indent = match.group(1)
                func_name = match.group(2)
                if any(k in func_name.lower() for k in ml_keywords):
                    new_lines.append(f"{func_indent}    if platform == 'android':")
                    new_lines.append(f"{func_indent}        show_android_warning('Функция недоступна на Android')")
                    new_lines.append(f"{func_indent}        return")
                    modified = True
        
        if modified:
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(new_lines))
                
    except Exception as e:
        pass

# СОЗДАНИЕ main.py
main_py_path = os.path.join(project_dir, "main.py")
print(f"Создание точки входа: {main_py_path}")

entry_content = f"""# Auto-generated entry point for Android Build
# Generated by Free Karaoke APK Builder v6.2
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from core.main import {app_class_name}
    
    if __name__ == '__main__':
        print(f"Starting {{ {app_class_name} }}...")
        {app_class_name}().run()
        
except ImportError as e:
    print(f"Error importing core.main.{app_class_name}: {{e}}")
    try:
        from main_window import {app_class_name}
        if __name__ == '__main__':
            {app_class_name}().run()
    except Exception as e2:
        print(f"Fallback error: {{e2}}")
        raise
"""

with open(main_py_path, 'w', encoding='utf-8') as f:
    f.write(entry_content)

print(f"main.py успешно создан с классом {app_class_name}.")

PYEOF

# ------------------------------------------------------------------------------
# Шаг 10: ФИНАЛЬНАЯ ПРОВЕРКА ПЕРЕД СБОРКОЙ
# ------------------------------------------------------------------------------
log "Проверка целостности файлов перед сборкой..."

if [ ! -f "$PROJECT_DIR/main.py" ]; then
    log_error_exit "Критическая ошибка: main.py не был создан!"
fi

if [ ! -f "$PROJECT_DIR/buildozer.spec" ]; then
    log_error_exit "Критическая ошибка: buildozer.spec не был создан!"
fi

# Проверка, что spec не содержит дубликатов
ORIENTATION_COUNT=$(grep -c "^orientation = " "$PROJECT_DIR/buildozer.spec" || true)
if [ "$ORIENTATION_COUNT" -gt 1 ]; then
    log_error_exit "Критическая ошибка: В buildozer.spec обнаружены дубликаты параметра orientation!"
fi

# Проверка наличия version
if ! grep -q "^version = " "$PROJECT_DIR/buildozer.spec"; then
    log_error_exit "Критическая ошибка: В buildozer.spec отсутствует параметр version!"
fi

log "Все проверки пройдены успешно." "SUCCESS"

# ------------------------------------------------------------------------------
# Шаг 11: Сборка APK
# ------------------------------------------------------------------------------
log "НАЧАЛО СБОРКИ APK (это займет от 15 до 40 минут)..."
log "Не закрывайте окно терминала!"

cd "$PROJECT_DIR"

export CMAKE_POLICY_VERSION_MINIMUM=3.5
log "Используется изолированный CMake из: $CMAKE_DIR/bin"
log "Установлена переменная CMAKE_POLICY_VERSION_MINIMUM=3.5."

set +e
buildozer -v android debug release 2>&1 | tee "$BUILD_ROOT/logs/buildozer_output.log"
BUILD_CODE=${PIPESTATUS[0]}
set -e

if [ $BUILD_CODE -ne 0 ]; then
    log "Сборка завершилась с ошибкой (код $BUILD_CODE)." "ERROR"
    log "Проверьте файл $BUILD_ROOT/logs/buildozer_output.log для деталей." "ERROR"
else
    log "Сборка успешна!" "SUCCESS"
fi

BIN_DIR="$PROJECT_DIR/bin"
if [ -d "$BIN_DIR" ]; then
    APK_COUNT=$(find "$BIN_DIR" -name "*.apk" | wc -l)
    if [ "$APK_COUNT" -gt 0 ]; then
        mkdir -p "$BUILD_ROOT/output"
        cp "$BIN_DIR"/*.apk "$BUILD_ROOT/output/"
        log "APK файлы скопированы в: $BUILD_ROOT/output" "SUCCESS"
        ls -lh "$BUILD_ROOT/output"
    else
        log "APK файл не найден в bin/, несмотря на успешный код возврата." "WARN"
    fi
fi

# ------------------------------------------------------------------------------
# Шаг 12: Финал
# ------------------------------------------------------------------------------
echo ""
log "Процесс завершен."
log "Результат: $BUILD_ROOT/output"
log "Логи: $BUILD_ROOT/logs"

read -p "Удалить временные файлы (src, env, tools) для экономии места? (y/n): " CLEANUP
if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    log "Очистка..."
    rm -rf "$BUILD_ROOT/src"
    rm -rf "$BUILD_ROOT/env"
    rm -rf "$BUILD_ROOT/tools"
    log "Готово. Оставлены только APK и логи." "SUCCESS"
else
    log "Временные файлы сохранены. Вы можете удалить папку tools вручную позже."
fi

echo ""
read -p "Нажмите Enter для выхода..."