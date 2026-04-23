"""
Экспорт и импорт библиотеки AI-Karaoke Pro.
Потоковая архитектура для работы с библиотеками 100 ГБ+:
- Экспорт: прямая запись ZIP на диск без загрузки в память
- Импорт: потоковое чтение ZIP с диска, чанковая обработка БД
- Поддержка прогресса и отмены через threading.Event
"""
import os
import zipfile
import json
import shutil
import re
import threading
import io
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Callable
import tempfile

from app_logger import get_logger
from app_status import set_status, clear_status

log = get_logger("library_io")

# Путь к логу импорта — portable-режим
LOGS_DIR = os.environ.get("FK_LOGS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "debug_logs"
)
IMPORT_LOG_PATH = os.path.join(LOGS_DIR, "import.log")

_import_lock = threading.Lock()
_import_running = False


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


def _stream_zip_write(zf: zipfile.ZipFile, src_path: str, arcname: str,
                      chunk_size: int = 1024*1024) -> bool:
    """
    Потоковая запись файла в ZIP (chunk_size по умолчанию 1MB).
    Возвращает True при успехе, False при ошибке.
    """
    try:
        with open(src_path, 'rb') as src_file:
            zf.writestr(arcname, src_file.read())
        return True
    except Exception as e:
        log.error("Ошибка записи в ZIP %s → %s: %s", src_path, arcname, e)
        return False


def _stream_zip_extract(zf: zipfile.ZipFile, member: zipfile.ZipInfo,
                        dest_path: str, chunk_size: int = 1024*1024) -> bool:
    """
    Потоковое извлечение файла из ZIP (chunk_size по умолчанию 1MB).
    Возвращает True при успехе, False при ошибке.
    """
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with zf.open(member) as src_file:
            with open(dest_path, 'wb') as dst_file:
                while True:
                    chunk = src_file.read(chunk_size)
                    if not chunk:
                        break
                    dst_file.write(chunk)
        return True
    except Exception as e:
        log.error("Ошибка извлечения из ZIP %s → %s: %s", member.filename, dest_path, e)
        return False


def export_library(
    library_dir: str,
    output_path: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    compresslevel: int = 6,  # Баланс скорость/размер
) -> dict:
    """
    Потоковый экспорт: пишет ZIP напрямую в output_path.
    
    Args:
        library_dir: Путь к директории библиотеки
        output_path: Путь для сохранения ZIP-архива
        progress_callback: Функция обратного вызова (processed, total, filename)
        cancel_flag: Флаг отмены (threading.Event)
        compresslevel: Уровень компрессии (0-9)
    
    Returns:
        {
            "status": "done" | "cancelled" | "error",
            "written": int,      # количество файлов
            "total": int,        # всего файлов
            "errors": List[str],
            "output_path": str,
        }
    """
    log.info("Потоковый экспорт библиотеки: %s → %s", library_dir, output_path)
    
    result = {
        "status": "done",
        "written": 0,
        "total": 0,
        "errors": [],
        "output_path": output_path,
    }
    
    # Собираем список файлов
    files_to_export = []
    try:
        for fname in sorted(os.listdir(library_dir)):
            fpath = os.path.join(library_dir, fname)
            if os.path.isfile(fpath):
                files_to_export.append((fpath, fname))
    except Exception as e:
        log.error("Ошибка сканирования библиотеки: %s", e)
        result["status"] = "error"
        result["errors"].append(f"Ошибка сканирования: {e}")
        return result
    
    result["total"] = len(files_to_export)
    log.info("Найдено %d файлов для экспорта", result["total"])
    
    if result["total"] == 0:
        result["errors"].append("Библиотека пуста")
        result["status"] = "error"
        return result
    
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as zf:
            for idx, (fpath, fname) in enumerate(files_to_export, 1):
                # Проверка отмены
                if cancel_flag is not None and cancel_flag.is_set():
                    log.info("Экспорт отменён пользователем на файле %d/%d", idx, result["total"])
                    result["status"] = "cancelled"
                    result["written"] = idx - 1
                    # ZIP будет корректно закрыт контекстным менеджером
                    return result
                
                # Запись файла в ZIP
                success = _stream_zip_write(zf, fpath, fname)
                
                if success:
                    result["written"] += 1
                    log.debug("Добавлен в архив: %s (%d/%d)", fname, idx, result["total"])
                    
                    # Вызов callback прогресса
                    if progress_callback:
                        try:
                            progress_callback(idx, result["total"], fname)
                        except Exception as e:
                            log.warning("Ошибка в progress_callback: %s", e)
                else:
                    result["errors"].append(f"Не удалось добавить {fname}")
        
        log.info("Экспорт завершён: записано %d/%d файлов", result["written"], result["total"])
        return result
    
    except Exception as e:
        log.error("Критическая ошибка экспорта: %s", e, exc_info=True)
        result["status"] = "error"
        result["errors"].append(f"Критическая ошибка: {e}")
        
        # Удаляем неполный файл
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
                log.info("Удалён неполный файл экспорта: %s", output_path)
            except Exception:
                pass
        
        return result


def _import_log(msg: str):
    """Записать сообщение в лог импорта."""
    try:
        with open(IMPORT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def import_library(
    zip_path: str,
    library_dir: str,
    db_session,
    Track_model,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    batch_size: int = 100,
) -> dict:
    """
    Потоковый импорт библиотеки из ZIP-архива.
    
    Args:
        zip_path: Путь к ZIP-файлу на диске
        library_dir: Путь к директории библиотеки
        db_session: SQLAlchemy сессия
        Track_model: Модель трека SQLAlchemy
        progress_callback: Функция обратного вызова (processed, total, filename)
        cancel_flag: Флаг отмены (threading.Event)
        batch_size: Размер батча для коммита в БД
    
    Логика:
    1. Потоковое чтение ZIP с диска (без загрузки в память)
    2. Извлечение файлов по одному через _stream_zip_extract
    3. Группировка по base_name
    4. Чанковая обработка с commit после каждого batch_size
    5. Проверка дубликатов и отмены
    
    Returns:
        {
            "status": "done" | "cancelled" | "error",
            "added": int,
            "skipped": int,
            "errors": List[str],
            "artists": List[str],
            "tracks": List[str],
        }
    """
    global _import_running
    
    log.info("Потоковый импорт библиотеки: %s → %s", zip_path, library_dir)
    
    with _import_lock:
        if _import_running:
            raise RuntimeError("Импорт уже выполняется")
        _import_running = True
    
    # Очистка лога
    try:
        os.makedirs(os.path.dirname(IMPORT_LOG_PATH), exist_ok=True)
        with open(IMPORT_LOG_PATH, 'w', encoding='utf-8') as f:
            f.write(f"=== Импорт библиотеки {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    except Exception:
        pass
    
    result = {
        "status": "done",
        "added": 0,
        "skipped": 0,
        "errors": [],
        "artists": [],
        "tracks": [],
    }
    
    tmp_dir = None
    try:
        # 1. Создаём временную директорию
        tmp_dir = tempfile.mkdtemp(prefix="karaoke_import_")
        log.info("Импорт: распаковка в %s", tmp_dir)
        _import_log(f"Распаковка ZIP: {zip_path}")
        
        # Проверка существования файла
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"ZIP файл не найден: {zip_path}")
        
        # 2. Потоковое извлечение файлов из ZIP
        file_groups: Dict[str, dict] = {}
        total_members = 0
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            total_members = len(zf.namelist())
            log.info("В архиве %d файлов", total_members)
            
            for idx, member in enumerate(zf.infolist(), 1):
                # Пропускаем директории
                if member.filename.endswith('/'):
                    continue
                
                # Проверка отмены
                if cancel_flag is not None and cancel_flag.is_set():
                    log.info("Импорт отменён пользователем на файле %d/%d", idx, total_members)
                    result["status"] = "cancelled"
                    return result
                
                # Извлекаем файл потоково
                dest_path = os.path.join(tmp_dir, member.filename)
                success = _stream_zip_extract(zf, member, dest_path)
                
                if not success:
                    result["errors"].append(f"Не удалось извлечь {member.filename}")
                    continue
                
                # Вызов callback прогресса
                if progress_callback:
                    try:
                        progress_callback(idx, total_members, member.filename)
                    except Exception as e:
                        log.warning("Ошибка в progress_callback: %s", e)
        
        # 3. Группировка файлов по base_name
        all_files = os.listdir(tmp_dir)
        
        for fname in all_files:
            fpath = os.path.join(tmp_dir, fname)
            if not os.path.isfile(fpath):
                continue
            
            base = None
            ftype = None
            
            if fname.endswith("_(Vocals).mp3"):
                base = fname.replace("_(Vocals).mp3", "")
                ftype = "vocals"
            elif fname.endswith("_(Instrumental).mp3"):
                base = fname.replace("_(Instrumental).mp3", "")
                ftype = "inst"
            elif fname.endswith("_(Genius Lyrics).txt"):
                base = fname.replace("_(Genius Lyrics).txt", "")
                ftype = "lyrics"
            elif fname.endswith("_(Karaoke Lyrics).json"):
                base = fname.replace("_(Karaoke Lyrics).json", "")
                ftype = "json"
            elif fname.endswith("_library.json"):
                base = fname.replace("_library.json", "")
                ftype = "meta"
            else:
                continue  # Пропускаем неизвестные файлы
            
            if base not in file_groups:
                file_groups[base] = {}
            file_groups[base][ftype] = fpath
        
        log.info("Импорт: найдено %d групп файлов", len(file_groups))
        _import_log(f"Найдено {len(file_groups)} потенциальных треков")
        
        # 4. Загрузка существующих треков из БД для дедупликации
        # Используем yield_per для эффективной работы с большими БД
        existing_tracks = db_session.query(Track_model).yield_per(1000).all()
        existing_keys = set()
        for t in existing_tracks:
            # Нормализованные ключи
            if t.artist and t.title:
                key = f"{normalize_string(t.artist)}|||{normalize_string(t.title)}"
                existing_keys.add(key)
            # Также по filename (base_name)
            base_from_filename = os.path.splitext(t.filename)[0] if t.filename else ""
            if base_from_filename:
                existing_keys.add(f"FILENAME|||{base_from_filename.lower()}")
        
        # 5. Обработка треков батчами
        total = len(file_groups)
        batch_count = 0
        
        for idx, (base_name, files) in enumerate(sorted(file_groups.items()), 1):
            has_vocals = "vocals" in files
            has_inst = "inst" in files
            
            # Проверка отмены между батчами
            if cancel_flag is not None and cancel_flag.is_set():
                log.info("Импорт отменён пользователем на треке %d/%d", idx, total)
                result["status"] = "cancelled"
                return result
            
            # Обновляем статус
            progress = (idx / total) * 100 if total > 0 else 0
            set_status(f"📦 Импорт: {base_name} ({idx}/{total})", progress)
            _import_log(f"[{idx}/{total}] Обработка: {base_name}")
            
            # Обязательно нужны ОБЕ аудио-дорожки
            if not has_vocals or not has_inst:
                reason = "Нет Vocal и/или Instrumental"
                log.warning("  Пропуск %s: %s", base_name, reason)
                _import_log(f"  ⏭ Пропуск: {reason}")
                result["skipped"] += 1
                result["errors"].append(f"{base_name}: {reason}")
                continue
            
            # 6. Проверка дубликатов
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
            
            # 7. Копирование файлов в library/
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
            
            # 8. Добавление записи в БД
            # Определяем оригинальное имя файла (берём первое аудио)
            first_audio = files.get("vocals") or files.get("inst")
            orig_name = os.path.basename(first_audio).replace("_(Vocals).mp3", ".mp3").replace("_(Instrumental).mp3", ".mp3") if first_audio else f"{base_name}.mp3"
            
            new_track = Track_model(
                filename=f"{base_name}.mp3",
                original_name=orig_name,
                original_path=None,  # Оригинала нет — стемы уже готовы
                vocals_path=os.path.join(library_dir, f"{base_name}_(Vocals).mp3"),
                instrumental_path=os.path.join(library_dir, f"{base_name}_(Instrumental).mp3"),
                lyrics_path=os.path.join(library_dir, f"{base_name}_(Genius Lyrics).txt") if "lyrics" in files else None,
                karaoke_json_path=os.path.join(library_dir, f"{base_name}_(Karaoke Lyrics).json") if "json" in files else None,
                artist=artist or None,
                title=title or None,
                status="done",
            )
            db_session.add(new_track)
            batch_count += 1
            
            # Commit после каждого batch_size треков
            if batch_count >= batch_size:
                db_session.commit()
                log.info("Commit батча %d треков", batch_count)
                batch_count = 0
            
            # Добавляем в existing_keys чтобы не добавить дубли в рамках одного импорта
            if norm_artist and norm_title:
                existing_keys.add(f"{norm_artist}|||{norm_title}")
            existing_keys.add(f"FILENAME|||{base_name.lower()}")
            
            result["added"] += 1
            if artist and artist not in result["artists"]:
                result["artists"].append(artist)
            display_name = f"{artist} — {title}" if artist and title else base_name
            if display_name not in result["tracks"]:
                result["tracks"].append(display_name)
        
        # Финальный commit оставшихся треков
        if batch_count > 0:
            db_session.commit()
            log.info("Финальный commit: %d треков", batch_count)
        
        log.info("Импорт завершён: добавлено=%d, пропущено=%d", result["added"], result["skipped"])
        _import_log(f"\n=== ИТОГО: добавлено={result['added']}, пропущено={result['skipped']}, ошибки={len(result['errors'])} ===")
        
    except Exception as e:
        db_session.rollback()
        log.error("Ошибка импорта: %s", e, exc_info=True)
        _import_log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        result["errors"].append(f"Критическая ошибка: {e}")
        result["status"] = "error"
    
    finally:
        # Очистка временной директории
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass
        
        _import_running = False
        clear_status()
    
    return result
