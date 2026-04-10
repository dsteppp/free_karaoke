"""
Глобальный статус приложения — единый источник для строки состояния в UI.
Хранится в JSON-файле, т.к. Huey worker и FastAPI — разные процессы.
"""
import json
import os

# ── Portable-режим: запись в FK_CACHE_DIR (не в core/) ──────────────────────
_CACHE_DIR = os.environ.get("FK_CACHE_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache"
)
_STATUS_FILE = os.path.join(_CACHE_DIR, "app_status.json")

_EMPTY = {"active": False, "message": "", "progress": None}


def _ensure_dir():
    """Ленивое создание директории (не при импорте!)."""
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
    except OSError:
        pass


def set_status(message: str, progress: float | None = None):
    """Установить статус. progress=None → спиннер, 0..100 → прогресс-бар."""
    _ensure_dir()
    data = {
        "active": True,
        "message": message,
        "progress": max(0.0, min(100.0, progress)) if progress is not None else None,
    }
    _write(data)


def clear_status():
    """Очистить статус."""
    _ensure_dir()
    _write(_EMPTY)


def read_status() -> dict:
    """Прочитать текущий статус."""
    try:
        with open(_STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_EMPTY)


def _write(data: dict):
    """Атомарная запись (write → rename)."""
    tmp = _STATUS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _STATUS_FILE)
    except Exception:
        pass
