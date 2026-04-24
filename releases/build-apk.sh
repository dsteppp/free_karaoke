#!/bin/bash

# ==============================================================================
# Free Karaoke Android Release Builder (FastAPI + WebView Edition)
# Версия: 7.9.6 (Fix: Local Module Imports & Smart FastAPI App Discovery)
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

while true; do
    read -p "Введите полный путь к папке для сборки (например, /home/$USER/apk_build): " BUILD_ROOT
    if [ -z "$BUILD_ROOT" ]; then continue; fi
    if mkdir -p "$BUILD_ROOT"/{src,logs,output,env,tools,keystore} 2>/dev/null; then break; else log "Ошибка доступа к директории." "ERROR"; fi
done

LOG_FILE="$BUILD_ROOT/logs/build_script.log"
: > "$LOG_FILE"
log "Рабочая директория: $BUILD_ROOT"

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

log "Создание изолированного Python окружения..."
if [ -d "env" ]; then rm -rf env; fi
python3.11 -m venv env
source env/bin/activate
pip install --upgrade pip setuptools wheel
pip install "Cython<3.0" requests packaging
pip install --upgrade "git+https://github.com/kivy/buildozer.git"

log "Очистка кэша сборки (без удаления скачанных SDK/NDK)..."
rm -rf "$PROJECT_DIR/.buildozer" 2>/dev/null || true
rm -rf "$PROJECT_DIR/bin" 2>/dev/null || true

log "Модификация бэкенда: решение проблем локальных импортов, БД и умный поиск сервера..."
export PROJECT_DIR
python3 << 'PYEOF'
import os

project_dir = os.environ.get('PROJECT_DIR', '.')
req_path = os.path.join(project_dir, 'requirements.txt')

safe_reqs = [
    'python3', 'sqlite3', 'openssl', 'fastapi==0.95.2', 'pydantic==1.10.13', 
    'sqlalchemy', 'databases', 'uvicorn', 'jinja2', 'requests', 'pyjnius', 'android', 
    'kivy==2.3.0', 'mutagen', 'pillow', 'aiofiles', 'starlette', 'anyio', 
    'typing_extensions', 'click', 'h11', 'markupsafe', 'python-multipart'
]

blocked_libs = [
    'torch', 'torchaudio', 'torchvision', 'whisper', 'demucs', 'librosa', 
    'onnx', 'numba', 'soundfile', 'scipy', 'numpy', 'faiss', 'yt_dlp', 'pytube', 
    'pydantic-core', 'annotated-types', 'annotated-doc'
]

if os.path.exists(req_path):
    with open(req_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    for line in lines:
        lib = line.split('==')[0].split('>')[0].split('<')[0].split('[')[0].strip().lower()
        
        is_blocked = any(b in lib for b in blocked_libs)
        is_already_in_safe = any(lib == sr.split('==')[0] for sr in safe_reqs)
        
        if lib and not is_blocked and not is_already_in_safe:
            safe_reqs.append(lib)

req_string = ','.join(safe_reqs)

spec_content = f"""[app]
title = Free Karaoke
package.name = freekaraoke
package.domain = org.dstep
version = 1.0.0
source.dir = .
source.include_exts = py,png,jpg,svg,ico,kv,atlas,json,ttf,woff,woff2,eot,wav,mp3,html,js,css,map
orientation = landscape
osx.python_version = 3.11
min_android_version = 24
android.api = 33
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.permissions = INTERNET, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, MANAGE_EXTERNAL_STORAGE, RECORD_AUDIO, MODIFY_AUDIO_SETTINGS
requirements = {req_string}
android.accept_all_licenses = True
android.release_artifact = apk
android.manifest.application_meta_data = android:usesCleartextTraffic=true
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
import traceback
from unittest.mock import MagicMock

# 1. ФИКС ПУТЕЙ ИМПОРТА (чтобы находились файлы типа core/database.py)
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

# Добавляем все возможные подпапки в системные пути
for subdir in ['core', 'server', 'app', 'backend', 'db']:
    subpath = os.path.join(APP_DIR, subdir)
    if os.path.isdir(subpath) and subpath not in sys.path:
        sys.path.insert(0, subpath)

# 2. ЖЕСТКОЕ ЗАМЕЩЕНИЕ ТЯЖЕЛЫХ БИБЛИОТЕК
blocked_libs = ['torch', 'torchaudio', 'torchvision', 'whisper', 'demucs', 'librosa', 'onnx', 'onnxruntime', 'numba', 'soundfile', 'scipy', 'numpy', 'faiss', 'pytube', 'yt_dlp']
for lib in blocked_libs:
    sys.modules[lib] = MagicMock()

print("[APP] Starting Free Karaoke Android Initialization")

def setup_storage():
    try:
        from jnius import autoclass
        Environment = autoclass('android.os.Environment')
        music_dir = os.path.join(Environment.getExternalStorageDirectory().getAbsolutePath(), 'Music', 'free_karaoke_library')
        os.environ['FREE_KARAOKE_LIBRARY_PATH'] = music_dir
        print("[STORAGE] Env path set to:", music_dir)
    except Exception as e:
        print("[STORAGE] Error setting env path:", e)

setup_storage()

import fastapi
import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

SERVER_STARTED = False
original_app = None

# Умный поиск инстанса сервера FastAPI
def find_fastapi_app(mod):
    # Сначала проверяем стандартные имена
    for name in ['app', 'api', 'server', 'application']:
        if hasattr(mod, name):
            attr = getattr(mod, name)
            if isinstance(attr, fastapi.FastAPI):
                return attr
    # Если не нашли, сканируем вообще все переменные в модуле
    for attr_name in dir(mod):
        attr = getattr(mod, attr_name)
        if isinstance(attr, fastapi.FastAPI):
            return attr
    return None

# 3. ИМПОРТ И ЗАПУСК БЭКЕНДА
try:
    for module_path in ['desktop_main', 'server', 'core.main', 'main']:
        try:
            if '.' in module_path:
                mod_name, attr = module_path.rsplit('.', 1)
                mod = __import__(mod_name, fromlist=[attr])
                target_mod = getattr(mod, attr)
            else:
                target_mod = __import__(module_path)
            
            app_instance = find_fastapi_app(target_mod)
            if app_instance:
                original_app = app_instance
                print(f"[SERVER] SUCCESS: Found FastAPI app in '{module_path}'")
                break
            else:
                print(f"[SERVER] Module '{module_path}' imported, but no FastAPI app instance found inside.")
                
        except ImportError as ie:
            print(f"[SERVER] ImportError in '{module_path}': {ie}")
            continue
        except Exception as e:
            print(f"[SERVER] Critical error while executing '{module_path}':")
            traceback.print_exc()
            continue
    
    if not original_app:
        raise ImportError("Could not locate FastAPI app instance in any backend files.")

    @original_app.get("/health")
    async def health_check():
        return {"status": "ok", "server": "android"}

    @original_app.middleware("http")
    async def block_ml_features(request: Request, call_next):
        ml_endpoints = ["separate", "transcribe", "rescan", "fix", "upload"]
        path = request.url.path.lower()
        if any(endpoint in path for endpoint in ml_endpoints):
            return JSONResponse(
                status_code=400,
                content={"error": "Эта функция требует нейросетей и доступна только в десктопной версии.", "detail": "blocked"}
            )
        return await call_next(request)

    def run_server():
        global SERVER_STARTED
        try:
            print("[SERVER] Starting uvicorn on 127.0.0.1:8000")
            uvicorn.run(original_app, host="127.0.0.1", port=8000, log_level="info")
        except Exception as e:
            print("[SERVER] Uvicorn thread crashed:", e)
            traceback.print_exc()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    time.sleep(4)
    SERVER_STARTED = True
    print("[SERVER] Uvicorn background thread is running")
    
except Exception as e:
    print("[SERVER] Fatal Backend Init Error:", e)
    traceback.print_exc()
    SERVER_STARTED = False

# 4. KIVY И WEBVIEW
from kivy.app import App
from kivy.clock import Clock
from kivy.utils import platform
from kivy.uix.label import Label

class WebWrapperApp(App):
    def build(self):
        self.label = Label(text="Запуск сервера Free Karaoke...\\n\\nПожалуйста, подождите.", font_size='20sp', halign='center')
        
        if platform == 'android':
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([
                    Permission.INTERNET,
                    Permission.READ_EXTERNAL_STORAGE,
                    Permission.WRITE_EXTERNAL_STORAGE,
                    Permission.RECORD_AUDIO,
                    Permission.MODIFY_AUDIO_SETTINGS
                ], self.on_permissions_callback)
            except Exception as e:
                print("[PERM] Permission request error:", e)
                self.on_permissions_callback([], [])
        else:
            Clock.schedule_once(self.open_webview, 2)
            
        if not SERVER_STARTED:
            self.label.text = "Ошибка запуска сервера.\\nПодключитесь по USB и введите:\\nadb logcat -s python"
            
        return self.label

    def on_permissions_callback(self, permissions, results):
        print("[PERM] Granted statuses:", list(zip(permissions, results)))
        try:
            music_dir = os.environ.get('FREE_KARAOKE_LIBRARY_PATH')
            if music_dir:
                os.makedirs(music_dir, exist_ok=True)
                print("[STORAGE] Directory verified:", music_dir)
        except Exception as e:
            print("[STORAGE] Mkdir Error (Normal if waiting for MANAGE_EXTERNAL_STORAGE):", e)
        
        self.check_manage_storage()

    def check_manage_storage(self):
        if platform != 'android':
            Clock.schedule_once(self.open_webview, 1)
            return
            
        try:
            from jnius import autoclass
            from android.runnable import run_on_ui_thread
            
            Environment = autoclass('android.os.Environment')
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            
            if hasattr(Environment, 'isExternalStorageManager'):
                if not Environment.isExternalStorageManager():
                    print("[PERM] MANAGE_EXTERNAL_STORAGE not granted, opening settings...")
                    @run_on_ui_thread
                    def launch_settings():
                        Intent = autoclass('android.content.Intent')
                        Uri = autoclass('android.net.Uri')
                        try:
                            intent = Intent(Intent.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                            intent.setData(Uri.parse("package:" + activity.getPackageName()))
                            activity.startActivity(intent)
                        except:
                            intent = Intent(Intent.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                            activity.startActivity(intent)
                    
                    launch_settings()
                    self.label.text = (
                        "Требуется полный доступ к файлам\\n\\n"
                        "1. Найдите 'Free Karaoke' в списке\\n"
                        "2. Включите 'Разрешить управление всеми файлами'\\n"
                        "3. Вернитесь в приложение (нажмите Назад)\\n\\n"
                        "Интерфейс загрузится автоматически."
                    )
                    return
        except Exception as e:
            print("[PERM] Scoped storage check error:", e)
        
        Clock.schedule_once(self.open_webview, 2)

    def open_webview(self, dt):
        if not SERVER_STARTED:
            return
            
        if platform != 'android':
            import webbrowser
            webbrowser.open('http://127.0.0.1:8000')
            return
            
        try:
            from jnius import autoclass
            from android.runnable import run_on_ui_thread
            import urllib.request
            
            WebView = autoclass('android.webkit.WebView')
            WebViewClient = autoclass('android.webkit.WebViewClient')
            activity = autoclass('org.kivy.android.PythonActivity').mActivity
            
            def wait_for_server(max_attempts=30):
                for i in range(max_attempts):
                    try:
                        urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=1)
                        return True
                    except:
                        time.sleep(1)
                return False
            
            @run_on_ui_thread
            def create_webview():
                if not wait_for_server():
                    self.label.text = "Таймаут: сервер не ответил за 30 сек."
                    return
                    
                try:
                    webview = WebView(activity)
                    settings = webview.getSettings()
                    settings.setJavaScriptEnabled(True)
                    settings.setDomStorageEnabled(True)
                    settings.setMediaPlaybackRequiresUserGesture(False)
                    settings.setAllowFileAccess(True)
                    settings.setAllowContentAccess(True)
                    
                    webview.setWebViewClient(WebViewClient())
                    webview.loadUrl('http://127.0.0.1:8000')
                    activity.setContentView(webview)
                    print("[WEBVIEW] Successfully loaded UI")
                    
                except Exception as e:
                    print("[WEBVIEW] Internal Error:", e)
                    self.label.text = "Ошибка WebView: " + str(e)
            
            create_webview()
            
        except Exception as e:
            print("[WEBVIEW] Init Error:", e)
            self.label.text = "Ошибка: " + str(e)

    def on_resume(self):
        if platform == 'android' and SERVER_STARTED:
            Clock.schedule_once(lambda dt: self.open_webview(dt), 2)
        return True

if __name__ == '__main__':
    print("[APP] Entering Kivy App Loop")
    WebWrapperApp().run()
"""

orig_main = os.path.join(project_dir, 'main.py')
if os.path.exists(orig_main):
    os.rename(orig_main, os.path.join(project_dir, 'desktop_main.py'))

with open(orig_main, 'w', encoding='utf-8') as f:
    f.write(main_py_code)

PYEOF

log "Генерация конфигурации завершена." "SUCCESS"

KEYSTORE_PATH="$BUILD_ROOT/keystore/freekaraoke.keystore"
KEY_PASS="karaokepass123"

if [ ! -f "$KEYSTORE_PATH" ]; then
    log "Генерация ключа подписи для Release APK..."
    keytool -genkey -v -keystore "$KEYSTORE_PATH" -alias fk_alias \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -storepass "$KEY_PASS" -keypass "$KEY_PASS" \
        -dname "CN=Free Karaoke, OU=Android, O=FreeKaraoke, C=RU"
fi

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
    
    log "РЕЛИ ГОТОВ!" "SUCCESS"
    log "Файл находится здесь: $FINAL_APK" "SUCCESS"
else
    log_error_exit "Не удалось найти итоговый apk файл в папке bin/"
fi

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