"""
Экспорт и импорт библиотеки AI-Karaoke Pro — ПОТОКОВАЯ ВЕРСИЯ для 100 ГБ+
- Экспорт: потоковая запись ZIP напрямую в файл (не в память)
- Импорт: потоковое чтение ZIP с диска, обработка чанками
- Поддержка прогресса, отмены и восстановления
"""
import os
import zipfile
import json
import shutil
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Callable

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
    Потоковая запись файла в ZIP (1MB chunks) — не грузит весь файл в память.
    """
    try:
        with open(src_path, 'rb') as src:
            with zf.open(arcname, 'w') as dst:
                while True:
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dst.write(chunk)
        return True
    except Exception as e:
        log.error("Ошибка записи %s в ZIP: %s", arcname, e)
        return False


def _stream_zip_extract(zf: zipfile.ZipFile, member: zipfile.ZipInfo, 
                        dest_path: str, chunk_size: int = 1024*1024) -> bool:
    """
    Потоковое извлечение файла из ZIP (1MB chunks) — не грузит весь файл в память.
    """
    try:
        with zf.open(member) as src, open(dest_path, 'wb') as dst:
            while True:
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
        return True
    except Exception as e:
        log.error("Ошибка извлечения %s: %s", member.filename, e)
        return False


def export_library(
    library_dir: str,
    output_path: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_flag: Optional[threading.Event] = None,
    compresslevel: int = 6,
) -> dict:
    """
    Потоковый экспорт библиотеки: пишет ZIP напрямую в output_path.
    
    Args:
        library_dir: Путь к директории с файлами библиотеки
        output_path: Полный путь к целевому ZIP-файлу (создаётся сразу)
        progress_callback: func(processed: int, total: int, current_file: str)
        cancel_flag: threading.Event для отмены операции
        compresslevel: Уровень сжатия (1-9, 6 — баланс скорость/размер)
    
    Returns:
        {
            "status": "done" | "cancelled" | "error",
            "written": int,      # количество успешно записанных файлов
            "total": int,        # всего файлов для экспорта
            "errors": List[str], # список ошибок
            "output_path": str,  # путь к созданному файлу
            "size": int,         # размер файла в байтах
        }
    """
    log.info("Потоковый экспорт библиотеки: %s → %s", library_dir, output_path)
    
    # Собираем список файлов для экспорта
    files_to_export = []
    for fname in sorted(os.listdir(library_dir)):
        fpath = os.path.join(library_dir, fname)
        if os.path.isfile(fpath):
            files_to_export.append((fname, fpath))
    
    total = len(files_to_export)
    written = 0
    errors = []
    
    try:
        # ✅ ZIP пишется ПРЯМО в файл на диске, не в память
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as zf:
            for idx, (fname, fpath) in enumerate(files_to_export, 1):
                # Проверка отмены
                if cancel_flag and cancel_flag.is_set():
                    log.info("Экспорт отменён пользователем на файле %d/%d", written, total)
                    # ZIP закроется корректно, файл останется валидным (частичным)
                    return {
                        "status": "cancelled",
                        "written": written,
                        "total": total,
                        "errors": errors,
                        "output_path": output_path,
                        "size": os.path.getsize(output_path) if os.path.exists(output_path) else 0,
                    }
                
                try:
                    # Потоковая запись файла в ZIP
                    if _stream_zip_write(zf, fpath, fname):
                        written += 1
                        if progress_callback:
                            progress_callback(written, total, fname)
                        log.debug("  Добавлен в архив: %s (%d/%d)", fname, written, total)
                    else:
                        errors.append(f"{fname}: ошибка записи")
                except Exception as e:
                    log.warning("Ошибка добавления %s: %s", fname, e)
                    errors.append(f"{fname}: {e}")
        
        final_size = os.path.getsize(output_path)
        log.info("Экспорт завершён: %d/%d файлов, размер: %.1f MB", 
                 written, total, final_size / 1024**2)
        
        return {
            "status": "done",
            "written": written,
            "total": total,
            "errors": errors,
            "output_path": output_path,
            "size": final_size,
        }
        
    except Exception as e:
        log.error("Критическая ошибка экспорта: %s", e, exc_info=True)
        # При ошибке удаляем неполный файл
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
                log.info("Удалён неполный файл экспорта: %s", output_path)
            except Exception as cleanup_err:
                log.warning("Не удалось удалить неполный файл: %s", cleanup_err)
        
        return {
            "status": "error",
            "written": written,
            "total": total,
            "errors": errors + [str(e)],
            "output_path": output_path,
            "size": 0,
        }


def _import_log(msg: str):
    """Записать сообщение в лог импорта."""
    try:
        with open(IMPORT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def _load_existing_keys(db_session, Track_model, batch_size: int = 1000) -> set:
    """
    Загружает ключи дедупликации итеративно (не грузит всю БД в память).
    """
    keys = set()
    try:
        # ✅ Итеративная загрузка вместо .all()
        for t in db_session.query(Track_model.artist, Track_model.title, Track_model.filename).yield_per(batch_size):
            if t.artist and t.title:
                key = f"{normalize_string(t.artist)}|||{normalize_string(t.title)}"
                keys.add(key)
            if t.filename:
                base = os.path.splitext(t.filename)[0]
                if base:
                    keys.add(f"FILENAME|||{base.lower()}")
    except Exception as e:
        log.warning("Ошибка загрузки ключей дедупликации: %s", e)
    return keys


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
    
    Логика:
    1. Открыть ZIP напрямую с диска (не грузить в память)
    2. Сгруппировать файлы по base_name (метаданные, не контент)
    3. Загрузить ключи дедупликации итеративно
    4. Обрабатывать треки чанками по batch_size
    5. Извлекать файлы потоково прямо в library_dir (без temp dir)
    6. Добавлять записи в БД с периодическим commit()
    
    Args:
        zip_path: Путь к ZIP-файлу на диске
        library_dir: Целевая директория для файлов библиотеки
        db_session: SQLAlchemy session
        Track_model: SQLAlchemy модель Track
        progress_callback: func(processed: int, total: int, current_item: str)
        cancel_flag: threading.Event для отмены
        batch_size: Количество треков для обработки за один коммит
    
    Returns:
        {
            "added": int,
            "skipped": int,
            "errors": List[str],
            "artists": List[str],
            "tracks": List[str],
            "status": "done" | "cancelled" | "error",
        }
    """
    global _import_running
    
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
        "added": 0,
        "skipped": 0,
        "errors": [],
        "artists": [],
        "tracks": [],
        "status": "running",
    }
    
    try:
        # 1. Открываем ZIP прямо с диска, не грузим в память
        log.info("Импорт: открытие ZIP %s", zip_path)
        _import_log(f"Открытие архива: {zip_path}")
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Сначала собираем список файлов (метаданные, не контент)
            file_list = [m for m in zf.infolist() if not m.is_dir()]
            total_members = len(file_list)
            _import_log(f"Найдено {total_members} файлов в архиве")
            
            # 2. Группируем по base_name (то же, что в оригинале, но без extractall)
            file_groups: Dict[str, dict] = {}
            
            for member in file_list:
                fname = os.path.basename(member.filename)
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
                # ✅ Сохраняем ZipInfo, не извлекаем на диск
                file_groups[base][ftype] = member
            
            total_groups = len(file_groups)
            log.info("Импорт: найдено %d групп файлов (потенциальных треков)", total_groups)
            _import_log(f"Найдено {total_groups} потенциальных треков")
            
            # 3. Загружаем существующие ключи дедупликации (итеративно)
            existing_keys = _load_existing_keys(db_session, Track_model)
            log.info("Загружено %d ключей для дедупликации", len(existing_keys))
            
            # 4. Обрабатываем чанками
            groups_list = list(sorted(file_groups.items()))
            
            for batch_start in range(0, len(groups_list), batch_size):
                # Проверка отмены между батчами
                if cancel_flag and cancel_flag.is_set():
                    log.info("Импорт отменён пользователем на батче %d", batch_start // batch_size + 1)
                    _import_log("⚠ Импорт отменён пользователем")
                    result["status"] = "cancelled"
                    return result
                
                batch = groups_list[batch_start:batch_start + batch_size]
                processed_in_batch = 0
                
                for base_name, files in batch:
                    # Проверка отмены внутри батча
                    if cancel_flag and cancel_flag.is_set():
                        result["status"] = "cancelled"
                        return result
                    
                    has_vocals = "vocals" in files
                    has_inst = "inst" in files
                    
                    # Обновляем статус
                    global_processed = batch_start + processed_in_batch
                    progress = (global_processed / total_groups) * 100 if total_groups > 0 else 0
                    set_status(f"📦 Импорт: {base_name} ({global_processed + 1}/{total_groups})", int(progress))
                    _import_log(f"[{global_processed + 1}/{total_groups}] Обработка: {base_name}")
                    
                    if progress_callback:
                        progress_callback(global_processed + 1, total_groups, base_name)
                    
                    # Обязательно нужны ОБЕ аудио-дорожки
                    if not has_vocals or not has_inst:
                        reason = "Нет Vocal и/или Instrumental"
                        log.warning("  Пропуск %s: %s", base_name, reason)
                        _import_log(f"  ⏭ Пропуск: {reason}")
                        result["skipped"] += 1
                        result["errors"].append(f"{base_name}: {reason}")
                        processed_in_batch += 1
                        continue
                    
                    # 5. Проверка дубликатов
                    artist = ""
                    title = ""
                    
                    # Пытаемся прочитать artist/title из _library.json (если есть в архиве)
                    if "meta" in files:
                        try:
                            # ✅ Потоковое чтение метаданных из ZIP
                            meta_member = files["meta"]
                            with zf.open(meta_member) as meta_file:
                                import io
                                meta_content = meta_file.read().decode('utf-8')
                                meta = json.loads(meta_content)
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
                        processed_in_batch += 1
                        continue
                    
                    # 6. Потоковое копирование файлов прямо в library_dir (без temp dir)
                    log.info("  Добавление: %s (artist=%s, title=%s)", base_name, artist, title)
                    _import_log(f"  ✅ Добавление: {artist} — {title}")
                    
                    files_copied = 0
                    for ftype, member in files.items():
                        dest_path = os.path.join(library_dir, os.path.basename(member.filename))
                        try:
                            # ✅ Потоковое извлечение из ZIP в файл
                            if _stream_zip_extract(zf, member, dest_path):
                                files_copied += 1
                            else:
                                result["errors"].append(f"{base_name}/{member.filename}: ошибка извлечения")
                        except Exception as e:
                            log.error("  Ошибка копирования %s: %s", member.filename, e)
                            _import_log(f"  ❌ Ошибка извлечения: {e}")
                            result["errors"].append(f"{base_name}/{os.path.basename(member.filename)}: {e}")
                    
                    if files_copied == 0:
                        result["errors"].append(f"{base_name}: не скопировано ни одного файла")
                        processed_in_batch += 1
                        continue
                    
                    # 7. Добавление записи в БД
                    first_audio_member = files.get("vocals") or files.get("inst")
                    orig_name = os.path.basename(first_audio_member.filename).replace("_(Vocals).mp3", ".mp3").replace("_(Instrumental).mp3", ".mp3") if first_audio_member else f"{base_name}.mp3"
                    
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
                    if artist and artist not in result["artists"]:
                        result["artists"].append(artist)
                    display_name = f"{artist} — {title}" if artist and title else base_name
                    if display_name not in result["tracks"]:
                        result["tracks"].append(display_name)
                    
                    processed_in_batch += 1
                
                # Флеш БД после каждого батча (безопасность + прогресс)
                try:
                    db_session.commit()
                    log.debug("Коммит БД после батча: добавлено %d треков", result["added"])
                except Exception as e:
                    log.error("Ошибка коммита БД: %s", e)
                    db_session.rollback()
                    result["errors"].append(f"Ошибка БД: {e}")
                    result["status"] = "error"
                    return result
            
            # Финальный коммит
            db_session.commit()
        
        result["status"] = "done"
        log.info("Импорт завершён: добавлено=%d, пропущено=%d, ошибки=%d", 
                 result["added"], result["skipped"], len(result["errors"]))
        _import_log(f"\n=== ИТОГО: добавлено={result['added']}, пропущено={result['skipped']}, ошибки={len(result['errors'])} ===")
        
    except Exception as e:
        db_session.rollback()
        log.error("Ошибка импорта: %s", e, exc_info=True)
        _import_log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        result["errors"].append(f"Критическая ошибка: {e}")
        result["status"] = "error"
    
    finally:
        _import_running = False
        clear_status()
    
    return result