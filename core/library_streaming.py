"""
Потоковый экспорт/импорт библиотеки AI-Karaoke Pro.
- Экспорт: генерация ZIP чанками напрямую в HTTP-поток
- Импорт: фоновая задача с пакетной обработкой файлов
"""
import os
import zipfile
import json
import shutil
import re
import threading
import tempfile
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Generator, BinaryIO
from contextlib import contextmanager

from app_logger import get_logger
from app_status import set_status, clear_status

log = get_logger("library_streaming")

# Путь к логу импорта — portable-режим
LOGS_DIR = os.environ.get("FK_LOGS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "debug_logs"
)
IMPORT_LOG_PATH = os.path.join(LOGS_DIR, "import_streaming.log")

_import_lock = threading.Lock()


def normalize_string(s: str) -> str:
    """
    Нормализация строки для сравнения:
    - lowercase
    - удаление пунктуации
    - collapse whitespace
    - strip
    """
    if not s:
        return ""
    s = s.lower().strip()
    # Убираем пунктуацию и спецсимволы
    s = re.sub(r'[^\w\sа-яёa-z0-9]', '', s, flags=re.IGNORECASE | re.UNICODE)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _import_log(msg: str):
    """Записать сообщение в лог импорта."""
    try:
        os.makedirs(os.path.dirname(IMPORT_LOG_PATH), exist_ok=True)
        with open(IMPORT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


@contextmanager
def streaming_zip_writer(output_stream: BinaryIO, compresslevel: int = 6):
    """
    Контекстный менеджер для потоковой записи ZIP.
    Позволяет добавлять файлы по одному без загрузки всего архива в память.
    """
    zf = zipfile.ZipFile(output_stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=compresslevel)
    try:
        yield zf
    finally:
        zf.close()


def stream_library_export(library_dir: str, chunk_size: int = 64 * 1024) -> Generator[bytes, None, None]:
    """
    Потоковый экспорт библиотеки в ZIP формат.
    
    Генерирует ZIP архив чанками, не загружая весь архив в память.
    Идеально для библиотек любого размера.
    
    Args:
        library_dir: Путь к директории библиотеки
        chunk_size: Размер чанка для отправки (по умолчанию 64 КБ)
    
    Yields:
        Байты ZIP архива чанками
    """
    log.info("Потоковый экспорт библиотеки: %s", library_dir)
    
    files_added = 0
    total_bytes = 0
    
    # Получаем список файлов заранее для прогресса
    all_files = sorted([
        f for f in os.listdir(library_dir)
        if os.path.isfile(os.path.join(library_dir, f))
    ])
    total_files = len(all_files)
    
    log.info("Найдено %d файлов для экспорта", total_files)
    
    # Используем итеративный подход с временным файлом для ZIP
    # Это необходимо т.к. ZipFile требует seekable stream для central directory
    tmp_zip_path = None
    try:
        # Создаём временный ZIP файл
        import tempfile
        tmp_fd, tmp_zip_path = tempfile.mkstemp(suffix='.zip', prefix='karaoke_export_')
        os.close(tmp_fd)
        
        with zipfile.ZipFile(tmp_zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for idx, fname in enumerate(all_files, 1):
                fpath = os.path.join(library_dir, fname)
                zf.write(fpath, arcname=fname)
                files_added += 1
                log.debug("  Добавлен в архив (%d/%d): %s", idx, total_files, fname)
                
                # Обновляем статус
                progress = (idx / total_files) * 100 if total_files > 0 else 0
                set_status(f"📦 Экспорт: {fname} ({idx}/{total_files})", progress)
        
        # Теперь читаем временный файл чанками и отдаём в поток
        log.info("Архив создан, начинаем потоковую передачу")
        set_status("📦 Отправка архива...", 100)
        
        with open(tmp_zip_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                total_bytes += len(chunk)
                yield chunk
        
        log.info("Экспорт завершён: %d файлов, %d байт", files_added, total_bytes)
        _import_log(f"✅ Экспорт завершён: {files_added} файлов, {total_bytes} байт")
        
    finally:
        # Очищаем временный файл
        if tmp_zip_path and os.path.exists(tmp_zip_path):
            try:
                os.remove(tmp_zip_path)
                log.debug("Временный файл удалён: %s", tmp_zip_path)
            except Exception as e:
                log.warning("Не удалось удалить временный файл: %s", e)
        
        clear_status()


def process_import_batch(
    batch_files: Dict[str, dict],
    library_dir: str,
    db_session,
    Track_model,
    existing_keys: set,
    tmp_dir: str,
) -> dict:
    """
    Обработать пакет файлов импорта.
    
    Args:
        batch_files: Словарь {base_name: {ftype: path}}
        library_dir: Целевая директория библиотеки
        db_session: SQLAlchemy сессия
        Track_model: Модель трека
        existing_keys: Множество существующих ключей для дедупликации
        tmp_dir: Временная директория с распакованными файлами
    
    Returns:
        Статистика по пакету: {"added": int, "skipped": int, "errors": list}
    """
    result = {"added": 0, "skipped": 0, "errors": []}
    
    for base_name, files in batch_files.items():
        has_vocals = "vocals" in files
        has_inst = "inst" in files
        
        # Обязательно нужны ОБЕ аудио-дорожки
        if not has_vocals or not has_inst:
            reason = "Нет Vocal и/или Instrumental"
            log.warning("  Пропуск %s: %s", base_name, reason)
            _import_log(f"  ⏭ Пропуск: {reason}")
            result["skipped"] += 1
            result["errors"].append(f"{base_name}: {reason}")
            continue
        
        # Проверка дубликатов
        artist = ""
        title = ""
        
        # Пытаемся прочитать artist/title из _library.json
        if "meta" in files:
            try:
                with open(files["meta"], 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                artist = meta.get("artist", "") or ""
                title = meta.get("title", "") or ""
            except Exception as e:
                log.warning("  Не удалось прочитать meta для %s: %s", base_name, e)
        
        # Если нет artist/title — используем base_name
        if not artist or not title:
            artist = base_name
            title = ""
        
        # Формируем ключ для проверки дубликата
        norm_artist = normalize_string(artist)
        norm_title = normalize_string(title)
        
        is_duplicate = False
        
        if norm_artist and norm_title:
            key = f"{norm_artist}|||{norm_title}"
            if key in existing_keys:
                is_duplicate = True
                log.info("  Дубликат: %s — %s", artist, title)
                _import_log(f"  ⏭ Дубликат: {artist} — {title}")
        
        # Также проверяем по filename
        if not is_duplicate:
            fname_key = f"FILENAME|||{base_name.lower()}"
            if fname_key in existing_keys:
                is_duplicate = True
                log.info("  Дубликат по filename: %s", base_name)
                _import_log(f"  ⏭ Дубликат по filename: {base_name}")
        
        if is_duplicate:
            result["skipped"] += 1
            continue
        
        # Копирование файлов в library/
        log.info("  Добавление: %s (artist=%s, title=%s)", base_name, artist, title)
        _import_log(f"  ✅ Добавление: {artist} — {title}")
        
        files_copied = 0
        for ftype, src_path in files.items():
            dest_path = os.path.join(library_dir, os.path.basename(src_path))
            try:
                shutil.copy2(src_path, dest_path)
                files_copied += 1
            except Exception as e:
                log.error("  Ошибка копирования %s: %s", src_path, e)
                _import_log(f"  ❌ Ошибка копирования: {e}")
                result["errors"].append(f"{base_name}/{os.path.basename(src_path)}: {e}")
        
        if files_copied == 0:
            result["errors"].append(f"{base_name}: не скопировано ни одного файла")
            continue
        
        # Добавление записи в БД
        first_audio = files.get("vocals") or files.get("inst")
        orig_name = os.path.basename(first_audio).replace("_(Vocals).mp3", ".mp3").replace("_(Instrumental).mp3", ".mp3") if first_audio else f"{base_name}.mp3"
        
        new_track = Track_model(
            filename=f"{base_name}.mp3",
            original_name=orig_name,
            original_path=None,
            vocals_path=os.path.join(library_dir, f"{base_name}_(Vocals).mp3"),
            instrumental_path=os.path.join(library_dir, f"{base_name}_(Instrumental).mp3"),
            lyrics_path=os.path.join(library_dir, f"{base_name}_(Genius Lyrics).txt") if "lyrics" in files else None,
            karaoke_json_path=os.path.join(library_dir, f"{base_name}_(Karaoke Lyrics).json") if "json" in files else None,
            artist=artist or None,
            title=title or None,
            status="done",
        )
        db_session.add(new_track)
        
        # Добавляем в existing_keys чтобы не добавить дубли в рамках одного импорта
        if norm_artist and norm_title:
            existing_keys.add(f"{norm_artist}|||{norm_title}")
        existing_keys.add(f"FILENAME|||{base_name.lower()}")
        
        result["added"] += 1
        
        # Коммит после каждого трека для надёжности
        db_session.commit()
    
    return result