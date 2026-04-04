"""
sse_events.py — Система SSE-событий для реалтайм-отчёта о прогрессе обработки
"""

import json
import queue
import threading
from typing import Optional

# ── Глобальные очереди событий (один клиент — одна очередь) ──────────────────
_event_queues: dict[str, queue.Queue] = {}
_lock = threading.Lock()

# ── Текущее событие для нового клиента (чтобы не ждать первого push) ─────────
_current_events: dict[str, dict] = {}


def register_client(client_id: str) -> queue.Queue:
    """Регистрирует нового SSE-клиента и возвращает его очередь."""
    q = queue.Queue(maxsize=500)
    with _lock:
        _event_queues[client_id] = q
        # Отправляем последнее известное событие, чтобы клиент не висел
        if client_id in _current_events:
            q.put_nowait(_current_events[client_id])
    return q


def unregister_client(client_id: str):
    """Удаляет очередь клиента."""
    with _lock:
        _event_queues.pop(client_id, None)


def broadcast_progress(
    track_id: str,
    track_name: str,
    stage: str,
    percent: int,
    message: str,
    queue_position: Optional[str] = None,
    sub_percent: Optional[int] = None,
):
    """
    Рассылает событие прогресса всем подключённым клиентам.

    Args:
        track_id: ID трека
        track_name: Отображаемое имя трека
        stage: Ключ этапа (upload, convert, separate, lyrics, covers, vad, transcribe, match, elastic, save)
        percent: Общий процент 0-100
        message: Человекочитаемое описание этапа
        queue_position: Позиция в очереди, например "3/7"
        sub_percent: Прогресс внутри текущего этапа (0-100), опционально
    """
    event = {
        "type": "progress",
        "track_id": track_id,
        "track_name": track_name,
        "stage": stage,
        "percent": min(100, max(0, percent)),
        "message": message,
        "queue_position": queue_position or "",
        "sub_percent": sub_percent,
    }

    with _lock:
        _current_events[track_id] = event
        dead = []
        for cid, q in _event_queues.items():
            try:
                q.put_nowait(event)
            except queue.Full:
                # Очередь переполнена — клиент не читает, помечаем на удаление
                dead.append(cid)

        # Удаляем мёртвые очереди
        for cid in dead:
            _event_queues.pop(cid, None)


def broadcast_done(track_id: str, track_name: str, success: bool, error: str = ""):
    """Рассылает событие завершения обработки."""
    event = {
        "type": "done",
        "track_id": track_id,
        "track_name": track_name,
        "success": success,
        "error": error,
        "percent": 100,
        "stage": "done" if success else "error",
        "message": "Готово!" if success else "Ошибка обработки",
        "queue_position": "",
        "sub_percent": None,
    }

    with _lock:
        _current_events[track_id] = event
        dead = []
        for cid, q in _event_queues.items():
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(cid)
        for cid in dead:
            _event_queues.pop(cid, None)


def get_active_queue_count() -> int:
    """Возвращает количество активных SSE-подключений."""
    with _lock:
        return len(_event_queues)
