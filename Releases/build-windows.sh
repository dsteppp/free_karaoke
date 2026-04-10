#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════
# Free Karaoke — Сборка Windows Portable
# Создаёт portable-папку с .bat лаунчером
# (PyInstaller кросс-компиляция Linux→Windows невозможна)
# ═══════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CORE_DIR="$PROJECT_ROOT/core"
BUILD_DIR="$SCRIPT_DIR/_build-env"
OUTPUT_DIR="$SCRIPT_DIR/v1.0.0"
VENV_SOURCE="$PROJECT_ROOT/.venv"

echo "🪟 Free Karaoke — Сборка Windows Portable"
echo "   Проект: $PROJECT_ROOT"
echo ""

FREE_KARAOKE="$OUTPUT_DIR/Free_Karaoke"

if [ ! -d "$VENV_SOURCE" ]; then echo "❌ .venv не найден"; exit 1; fi

# ── Очистка ─────────────────────────────────────────────
rm -rf "$FREE_KARAOKE"
mkdir -p "$FREE_KARAOKE"

# ── Создание portable-папки ─────────────────────────────
echo "📦 Создание portable-папки..."

# Копируем core (без Linux-специфичного мусора)
echo "   Копирование core/..."
rsync -a --exclude='cache' --exclude='debug_logs' --exclude='__pycache__' \
       --exclude='*.db*' --exclude='.env' --exclude='.env.cache' \
       --exclude='library' --exclude='models' --exclude='*.so' \
       "$CORE_DIR/" "$FREE_KARAOKE/app/"

# Копируем .venv (Python 3.11 + все пакеты)
echo "   Копирование Python venv (это может занять время, ~19 ГБ)..."
echo "   Альтернатива: скопируйте .venv вручную в $FREE_KARAOKE/_runtime/"
cp -r "$VENV_SOURCE" "$FREE_KARAOKE/_runtime"
echo "   ✅ venv скопирован"

# Копируем модели (Whisper)
MODELS_DIR="$BUILD_DIR/models"
if [ -f "$MODELS_DIR/whisper/medium.pt" ]; then
    echo "   Копирование Whisper модели..."
    mkdir -p "$FREE_KARAOKE/models/whisper"
    cp "$MODELS_DIR/whisper/medium.pt" "$FREE_KARAOKE/models/whisper/"
fi

# portable.env.example
if [ -f "$PROJECT_ROOT/desktop/portable.env.example" ]; then
    mkdir -p "$FREE_KARAOKE/config"
    cp "$PROJECT_ROOT/desktop/portable.env.example" "$FREE_KARAOKE/config/"
fi

# Создаём пользовательские директории
mkdir -p "$FREE_KARAOKE/user"/{library,config,logs,cache}

# ── Создание .bat лаунчера ─────────────────────────────
echo "   Создание FreeKaraoke.bat..."
cat > "$FREE_KARAOKE/FreeKaraoke.bat" << 'BAT'
@echo off
chcp 65001 >nul
title Free Karaoke

echo =============================================
echo    Free Karaoke v1.0.0 — запуск...
echo =============================================
echo.

set "BASE_DIR=%~dp0"
set "APP_DIR=%BASE_DIR%app"
set "VENV_DIR=%BASE_DIR%_runtime"
set "USER_DIR=%BASE_DIR%user"

:: Создаём директории если нет
if not exist "%USER_DIR%\library" mkdir "%USER_DIR%\library"
if not exist "%USER_DIR%\config" mkdir "%USER_DIR%\config"
if not exist "%USER_DIR%\logs" mkdir "%USER_DIR%\logs"
if not exist "%USER_DIR%\cache" mkdir "%USER_DIR%\cache"

:: Portable переменные окружения
set "FK_LIBRARY_DIR=%USER_DIR%\library"
set "FK_CONFIG_DIR=%USER_DIR%\config"
set "FK_CACHE_DIR=%USER_DIR%\cache"
set "FK_LOGS_DIR=%USER_DIR%\logs"
set "FK_DB_DIR=%BASE_DIR%"
set "FK_MODELS_DIR=%BASE_DIR%models"

:: Загружаем portable.env если есть
if exist "%USER_DIR%\config\portable.env" (
    for /f "tokens=1,* delims==" %%a in ('findstr /v "^#" "%USER_DIR%\config\portable.env"') do (
        set "%%a=%%b"
    )
)

:: Активируем venv и запускаем
cd /d "%APP_DIR%"
call "%VENV_DIR%\Scripts\activate.bat"
python launcher.py

pause
BAT

# ── Создаём инструкцию ─────────────────────────────────
cat > "$FREE_KARAOKE/README.txt" << 'TXT'
═══════════════════════════════════════════════
  Free Karaoke v1.0.0 — Windows Portable
═══════════════════════════════════════════════

🚀 ЗАПУСК:
   Дважды кликните FreeKaraoke.bat

📁 СТРУКТУРА:
   app/            — исходники приложения
   _runtime/       — Python 3.11 + все пакеты
   models/         — ML-модели (Whisper)
   config/         — настройки (portable.env)
   user/           — ваши данные (библиотека, кэш, логи)

🔑 ТОКЕНЫ:
   Откройте config/portable.env и вставьте:
   - GENIUS_ACCESS_TOKEN
   - HF_TOKEN

📦 ИМПОРТ/ЭКСПОРТ:
   ZIP-файлы библиотеки полностью совместимы
   с Linux и Android версиями.

🗑️ УДАЛЕНИЕ:
   Просто удалите всю папку Free_Karaoke.
   Никаких следов в системе не останется.
TXT

# ── Упаковка в ZIP ─────────────────────────────────────
echo "📦 Упаковка в ZIP..."
rm -f "$OUTPUT_DIR/FreeKaraoke-Windows.zip"
cd "$OUTPUT_DIR"
python3 -c "
import shutil
shutil.make_archive('FreeKaraoke-Windows', 'zip', '.', 'Free_Karaoke')
print('✅ ZIP создан')
"
echo ""

# ── Итог ────────────────────────────────────────────────
ZIP_SIZE=$(du -sh "$OUTPUT_DIR/FreeKaraoke-Windows.zip" | cut -f1)
echo "═══════════════════════════════════════════"
echo "✅ Сборка Windows Portable завершена!"
echo "═══════════════════════════════════════════"
echo ""
echo "📦 Артефакт: $OUTPUT_DIR/FreeKaraoke-Windows.zip"
echo "📐 Размер: $ZIP_SIZE"
echo ""
echo "🚀 На Windows: распакуйте → FreeKaraoke.bat"
echo ""
