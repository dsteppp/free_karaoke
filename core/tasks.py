from huey_config import huey
from database import SessionLocal, Track, LIBRARY_DIR
from ai_pipeline import (
    convert_to_mp3,
    separate_vocals,
    fetch_lyrics,
    generate_karaoke_subtitles,
    get_audio_metadata,
    save_library_meta,
)
from app_status import set_status, clear_status
from app_logger import get_logger
from tinytag import TinyTag
import os
import traceback
import threading
import gc
import torch
import json
import librosa
import numpy as np
import zipfile
import tempfile
import shutil
from datetime import datetime

log = get_logger("worker")

# ──────────────────────────────────────────────────────────────────────────────
# Глобальный мьютекс: гарантирует, что только один трек обрабатывается
# в любой момент времени, даже если Huey worker получит задачу раньше,
# чем предыдущая полностью завершится (включая очистку GPU).
# ──────────────────────────────────────────────────────────────────────────────
_processing_lock = threading.Lock()


@huey.task()
def process_audio_task(track_id: str):
    with _processing_lock:
        _process_track(track_id)


def _process_track(track_id: str):
    db = SessionLocal()

    try:
        track = db.query(Track).filter(Track.id == track_id).first()
        if not track:
            log.warning("Трек %s не найден в БД — пропуск.", track_id)
            return

        # ── Проверка отмены ───────────────────────────────────────────────
        def check_if_cancelled():
            db.expire(track)
            current_status = db.query(Track.status).filter(Track.id == track_id).scalar()
            if current_status == "error":
                raise InterruptedError("Обработка прервана пользователем.")

        log.info("=" * 50)
        log.info("СТАРТ: %s (id=%s)", track.original_name, track_id)

        # Формируем читаемое имя трека для строки состояния
        display_name = track.title or track.original_name or track.filename
        if track.artist:
            display_name = f"{track.artist} — {display_name}"

        base_name         = os.path.splitext(track.filename)[0]
        base_path         = os.path.join(LIBRARY_DIR, base_name)

        # ── Разрешение путей: приоритет БД (импорт), fallback на построение (новая загрузка) ──
        def _resolve_path(db_path: str | None, fallback: str) -> str:
            """Если в БД есть абсолютный путь и файл существует — используем его.
            Иначе — строим относительный (для новых загрузок)."""
            if db_path and os.path.isabs(db_path) and os.path.exists(db_path):
                return db_path
            return fallback

        vocals_path       = _resolve_path(track.vocals_path,       f"{base_path}_(Vocals).mp3")
        instrumental_path = _resolve_path(track.instrumental_path, f"{base_path}_(Instrumental).mp3")
        lyrics_path       = _resolve_path(track.lyrics_path,       f"{base_path}_(Genius Lyrics).txt")
        karaoke_json_path = _resolve_path(track.karaoke_json_path, f"{base_path}_(Karaoke Lyrics).json")

        log.debug("base_name=%s, base_path=%s", base_name, base_path)
        log.debug("vocals=%s, inst=%s, lyrics=%s, json=%s",
                  vocals_path, instrumental_path, lyrics_path, karaoke_json_path)

        check_if_cancelled()

        # ── 1. Конвертация + сепарация ────────────────────────────────────
        if not (os.path.exists(vocals_path) and os.path.exists(instrumental_path)):
            if not track.original_path or not os.path.exists(track.original_path):
                raise FileNotFoundError(
                    "Исходный файл удалён. Загрузите трек заново."
                )

            track.status = "Конвертация в MP3..."
            db.commit()
            set_status(f"🎵 {display_name} | Конвертация в MP3…")
            log.info("Конвертация: %s", track.original_path)

            # Сохраняем путь к оригиналу ДО конвертации — нужен для извлечения тегов
            original_file_before_conv = track.original_path

            mp3_path = convert_to_mp3(track.original_path)
            track.filename      = os.path.basename(mp3_path)
            track.original_path = mp3_path

            try:
                tag = TinyTag.get(mp3_path)
                if tag.duration:
                    track.duration_sec = int(tag.duration)
                    log.debug("Длительность: %d с", track.duration_sec)
            except Exception:
                pass

            artist, title  = get_audio_metadata(mp3_path, track.original_name)
            # Сохраняем artist/title из БД если они уже есть (пересканирование)
            if not track.artist and artist:
                track.artist = artist
            if not track.title and title:
                track.title = title
            # Обновляем display_name после извлечения метаданных
            display_name = track.title or track.original_name or track.filename
            if track.artist:
                display_name = f"{track.artist} — {display_name}"
            log.info("Метаданные: artist=%s, title=%s", track.artist, track.title)
            db.commit()

            check_if_cancelled()

            track.status = "Разделение вокала и музыки..."
            db.commit()
            set_status(f"🎵 {display_name} | Разделение вокала и музыки…")
            log.info("Сепарация вокала...")
            vocals_path, instrumental_path = separate_vocals(mp3_path)
            track.vocals_path       = vocals_path
            track.instrumental_path = instrumental_path
            log.info("Сепарация завершена: vocals=%s, inst=%s", vocals_path, instrumental_path)
            db.commit()

        else:
            log.info("Стемы уже существуют — пропуск сепарации.")
            if not track.title:
                artist, title = get_audio_metadata(vocals_path, track.original_name)
                track.artist  = artist or None
                track.title   = title  or None
                log.info("Метаданные из стемов: artist=%s, title=%s", track.artist, track.title)
                db.commit()

            # Если оригинал ещё остался от прошлого запуска — удаляем
            if track.original_path and os.path.exists(track.original_path):
                log.info("Удаляем оставшийся оригинал: %s", track.original_path)
                try:
                    os.remove(track.original_path)
                except Exception:
                    pass

        check_if_cancelled()

        # ── 2. Поиск текста и обложек ─────────────────────────────────────
        lib_path_check = f"{base_path}_library.json"
        if not os.path.exists(lyrics_path) or not os.path.exists(lib_path_check):
            track.status = "Поиск текста и обложек..."
            db.commit()
            set_status(f"🎵 {display_name} | Поиск текста и обложек…")
            log.info("Поиск текста на Genius: artist=%s, title=%s", track.artist, track.title)

            check_if_cancelled()

            new_lyrics, genius_artist, genius_title = fetch_lyrics(
                track.artist, track.title, base_path
            )

            if new_lyrics:
                lyrics_path = new_lyrics
                log.info("Текст найден: %s", lyrics_path)

                # Сохраняем artist/title из БД если они уже есть (пересканирование)
                if not track.artist and genius_artist:
                    track.artist = genius_artist
                    log.info("Artist обновлён из Genius: %s", genius_artist)
                if not track.title and genius_title:
                    track.title = genius_title
                    log.info("Title обновлён из Genius: %s", genius_title)
                    display_name = f"{track.artist or ''} — {track.title}".strip(" —")
            else:
                log.warning("Текст не найден на Genius.")

            track.lyrics_path = lyrics_path
            db.commit()
        else:
            log.info("Текст и обложки уже существуют — пропуск.")

        # ── Удаляем оригинал ПОСЛЕ извлечения тегов (экономия места) ─────
        if 'original_file_before_conv' in dir() and original_file_before_conv and os.path.exists(original_file_before_conv):
            log.info("Удаляем оригинал (теги извлечены): %s", original_file_before_conv)
            try:
                os.remove(original_file_before_conv)
            except Exception as e:
                log.warning("Не удалось удалить оригинал: %s", e)

        check_if_cancelled()

        # ── 3. Нейросетевая синхронизация (Whisper) ───────────────────────
        if lyrics_path and os.path.exists(lyrics_path):
            if not os.path.exists(karaoke_json_path):
                track.status = "Нейросетевая синхронизация (Whisper)..."
                db.commit()
                set_status(f"🎵 {display_name} | Нейросетевая синхронизация (Whisper)…")
                log.info("Запуск Whisper-синхронизации...")

                karaoke_json_path = generate_karaoke_subtitles(
                    instrumental_path,
                    vocals_path,
                    lyrics_path
                )

                track.karaoke_json_path = karaoke_json_path
                if karaoke_json_path:
                    log.info("Караоке JSON создан: %s", karaoke_json_path)
                else:
                    log.warning("Караоке JSON не был создан (ошибка выравнивания).")
                db.commit()
            else:
                log.info("Караоке JSON уже существует — пропуск.")
        else:
            log.warning("Текст не найден — JSON не будет создан.")

        check_if_cancelled()

        # ── 4. Очистка промежуточных файлов ───────────────────────────────
        if track.original_path and os.path.exists(track.original_path):
            set_status(f"🎵 {display_name} | Завершение…")
            log.info("Удаляем промежуточный MP3: %s", track.original_path)
            try:
                os.remove(track.original_path)
                track.original_path = None
            except Exception as e:
                log.warning("Не удалось удалить промежуточный файл: %s", e)

        # ── 5. Сохранение полных метаданных в _library.json ────────────────
        try:
            save_library_meta(base_path, original_file_before_conv if 'original_file_before_conv' in dir() else "")
        except Exception as e:
            log.warning("Не удалось сохранить _library.json: %s", e)

        track.status = "done"
        db.commit()
        log.info("ФИНИШ: %s (artist=%s, title=%s)", track.original_name, track.artist, track.title)
        log.info("=" * 50)

    except InterruptedError as e:
        db.rollback()
        log.warning("ОСТАНОВКА: %s", e)

    except Exception as e:
        db.rollback()
        error_track = db.query(Track).filter(Track.id == track_id).first()
        if error_track and error_track.status != "error":
            error_track.status        = "error"
            error_track.error_message = str(e)
            db.commit()
        log.error("ОШИБКА: %s", e)
        log.debug("Traceback:\n%s", traceback.format_exc())

    finally:
        db.close()
        clear_status()

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

        log.info("GPU память сброшена.")


# ──────────────────────────────────────────────────────────────────────────────
# TASK: Импорт библиотеки (фоновая задача с потоковой обработкой)
# ──────────────────────────────────────────────────────────────────────────────
@huey.task()
def import_library_task(zip_path: str, library_dir: str):
    """
    Фоновая задача для импорта библиотеки из ZIP файла.
    
    Обрабатывает файлы пакетно, не загружая весь архив в память.
    Поддерживает прерывание и прогресс через app_status.
    
    Args:
        zip_path: Путь к ZIP файлу
        library_dir: Целевая директория библиотеки
    """
    from library_streaming import normalize_string, _import_log
    from database import Track
    
    db = SessionLocal()
    tmp_dir = None
    
    # Глобальный результат
    result = {
        "added": 0,
        "skipped": 0,
        "errors": [],
        "artists": [],
        "tracks": [],
    }
    
    try:
        log.info("=" * 60)
        log.info("ИМПОРТ БИБЛИОТЕКИ (фоновая задача)")
        log.info("ZIP: %s", zip_path)
        log.info("Цель: %s", library_dir)
        log.info("=" * 60)
        
        # Очистка лога
        try:
            os.makedirs(os.path.dirname(_import_log.__globals__['IMPORT_LOG_PATH']), exist_ok=True)
            with open(_import_log.__globals__['IMPORT_LOG_PATH'], 'w', encoding='utf-8') as f:
                f.write(f"=== Импорт библиотеки {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except Exception:
            pass
        
        _import_log(f"Распаковка ZIP: {zip_path}")
        
        # 1. Распаковка во временную директорию
        tmp_dir = tempfile.mkdtemp(prefix="karaoke_import_")
        log.info("Временная директория: %s", tmp_dir)
        
        with zipfile.ZipFile(zip_path, 'r') as zf:
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
        
        log.info("Найдено %d групп файлов", len(file_groups))
        _import_log(f"Найдено {len(file_groups)} потенциальных треков")
        
        # 3. Загрузка существующих треков из БД для дедупликации
        # Используем итеративный подход для больших БД
        existing_keys = set()
        
        # Загружаем пакеты по 1000 записей
        offset = 0
        batch_size = 1000
        
        while True:
            batch = db.query(Track).offset(offset).limit(batch_size).all()
            if not batch:
                break
            
            for t in batch:
                if t.artist and t.title:
                    key = f"{normalize_string(t.artist)}|||{normalize_string(t.title)}"
                    existing_keys.add(key)
                base_from_filename = os.path.splitext(t.filename)[0] if t.filename else ""
                if base_from_filename:
                    existing_keys.add(f"FILENAME|||{base_from_filename.lower()}")
            
            offset += batch_size
            log.debug("Загружено %d записей для дедупликации", offset)
        
        log.info("Существующих треков: %d", len(existing_keys))
        _import_log(f"Существующих треков в БД: {len(existing_keys)}")
        
        # 4. Обработка файлов пакетными батчами
        sorted_groups = sorted(file_groups.items())
        total = len(sorted_groups)
        batch_size_import = 50  # Треков на один коммит
        
        current_batch = {}
        batch_count = 0
        
        for idx, (base_name, files) in enumerate(sorted_groups, 1):
            current_batch[base_name] = files
            
            # Обновляем статус
            progress = (idx / total) * 100 if total > 0 else 0
            set_status(f"📦 Импорт: {base_name} ({idx}/{total})", progress)
            _import_log(f"[{idx}/{total}] Обработка: {base_name}")
            
            # Когда набрали батч — обрабатываем
            if len(current_batch) >= batch_size_import or idx == total:
                batch_count += 1
                log.info("Обработка батча %d (%d треков)", batch_count, len(current_batch))
                
                # Обработка батча
                batch_result = _process_import_batch(
                    current_batch, library_dir, db, Track, existing_keys, tmp_dir
                )
                
                result["added"] += batch_result["added"]
                result["skipped"] += batch_result["skipped"]
                result["errors"].extend(batch_result["errors"])
                
                # Собираем артистов и треки
                for base, files in current_batch.items():
                    if "meta" in files:
                        try:
                            with open(files["meta"], 'r', encoding='utf-8') as f:
                                meta = json.load(f)
                            artist = meta.get("artist", "") or ""
                            title = meta.get("title", "") or ""
                        except:
                            artist, title = "", ""
                    else:
                        artist, title = base, ""
                    
                    display_name = f"{artist} — {title}" if artist and title else base
                    if artist and artist not in result["artists"]:
                        result["artists"].append(artist)
                    if display_name not in result["tracks"]:
                        result["tracks"].append(display_name)
                
                # Коммит батча
                db.commit()
                log.info("Батч %d завершён: добавлено=%d, пропущено=%d", 
                        batch_count, batch_result["added"], batch_result["skipped"])
                
                # Очищаем текущий батч
                current_batch = {}
        
        log.info("Импорт завершён: добавлено=%d, пропущено=%d, ошибки=%d", 
                result["added"], result["skipped"], len(result["errors"]))
        _import_log(f"\n=== ИТОГО: добавлено={result['added']}, пропущено={result['skipped']}, ошибки={len(result['errors'])} ===")
        
        # Сохраняем результат в кэш для получения через API
        from app_status import _ensure_dir
        import json as json_mod
        _ensure_dir()
        cache_file = os.path.join(
            os.environ.get("FK_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache"),
            "import_result.json"
        )
        with open(cache_file, 'w', encoding='utf-8') as f:
            json_mod.dump(result, f, ensure_ascii=False)
        
    except Exception as e:
        db.rollback()
        log.error("Ошибка импорта: %s", e, exc_info=True)
        _import_log(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        result["errors"].append(f"Критическая ошибка: {e}")
        
        # Сохраняем ошибку в кэш
        from app_status import _ensure_dir
        import json as json_mod
        _ensure_dir()
        cache_file = os.path.join(
            os.environ.get("FK_CACHE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache"),
            "import_result.json"
        )
        with open(cache_file, 'w', encoding='utf-8') as f:
            json_mod.dump(result, f, ensure_ascii=False)
    
    finally:
        # Очистка временной директории
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                shutil.rmtree(tmp_dir)
                log.debug("Временная директория удалена: %s", tmp_dir)
            except Exception:
                pass
        
        # Удаляем ZIP после обработки
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
                log.debug("ZIP файл удалён: %s", zip_path)
            except Exception:
                pass
        
        db.close()
        clear_status()
        
        log.info("Импорт библиотеки завершён")


def _process_import_batch(
    batch_files: dict,
    library_dir: str,
    db_session,
    Track_model,
    existing_keys: set,
    tmp_dir: str,
) -> dict:
    """
    Внутренняя функция для обработки батча импорта.
    Дублирует логику из library_streaming для автономности задачи.
    """
    from library_streaming import normalize_string, _import_log
    
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
    
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Partial Rescan Task: перескан таймингов от указанного слова до конца песни
# ──────────────────────────────────────────────────────────────────────────────
@huey.task()
def partial_rescan_task(track_id: str, start_word_index: int, anchor_time: float):
    """
    Частичный перескан таймингов: обрабатывает только слова [start_word_index:] до конца песни.
    Слова до start_word_index НЕ изменяются — их тайминги сохраняются как есть.

    anchor_time — точное время (секунды) ручного якоря, установленного пользователем.
    Аудио и VAD обрезаются от anchor_time, чтобы Whisper и matching работали только
    от указанной точки, игнорируя сломанные тайминги до неё.
    """
    db = SessionLocal()

    try:
        track = db.query(Track).filter(Track.id == track_id).first()
        if not track:
            log.warning("Трек %s не найден в БД — пропуск partial rescan.", track_id)
            return

        log.info("=" * 80)
        log.info("🔄 PARTIAL RESCAN: СТАРТ")
        log.info("   🆔 Трек: %s", track_id)
        log.info("   🎵 Имя файла: %s", track.filename)
        log.info("   📝 Title: %s", track.title)
        log.info("   🎤 Artist: %s", track.artist)
        log.info("   ⚓ Якорь: слово #%d на %.2fс", start_word_index, anchor_time)
        log.info("=" * 80)

        # Формируем читаемое имя трека
        display_name = track.title or track.original_name or track.filename
        if track.artist:
            display_name = f"{track.artist} — {display_name}"

        base_name = os.path.splitext(track.filename)[0]
        base_path = os.path.join(LIBRARY_DIR, base_name)

        # ── Разрешение путей: приоритет БД (импорт), fallback на построение ──
        def _resolve_path(db_path: str | None, fallback: str) -> str:
            if db_path and os.path.isabs(db_path) and os.path.exists(db_path):
                return db_path
            return fallback

        vocals_path = _resolve_path(track.vocals_path, f"{base_path}_(Vocals).mp3")
        lyrics_path = _resolve_path(track.lyrics_path, f"{base_path}_(Genius Lyrics).txt")
        karaoke_json_path = _resolve_path(track.karaoke_json_path, f"{base_path}_(Karaoke Lyrics).json")
        vad_path = f"{base_path}_(VAD).json"

        # ── Загрузка входных данных ──────────────────────────────────────────
        log.info("─" * 60)
        log.info("📂 ЭТАП 1: Загрузка входных данных")
        log.info("   📁 Vocals: %s (exists=%s)", vocals_path, os.path.exists(vocals_path))
        log.info("   📁 Lyrics: %s (exists=%s)", lyrics_path, os.path.exists(lyrics_path))
        log.info("   📁 Karaoke JSON: %s (exists=%s)", karaoke_json_path, os.path.exists(karaoke_json_path))
        log.info("   📁 VAD кэш: %s (exists=%s)", vad_path, os.path.exists(vad_path))

        # Устанавливаем статус (блокировка UI)
        set_status(f"🔄 {display_name} | Рескан таймингов от слова {start_word_index + 1} ({anchor_time:.0f}с)…", progress=None)

        # Загружаем текст песни
        if not lyrics_path or not os.path.exists(lyrics_path):
            raise FileNotFoundError(f"Файл текста не найден: {lyrics_path}")

        with open(lyrics_path, "r", encoding="utf-8") as f:
            lyrics_text = f.read()

        log.info("   📄 Текст загружен: %d символов", len(lyrics_text))

        # Загружаем существующие тайминги (старые)
        if not karaoke_json_path or not os.path.exists(karaoke_json_path):
            raise FileNotFoundError(f"Файл караоке JSON не найден: {karaoke_json_path}")

        with open(karaoke_json_path, "r", encoding="utf-8") as f:
            old_karaoke_data = json.load(f)

        log.info("   📊 Karaoke JSON загружен: %d слов", len(old_karaoke_data))

        # ── Логирование состояния слов до рескана ────────────────────────────
        log.info("─" * 60)
        log.info("📊 ЭТАП 2: Анализ исходных таймингов")

        # Считаем слова с broken таймингами
        broken_before = 0
        manual_before = 0
        valid_before = 0
        broken_after = 0

        for idx, w in enumerate(old_karaoke_data):
            is_broken = (w.get("start", -1) == -1 or w.get("end", -1) == -1)
            is_manual = w.get("is_manual_start", False) or w.get("is_manual_end", False)
            is_before = idx < start_word_index

            if is_before:
                if is_broken:
                    broken_before += 1
                elif is_manual:
                    manual_before += 1
                else:
                    valid_before += 1
            else:
                if is_broken:
                    broken_after += 1

        log.info("   📍 ДО якоря (слов %d):", start_word_index)
        log.info("      ✅ Рабочих таймингов: %d", valid_before)
        log.info("      ⚓ Ручных якорей: %d", manual_before)
        log.info("      ❌ Сломанных (start=-1): %d", broken_before)
        log.info("   📍 ПОСЛЕ якоря (слов %d):", len(old_karaoke_data) - start_word_index)
        log.info("      ❌ Сломанных (требуют рескана): %d", broken_after)

        # Логирование ключевого слова-якоря
        anchor_word = old_karaoke_data[start_word_index]
        log.info("   ⚓ СЛОВО-ЯКОРЬ #%d: «%s»", start_word_index, anchor_word.get("word", "?"))
        log.info("      🕐 Старый start: %.3fс", anchor_word.get("start", -1))
        log.info("      🕐 Старый end: %.3fс", anchor_word.get("end", -1))
        log.info("      ⚓ Новый anchor_time: %.3fс (установлен вручную)", anchor_time)
        log.info("      🔄 Разница: %.3fс", anchor_time - anchor_word.get("start", -1))

        if start_word_index >= len(old_karaoke_data):
            log.warning("start_word_index=%d >= всего слов=%d — рескан невозможен", start_word_index, len(old_karaoke_data))
            set_status(f"❌ {display_name} | Ошибка: индекс слова вне диапазона")
            return

        # ── КЛЮЧЕВОЙ ЭТАП: обрезаем аудио и VAD по anchor_time ───────────────
        log.info("─" * 60)
        log.info("✂️ ЭТАП 3: Обрезка аудио и VAD по якорю")

        # Буфер перед якорем (0.5с) — чтобы захватить начало слога
        ANCHOR_BUFFER = 0.5
        audio_start_time = max(0.0, anchor_time - ANCHOR_BUFFER)

        log.info("   ⚓ Якорь пользователя: %.2fс", anchor_time)
        log.info("   📐 Буфер для захвата начала слога: %.2fс", ANCHOR_BUFFER)
        log.info("   📍 Аудио начинаем с: %.2fс", audio_start_time)

        # Загружаем полное аудио
        log.info("   🎧 Загрузка вокального стема...")
        audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
        full_duration = len(audio_data) / sr

        # Обрезаем аудио-массив: берём только от anchor_time - buffer до конца
        start_sample = int(audio_start_time * sr)
        audio_partial = audio_data[start_sample:]
        partial_duration = len(audio_partial) / sr

        log.info("   📊 Полное аудио: %.2fс (%d сэмплов)", full_duration, len(audio_data))
        log.info("   📊 Обрезанное аудио: %.2fс (%d сэмплов) — с %.2fс до конца", partial_duration, len(audio_partial), audio_start_time)
        log.info("   📉 Обрезано: %.2fс тишины/проигрыша в начале", audio_start_time)

        # Загружаем или вычисляем VAD
        log.info("   🔊 Загрузка/расчёт VAD-интервалов...")
        vad_intervals = None
        if os.path.exists(vad_path):
            try:
                with open(vad_path, "r", encoding="utf-8") as f:
                    vad_data = json.load(f)
                all_vad = vad_data.get("intervals", [])
                log.info("   📂 VAD загружен из кэша: %d интервалов", len(all_vad))
                # Покажем первые 5 интервалов для понимания
                for i, (vs, ve) in enumerate(all_vad[:5]):
                    log.info("      VAD[%d]: %.2fс — %.2fс (%.2fс)", i, vs, ve, ve - vs)
                if len(all_vad) > 5:
                    log.info("      ... и ещё %d интервалов", len(all_vad) - 5)
            except Exception as e:
                log.warning("Не удалось загрузить VAD из кэша: %s", e)
                all_vad = []
        else:
            log.info("   🔄 VAD кэш не найден — вычисляем заново...")
            from aligner_acoustics import get_vocal_intervals
            all_vad = get_vocal_intervals(audio_data, sr, top_db=35.0)
            if not all_vad:
                all_vad = [(0.0, full_duration)]
            log.info("   🔊 VAD рассчитан: %d интервалов", len(all_vad))

        # Обрезаем VAD-интервалы: только те, что пересекаются с [audio_start_time, full_duration]
        vad_intervals = []
        vad_clipped_count = 0
        vad_dropped_count = 0
        for vs, ve in all_vad:
            # Интервал должен хотя бы частично быть после audio_start_time
            if ve > audio_start_time:
                # Обрезаем начало интервала, если оно раньше audio_start_time
                if vs < audio_start_time:
                    clipped_start = audio_start_time
                    vad_clipped_count += 1
                else:
                    clipped_start = vs
                vad_intervals.append((clipped_start, ve))
            else:
                vad_dropped_count += 1

        log.info("   ✂️ VAD обрезан по якорю (%.2fс):", audio_start_time)
        log.info("      📥 Было интервалов: %d", len(all_vad))
        log.info("      ✂️ Обрезано начало: %d", vad_clipped_count)
        log.info("      🗑️ Отброшено (до якоря): %d", vad_dropped_count)
        log.info("      ✅ Осталось для анализа: %d", len(vad_intervals))

        # Покажем первые 5 обрезанных VAD интервалов
        for i, (vs, ve) in enumerate(vad_intervals[:5]):
            log.info("      VAD_clip[%d]: %.2fс — %.2fс (%.2fс)", i, vs, ve, ve - vs)
        if len(vad_intervals) > 5:
            log.info("      ... и ещё %d интервалов", len(vad_intervals) - 5)

        # ── Транскрипция через Whisper ТОЛЬКО обрезанного аудио ──────────────
        log.info("─" * 60)
        log.info("🎤 ЭТАП 4: Whisper-транскрипция (обрезанное аудио)")
        log.info("   🌐 Аудио: %.2fс (от %.2fс до конца)", partial_duration, audio_start_time)
        log.info("   🧠 Модель: medium")

        from stable_whisper import load_model
        from aligner_utils import detect_language, prepare_text, clean_word
        from karaoke_aligner import KaraokeAligner

        lang = detect_language(lyrics_text)
        aligner = KaraokeAligner()
        model = load_model("medium", download_root=aligner.whisper_model_dir, device=aligner.device)

        log.info("   🌍 Язык: %s", lang)
        log.info("   ⏳ Запуск transcribe...")

        result = model.transcribe(
            audio_partial,
            language=lang,
            word_timestamps=True,
            vad=True,
        )

        # Подсчитаем сегменты и слова от Whisper
        total_segments = len(result.segments)
        total_raw_words = sum(len(seg.words) for seg in result.segments)
        log.info("   ✅ Транскрипция завершена")
        log.info("   📊 Сегментов: %d, слов (сырых): %d", total_segments, total_raw_words)

        # Лог первых нескольких сегментов
        for seg_idx, seg in enumerate(result.segments[:3]):
            words_sample = [f"«{w.word.strip()}»({w.start:.2f}-{w.end:.2f})" for w in seg.words[:5]]
            log.info("   Сегмент[%d]: %s ...", seg_idx, " ".join(words_sample))
        if total_segments > 3:
            log.info("   ... и ещё %d сегментов", total_segments - 3)

        # Формируем raw_heard_words — сдвигаем тайминги обратно к абсолютным значениям
        raw_heard_words = []
        for segment in result.segments:
            for w in segment.words:
                cw = clean_word(w.word)
                if cw:
                    # Сдвигаем тайминги: Whisper дал время от 0 (обрезанное аудио),
                    # нам нужно абсолютное время в оригинальном аудио
                    abs_start = w.start + audio_start_time
                    abs_end = w.end + audio_start_time
                    raw_heard_words.append({
                        "word": w.word,
                        "clean": cw,
                        "start": abs_start,
                        "end": abs_end,
                        "probability": w.probability,
                    })

        log.info("   📝 raw_heard_words: %d слов (после clean_word)", len(raw_heard_words))
        # Покажем первые 10 heard words
        for i, hw in enumerate(raw_heard_words[:10]):
            log.info("      heard[%d]: «%s» clean=«%s» %.2fс-%.2fс p=%.2f",
                     i, hw["word"].strip(), hw["clean"], hw["start"], hw["end"], hw["probability"])
        if len(raw_heard_words) > 10:
            log.info("      ... и ещё %d слов", len(raw_heard_words) - 10)

        # ── Фильтрация галлюцинаций ─────────────────────────────────────────
        log.info("─" * 60)
        log.info("🧹 ЭТАП 5: Фильтрация галлюцинаций по VAD")
        log.info("   📥 Вход: %d raw_heard_words", len(raw_heard_words))
        log.info("   📊 VAD интервалов для фильтрации: %d", len(vad_intervals))

        from aligner_acoustics import filter_whisper_hallucinations
        heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

        filtered_out = len(raw_heard_words) - len(heard_words)
        log.info("   ✅ После фильтрации: %d слов (отфильтровано: %d)", len(heard_words), filtered_out)

        # Покажем первые 10 отфильтрованных слов
        for i, hw in enumerate(heard_words[:10]):
            log.info("      clean[%d]: «%s» %.2fс-%.2fс", i, hw["clean"], hw["start"], hw["end"])
        if len(heard_words) > 10:
            log.info("      ... и ещё %d слов", len(heard_words) - 10)

        # ── Sequence Matching ───────────────────────────────────────────────
        log.info("─" * 60)
        log.info("🧠 ЭТАП 6: Sequence Matching (сопоставление текста с аудио)")
        log.info("   ⚓ Partial rescan от слова #%d («%s»)", start_word_index, anchor_word.get("word", "?"))
        log.info("   ⚓ Anchor time: %.2fс", anchor_time)
        log.info("   📝 Слов в тексте (всего): %d", len(old_karaoke_data))
        log.info("   📝 Слов после якоря: %d", len(old_karaoke_data) - start_word_index)
        log.info("   🎤 heard_words для matching: %d", len(heard_words))

        from aligner_orchestra import execute_sequence_matching
        canon_words = prepare_text(lyrics_text)

        log.info("   📄 canon_words (из lyrics): %d слов", len(canon_words))

        # ── КРИТИЧЕСКОЕ: копируем старые тайминги слов ДО якоря ─────────────
        # prepare_text создаёт ВСЕ слова с start=-1, end=-1.
        # prepare_text МОЖЕТ дать другое количество слов, чем old_karaoke_data
        # (например, если в JSON есть теги [Chorus] которые были удалены).
        # Нужно сопоставить слова по тексту и скопировать тайминги.
        log.info("   🔄 Восстановление старых таймингов для слов [0:%d]...", start_word_index)

        restored_count = 0
        mismatch_count = 0

        for idx in range(start_word_index):
            if idx >= len(canon_words):
                log.warning("   ⚠️ canon_words короче old_karaoke_data — остановка на idx=%d", idx)
                break

            old_w = old_karaoke_data[idx]
            new_w = canon_words[idx]

            # Сравниваем текст слов (case-insensitive, strip)
            old_text = old_w.get("word", "").strip().lower()
            new_text = new_w["word"].strip().lower()

            if old_text == new_text:
                new_w["start"] = old_w.get("start", -1.0)
                new_w["end"] = old_w.get("end", -1.0)
                # Копируем флаги ручных якорей если они были в JSON
                if "is_manual_start" in old_w:
                    new_w["is_manual_start"] = old_w["is_manual_start"]
                if "is_manual_end" in old_w:
                    new_w["is_manual_end"] = old_w["is_manual_end"]
                if old_w.get("start", -1) >= 0:
                    restored_count += 1
            else:
                mismatch_count += 1
                log.warning("   ⚠️ Несоответствие слов [%d]: old=«%s» ≠ new=«%s» — пропускаем",
                            idx, old_w.get("word", "?"), new_w["word"])

        log.info("   ✅ Восстановлено таймингов: %d | Несовпадений: %d", restored_count, mismatch_count)

        # Лог первых слов canon (после восстановления)
        for i in range(min(5, len(canon_words))):
            w = canon_words[i]
            status = "✅" if w.get("start", -1) >= 0 else "❌"
            log.info("      %s canon[%d]: «%s» clean=«%s» start=%.3f end=%.3f",
                     status, i, w["word"], w["clean_text"], w.get("start", -1), w.get("end", -1))

        # ВАЖНО: canon_words — это полный массив, включая старые тайминги
        # execute_sequence_matching с start_word_index > 0 обработает только часть
        canon_words = execute_sequence_matching(
            canon_words, heard_words, vad_intervals, full_duration, start_word_index, anchor_time
        )

        # ── Анализ результатов matching ─────────────────────────────────────
        log.info("─" * 60)
        log.info("📊 ЭТАП 7: Анализ результатов matching")

        matched_after = 0
        broken_after_match = 0
        manual_anchors_after = 0

        for idx in range(start_word_index, len(canon_words)):
            w = canon_words[idx]
            if w.get("start", -1) >= 0:
                matched_after += 1
                if w.get("is_manual_start", False) or w.get("is_manual_end", False):
                    manual_anchors_after += 1
            else:
                broken_after_match += 1

        log.info("   ✅ Слов с таймингами после рескана: %d", matched_after)
        log.info("   ⚓ Ручных якорей (сохранены): %d", manual_anchors_after)
        log.info("   ❌ Слов без таймингов (слепые зоны): %d", broken_after_match)

        # Лог первых 10 слов после якоря
        log.info("   📝 Первые 10 слов после якоря:")
        for i in range(start_word_index, min(start_word_index + 10, len(canon_words))):
            w = canon_words[i]
            status = "✅" if w.get("start", -1) >= 0 else "❌"
            manual = " ⚓MANUAL" if (w.get("is_manual_start") or w.get("is_manual_end")) else ""
            log.info("      %s canon[%d]: «%s» start=%.3f end=%.3f%s",
                     status, i, w["word"], w.get("start", -1), w.get("end", -1), manual)

        # ── Физический контроль (VAD-Magnet) ────────────────────────────────
        log.info("─" * 60)
        log.info("🧲 ЭТАП 8: VAD-Magnet (притягивание к голосу)")
        from aligner_acoustics import constrain_to_vad
        vad_magnet_shifts = 0
        for idx, w in enumerate(canon_words):
            if idx >= start_word_index and w["start"] >= 0:
                old_start = w["start"]
                old_end = w["end"]
                w["start"], w["end"], _ = constrain_to_vad(w["start"], w["end"], vad_intervals, max_shift_sec=1.5)
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1
                if abs(w["start"] - old_start) > 0.01:
                    vad_magnet_shifts += 1

        log.info("   📍 Слов сдвинуто VAD-Magnet: %d", vad_magnet_shifts)

        # ── Устранение нахлёстов ────────────────────────────────────────────
        log.info("─" * 60)
        log.info("🔧 ЭТАП 9: Устранение нахлёстов")
        from karaoke_aligner import KaraokeAligner
        temp_aligner = KaraokeAligner()
        temp_aligner._resolve_overlaps(canon_words[start_word_index:])
        log.info("   ✅ Нахлёсты устранены")

        # ── Итоговая сводка ─────────────────────────────────────────────────
        log.info("─" * 60)
        log.info("📋 ЭТАП 10: Итоговая сводка partial rescan")

        total_with_timing = 0
        total_broken = 0
        total_manual = 0
        for idx, w in enumerate(canon_words):
            if w.get("start", -1) >= 0:
                total_with_timing += 1
                if w.get("is_manual_start", False) or w.get("is_manual_end", False):
                    total_manual += 1
            else:
                total_broken += 1

        log.info("   📊 ВСЕГО слов: %d", len(canon_words))
        log.info("   ✅ С таймингами: %d (%.1f%%)", total_with_timing, 100.0 * total_with_timing / max(1, len(canon_words)))
        log.info("   ⚓ Ручных якорей: %d", total_manual)
        log.info("   ❌ Без таймингов: %d (%.1f%%)", total_broken, 100.0 * total_broken / max(1, len(canon_words)))
        log.info("   📍 ДО якоря (не тронуты): %d слов", start_word_index)
        log.info("   📍 ПОСЛЕ якоря (обработаны): %d слов", len(canon_words) - start_word_index)

        # Лог последних 5 слов для проверки конца
        log.info("   📝 Последние 5 слов:")
        for i in range(max(0, len(canon_words) - 5), len(canon_words)):
            w = canon_words[i]
            status = "✅" if w.get("start", -1) >= 0 else "❌"
            log.info("      %s canon[%d]: «%s» start=%.3f end=%.3f",
                     status, i, w["word"], w.get("start", -1), w.get("end", -1))

        # Формируем JSON
        log.info("─" * 60)
        log.info("💾 ЭТАП 11: Сохранение результатов")

        final_json = []
        for w in canon_words:
            final_json.append({
                "word": w["word"],
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "line_break": w["line_break"],
                "letters": [],
            })

        with open(karaoke_json_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, ensure_ascii=False, indent=2)

        log.info("   💾 JSON сохранён: %s", karaoke_json_path)
        log.info("   📝 Записано слов: %d", len(final_json))

        log.info("=" * 80)
        log.info("✅ PARTIAL RESCAN ЗАВЕРШЁН УСПЕШНО")
        log.info("   📊 Слов обработано: %d (из %d)", len(canon_words) - start_word_index, len(canon_words))
        log.info("   ✅ С таймингами: %d | ❌ Без таймингов: %d", total_with_timing - (start_word_index - broken_before - manual_before), total_broken)
        log.info("=" * 80)

        # Освобождение памяти
        if 'model' in locals() and model:
            del model
        if 'audio_data' in locals():
            del audio_data
        if 'audio_partial' in locals():
            del audio_partial
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

        log.info("💾 GPU память сброшена после partial rescan.")
        log.info("=" * 80)

    except InterruptedError as e:
        db.rollback()
        log.warning("PARTIAL RESCAN ОСТАНОВЛЕН: %s", e)

    except Exception as e:
        db.rollback()
        log.error("PARTIAL RESCAN ОШИБКА: %s", e)
        log.debug("Traceback:\n%s", traceback.format_exc())

    finally:
        db.close()
        clear_status()

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

        log.info("GPU память сброшена (finally partial rescan).")
