"""
Экспорт и импорт библиотеки AI-Karaoke Pro.
- Экспорт: все файлы library/ → ZIP-архив
- Импорт: ZIP-архив → валидация → дедупликация → копирование в library/
"""
import os
import zipfile
import json
import shutil
import re
import threading
import io
from datetime import datetime
from typing import Dict, List, Tuple, Optional

from app_logger import get_logger
from app_status import set_status, clear_status

log = get_logger("library_io")

# Путь к логу импорта — удаляется при старте приложения
IMPORT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "debug_logs",
    "import.log"
)

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


def export_library(library_dir: str) -> bytes:
    """
    Создать ZIP-архив со всеми файлами библиотеки.
    Возвращает байты ZIP-файла.
    """
    log.info("Экспорт библиотеки: %s", library_dir)
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for fname in sorted(os.listdir(library_dir)):
            fpath = os.path.join(library_dir, fname)
            if os.path.isfile(fpath):
                zf.write(fpath, arcname=fname)
                log.debug("  Добавлен в архив: %s", fname)
    
    result = zip_buffer.getvalue()
    log.info("Экспорт завершён: %d байт", len(result))
    return result


def _import_log(msg: str):
    """Записать сообщение в лог импорта."""
    try:
        with open(IMPORT_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def import_library(
    zip_bytes: bytes,
    library_dir: str,
    db_session,
    Track_model,
) -> dict:
    """
    Импортировать библиотеку из ZIP-архива.
    
    Логика:
    1. Распаковать ZIP во временную директорию
    2. Для каждого трека проверить наличие Vocal + Instrumental
    3. Сравнить artist+title с существующими (нормализованное сравнение)
    4. Если нет дубликата — скопировать файлы в library/
    5. Добавить запись в БД
    
    Возвращает:
    {
        "added": int,
        "skipped": int,
        "errors": List[str],
        "artists": List[str],
        "tracks": List[str],
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
    }
    
    tmp_dir = None
    try:
        # 1. Распаковка во временную директорию
        import tempfile
        tmp_dir = tempfile.mkdtemp(prefix="karaoke_import_")
        log.info("Импорт: распаковка в %s", tmp_dir)
        _import_log(f"Распаковка ZIP ({len(zip_bytes)} байт)")
        
        with zipfile.ZipFile(io.BytesIO(zip_bytes), 'r') as zf:
            zf.extractall(tmp_dir)
        
        # 2. Группировка файлов по base_name
        file_groups: Dict[str, dict] = {}
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
        
        # 3. Загрузка существующих треков из БД для дедупликации
        existing_tracks = db_session.query(Track_model).all()
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
        
        total = len(file_groups)
        for idx, (base_name, files) in enumerate(sorted(file_groups.items()), 1):
            has_vocals = "vocals" in files
            has_inst = "inst" in files
            
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
            
            # 4. Проверка дубликатов
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
            
            # 5. Копирование файлов в library/
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
            
            # 6. Добавление записи в БД
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
        
        db_session.commit()
        log.info("Импорт завершён: добавлено=%d, пропущено=%d", result["added"], result["skipped"])
        _import_log(f"\n=== ИТОГО: добавлено={result['added']}, пропущено={result['skipped']}, ошибки={len(result['errors'])} ===")
        
    except Exception as e:
        db_session.rollback()
        log.error("Ошибка импорта: %s", e, exc_info=True)
        _import_log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        result["errors"].append(f"Критическая ошибка: {e}")
    
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
