#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Free Karaoke — Сборка Linux AppImage
# Использует существующий .venv через symlink (мгновенно)
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CORE_DIR="$PROJECT_ROOT/core"
BUILD_DIR="$SCRIPT_DIR/_build-env"
OUTPUT_DIR="$SCRIPT_DIR/v1.0.0"
APPDIR="$BUILD_DIR/AppDir"
VENV_SOURCE="$PROJECT_ROOT/.venv"

echo "🏗️  Free Karaoke — Сборка Linux AppImage"
echo "   Проект: $PROJECT_ROOT"
echo ""

APPIMAGETOOL="$BUILD_DIR/appimagetool/appimagetool-x86_64.AppImage"

if [ ! -d "$VENV_SOURCE" ]; then echo "❌ .venv не найден"; exit 1; fi
if [ ! -f "$APPIMAGETOOL" ]; then echo "❌ appimagetool не найден"; exit 1; fi

# ── Очистка ─────────────────────────────────────────────
if [ -d "$APPDIR" ]; then
    echo "🗑️  Очистка предыдущего AppDir..."
    rm -rf "$APPDIR"
fi

# ── Создание AppDir ─────────────────────────────────────
echo "📦 Создание AppDir..."
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/ai-karaoke"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Копируем core (без мусора)
echo "   Копирование core/..."
rsync -a --exclude='cache' --exclude='debug_logs' --exclude='__pycache__' \
       --exclude='*.db*' --exclude='.env' --exclude='.env.cache' \
       --exclude='library' --exclude='models' \
       "$CORE_DIR/" "$APPDIR/usr/share/ai-karaoke/core/"

# Symlink на существующий .venv (мгновенно, без копирования 19 ГБ)
echo "   Symlink .venv → $VENV_SOURCE"
ln -s "$VENV_SOURCE" "$APPDIR/usr/share/ai-karaoke/.venv"

# Иконка + desktop-файл
DESKTOP_DIR="$PROJECT_ROOT/desktop/linux"
cp "$DESKTOP_DIR/ai-karaoke.svg" "$APPDIR/ai-karaoke.svg"
cp "$DESKTOP_DIR/ai-karaoke.svg" "$APPDIR/usr/share/icons/hicolor/256x256/apps/ai-karaoke.svg"
cp "$DESKTOP_DIR/ai-karaoke.desktop" "$APPDIR/ai-karaoke.desktop"

# Модели (Whisper из _build-env)
MODELS_DIR="$BUILD_DIR/models"
if [ -f "$MODELS_DIR/whisper/medium.pt" ]; then
    echo "   Копирование Whisper модели..."
    mkdir -p "$APPDIR/usr/share/ai-karaoke/models/whisper"
    cp "$MODELS_DIR/whisper/medium.pt" "$APPDIR/usr/share/ai-karaoke/models/whisper/"
fi

# portable.env.example
if [ -f "$PROJECT_ROOT/desktop/portable.env.example" ]; then
    mkdir -p "$APPDIR/usr/share/ai-karaoke/config"
    cp "$PROJECT_ROOT/desktop/portable.env.example" "$APPDIR/usr/share/ai-karaoke/config/"
fi

# ── AppRun ──────────────────────────────────────────────
echo "   Создание AppRun..."
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
APPDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "$APPIMAGE" ]; then
    BASE_DIR="$(dirname "$APPIMAGE")"
    PORTABLE_DIR="$BASE_DIR/FreeKaraoke"
else
    PORTABLE_DIR="$APPDIR/user"
fi

mkdir -p "$PORTABLE_DIR"/{library,config,logs,cache}

export FK_LIBRARY_DIR="$PORTABLE_DIR/library"
export FK_CONFIG_DIR="$PORTABLE_DIR/config"
export FK_CACHE_DIR="$PORTABLE_DIR/cache"
export FK_LOGS_DIR="$PORTABLE_DIR/logs"
export FK_DB_DIR="$PORTABLE_DIR"
export FK_MODELS_DIR="$APPDIR/usr/share/ai-karaoke/models"

export TORCH_HOME="$PORTABLE_DIR/cache/torch"
export HF_HOME="$PORTABLE_DIR/cache/huggingface"
export HUGGINGFACE_HUB_CACHE="$PORTABLE_DIR/cache/huggingface/hub"
export TRANSFORMERS_CACHE="$PORTABLE_DIR/cache/huggingface/hub"
export UV_CACHE_DIR="$PORTABLE_DIR/cache/uv"
export XDG_CACHE_HOME="$PORTABLE_DIR/cache"

ENV_FILE="$PORTABLE_DIR/config/portable.env"
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

source "$APPDIR/usr/share/ai-karaoke/.venv/bin/activate"
cd "$APPDIR/usr/share/ai-karaoke/core"
exec python launcher.py "$@"
APPRUN

chmod +x "$APPDIR/AppRun"

# ── Сборка AppImage ────────────────────────────────────
echo "🔨 Сборка AppImage..."
mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_DIR/FreeKaraoke-x86_64.AppImage"

ARCH=x86_64 "$APPIMAGETOOL" \
    --appimage-extract-and-run \
    "$APPDIR" \
    "$OUTPUT_DIR/FreeKaraoke-x86_64.AppImage" 2>&1

chmod +x "$OUTPUT_DIR/FreeKaraoke-x86_64.AppImage"

# ── Итог ────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo "✅ Сборка AppImage завершена!"
echo "═══════════════════════════════════════════"
echo ""
APPIMAGE_SIZE=$(du -sh "$OUTPUT_DIR/FreeKaraoke-x86_64.AppImage" | cut -f1)
echo "📦 Артефакт: $OUTPUT_DIR/FreeKaraoke-x86_64.AppImage"
echo "📐 Размер: $APPIMAGE_SIZE"
echo ""
