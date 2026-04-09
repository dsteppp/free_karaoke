#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Free Karaoke — Сборка Linux AppImage
# ═══════════════════════════════════════════════════════
# Запускать:
#   cd desktop/linux
#   bash build-linux.sh
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CORE_DIR="$PROJECT_ROOT/core"
BUILD_DIR="$SCRIPT_DIR/build"
APPDIR="$BUILD_DIR/AppDir"
OUTPUT="FreeKaraoke-x86_64.AppImage"

echo "🏗️  Free Karaoke — Сборка Linux AppImage"
echo "   Проект: $PROJECT_ROOT"
echo ""

# ── 1. Проверка зависимостей ───────────────────────────
check_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo "❌ Не найден: $1"
        echo "   Установите: $2"
        exit 1
    fi
}

check_dep python3 "python3"
check_dep pip3 "python3-pip"
check_dep appimagetool "appimagetool (https://github.com/AppImage/AppImageKit)"
check_dep ffmpeg "ffmpeg"

echo "✅ Зависимости найдены"

# ── 2. Очистка ─────────────────────────────────────────
if [ -d "$BUILD_DIR" ]; then
    echo "🗑️  Очистка предыдущей сборки..."
    rm -rf "$BUILD_DIR"
fi

# ── 3. Создание AppDir ─────────────────────────────────
echo "📦 Создание AppDir..."
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib"
mkdir -p "$APPDIR/usr/share/ai-karaoke"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Копируем исходники
echo "   Копирование core/..."
cp -r "$CORE_DIR" "$APPDIR/usr/share/ai-karaoke/core"

# Копируем иконку
if [ -f "$SCRIPT_DIR/ai-karaoke.svg" ]; then
    cp "$SCRIPT_DIR/ai-karaoke.svg" "$APPDIR/ai-karaoke.svg"
    cp "$SCRIPT_DIR/ai-karaoke.svg" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ai-karaoke.svg"
fi

# Копируем desktop-файл
if [ -f "$SCRIPT_DIR/ai-karaoke.desktop" ]; then
    cp "$SCRIPT_DIR/ai-karaoke.desktop" "$APPDIR/ai-karaoke.desktop"
fi

# Копируем модели (если есть)
MODELS_DIR="$PROJECT_ROOT/desktop/shared/models"
if [ -d "$MODELS_DIR" ]; then
    HAS_MODELS=false
    ls "$MODELS_DIR"/*.pt &>/dev/null && HAS_MODELS=true
    ls "$MODELS_DIR"/*.h5 &>/dev/null && HAS_MODELS=true

    if [ "$HAS_MODELS" = true ]; then
        echo "   Копирование ML-моделей..."
        mkdir -p "$APPDIR/usr/share/ai-karaoke/models"
        cp -r "$MODELS_DIR"/* "$APPDIR/usr/share/ai-karaoke/models/" 2>/dev/null || true
    else
        echo "   ⚠️  Модели не найдены. Запустите download-models.sh"
    fi
fi

# Копируем portable.env.example
if [ -f "$PROJECT_ROOT/desktop/portable.env.example" ]; then
    mkdir -p "$APPDIR/usr/share/ai-karaoke/config"
    cp "$PROJECT_ROOT/desktop/portable.env.example" "$APPDIR/usr/share/ai-karaoke/config/"
fi

# ── 4. Создание Python venv в AppDir ───────────────────
echo "📦 Создание Python venv..."
python3 -m venv "$APPDIR/usr/share/ai-karaoke/.venv"
source "$APPDIR/usr/share/ai-karaoke/.venv/bin/activate"

pip install --upgrade pip -q
pip install -r "$CORE_DIR/requirements.txt" -q

# ── 5. Создание AppRun ─────────────────────────────────
echo "   Создание AppRun..."
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
# AppRun — точка входа AppImage

# Определяем базовую директорию
if [ -n "$APPIMAGE" ]; then
    # Запущено из AppImage
    BASE_DIR="$(dirname "$APPIMAGE")"
    APPDIR="${APPIMAGE%/*}"

    # Portable-режим: данные рядом с AppImage
    PORTABLE_DIR="$BASE_DIR/FreeKaraoke"
    mkdir -p "$PORTABLE_DIR"/{library,config,logs,cache}

    # Переменные окружения для portable-режима
    export FK_LIBRARY_DIR="$PORTABLE_DIR/library"
    export FK_CONFIG_DIR="$PORTABLE_DIR/config"
    export FK_CACHE_DIR="$PORTABLE_DIR/cache"
    export FK_LOGS_DIR="$PORTABLE_DIR/logs"
    export FK_MODELS_DIR="$APPDIR/usr/share/ai-karaoke/models"

    # Изоляция кэшей
    export TORCH_HOME="$PORTABLE_DIR/cache/torch"
    export HF_HOME="$PORTABLE_DIR/cache/huggingface"
    export HUGGINGFACE_HUB_CACHE="$PORTABLE_DIR/cache/huggingface/hub"
    export TRANSFORMERS_CACHE="$PORTABLE_DIR/cache/huggingface/hub"
    export UV_CACHE_DIR="$PORTABLE_DIR/cache/uv"
    export XDG_CACHE_HOME="$PORTABLE_DIR/cache"

    # Загружаем portable.env если есть
    ENV_FILE="$PORTABLE_DIR/config/portable.env"
    if [ -f "$ENV_FILE" ]; then
        set -a
        source "$ENV_FILE"
        set +a
    fi
else
    # Запущено из распакованного AppDir (для отладки)
    APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PORTABLE_DIR="$APPDIR/user"
    mkdir -p "$PORTABLE_DIR"/{library,config,logs,cache}

    export FK_LIBRARY_DIR="$PORTABLE_DIR/library"
    export FK_CONFIG_DIR="$PORTABLE_DIR/config"
    export FK_CACHE_DIR="$PORTABLE_DIR/cache"
    export FK_LOGS_DIR="$PORTABLE_DIR/logs"
fi

# Активируем venv
source "$APPDIR/usr/share/ai-karaoke/.venv/bin/activate"

# Переходим в core/
cd "$APPDIR/usr/share/ai-karaoke/core"

# Запускаем launcher
exec python launcher.py "$@"
APPRUN

chmod +x "$APPDIR/AppRun"

# ── 6. Сборка AppImage ─────────────────────────────────
echo "🔨 Сборка AppImage..."

cd "$BUILD_DIR"

# Удаляем старый AppImage
rm -f "$SCRIPT_DIR/$OUTPUT"

# AppImageTool
appimagetool \
    --comp zstd \
    -u "gh-releases-zsync|dstp|free_karaoke|latest|FreeKaraoke-x86_64.AppImage.zsync" \
    AppDir \
    "$SCRIPT_DIR/$OUTPUT"

chmod +x "$SCRIPT_DIR/$OUTPUT"

# ── 7. Итог ────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo "✅ Сборка завершена!"
echo "═══════════════════════════════════════════"
echo ""
echo "📦 Артефакт: $SCRIPT_DIR/$OUTPUT"
APPIMAGE_SIZE=$(du -sh "$SCRIPT_DIR/$OUTPUT" | cut -f1)
echo "📐 Размер: $APPIMAGE_SIZE"
echo ""
echo "🚀 Использование:"
echo "   chmod +x $OUTPUT"
echo "   ./$OUTPUT"
echo ""
echo "   При первом запуске создастся папка FreeKaraoke/ рядом с AppImage"
echo "   для данных пользователя (библиотека, кэш, логи)."
echo ""
