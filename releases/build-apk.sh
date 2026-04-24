#!/bin/bash

# ==============================================================================
# Free Karaoke Android Release Builder (FastAPI + WebView Edition)
# Версия: 7.8 (SDK Tools Locator - Final)
# ==============================================================================

set -euo pipefail

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

LOG_FILE=""
BUILD_ROOT=""
REPO_URL="https://github.com/dsteppp/free_karaoke.git"
REQUIRED_PYTHON_VER="3.11"
CMAKE_VERSION="3.24.3"

# ------------------------------------------------------------------------------
# Функции логирования
# ------------------------------------------------------------------------------
log() {
    local msg="$1"
    local level="${2:-INFO}"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local colored_msg=""

    case "$level" in
        ERROR)   colored_msg="${RED}[ERROR] $msg${NC}" ;;
        SUCCESS) colored_msg="${GREEN}[SUCCESS] $msg${NC}" ;;
        WARN)    colored_msg="${YELLOW}[WARN] $msg${NC}" ;;
        *)       colored_msg="${BLUE}[INFO] $msg${NC}" ;;
    esac

    echo -e "$colored_msg"
    if [ -n "$LOG_FILE" ]; then echo "[$timestamp] $level: $msg" >> "$LOG_FILE"; fi
}

log_error_exit() {
    log "$1" "ERROR"
    echo ""
    read -p "Нажмите Enter для выхода..."
    exit 1
}

trap 'last_line=$LINENO; log "Критическая ошибка на строке $last_line. Проверьте логи: $LOG_FILE" "ERROR"; read -p "Нажмите Enter для выхода..."; exit 1' ERR

# ------------------------------------------------------------------------------
# Шаг 0: Принудительный запуск в терминале
# ------------------------------------------------------------------------------
if [ -z "${TERM:-}" ] || [ "$TERM" == "dumb" ]; then
    TERMINALS=("konsole" "gnome-terminal" "xfce4-terminal" "alacritty" "kitty" "xterm")
    SCRIPT_PATH="$(readlink -f "$0")"
    for t in "${TERMINALS[@]}"; do
        if command -v "$t" &> /dev/null; then
            if [[ "$t" == "gnome-terminal" ]]; then
                $t -- "$SCRIPT_PATH"
            else
                $t -e "$SCRIPT_PATH"
            fi
            exit 0
        fi
    done
    echo "Запустите скрипт вручную из эмулятора терминала командой: bash $0"
    exit 1
fi

clear
echo -e "${GREEN}==============================================${NC}"
echo -e "${GREEN}  Free Karaoke Android Builder (Release)      ${NC}"
echo -e "${GREEN}==============================================${NC}"
log "Инициализация среды сборки APK..."

# ------------------------------------------------------------------------------
# Шаг 1: Выбор директории
# ------------------------------------------------------------------------------
while true; do
    read -p "Введите полный путь к папке для сборки (например, /home/$USER/apk_build): " BUILD_ROOT
    if [ -z "$BUILD_ROOT" ]; then continue; fi
    if mkdir -p "$BUILD_ROOT"/{src,logs,output,env,tools,keystore} 2>/dev/null; then break; else log "Ошибка доступа к директории." "ERROR"; fi
done

LOG_FILE="$BUILD_ROOT/logs/build_script.log"
: > "$LOG_FILE"
log "Рабочая директория: $BUILD_ROOT"

# ------------------------------------------------------------------------------
# Шаг 2: Установка системных зависимостей
# ------------------------------------------------------------------------------
log "Проверка менеджера пакетов и зависимостей..."
INSTALL_CMD=""
if command -v yay &> /dev/null; then INSTALL_CMD="yay -S --noconfirm --needed"
elif command -v pacman &> /dev/null; then INSTALL_CMD="sudo pacman -S --noconfirm --needed"
elif command -v apt &> /dev/null; then INSTALL_CMD="sudo apt update && sudo apt install -y"
elif command -v dnf &> /dev/null; then INSTALL_CMD="sudo dnf install -y"
else log_error_exit "Не найден поддерживаемый менеджер пакетов (yay, pacman, apt, dnf)."; fi

PACKAGES=()
if [[ "$INSTALL_CMD" == *"yay"* || "$INSTALL_CMD" == *"pacman"* ]]; then
    PACKAGES=(python311 jdk17-openjdk git zip unzip libffi openssl zlib gcc base-devel pkgconf gstreamer wget ninja)
elif [[ "$INSTALL_CMD" == *"apt"* ]]; then
    PACKAGES=(python3.11 openjdk-17-jdk git zip unzip libffi-dev libssl-dev zlib1g-dev gcc build-essential pkg-config wget ninja-build)
fi

if ! command -v ninja &> /dev/null; then
    log "Установка системных пакетов (может потребоваться пароль sudo)..."
    eval "$INSTALL_CMD ${PACKAGES[*]}" || log "Некоторые пакеты уже установлены или недоступны." "WARN"
fi

if [ -d "/usr/lib/jvm/java-17-openjdk" ]; then
    export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
elif [ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]; then
    export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"
elif [ -d "/usr/lib/jvm/jre-17-openjdk" ]; then
    export JAVA_HOME="/usr/lib/jvm/jre-17-openjdk"
else
    export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
fi
export PATH="$JAVA_HOME/bin:$PATH"
log "Используется Java: $JAVA_HOME" "SUCCESS"

# ------------------------------------------------------------------------------
# Шаг 3: Подготовка CMake 3.24.3
# ------------------------------------------------------------------------------
log "Настройка изолированной среды CMake $CMAKE_VERSION..."
CMAKE_DIR="$BUILD_ROOT/tools/cmake-$CMAKE_VERSION-linux-x86_64"

if [ ! -d "$CMAKE_DIR" ]; then
    CMAKE_TARBALL="cmake-$CMAKE_VERSION-linux-x86_64.tar.gz"
    CMAKE_URL="https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/$CMAKE_TARBALL"
    cd "$BUILD_ROOT/tools"
    if ! wget -q --show-progress "$CMAKE_URL" -O "$CMAKE_TARBALL"; then
        log_error_exit "Не удалось загрузить CMake. Проверьте соединение."
    fi
    tar -xzf "$CMAKE_TARBALL"
    rm "$CMAKE_TARBALL"
fi

export PATH="$CMAKE_DIR/bin:$PATH"
export CMAKE_POLICY_VERSION_MINIMUM=3.5

# ------------------------------------------------------------------------------
# Шаг 4: Работа с репозиторием
# ------------------------------------------------------------------------------
PROJECT_DIR="$BUILD_ROOT/src/project_src"
log "Загрузка актуального кода проекта..."

if [ -d "$PROJECT_DIR/.git" ]; then
    cd "$PROJECT_DIR"
    git fetch --all && git reset --hard origin/main || git reset --hard origin/master
    git pull
else
    cd "$BUILD_ROOT"
    rm -rf "$PROJECT_DIR"
    git clone "$REPO_URL" "$PROJECT_DIR"
fi
cd "$BUILD_ROOT"

# ------------------------------------------------------------------------------
# Шаг 5: Виртуальное окружение
# ------------------------------------------------------------------------------
log "Создание изолированного Python окружения..."
if [ -d "env" ]; then rm -rf env; fi
python3.11 -m venv env
source env/bin/activate
pip install --upgrade pip setuptools wheel
pip install "Cython<3.0" requests packaging
pip install --upgrade "git+https://github.com/kivy/buildozer.git"

# ------------------------------------------------------------------------------
# Шаг 6: Глубокая очистка
# ------------------------------------------------------------------------------
log "Очистка кэша сборки (без удаления скачанных SDK/NDK)..."
rm -rf "$PROJECT_DIR/.buildozer" 2>/dev/null || true
rm -rf "$PROJECT_DIR/bin" 2>/dev/null || true

# ------------------------------------------------------------------------------
# Шаг 7: Патчинг кода
# ------------------------------------------------------------------------------
log "Модификация бэкенда: отключение ML и настройка WebView..."
export PROJECT_DIR
python3 << 'PYEOF'
import os

project_dir = os.environ.get('PROJECT_DIR', '.')
req_path = os.path.join(project_dir, 'requirements.txt')
safe_reqs = ['python3', 'fastapi', 'uvicorn', 'jinja2', 'requests', 'pyjnius', 'android', 'kivy==2.3.0', 'mutagen', 'pillow', 'aiofiles']
blocked_libs = ['torch', 'torchaudio', 'torchvision', 'whisper', 'demucs', 'librosa', 'onnx', 'numba', 'soundfile', 'scipy']

if os.path.exists(req_path):
    with open(req_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for line in lines:
        lib = line.split('==')[0].split('>')[0].split('<')[0].strip().lower()
        if lib and not any(b in lib for b in blocked_libs) and lib not in safe_reqs:
            safe_reqs.append(lib)

req_string = ','.join(safe_reqs)

spec_content = f"""[app]
title = Free Karaoke
package.name = freekaraoke
package.domain = org.dstep
version = 1.0.0
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,ttf,wav,mp3,html,js,css
orientation = landscape
osx.python_version = 3.11
min_android_version = 24
android.api = 33
android.ndk = 25b
android.permissions = INTERNET, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, MANAGE_EXTERNAL_STORAGE, RECORD_AUDIO, MODIFY_AUDIO_SETTINGS
requirements = {req_string}
android.accept_all_licenses = True
android.release_artifact = apk
android.add_args = --orientation=sensorLandscape
[buildozer]
log_level = 2
warn_on_root = 1
"""
with open(os.path.join(project_dir, 'buildozer.spec'), 'w', encoding='utf-8') as f:
    f.write(spec_content)

main_py_code = """
import sys
import os
import threading
import time

try:
    from jnius import autoclass
    Environment = autoclass('android.os.Environment')
    music_dir = os.path.join(Environment.getExternalStorageDirectory().getAbsolutePath(), 'Music', 'free_karaoke_library')
    os.makedirs(music_dir, exist_ok=True)
    os.environ['FREE_KARAOKE_LIBRARY_PATH'] = music_dir
except Exception as e:
    print("Ошибка настройки путей JNI:", e)

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

try:
    from main import app as original_app
except ImportError:
    try:
        from server import app as original_app
    except ImportError:
        from core.main import app as original_app

@original_app.middleware("http")
async def block_ml_features(request: Request, call_next):
    ml_endpoints = ["separate", "transcribe", "rescan", "fix"]
    path = request.url.path.lower()
    
    if any(endpoint in path for endpoint in ml_endpoints):
        return JSONResponse(
            status_code=400,
            content={"error": "Эта функция требует работы нейросетей и доступна только в Desktop версии программы.", "detail": "blocked"}
        )
    return await call_next(request)

def run_server():
    uvicorn.run(original_app, host="127.0.0.1", port=8000, log_level="info")

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

from kivy.app import App
from kivy.clock import Clock
from kivy.utils import platform

class WebWrapperApp(App):
    def build(self):
        Clock.schedule_once(self.open_webview, 1)
        from kivy.uix.label import Label
        return Label(text="Запуск сервера Free Karaoke...")

    def open_webview(self, dt):
        if platform == 'android':
            from jnius import autoclass
            from android.runnable import run_on_ui_thread
            
            WebView = autoclass('android.webkit.WebView')
            WebViewClient = autoclass('android.webkit.WebViewClient')
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            
            @run_on_ui_thread
            def create_webview():
                webview = WebView(activity)
                settings = webview.getSettings()
                settings.setJavaScriptEnabled(True)
                settings.setDomStorageEnabled(True)
                settings.setMediaPlaybackRequiresUserGesture(False)
                
                webview.setWebViewClient(WebViewClient())
                webview.loadUrl('http://127.0.0.1:8000')
                
                activity.setContentView(webview)
            
            create_webview()

if __name__ == '__main__':
    WebWrapperApp().run()
"""

orig_main = os.path.join(project_dir, 'main.py')
if os.path.exists(orig_main):
    os.rename(orig_main, os.path.join(project_dir, 'desktop_main.py'))

with open(orig_main, 'w', encoding='utf-8') as f:
    f.write(main_py_code)

PYEOF

log "Генерация конфигурации завершена." "SUCCESS"

# ------------------------------------------------------------------------------
# Шаг 8: Генерация Keystore
# ------------------------------------------------------------------------------
KEYSTORE_PATH="$BUILD_ROOT/keystore/freekaraoke.keystore"
KEY_PASS="karaokepass123"

if [ ! -f "$KEYSTORE_PATH" ]; then
    log "Генерация ключа подписи для Release APK..."
    keytool -genkey -v -keystore "$KEYSTORE_PATH" -alias fk_alias \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -storepass "$KEY_PASS" -keypass "$KEY_PASS" \
        -dname "CN=Free Karaoke, OU=Android, O=FreeKaraoke, C=RU"
fi

# ------------------------------------------------------------------------------
# Шаг 9: Сборка и подпись APK
# ------------------------------------------------------------------------------
cd "$PROJECT_DIR"
log "НАЧАЛО СБОРКИ RELEASE APK..."

set +e
trap - ERR

MAX_RETRIES=10
RETRY_COUNT=0
BUILD_CODE=1

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    buildozer -v android release 2>&1 | tee "$BUILD_ROOT/logs/buildozer_output.log"
    BUILD_CODE=${PIPESTATUS[0]}
    if [ $BUILD_CODE -eq 0 ]; then break; fi
    RETRY_COUNT=$((RETRY_COUNT+1))
    if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
        log "Ошибка сборки (Код: $BUILD_CODE). Попытка $RETRY_COUNT из $MAX_RETRIES через 10 секунд..." "WARN"
        sleep 10
    fi
done

set -e
trap 'last_line=$LINENO; log "Критическая ошибка на строке $last_line. Проверьте логи: $LOG_FILE" "ERROR"; read -p "Нажмите Enter для выхода..."; exit 1' ERR

if [ $BUILD_CODE -ne 0 ]; then
    log_error_exit "Сборка завершилась с ошибкой. Проверьте логи."
fi

log "Сборка успешна. Поиск не подписанного APK..."
UNSIGNED_APK=$(find bin/ -name "*-release-unsigned.apk" | head -n 1)

if [ -n "$UNSIGNED_APK" ]; then
    log "Подписываем APK..."
    FINAL_APK="$BUILD_ROOT/output/FreeKaraoke-Release-Signed.apk"
    
    # Ищем apksigner и zipalign во внутренних инструментах Android SDK (Скачанных Buildozer)
    ZIPALIGN_CMD="zipalign"
    if ! command -v zipalign &> /dev/null; then
        ZIPALIGN_CMD=$(find ~/.buildozer/android/platform/android-sdk/build-tools -name "zipalign" | sort -r | head -n 1 || echo "")
    fi

    APKSIGNER_CMD="apksigner"
    if ! command -v apksigner &> /dev/null; then
        APKSIGNER_CMD=$(find ~/.buildozer/android/platform/android-sdk/build-tools -name "apksigner" | sort -r | head -n 1 || echo "")
    fi

    if [ -z "$APKSIGNER_CMD" ] || [ ! -x "$APKSIGNER_CMD" ]; then
        log_error_exit "Не удалось найти apksigner. Сборка завершена, но APK не подписан!"
    fi

    log "Используется apksigner: $APKSIGNER_CMD"
    
    if [ -n "$ZIPALIGN_CMD" ] && [ -x "$ZIPALIGN_CMD" ]; then
        log "Выравнивание APK ($ZIPALIGN_CMD)..."
        "$ZIPALIGN_CMD" -v -p 4 "$UNSIGNED_APK" "bin/aligned.apk"
        "$APKSIGNER_CMD" sign --ks "$KEYSTORE_PATH" --ks-pass "pass:$KEY_PASS" --out "$FINAL_APK" "bin/aligned.apk"
    else
        log "zipalign не найден, подписываем напрямую..." "WARN"
        "$APKSIGNER_CMD" sign --ks "$KEYSTORE_PATH" --ks-pass "pass:$KEY_PASS" --out "$FINAL_APK" "$UNSIGNED_APK"
    fi
    
    log "РЕЛИЗ ГОТОВ!" "SUCCESS"
    log "Файл находится здесь: $FINAL_APK" "SUCCESS"
else
    log_error_exit "Не удалось найти итоговый apk файл в папке bin/"
fi

# ------------------------------------------------------------------------------
# Шаг 10: Завершение
# ------------------------------------------------------------------------------
echo ""
read -p "Удалить тяжелые временные файлы Buildozer (исходники, NDK/SDK)? (y/n): " CLEANUP
if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    log "Очистка временных файлов..."
    rm -rf "$PROJECT_DIR"
    rm -rf "$BUILD_ROOT/env"
    rm -rf "$BUILD_ROOT/tools"
    log "Очистка завершена." "SUCCESS"
else
    log "Временные файлы сохранены в $BUILD_ROOT/src"
fi

echo -e "\n${GREEN}Установка завершена. Скопируйте APK на Android устройство и установите.${NC}"
read -p "Нажмите Enter для выхода из скрипта..."