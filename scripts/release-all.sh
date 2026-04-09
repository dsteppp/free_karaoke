#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Free Karaoke — Помощник создания релиза
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Free Karaoke — Помощник создания релиза"
echo ""

# ── 1. Версия ──────────────────────────────────────────
read -p "📋 Версия релиза (например, v1.0.0): " VERSION
if [ -z "$VERSION" ]; then
    echo "❌ Версия не указана"
    exit 1
fi

# ── 2. Проверка CHANGELOG ─────────────────────────────
if ! grep -q "## \[$VERSION\]" "$PROJECT_ROOT/CHANGELOG.md" 2>/dev/null; then
    echo "⚠️  CHANGELOG.md не содержит записи для $VERSION"
    read -p "Продолжить без CHANGELOG? (y/N): " CONTINUE
    if [ "$CONTINUE" != "y" ]; then
        echo "Обновите CHANGELOG.md и запустите снова."
        exit 1
    fi
fi

# ── 3. Сборка Windows ─────────────────────────────────
echo ""
echo "🪟 Сборка Windows..."
if [ -f "$PROJECT_ROOT/desktop/windows/build-windows.ps1" ]; then
    echo "   ⚠️  Запустите на Windows: desktop/windows/build-windows.ps1"
    echo "   Файл: FreeKaraoke-Windows.zip"
else
    echo "   ❌ build-windows.ps1 не найден"
fi

# ── 4. Сборка Linux ───────────────────────────────────
echo ""
echo "🐧 Сборка Linux..."
if [ -f "$PROJECT_ROOT/desktop/linux/build-linux.sh" ]; then
    read -p "Собрать AppImage сейчас? (y/N): " BUILD_LINUX
    if [ "$BUILD_LINUX" = "y" ]; then
        bash "$PROJECT_ROOT/desktop/linux/build-linux.sh"
    else
        echo "   ⚠️  Запустите: bash desktop/linux/build-linux.sh"
    fi
else
    echo "   ❌ build-linux.sh не найден"
fi

# ── 5. Сборка Android ─────────────────────────────────
echo ""
echo "🤖 Сборка Android..."
if [ -f "$PROJECT_ROOT/android/gradlew" ]; then
    read -p "Собрать APK сейчас? (y/N): " BUILD_ANDROID
    if [ "$BUILD_ANDROID" = "y" ]; then
        cd "$PROJECT_ROOT/android"
        ./gradlew assembleRelease
        echo "   ✅ APK: android/app/build/outputs/apk/release/app-release.apk"
    else
        echo "   ⚠️  Запустите: cd android && ./gradlew assembleRelease"
    fi
else
    echo "   ⚠️  Gradle wrapper не найден. Сгенерируйте: gradle wrapper"
    echo "   Затем: cd android && ./gradlew assembleRelease"
fi

# ── 6. Контрольные суммы ──────────────────────────────
echo ""
echo "🔐 Генерация контрольных сумм..."
CHECKSUM_FILE="$PROJECT_ROOT/checksums.sha256"
> "$CHECKSUM_FILE"

for artifact in \
    "$PROJECT_ROOT/desktop/windows/FreeKaraoke-Windows.zip" \
    "$PROJECT_ROOT/desktop/linux/FreeKaraoke-x86_64.AppImage" \
    "$PROJECT_ROOT/android/app/build/outputs/apk/release/app-release.apk"
do
    if [ -f "$artifact" ]; then
        (cd "$(dirname "$artifact")" && sha256sum "$(basename "$artifact")") >> "$CHECKSUM_FILE"
        echo "   ✅ $(basename "$artifact")"
    else
        echo "   ⏭  $(basename "$artifact") — не найден (пропущен)"
    fi
done

# ── 7. Git тег ────────────────────────────────────────
echo ""
read -p "Создать git-тег $VERSION? (y/N): " CREATE_TAG
if [ "$CREATE_TAG" = "y" ]; then
    cd "$PROJECT_ROOT"
    git tag -a "$VERSION" -m "Release $VERSION"
    echo "   ✅ Тег $VERSION создан"
    echo "   Отправьте: git push origin $VERSION"
fi

# ── 8. Итог ───────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "✅ Помощник релиза завершён!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "📋 Следующие шаги для GitHub Releases:"
echo "   1. Перейдите: https://github.com/dstp/free_karaoke/releases/new"
echo "   2. Выберите тег: $VERSION"
echo "   3. Загрузите артефакты:"
echo "      - FreeKaraoke-Windows.zip"
echo "      - FreeKaraoke-x86_64.AppImage"
echo "      - FreeKaraoke-Android.apk"
echo "      - checksums.sha256"
echo "   4. Напишите описание релиза (из CHANGELOG.md)"
echo "   5. Опубликуйте!"
echo ""
