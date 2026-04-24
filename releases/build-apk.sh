#!/bin/bash

# ==============================================================================
# Free Karaoke Android Release Builder (FastAPI + WebView Edition)
# Версия: 7.1 (Fixed Orientation & NDK Regression)
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
# Шаг 2: Установка системных зависимостей (OS-Agnostic)
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
    PACKAGES=(python311 jdk17-openjdk git zip unzip libffi openssl zlib gcc base-devel pkgconf gstreamer wget cmake ninja apksigner)
elif [[ "$INSTALL_CMD" == *"apt"* ]]; then
    PACKAGES=(python3.11 openjdk-17-jdk git zip unzip libffi-dev libssl-dev zlib1g-dev gcc build-essential pkg-config wget cmake ninja-build apksigner)
fi

if ! command -v apksigner &> /dev/null || ! command -v cmake &> /dev/null; then
    log "Установка системных пакетов (может потребоваться пароль sudo)..."
    eval "$INSTALL_CMD ${PACKAGES[*]}" || log "Некоторые пакеты уже установлены или недоступны." "WARN"
fi

if ! command -v java &> /dev/null; then log_error_exit "Java не найдена. Ошибка установки."; fi
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
export PATH="$JAVA_HOME/bin:$PATH"

# ------------------------------------------------------------------------------
# Шаг 3: Работа с репозиторием
# ------------------------------------------------------------------------------
PROJECT_DIR="$BUILD_ROOT/src/project_src"
log "Загрузка актуального кода проекта..."

if [ -d "$PROJECT_DIR/.git" ]; then
    cd "$PROJECT_DIR"
    git fetch --all && git reset --hard origin/main || git reset --hard origin/master
    git pull
else
    rm -rf "$PROJECT_DIR"
    git clone "$REPO_URL" "$PROJECT_DIR"
fi

cd "$BUILD_ROOT"

# ------------------------------------------------------------------------------
# Шаг 4: Виртуальное окружение
# ------------------------------------------------------------------------------
log "Создание изолированного Python окружения..."
if [ -d "env" ]; then rm -rf env; fi
python3.11 -m venv env
source env/bin/activate

pip install --upgrade pip setuptools wheel
pip install "Cython<3.0" requests packaging
pip install --upgrade "git+https://github.com/kivy/buildozer.git"

# ------------------------------------------------------------------------------
# Шаг 5: Очистка кэша сборки
# ------------------------------------------------------------------------------
log "Глубокая очистка предыдущих билдов..."
rm -rf "$PROJECT_DIR/.buildozer/android/platform/build-"* 2>/dev/null || true
rm -rf "$PROJECT_DIR/.buildozer/android/app" 2>/dev/null || true
rm -f "$PROJECT_DIR/bin/"*.apk 2>/dev/null || true

# ------------------------------------------------------------------------------
# Шаг 6: Интеллектуальный парсинг зависимостей и патчинг кода (PYTHON BLOCK)
# ------------------------------------------------------------------------------
log "Модификация бэкенда: отключение ML и настройка WebView..."

export PROJECT_DIR

python3 << 'PYEOF'
import os
import re

project_dir = os.environ.get('PROJECT_DIR', '.')

# 1. Формируем список легковесных зависимостей, вырезая ML
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
print(f"Android Dependencies: {req_string}")

# 2. Создаем buildozer.spec (ИСПРАВЛЕН ORIENTATION И ДОБАВЛЕН NDK)
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
android.add_args = --orientation=sensorLandscape
[buildozer]
log_level = 2
warn_on_root = 1
"""
with open(os.path.join(project_dir, 'buildozer.spec'), 'w', encoding='utf-8') as f:
    f.write(spec_content)

# 3. Создаем главный файл для Android (main.py)
main_py_code = """
import sys
import os
import threading
import time

# --- Настройка путей для Android ---
try:
    from jnius import autoclass
    Environment = autoclass('android.os.Environment')
    music_dir = os.path.join(Environment.getExternalStorageDirectory().getAbsolutePath(), 'Music', 'free_karaoke_library')
    os.makedirs(music_dir, exist_ok=True)
    os.environ['FREE_KARAOKE_LIBRARY_PATH'] = music_dir # Подменяем путь
except Exception as e:
    print("Ошибка настройки путей JNI:", e)

# --- Бэкенд (FastAPI) ---
import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

# Пытаемся импортировать твой основной объект FastAPI
try:
    from main import app as original_app
except ImportError:
    try:
        from server import app as original_app
    except ImportError:
        from core.main import app as original_app

# Внедряем Middleware для перехвата ML-функций
@original_app.middleware("http")
async def block_ml_features(request: Request, call_next):
    ml_endpoints = ["separate", "transcribe", "rescan", "fix"] # Ключевые слова в URL ML-роутов
    path = request.url.path.lower()
    
    if any(endpoint in path for endpoint in ml_endpoints):
        return JSONResponse(
            status_code=400,
            content={"error": "Эта функция требует работы нейросетей и доступна только в Desktop версии программы.", "detail": "blocked"}
        )
    return await call_next(request)

def run_server():
    uvicorn.run(original_app, host="127.0.0.1", port=8000, log_level="info")

# Запускаем сервер в фоновом потоке
server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

# --- Фронтенд (Android WebView) ---
from kivy.app import App
from kivy.clock import Clock
from kivy.utils import platform

class WebWrapperApp(App):
    def build(self):
        # Даем серверу секунду на старт
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
                settings.setMediaPlaybackRequiresUserGesture(False) # Разрешаем звук без клика
                
                webview.setWebViewClient(WebViewClient())
                webview.loadUrl('http://127.0.0.1:8000')
                
                # Заменяем Kivy UI на WebView
                activity.setContentView(webview)
            
            create_webview()

if __name__ == '__main__':
    WebWrapperApp().run()
"""

# Переименовываем оригинальный main.py чтобы не конфликтовать
orig_main = os.path.join(project_dir, 'main.py')
if os.path.exists(orig_main):
    os.rename(orig_main, os.path.join(project_dir, 'desktop_main.py'))

with open(orig_main, 'w', encoding='utf-8') as f:
    f.write(main_py_code)

print("Python-патчинг успешно завершен. Создан Android WebView и ML-Middleware.")
PYEOF

log "Генерация конфигурации завершена." "SUCCESS"

# ------------------------------------------------------------------------------
# Шаг 7: Генерация Keystore (Для релизной подписи)
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
# Шаг 8: Сборка и подпись APK
# ------------------------------------------------------------------------------
cd "$PROJECT_DIR"
export CMAKE_POLICY_VERSION_MINIMUM=3.5
log "НАЧАЛО СБОРКИ RELEASE APK (Это займет от 10 до 30 минут)..."
log "Качаются NDK, SDK и компилируется код. Не закрывайте терминал!"

set +e
buildozer -v android release 2>&1 | tee "$BUILD_ROOT/logs/buildozer_output.log"
BUILD_CODE=${PIPESTATUS[0]}
set -e

if [ $BUILD_CODE -ne 0 ]; then
    log_error_exit "Сборка завершилась с ошибкой. Проверьте $BUILD_ROOT/logs/buildozer_output.log"
fi

log "Сборка успешна. Поиск не подписанного APK..."
UNSIGNED_APK=$(find bin/ -name "*-release-unsigned.apk" | head -n 1)

if [ -n "$UNSIGNED_APK" ]; then
    log "Подписываем APK..."
    FINAL_APK="$BUILD_ROOT/output/FreeKaraoke-Release-Signed.apk"
    
    # Выравнивание (zipalign) если доступно
    if command -v zipalign &> /dev/null; then
        zipalign -v -p 4 "$UNSIGNED_APK" "bin/aligned.apk"
        apksigner sign --ks "$KEYSTORE_PATH" --ks-pass "pass:$KEY_PASS" --out "$FINAL_APK" "bin/aligned.apk"
    else
        apksigner sign --ks "$KEYSTORE_PATH" --ks-pass "pass:$KEY_PASS" --out "$FINAL_APK" "$UNSIGNED_APK"
    fi
    
    log "РЕЛИЗ ГОТОВ!" "SUCCESS"
    log "Файл находится здесь: $FINAL_APK" "SUCCESS"
else
    AAB_FILE=$(find bin/ -name "*.aab" | head -n 1)
    if [ -n "$AAB_FILE" ]; then
        cp "$AAB_FILE" "$BUILD_ROOT/output/"
        log "Buildozer собрал AAB вместо APK: $BUILD_ROOT/output/$(basename "$AAB_FILE")" "WARN"
    else
        log_error_exit "Не удалось найти итоговый файл в папке bin/"
    fi
fi

# ------------------------------------------------------------------------------
# Шаг 9: Завершение
# ------------------------------------------------------------------------------
echo ""
read -p "Удалить тяжелые временные файлы Buildozer (исходники, NDK/SDK)? (y/n): " CLEANUP
if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    log "Очистка временных файлов..."
    rm -rf "$PROJECT_DIR"
    rm -rf "$BUILD_ROOT/env"
    log "Очистка завершена." "SUCCESS"
else
    log "Временные файлы сохранены в $BUILD_ROOT/src"
fi

echo -e "\n${GREEN}Установка завершена. Скопируйте APK на Android устройство и установите.${NC}"
read -p "Нажмите Enter для выхода из скрипта..."