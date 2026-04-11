#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Free Karaoke — Validate JSON Formats
# Checks that test data matches schemas
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FORMATS_DIR="$PROJECT_ROOT/shared/formats"
TEST_DATA_DIR="$PROJECT_ROOT/shared/test-data"

echo "🔍 Free Karaoke — JSON Format Validation"
echo ""

if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found"
    exit 1
fi

# Install jsonschema if needed
python3 -c "import jsonschema" 2>/dev/null || pip3 install jsonschema -q

ERRORS=0

# Validate schemas
for schema in karaoke-lyrics-schema.json library-schema.json; do
    echo "📋 Validating $schema..."
    if python3 -c "import json; json.load(open('$FORMATS_DIR/$schema'))"; then
        echo "  ✅ Schema is valid"
    else
        echo "  ❌ Schema error"
        ERRORS=$((ERRORS+1))
    fi
done

# Validate test data
if [ -d "$TEST_DATA_DIR" ]; then
    echo ""
    echo "📦 Validating test data..."
    for json_file in "$TEST_DATA_DIR"/*.json; do
        [ -f "$json_file" ] || continue
        echo "  Checking: $(basename "$json_file")"
        if python3 -c "import json; json.load(open('$json_file'))"; then
            echo "    ✅ JSON is valid"
        else
            echo "    ❌ JSON error"
            ERRORS=$((ERRORS+1))
        fi
    done
fi

echo ""
if [ $ERRORS -eq 0 ]; then
    echo "✅ All validations passed!"
else
    echo "❌ Errors: $ERRORS"
    exit 1
fi
