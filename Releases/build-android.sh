#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Free Karaoke — Сборка Android APK
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ANDROID_DIR="$PROJECT_ROOT/android"
BUILD_DIR="$SCRIPT_DIR/_build-env"
OUTPUT_DIR="$SCRIPT_DIR/v1.0.0"

export ANDROID_HOME="$BUILD_DIR/android-sdk"
export JAVA_HOME="$BUILD_DIR/jdk-21.0.2"
GRADLE="$BUILD_DIR/gradle-8.12/bin/gradle"

echo "🤖 Free Karaoke — Сборка Android APK"
echo "   ANDROID_HOME: $ANDROID_HOME"
echo ""

if [ ! -d "$ANDROID_HOME" ]; then echo "❌ Android SDK не найден"; exit 1; fi
if [ ! -f "$GRADLE" ]; then echo "❌ Gradle не найден"; exit 1; fi

cd "$ANDROID_DIR"

# ── Gradle wrapper (если нет) ─────────────────────────
if [ ! -f "./gradlew" ]; then
    echo "📦 Создание Gradle wrapper..."
    "$GRADLE" wrapper 2>&1 | tail -5
fi

# ── Принятие лицензий ──────────────────────────────────
mkdir -p "$ANDROID_HOME/licenses"
echo -e "\n24333f8a63b6825ea9c5514f83c2829b004d1fee" > "$ANDROID_HOME/licenses/android-sdk-license"
echo -e "\n84831b9409646a918e30573bab4c9c91346d8abd" >> "$ANDROID_HOME/licenses/android-sdk-license"

# ── Сборка Debug APK ────────────────────────────────────
echo "🔨 Сборка Debug APK..."
./gradlew assembleDebug --no-daemon 2>&1 | tail -20

# ── Копирование в Releases ─────────────────────────────
DEBUG_APK="$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk"
if [ -f "$DEBUG_APK" ]; then
    cp "$DEBUG_APK" "$OUTPUT_DIR/FreeKaraoke-Android-debug.apk"
    APK_SIZE=$(du -sh "$OUTPUT_DIR/FreeKaraoke-Android-debug.apk" | cut -f1)
    echo ""
    echo "═══════════════════════════════════════════"
    echo "✅ Сборка Android APK завершена!"
    echo "═══════════════════════════════════════════"
    echo ""
    echo "📦 Артефакт: $OUTPUT_DIR/FreeKaraoke-Android-debug.apk"
    echo "📐 Размер: $APK_SIZE"
    echo ""
    echo "🚀 Установка: adb install FreeKaraoke-Android-debug.apk"
    echo ""
else
    echo "❌ APK не найден: $DEBUG_APK"
    exit 1
fi
