#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# reinstall.sh — полная переустановка + изоляция AI-Karaoke Pro (через uv)
# ─────────────────────────────────────────────────────────────────────────────

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$DIR"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║        AI-Karaoke Pro — Переустановка окружения      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Предупреждение ────────────────────────────────────────────────────────────
echo "⚠️  Будут удалены и/или перенесены:"
echo "     • .venv          (виртуальное окружение)"
echo "     • models/        (AI-модели)"
echo "     • cache/         (кэши uv, torch, huggingface)"
echo "     • ~/.cache/uv    (будет перенесён сюда)"
echo "     • ~/.cache/torch (будет перенесён сюда)"
echo "     • ~/.cache/huggingface (будет перенесён сюда)"
echo ""
read -p "Продолжить? [y/N] " confirm
if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Отменено."
    exit 0
fi

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 1. Проверяем / устанавливаем uv
# ─────────────────────────────────────────────────────────────────────────────
echo "🔍 Проверяем uv..."
if ! command -v uv &> /dev/null; then
    echo "   uv не найден. Устанавливаем..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        echo "❌ uv не удалось установить. https://github.com/astral-sh/uv"
        exit 1
    fi
fi
echo "   ✓ uv $(uv --version)"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 2. Создаём внутренние папки кэша
# ─────────────────────────────────────────────────────────────────────────────
echo "📁 Создаём внутренние папки кэша..."
mkdir -p "$DIR/cache/uv"
mkdir -p "$DIR/cache/torch"
mkdir -p "$DIR/cache/huggingface"
mkdir -p "$DIR/models/whisper"
mkdir -p "$DIR/library"
mkdir -p "$DIR/static"
echo "   ✓ Папки созданы"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 3. Перенос кэша uv из системы
# ─────────────────────────────────────────────────────────────────────────────
echo "📦 Перенос кэша uv из системы..."

UV_SYS_CACHE="${UV_CACHE_DIR:-$HOME/.cache/uv}"

if [ -d "$UV_SYS_CACHE" ] && [ "$UV_SYS_CACHE" != "$DIR/cache/uv" ]; then
    echo "   Найден системный кэш uv: $UV_SYS_CACHE"

    # Переносим только нужные подпапки uv-кэша:
    # - wheels/       — скомпилированные колёса (самое ценное)
    # - archives/     — скачанные архивы пакетов
    # - builds/       — сборочные артефакты
    # Пропускаем: git/, interpreter/ — они системно-специфичны, не нужны

    for subdir in wheels archives builds; do
        SRC="$UV_SYS_CACHE/$subdir"
        DST="$DIR/cache/uv/$subdir"
        if [ -d "$SRC" ]; then
            echo "   → Переносим $subdir/..."
            mkdir -p "$DST"
            # rsync с hardlinks чтобы не дублировать файлы если FS одна
            if rsync --version &>/dev/null; then
                rsync -a --remove-source-files "$SRC/" "$DST/"
                find "$SRC" -type d -empty -delete 2>/dev/null || true
            else
                cp -al "$SRC/." "$DST/" 2>/dev/null || cp -a "$SRC/." "$DST/"
                rm -rf "$SRC"
            fi
            echo "     ✓ $subdir перенесён"
        fi
    done

    # Удаляем ненужные системные подпапки
    for subdir in git interpreter simple-v1 gdist; do
        if [ -d "$UV_SYS_CACHE/$subdir" ]; then
            echo "   🗑️  Удаляем ненужный кэш: $subdir/"
            rm -rf "$UV_SYS_CACHE/$subdir"
        fi
    done

    # Если системный кэш теперь пуст — удаляем директорию
    if [ -z "$(ls -A "$UV_SYS_CACHE" 2>/dev/null)" ]; then
        rmdir "$UV_SYS_CACHE" 2>/dev/null || true
        echo "   ✓ Системный кэш uv очищен"
    else
        echo "   ℹ️  В системном кэше uv остались файлы (возможно, от других проектов)"
        echo "      Путь: $UV_SYS_CACHE"
    fi
else
    echo "   ℹ️  Системный кэш uv не найден или уже внутри проекта"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 4. Перенос кэша torch из системы
# ─────────────────────────────────────────────────────────────────────────────
echo "🔥 Перенос кэша torch из системы..."

TORCH_SYS="${TORCH_HOME:-$HOME/.cache/torch}"

if [ -d "$TORCH_SYS" ] && [ "$TORCH_SYS" != "$DIR/cache/torch" ]; then
    echo "   Найден системный кэш torch: $TORCH_SYS"

    # Переносим только hub/ (скачанные модели torchvision, torchaudio, etc.)
    # Пропускаем kernels/ — JIT-кэш, он пересоберётся автоматически
    if [ -d "$TORCH_SYS/hub" ]; then
        echo "   → Переносим hub/..."
        mkdir -p "$DIR/cache/torch/hub"
        if rsync --version &>/dev/null; then
            rsync -a --remove-source-files "$TORCH_SYS/hub/" "$DIR/cache/torch/hub/"
            find "$TORCH_SYS/hub" -type d -empty -delete 2>/dev/null || true
        else
            cp -al "$TORCH_SYS/hub/." "$DIR/cache/torch/hub/" 2>/dev/null \
                || cp -a "$TORCH_SYS/hub/." "$DIR/cache/torch/hub/"
            rm -rf "$TORCH_SYS/hub"
        fi
        echo "     ✓ torch/hub перенесён"
    fi

    # Удаляем ненужное (JIT-кэш пересоберётся)
    if [ -d "$TORCH_SYS/kernels" ]; then
        echo "   🗑️  Удаляем JIT-кэш torch/kernels/ (пересоберётся)..."
        rm -rf "$TORCH_SYS/kernels"
    fi

    # Если папка пуста — удаляем
    if [ -z "$(ls -A "$TORCH_SYS" 2>/dev/null)" ]; then
        rmdir "$TORCH_SYS" 2>/dev/null || true
        echo "   ✓ Системный кэш torch очищен"
    else
        echo "   ℹ️  В системном кэше torch остались файлы (от других проектов)"
    fi
else
    echo "   ℹ️  Системный кэш torch не найден или уже внутри проекта"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 5. Перенос кэша HuggingFace из системы
# ─────────────────────────────────────────────────────────────────────────────
echo "🤗 Перенос кэша HuggingFace из системы..."

HF_SYS="${HF_HOME:-$HOME/.cache/huggingface}"

if [ -d "$HF_SYS" ] && [ "$HF_SYS" != "$DIR/cache/huggingface" ]; then
    echo "   Найден системный кэш HuggingFace: $HF_SYS"

    # Переносим только hub/ (скачанные модели)
    # Пропускаем: token (системный токен авторизации — не наш)
    if [ -d "$HF_SYS/hub" ]; then
        echo "   → Переносим hub/..."
        mkdir -p "$DIR/cache/huggingface/hub"
        if rsync --version &>/dev/null; then
            rsync -a --remove-source-files "$HF_SYS/hub/" "$DIR/cache/huggingface/hub/"
            find "$HF_SYS/hub" -type d -empty -delete 2>/dev/null || true
        else
            cp -al "$HF_SYS/hub/." "$DIR/cache/huggingface/hub/" 2>/dev/null \
                || cp -a "$HF_SYS/hub/." "$DIR/cache/huggingface/hub/"
            rm -rf "$HF_SYS/hub"
        fi
        echo "     ✓ huggingface/hub перенесён"
    fi

    # Удаляем ненужные системные файлы HF (не затрагиваем чужие проекты)
    for item in accelerate datasets modules; do
        if [ -d "$HF_SYS/$item" ]; then
            echo "   🗑️  Удаляем $item/ (пересоздастся)..."
            rm -rf "$HF_SYS/$item"
        fi
    done

    # Если папка пуста — удаляем
    if [ -z "$(ls -A "$HF_SYS" 2>/dev/null)" ]; then
        rmdir "$HF_SYS" 2>/dev/null || true
        echo "   ✓ Системный кэш HuggingFace очищен"
    else
        echo "   ℹ️  В системном кэше HuggingFace остались файлы (от других проектов)"
    fi
else
    echo "   ℹ️  Системный кэш HuggingFace не найден или уже внутри проекта"
fi
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 6. Записываем .env.cache — все переменные изоляции
# ─────────────────────────────────────────────────────────────────────────────
echo "📌 Записываем .env.cache..."
cat > "$DIR/.env.cache" << EOF
# Автогенерируется reinstall.sh — не редактировать вручную
# Все кэши изолированы внутри директории проекта

UV_CACHE_DIR=$DIR/cache/uv
TORCH_HOME=$DIR/cache/torch
HF_HOME=$DIR/cache/huggingface
HUGGINGFACE_HUB_CACHE=$DIR/cache/huggingface/hub
TRANSFORMERS_CACHE=$DIR/cache/huggingface/hub
XDG_CACHE_HOME=$DIR/cache
EOF
echo "   ✓ .env.cache записан"
echo ""

# ── Применяем переменные для текущей сессии ───────────────────────────────────
set -a
source "$DIR/.env.cache"
set +a

# ─────────────────────────────────────────────────────────────────────────────
# 7. Удаляем старое .venv
# ─────────────────────────────────────────────────────────────────────────────
if [ -d "$DIR/.venv" ]; then
    echo "🗑️  Удаляем старое .venv..."
    rm -rf "$DIR/.venv"
    echo "   ✓ .venv удалён"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 8. Удаляем старые models (AI-модели скачаются заново в нужные места)
# ─────────────────────────────────────────────────────────────────────────────
if [ -d "$DIR/models" ]; then
    echo "🗑️  Удаляем models/..."
    rm -rf "$DIR/models"
    echo "   ✓ models/ удалён"
fi
mkdir -p "$DIR/models/whisper"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 9. Создаём .venv через uv с кэшем внутри проекта
# ─────────────────────────────────────────────────────────────────────────────
echo "🐍 Создаём .venv (Python 3.11)..."
uv venv "$DIR/.venv" --python 3.11 --seed
echo "   ✓ .venv создан"
echo ""

source "$DIR/.venv/bin/activate"
echo "   ✓ Окружение активировано"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 10. Устанавливаем зависимости
#     uv автоматически использует UV_CACHE_DIR из окружения
#     и создаёт hardlinks вместо копий → нет дублирования
# ─────────────────────────────────────────────────────────────────────────────
if [ ! -f "$DIR/requirements.txt" ]; then
    echo "❌ requirements.txt не найден"
    exit 1
fi

echo "📦 Устанавливаем пакеты (uv + hardlinks, без дублирования)..."
uv pip install -r "$DIR/requirements.txt"
echo ""
echo "   ✓ Все пакеты установлены"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 11. Проверка ключевых пакетов
# ─────────────────────────────────────────────────────────────────────────────
echo "🔬 Проверка ключевых пакетов..."

check_pkg() {
    if python -c "import $1" 2>/dev/null; then
        echo "   ✓ $1"
    else
        echo "   ✗ $1 — НЕ НАЙДЕН"
    fi
}

check_pkg torch
check_pkg torchaudio
check_pkg fastapi
check_pkg uvicorn
check_pkg huey
check_pkg stable_whisper
check_pkg audio_separator
check_pkg lyricsgenius
check_pkg webview
check_pkg sqlalchemy
check_pkg tinytag

echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 12. Проверка CUDA
# ─────────────────────────────────────────────────────────────────────────────
echo "🎮 Проверка CUDA..."
python -c "
import torch
if torch.cuda.is_available():
    print(f'   ✓ CUDA: {torch.cuda.get_device_name(0)}')
    print(f'     VRAM: {torch.cuda.get_device_properties(0).total_memory // 1024**3} ГБ')
else:
    print('   ⚠️  CUDA недоступна — будет использован CPU')
"
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# 13. Итоговый размер директории
# ─────────────────────────────────────────────────────────────────────────────
echo "💾 Размер директории проекта:"
du -sh "$DIR/.venv"   2>/dev/null && echo "     ↑ .venv"   || true
du -sh "$DIR/cache"   2>/dev/null && echo "     ↑ cache/"  || true
du -sh "$DIR/models"  2>/dev/null && echo "     ↑ models/" || true
echo ""

# ─────────────────────────────────────────────────────────────────────────────
# Финал
# ─────────────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════╗"
echo "║              ✅ Установка завершена!                  ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "Проект полностью изолирован в: $DIR"
echo ""
echo "Для запуска:"
echo "   bash run.sh"
echo ""