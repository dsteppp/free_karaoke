#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Free Karaoke — Генерация иконок из SVG
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SVG_SOURCE="$PROJECT_ROOT/desktop/linux/ai-karaoke.svg"

echo "🎨 Free Karaoke — Генерация иконок"
echo ""

# Проверка rsvg-convert
if ! command -v rsvg-convert &>/dev/null; then
    echo "⚠️  rsvg-convert не найден"
    echo "   Установите: sudo apt install librsvg2-bin (Debian/Ubuntu)"
    echo "              или: brew install librsvg (macOS)"
    echo ""
    echo "   Альтернатива: используйте онлайн-конвертер"
    echo "   https://cloudconvert.com/svg-to-png"
    exit 0
fi

if [ ! -f "$SVG_SOURCE" ]; then
    echo "❌ SVG-источник не найден: $SVG_SOURCE"
    exit 1
fi

# ── Android mipmap иконки ──────────────────────────────
ANDROID_DIR="$PROJECT_ROOT/android/app/src/main/res"

declare -A SIZES=(
    ["mdpi"]=48
    ["hdpi"]=72
    ["xhdpi"]=96
    ["xxhdpi"]=144
    ["xxxhdpi"]=192
)

echo "📱 Android mipmap иконки..."
for density in mdpi hdpi xhdpi xxhdpi xxxhdpi; do
    size=${SIZES[$density]}
    output_dir="$ANDROID_DIR/mipmap-$density"
    mkdir -p "$output_dir"

    # Фон (круг) + иконка
    rsvg-convert \
        --width="$size" \
        --height="$size" \
        "$SVG_SOURCE" \
        -o "$output_dir/ic_launcher.png"

    echo "   ✅ mipmap-$density: ${size}x${size}"
done

# Play Store (512x512)
PLAY_STORE_DIR="$PROJECT_ROOT/android/play-store"
mkdir -p "$PLAY_STORE_DIR"
rsvg-convert --width=512 --height=512 "$SVG_SOURCE" -o "$PLAY_STORE_DIR/icon.png"
echo "   ✅ play-store: 512x512"

echo ""
echo "✅ Генерация иконок завершена!"
