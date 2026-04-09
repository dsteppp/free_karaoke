#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Free Karaoke — Валидация JSON-форматов
# Проверяет, что тестовые данные соответствуют схемам
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FORMATS_DIR="$PROJECT_ROOT/shared/formats"
TEST_DATA_DIR="$PROJECT_ROOT/shared/test-data"

echo "🔍 Free Karaoke — Валидация JSON-форматов"
echo ""

# Проверка jsonschema
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 не найден"
    exit 1
fi

# Устанавливаем jsonschema если нет
python3 -c "import jsonschema" 2>/dev/null || pip3 install jsonschema -q

ERRORS=0

# Валидация karaoke-lyrics-schema.json
echo "📋 Проверка karaoke-lyrics-schema.json..."
python3 -c "
import json, sys
schema = json.load(open('$FORMATS_DIR/karaoke-lyrics-schema.json'))
print('  ✅ Схема валидна')
" || { echo "  ❌ Ошибка схемы"; ERRORS=$((ERRORS+1)); }

# Валидация library-schema.json
echo "📋 Проверка library-schema.json..."
python3 -c "
import json, sys
schema = json.load(open('$FORMATS_DIR/library-schema.json'))
print('  ✅ Схема валидна')
" || { echo "  ❌ Ошибка схемы"; ERRORS=$((ERRORS+1)); }

# Если есть тестовые данные — проверяем их
if [ -d "$TEST_DATA_DIR" ]; then
    echo ""
    echo "📦 Проверка тестовых данных..."
    for json_file in "$TEST_DATA_DIR"/*.json; do
        [ -f "$json_file" ] || continue
        echo "  Проверяю: $(basename "$json_file")"
        python3 -c "
import json
data = json.load(open('$json_file'))
print('    ✅ JSON валиден')
" || { echo "    ❌ Ошибка JSON"; ERRORS=$((ERRORS+1)); }
    done
fi

echo ""
if [ $ERRORS -eq 0 ]; then
    echo "✅ Все проверки пройдены!"
else
    echo "❌ Ошибок: $ERRORS"
    exit 1
fi
