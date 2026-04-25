#!/bin/bash

# ==============================================================================
# Free Karaoke Android Release Builder
# Версия: 35.0 (Smart UI + Zero-Copy I/O + Fixes)
# ==============================================================================

set -euo pipefail

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

LOG_FILE=""
BUILD_ROOT=""
REPO_URL="https://github.com/dsteppp/free_karaoke.git"
ANDROID_COMPILE_SDK="34"
ANDROID_BUILD_TOOLS="34.0.0"

# --- ULTIMATE АВТО-АНАЛИЗАТОР ОШИБОК ---
print_diagnostics() {
    local logfile="$BUILD_ROOT/logs/gradle_build.log"
    if [ -n "$BUILD_ROOT" ] && [ -f "$logfile" ]; then
        echo -e "\n${RED}======================================================================${NC}"
        echo -e "${RED}                      АВТО-АНАЛИЗАТОР ОШИБОК                          ${NC}"
        echo -e "${RED}======================================================================${NC}"
        
        local found_error=false

        if grep -q "Traceback (most recent call last):" "$logfile"; then
            echo -e "${YELLOW}[!] НАЙДЕН PYTHON TRACEBACK (КРИТИЧЕСКАЯ ОШИБКА СКРИПТОВ):${NC}"
            awk '/Traceback \(most recent call last\):/{flag=1} /Chaquopy: Exit status/{print; flag=0; next} /BUILD FAILED/{flag=0} flag' "$logfile" | sed 's/^/    /'
            echo ""
            found_error=true
        fi

        if grep -q "Caused by: com.chaquo.python" "$logfile"; then
            echo -e "${YELLOW}[!] ОШИБКА ПЛАГИНА CHAQUOPY:${NC}"
            grep -A 15 "Caused by: com.chaquo.python" "$logfile" | sed 's/^/    /'
            echo ""
            found_error=true
        fi

        if grep -E -qi "Failed to build wheel|pip failed|error: subprocess-exited-with-error|ERROR: Could not build wheels" "$logfile"; then
            echo -e "${YELLOW}[!] НАЙДЕНА ОШИБКА УСТАНОВКИ PYTHON-БИБЛИОТЕК (PIP):${NC}"
            grep -E -i -B 2 -A 15 "Failed to build wheel|pip failed|error: subprocess-exited-with-error" "$logfile" | tail -n 25 | sed 's/^/    /'
            echo ""
            found_error=true
        fi

        if grep -q "\* What went wrong:" "$logfile"; then
            echo -e "${YELLOW}[!] ОТЧЕТ GRADLE О ПРИЧИНЕ ОШИБКИ:${NC}"
            awk '/\* What went wrong:/{flag=1} /\* Try:/{flag=0} flag' "$logfile" | sed 's/^/    /'
            echo ""
            found_error=true
        fi

        if [ "$found_error" = false ]; then
            echo -e "    ${YELLOW}Не удалось автоматически извлечь точную ошибку.${NC}"
            echo -e "    ${YELLOW}Последние 20 строк лога:${NC}"
            tail -n 20 "$logfile" | sed 's/^/    /'
        fi

        echo -e "${RED}======================================================================${NC}"
        echo -e "Полный лог сохранен в: ${BLUE}$logfile${NC}"
    fi
}

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
    print_diagnostics
    echo ""
    read -p "Нажмите Enter для выхода..."
    exit 1
}

trap 'last_line=$LINENO; log "Критическая ошибка на строке $last_line." "ERROR"; print_diagnostics; read -p "Нажмите Enter для выхода..."; exit 1' ERR

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
echo -e "${GREEN}  Free Karaoke Native Android Builder         ${NC}"
echo -e "${GREEN}  [ 35.0 - Zero-Copy I/O, Safe Logs, Fixes ]  ${NC}"
echo -e "${GREEN}==============================================${NC}"
log "Инициализация чистой среды сборки..."

while true; do
    read -p "Введите полный путь к папке для сборки (например, /home/$USER/apk_build): " BUILD_ROOT
    if [ -z "$BUILD_ROOT" ]; then continue; fi
    if mkdir -p "$BUILD_ROOT"/{src,logs,output,tools/android_sdk,tools/gradle,tools/gradle_cache,tools/android_cache,tools/pip_cache,keystore} 2>/dev/null; then break; else log "Ошибка доступа к директории." "ERROR"; fi
done

LOG_FILE="$BUILD_ROOT/logs/build_script.log"
: > "$LOG_FILE"
log "Рабочая директория: $BUILD_ROOT"

log "Проверка/создание Polyfill-заглушки для модуля cgi..."
mkdir -p "$BUILD_ROOT/tools/python_polyfills"
cat << 'EOF' > "$BUILD_ROOT/tools/python_polyfills/cgi.py"
def parse_header(line):
    if not line: return '', {}
    parts = [x.strip() for x in line.split(';')]
    key = parts[0].lower()
    pdict = {}
    for part in parts[1:]:
        if '=' in part:
            k, v = part.split('=', 1)
            pdict[k.strip().lower()] = v.strip().strip('"')
    return key, pdict
EOF
export PYTHONPATH="$BUILD_ROOT/tools/python_polyfills:${PYTHONPATH:-}"

export GRADLE_USER_HOME="$BUILD_ROOT/tools/gradle_cache"
export ANDROID_USER_HOME="$BUILD_ROOT/tools/android_cache"
export XDG_CACHE_HOME="$BUILD_ROOT/tools/pip_cache"
export PIP_CACHE_DIR="$BUILD_ROOT/tools/pip_cache"
export ANDROID_HOME="$BUILD_ROOT/tools/android_sdk"

log "Проверка системных пакетов..."
INSTALL_CMD=""
if command -v yay &> /dev/null; then INSTALL_CMD="yay -S --noconfirm --needed"
elif command -v pacman &> /dev/null; then INSTALL_CMD="sudo pacman -S --noconfirm --needed"
elif command -v apt &> /dev/null; then INSTALL_CMD="sudo apt update && sudo apt install -y"
elif command -v dnf &> /dev/null; then INSTALL_CMD="sudo dnf install -y"
else log_error_exit "Не найден поддерживаемый менеджер пакетов."; fi

PACKAGES=()
if [[ "$INSTALL_CMD" == *"yay"* || "$INSTALL_CMD" == *"pacman"* ]]; then
    PACKAGES=(jdk17-openjdk git zip unzip wget curl coreutils)
elif [[ "$INSTALL_CMD" == *"apt"* ]]; then
    PACKAGES=(openjdk-17-jdk git zip unzip wget curl coreutils)
fi

eval "$INSTALL_CMD ${PACKAGES[*]}" || log "Системные пакеты готовы." "SUCCESS"

if [ -d "/usr/lib/jvm/java-17-openjdk" ]; then export JAVA_HOME="/usr/lib/jvm/java-17-openjdk"
elif [ -d "/usr/lib/jvm/java-17-openjdk-amd64" ]; then export JAVA_HOME="/usr/lib/jvm/java-17-openjdk-amd64"
elif command -v java &> /dev/null; then export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which java))))
else log_error_exit "Java 17 не найдена."; fi
export PATH="$JAVA_HOME/bin:$PATH"

if [ ! -f "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" ]; then
    log "Загрузка Android SDK Command-line Tools..."
    cd "$BUILD_ROOT/tools"
    wget -q --show-progress "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" -O cmdline.zip
    unzip -q cmdline.zip -d "$ANDROID_HOME"
    mkdir -p "$ANDROID_HOME/cmdline-tools/latest"
    mv "$ANDROID_HOME/cmdline-tools/bin" "$ANDROID_HOME/cmdline-tools/lib" "$ANDROID_HOME/cmdline-tools/source.properties" "$ANDROID_HOME/cmdline-tools/latest/" 2>/dev/null || true
    rm cmdline.zip
fi

yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses > /dev/null 2>&1 || true
"$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "platform-tools" "platforms;android-$ANDROID_COMPILE_SDK" "build-tools;$ANDROID_BUILD_TOOLS" > /dev/null

GRADLE_DIR="$BUILD_ROOT/tools/gradle/gradle-8.5"
if [ ! -d "$GRADLE_DIR" ]; then
    log "Загрузка Gradle..."
    cd "$BUILD_ROOT/tools/gradle"
    wget -q --show-progress "https://services.gradle.org/distributions/gradle-8.5-bin.zip" -O gradle.zip
    unzip -q gradle.zip
    rm gradle.zip
fi
export PATH="$GRADLE_DIR/bin:$PATH"

PROJECT_DIR="$BUILD_ROOT/src/project_src"
log "Синхронизация кода проекта..."
if [ -d "$PROJECT_DIR/.git" ]; then
    cd "$PROJECT_DIR"
    git fetch --all && git reset --hard origin/main || git reset --hard origin/master
    git pull
else
    cd "$BUILD_ROOT"
    rm -rf "$PROJECT_DIR"
    git clone "$REPO_URL" "$PROJECT_DIR"
fi

log "Очистка старой сборки Android..."
ANDROID_DIR="$BUILD_ROOT/android_project"
rm -rf "$ANDROID_DIR" 2>/dev/null || true
mkdir -p "$ANDROID_DIR/app/src/main/java/org/dstep/freekaraoke"
mkdir -p "$ANDROID_DIR/app/src/main/python"
mkdir -p "$ANDROID_DIR/app/src/main/res/values"
mkdir -p "$ANDROID_DIR/app/src/main/res/mipmap"

cd "$ANDROID_DIR"

log "Генерация файлов проекта..."

cat << 'EOF' > gradle.properties
android.useAndroidX=true
android.enableJetifier=true
org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
EOF

cat << 'EOF' > settings.gradle.kts
pluginManagement {
    repositories { 
        gradlePluginPortal()
        google()
        mavenCentral()
        maven { url = uri("https://chaquo.com/maven") }
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { 
        google()
        mavenCentral()
        maven { url = uri("https://chaquo.com/maven") }
    }
}
rootProject.name = "FreeKaraoke"
include(":app")
EOF

cat << 'EOF' > build.gradle.kts
buildscript {
    repositories {
        google()
        mavenCentral()
        maven { url = uri("https://chaquo.com/maven") }
    }
    dependencies {
        classpath("com.android.tools.build:gradle:8.2.2")
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:1.9.22")
        classpath("com.chaquo.python:gradle:15.0.1")
    }
}

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}
EOF

cat << 'EOF' > app/build.gradle.kts
plugins {
    id("com.android.application")
    id("kotlin-android")
    id("com.chaquo.python")
}

android {
    namespace = "org.dstep.freekaraoke"
    compileSdk = 34

    defaultConfig {
        applicationId = "org.dstep.freekaraoke"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"
        ndk { abiFilters += listOf("arm64-v8a", "armeabi-v7a") }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.11"
        buildPython("python3")
        pip {
            install("pydantic==1.10.13")
            install("fastapi==0.110.0")
            install("python-multipart")
            install("a2wsgi")
            install("werkzeug")
            install("sqlalchemy")
            install("aiosqlite")
            install("mutagen")
            install("tinytag")
            install("python-dotenv")
            install("pyyaml")
            install("lyricsgenius")
            install("beautifulsoup4")
            install("requests")
            install("httpx")
            install("huey")
            install("platformdirs")
            install("aiofiles")
        }
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.12.0")
    implementation("androidx.appcompat:appcompat:1.6.1")
    implementation("com.google.android.material:material:1.11.0")
    implementation("androidx.webkit:webkit:1.10.0")
    implementation("androidx.activity:activity-ktx:1.8.2")
}
EOF

cat << 'EOF' > app/src/main/AndroidManifest.xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" />
    <uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" />
    <uses-permission android:name="android.permission.MANAGE_EXTERNAL_STORAGE" tools:ignore="ScopedStorage" />
    <uses-permission android:name="android.permission.READ_MEDIA_AUDIO" />

    <application
        android:allowBackup="true"
        android:icon="@mipmap/ic_launcher"
        android:label="Free Karaoke"
        android:theme="@style/Theme.AppCompat.NoActionBar"
        android:usesCleartextTraffic="true"
        android:requestLegacyExternalStorage="true">
        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:screenOrientation="fullUser"
            android:configChanges="orientation|keyboardHidden|screenSize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
EOF

cat << 'EOF' > app/src/main/res/values/strings.xml
<resources>
    <string name="app_name">Free Karaoke</string>
</resources>
EOF

cat << 'EOF' > app/src/main/res/values/themes.xml
<resources>
    <style name="Theme.AppCompat.NoActionBar" parent="Theme.AppCompat.Light.NoActionBar">
        <item name="android:windowNoTitle">true</item>
        <item name="android:windowActionBar">false</item>
        <item name="android:windowFullscreen">true</item>
        <item name="android:windowDrawsSystemBarBackgrounds">true</item>
        <item name="android:statusBarColor">@android:color/transparent</item>
    </style>
</resources>
EOF

# ИСПОЛЬЗУЕМ ВЕКТОРНУЮ ИКОНКУ XML ВМЕСТО PNG
cat << 'EOF' > app/src/main/res/mipmap/ic_launcher.xml
<?xml version="1.0" encoding="utf-8"?>
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="192dp"
    android:height="192dp"
    android:viewportWidth="108"
    android:viewportHeight="108">
    <path
        android:fillColor="#121212"
        android:pathData="M0,0h108v108h-108z"/>
    <path
        android:fillColor="#BB86FC"
        android:pathData="M54,10A44,44 0 1,0 98,54A44,44 0 0,0 54,10Z"/>
    <path
        android:fillColor="#121212"
        android:pathData="M65,34 L47,38 L47,62 A10,10 0 1,0 53,71 L53,46 L65,43 Z"/>
</vector>
EOF

cat << 'EOF' > app/src/main/java/org/dstep/freekaraoke/MainActivity.kt
package org.dstep.freekaraoke

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {
    private lateinit var webView: WebView
    private var isServerRunning = false
    private var permissionRequested = false
    
    private lateinit var importLauncher: ActivityResultLauncher<Intent>
    private lateinit var exportLauncher: ActivityResultLauncher<Intent>

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        webView = WebView(this)
        setContentView(webView)

        // ИМПОРТ - Чтение потока (File Descriptor) напрямую, обход проблем с путями контента
        importLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                result.data?.data?.let { uri ->
                    try {
                        val pfd = contentResolver.openFileDescriptor(uri, "r")
                        if (pfd != null) {
                            val fd = pfd.detachFd() // Отсоединяем для безопасной работы из Python
                            val path = "/proc/self/fd/$fd"
                            runOnUiThread { webView.evaluateJavascript("window.executeMobileImport('$path');", null) }
                        }
                    } catch (e: Exception) {
                        Toast.makeText(this, "Ошибка доступа к файлу архива", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }

        // ЭКСПОРТ - Создание нативного файла (Create Document) с автоименем
        exportLauncher = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK) {
                result.data?.data?.let { uri ->
                    try {
                        val pfd = contentResolver.openFileDescriptor(uri, "w")
                        if (pfd != null) {
                            val fd = pfd.detachFd()
                            val path = "/proc/self/fd/$fd"
                            runOnUiThread { webView.evaluateJavascript("window.executeMobileExport('$path');", null) }
                        }
                    } catch (e: Exception) {
                        Toast.makeText(this, "Ошибка создания файла экспорта", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            mediaPlaybackRequiresUserGesture = false
        }
        
        webView.addJavascriptInterface(AndroidBridge(), "AndroidBridge")
        
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?) = false
        }
        
        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: ConsoleMessage): Boolean {
                Log.d("FreeKaraoke-JS", consoleMessage.message())
                return true
            }
        }
        
        checkStoragePermission()
    }

    override fun onResume() {
        super.onResume()
        if (!isServerRunning && Environment.isExternalStorageManager()) {
            startApp()
        }
    }

    private fun checkStoragePermission() {
        if (Environment.isExternalStorageManager()) {
            startApp()
        } else if (!permissionRequested) {
            permissionRequested = true
            try {
                val intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                intent.data = Uri.parse("package:$packageName")
                startActivity(intent)
            } catch (e: Exception) {
                val intent = Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION)
                startActivity(intent)
            }
            Toast.makeText(this, "Требуется доступ ко всем файлам для библиотеки", Toast.LENGTH_LONG).show()
        }
    }

    private fun startApp() {
        if (isServerRunning) return
        try {
            if (!Python.isStarted()) Python.start(AndroidPlatform(this))
            Python.getInstance().getModule("mobile_server").callAttr("start_server")
            isServerRunning = true
            Thread.sleep(1500)
            webView.loadUrl("http://127.0.0.1:8000")
        } catch (e: Exception) { Toast.makeText(this, "Ошибка запуска: ${e.message}", Toast.LENGTH_LONG).show() }
    }

    inner class AndroidBridge {
        @JavascriptInterface fun triggerImport() { 
            val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply { 
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/zip" 
            }
            importLauncher.launch(intent) 
        }
        
        @JavascriptInterface fun triggerExport() { 
            val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "application/zip"
                val timeStamp = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())
                putExtra(Intent.EXTRA_TITLE, "FreeKaraoke_Library_$timeStamp.zip")
            }
            exportLauncher.launch(intent) 
        }
        
        @JavascriptInterface fun showToast(message: String) { 
            runOnUiThread { Toast.makeText(this@MainActivity, message, Toast.LENGTH_SHORT).show() } 
        }
    }
}
EOF

log "Копирование Python-кода проекта в Android-сборку..."
cp -r "$PROJECT_DIR"/* "$ANDROID_DIR/app/src/main/python/"
rm -rf "$ANDROID_DIR/app/src/main/python/.git"
rm -rf "$ANDROID_DIR/app/src/main/python/.buildozer" 2>/dev/null || true

cat << 'EOF' > "$ANDROID_DIR/app/src/main/python/mobile_server.py"
import sys
import os
import threading
from unittest.mock import MagicMock
import json
import traceback
import importlib.util
import logging
import warnings

# Скрываем спам предупреждений, чтобы не засорять ADB logcat
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Перехватываем файловые логи приложения, чтобы оно не засоряло память устройства
class NoOpFileHandler(logging.NullHandler):
    def __init__(self, *args, **kwargs):
        super().__init__()
logging.FileHandler = NoOpFileHandler

APP_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_DIR)
if APP_DIR not in sys.path: sys.path.insert(0, APP_DIR)

for subdir in ['core', 'server', 'app', 'backend', 'db']:
    subpath = os.path.join(APP_DIR, subdir)
    if os.path.isdir(subpath) and subpath not in sys.path: sys.path.insert(0, subpath)

blocked_libs = [
    'torch', 'torchaudio', 'torchvision', 'onnx', 'onnxruntime', 'whisper', 'openai_whisper', 
    'stable_ts', 'stable-ts', 'stable_whisper', 'tiktoken', 'demucs', 'librosa', 'ctranslate2', 'tokenizers', 
    'audio_separator', 'audio-separator', 'pydub', 'audioread', 'soxr', 'samplerate', 'resampy', 
    'julius', 'av', 'huggingface_hub', 'huggingface-hub', 'hf_xet', 'hf-xet', 'numpy', 'scipy', 
    'scikit_learn', 'scikit-learn', 'numba', 'llvmlite', 'einops', 'safetensors', 'diffq', 
    'rotary_embedding_torch', 'faiss', 'mpmath', 'sympy', 'networkx', 'threadpoolctl', 'joblib', 
    'pywebview', 'webview', 'PyQt6', 'PyQt6_WebEngine', 'qtpy', 'psutil', 'pytube', 'yt_dlp',
    'uvicorn', 'colorama', 'click', 'rich', 'websockets', 'soundfile', 'transformers', 'accelerate',
    'rapidfuzz'
]

class MockImporter:
    def __init__(self, blocked):
        self.blocked = set()
        for b in blocked:
            self.blocked.add(b)
            self.blocked.add(b.replace('_', '-'))
            
    def find_spec(self, fullname, path, target=None):
        if fullname.split('.')[0] in self.blocked:
            class MockLoader:
                def create_module(self, spec):
                    m = MagicMock()
                    m.__path__ = [] 
                    return m
                def exec_module(self, module): pass
            return importlib.util.spec_from_loader(fullname, MockLoader())
        return None

sys.meta_path.insert(0, MockImporter(blocked_libs))

JS_PATCH = """
<script>
window.mobile_patch_applied = true;
document.addEventListener("DOMContentLoaded", () => {
    const style = document.createElement('style');
    style.innerHTML = `
        * { touch-action: manipulation !important; -webkit-touch-callout: none; }
        input, textarea { user-select: auto !important; -webkit-user-select: auto !important; }
        ::-webkit-scrollbar { display: none !important; }
    `;
    document.head.appendChild(style);

    window.showAndroidToast = (msg) => {
        if (window.AndroidBridge) AndroidBridge.showToast(msg);
        else alert(msg);
    };

    document.addEventListener('click', (e) => {
        const target = e.target.closest('button, label, input, a');
        if (!target) return;

        const elText = (target.textContent || '').trim();
        const tooltip = target.getAttribute('data-tooltip') || '';
        
        console.log(`[FK_ACTION] Клик по элементу. ID=${target.id}, Текст=${elText.substring(0, 15)}`);

        const isMLBtn = target.matches('label[for="audio-files"]') || 
                        target.id === 'scan-btn' || 
                        target.id === 'ep-btn-rescan' ||
                        tooltip.includes('Пересинхронизировать') ||
                        elText.includes('Пересинхронизировать');
                        
        if (isMLBtn) {
            e.preventDefault(); e.stopPropagation();
            console.log("[FK_ACTION] ЗАБЛОКИРОВАНО: Требуются нейросети.");
            window.showAndroidToast("Функция требует нейросетей (только на ПК)");
            return;
        }

        if (target.id === 'meta-rescan-toggle' || target.matches('input[type="checkbox"]#meta-rescan-toggle')) {
            e.preventDefault(); e.stopPropagation();
            if (target.checked) target.checked = false; 
            console.log("[FK_ACTION] ЗАБЛОКИРОВАНО: Тумблер рескана.");
            window.showAndroidToast("Пересканирование недоступно на Android");
            return;
        }

        if (target.id === 'import-btn' || elText.includes('Импорт')) {
            e.preventDefault(); e.stopPropagation();
            console.log("[FK_ACTION] ВЫЗОВ: Импорт ZIP");
            if (window.AndroidBridge) AndroidBridge.triggerImport();
            return;
        }
        
        if (target.id === 'export-btn' || elText.includes('Экспорт')) {
            e.preventDefault(); e.stopPropagation();
            console.log("[FK_ACTION] ВЫЗОВ: Экспорт ZIP");
            if (window.AndroidBridge) AndroidBridge.triggerExport();
            return;
        }
    }, true);
});

window.executeMobileImport = (path) => {
    console.log("[FK_ACTION] API Request: Import " + path);
    window.showAndroidToast("Начат импорт архива...");
    fetch('/mobile_api/import', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: path}) });
};
window.executeMobileExport = (path) => {
    console.log("[FK_ACTION] API Request: Export " + path);
    window.showAndroidToast("Начат экспорт архива...");
    fetch('/mobile_api/export', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path: path}) });
};
</script>
"""

def inject_html_patch():
    for root, dirs, files in os.walk(APP_DIR):
        for file in files:
            if file.endswith('.html'):
                filepath = os.path.join(root, file)
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                if 'mobile_patch_applied' not in content:
                    content = content.replace('</body>', JS_PATCH + '\n</body>')
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)

inject_html_patch()

def setup_storage():
    music_dir = "/storage/emulated/0/Music/free_karaoke_library"
    os.makedirs(music_dir, exist_ok=True)
    os.environ['FK_LIBRARY_DIR'] = music_dir

    internal_data_dir = os.path.join(APP_DIR, "app_data")
    os.makedirs(internal_data_dir, exist_ok=True)
    os.environ['FK_DB_DIR'] = internal_data_dir
    os.environ['FK_CACHE_DIR'] = internal_data_dir
    # Возвращено на internal_data_dir как в 33.2, чтобы os.makedirs в приложении не падал с NotADirectoryError!
    os.environ['FK_LOGS_DIR'] = internal_data_dir 
    return music_dir

setup_storage()

import fastapi
from a2wsgi import ASGIMiddleware
original_app = None

for module_path in ['desktop_main', 'server', 'core.main', 'main']:
    try:
        if '.' in module_path:
            mod_name, attr = module_path.rsplit('.', 1)
            mod = __import__(mod_name, fromlist=[attr])
            target_mod = getattr(mod, attr)
        else:
            target_mod = __import__(module_path)
        for name in dir(target_mod):
            attr = getattr(target_mod, name)
            if isinstance(attr, fastapi.FastAPI):
                original_app = attr
                break
        if original_app: break
    except Exception as e:
        # Добавлен вывод реальной ошибки инициализации для отладки
        print(f"[SERVER_INIT] Пропуск {module_path}: {e}")
        continue

if not original_app:
    original_app = fastapi.FastAPI()
    @original_app.get("/")
    def read_root(): return {"status": "FastAPI Not Found."}

wsgi_app = ASGIMiddleware(original_app)

def proxy_app(environ, start_response):
    path = environ.get('PATH_INFO', '').lower()
    if environ['REQUEST_METHOD'] == 'POST' and path in ['/mobile_api/import', '/mobile_api/export']:
        try:
            length = int(environ.get('CONTENT_LENGTH', '0'))
            data = json.loads(environ['wsgi.input'].read(length))
            filepath = data.get('path')
            from core.tasks import import_library_task, export_library_task
            
            print(f"[FK_ACTION_PYTHON] Запуск задачи {'Импорт' if 'import' in path else 'Экспорт'}: {filepath}")
            if path == '/mobile_api/import':
                threading.Thread(target=import_library_task, args=(filepath,), daemon=True).start()
            else:
                threading.Thread(target=export_library_task, args=(filepath,), daemon=True).start()
                
            res = json.dumps({"status": "Task submitted"}).encode('utf-8')
            start_response('200 OK', [('Content-Type', 'application/json'), ('Content-Length', str(len(res)))])
            return [res]
        except Exception as e:
            res = json.dumps({"error": str(e)}).encode('utf-8')
            start_response('500 Error', [('Content-Type', 'application/json')])
            return [res]
    return wsgi_app(environ, start_response)

def start_server():
    from werkzeug.serving import make_server
    try:
        server = make_server('127.0.0.1', 8000, proxy_app)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print("[FK_SERVER] Mobile Server Started Successfully")
    except Exception as e:
        print("[FK_SERVER] Error:", traceback.format_exc())
EOF

log "Скрипты внедрены." "SUCCESS"

KEYSTORE_PATH="$BUILD_ROOT/keystore/freekaraoke.keystore"
KEY_PASS="karaokepass123"

if [ ! -f "$KEYSTORE_PATH" ]; then
    log "Генерация ключа подписи..."
    keytool -genkey -v -keystore "$KEYSTORE_PATH" -alias fk_alias \
        -keyalg RSA -keysize 2048 -validity 10000 \
        -storepass "$KEY_PASS" -keypass "$KEY_PASS" \
        -dname "CN=Free Karaoke, OU=Android, O=FreeKaraoke, C=RU"
fi

log "НАЧАЛО СБОРКИ RELEASE APK ЧЕРЕЗ GRADLE..."
cd "$ANDROID_DIR"

chmod +x "$GRADLE_DIR/bin/gradle"

"$GRADLE_DIR/bin/gradle" assembleRelease --stacktrace --info 2>&1 | tee "$BUILD_ROOT/logs/gradle_build.log"

if [ ${PIPESTATUS[0]} -ne 0 ]; then
    log_error_exit "Сборка Gradle завершилась с ошибкой! (Смотри анализ выше)"
fi

UNSIGNED_APK="$ANDROID_DIR/app/build/outputs/apk/release/app-release-unsigned.apk"

if [ -f "$UNSIGNED_APK" ]; then
    log "Подписываем APK..."
    FINAL_APK="$BUILD_ROOT/output/FreeKaraoke-Native-Release.apk"
    
    ZIPALIGN_CMD="$ANDROID_HOME/build-tools/$ANDROID_BUILD_TOOLS/zipalign"
    APKSIGNER_CMD="$ANDROID_HOME/build-tools/$ANDROID_BUILD_TOOLS/apksigner"
    
    "$ZIPALIGN_CMD" -f -v -p 4 "$UNSIGNED_APK" "$ANDROID_DIR/aligned.apk" > /dev/null
    "$APKSIGNER_CMD" sign --ks "$KEYSTORE_PATH" --ks-pass "pass:$KEY_PASS" --out "$FINAL_APK" "$ANDROID_DIR/aligned.apk"
    
    log "РЕЛИЗ ГОТОВ!" "SUCCESS"
    log "Файл находится здесь: $FINAL_APK" "SUCCESS"
else
    log_error_exit "Не удалось найти итоговый apk."
fi

echo ""
read -p "Удалить тяжелые временные файлы (Android SDK, исходники, Gradle и ВСЕ кэши)? (y/n): " CLEANUP
if [[ "$CLEANUP" =~ ^[Yy]$ ]]; then
    rm -rf "$ANDROID_DIR" "$PROJECT_DIR" "$BUILD_ROOT/tools"
    log "Очистка завершена. Система абсолютно чиста." "SUCCESS"
fi

echo -e "\n${GREEN}Установка завершена. Скопируйте APK на Android устройство и установите.${NC}"
echo -e "${YELLOW}Для отладки событий кнопок через ADB используйте команду:${NC}"
echo -e "${YELLOW}adb logcat -s FreeKaraoke-JS python FK_SERVER FK_ACTION_PYTHON${NC}\n"
read -p "Нажмите Enter для выхода из скрипта..."