"""
Глобальный статус приложения — единый источник для строки состояния в UI.
Хранится в JSON-файле, т.к. Huey worker и FastAPI — разные процессы.
"""
import json
import os

_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "app_status.json")

os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)

_EMPTY = {"active": False, "message": "", "progress": None}


def set_status(message: str, progress: float | None = None):
    """Установить статус. progress=None → спиннер, 0..100 → прогресс-бар."""
    data = {
        "active": True,
        "message": message,
        "progress": max(0.0, min(100.0, progress)) if progress is not None else None,
    }
    _write(data)


def clear_status():
    """Очистить статус."""
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
