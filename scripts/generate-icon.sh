#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Free Karaoke — Generate Icons from SVG
# Generates PNG icons for Android mipmap + Play Store
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SVG_SOURCE="$PROJECT_ROOT/desktop/linux/ai-karaoke.svg"

echo "🎨 Free Karaoke — Icon Generation"
echo ""

# Check rsvg-convert
if ! command -v rsvg-convert &>/dev/null; then
    echo "⚠️  rsvg-convert not found"
    echo "   Install: sudo apt install librsvg2-bin (Debian/Ubuntu)"
    echo "           or: brew install librsvg (macOS)"
    exit 0
fi

if [ ! -f "$SVG_SOURCE" ]; then
    echo "❌ SVG source not found: $SVG_SOURCE"
    exit 1
fi

# Windows .ico (256x256)
echo "🪟 Windows icon..."
rsvg-convert --width=256 --height=256 "$SVG_SOURCE" -o "$PROJECT_ROOT/releases/icon-256.png"
echo "   ✅ 256x256 → releases/icon-256.png"

# Linux AppImage icon (already SVG in releases/)
cp "$SVG_SOURCE" "$PROJECT_ROOT/releases/ai-karaoke.svg"
echo "   ✅ SVG → releases/ai-karaoke.svg"

echo ""
echo "✅ Icon generation complete!"
