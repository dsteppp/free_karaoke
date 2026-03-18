from huey_config import huey
from database import SessionLocal, Track
from ai_pipeline import (
    convert_to_mp3,
    separate_vocals,
    fetch_lyrics,
    generate_karaoke_subtitles,
    get_audio_metadata,
)
from app_logger import get_logger
from tinytag import TinyTag
import os
import traceback
import threading
import gc
import torch

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

        base_name         = os.path.splitext(track.filename)[0]
        base_path         = os.path.join("library", base_name)
        vocals_path       = f"{base_path}_(Vocals).mp3"
        instrumental_path = f"{base_path}_(Instrumental).mp3"
        lyrics_path       = f"{base_path}_(Genius Lyrics).txt"
        meta_path         = f"{base_path}_meta.json"
        karaoke_json_path = f"{base_path}_(Karaoke Lyrics).json"

        log.debug("base_name=%s, base_path=%s", base_name, base_path)

        check_if_cancelled()

        # ── 1. Конвертация + сепарация ────────────────────────────────────
        if not (os.path.exists(vocals_path) and os.path.exists(instrumental_path)):
            if not track.original_path or not os.path.exists(track.original_path):
                raise FileNotFoundError(
                    "Исходный файл удалён. Загрузите трек заново."
                )

            track.status = "Конвертация в MP3..."
            db.commit()
            log.info("Конвертация: %s", track.original_path)
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
            track.artist   = artist or None
            track.title    = title  or None
            log.info("Метаданные: artist=%s, title=%s", track.artist, track.title)
            db.commit()

            check_if_cancelled()

            track.status = "Разделение вокала и музыки..."
            db.commit()
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

        check_if_cancelled()

        # ── 2. Поиск текста и обложек ─────────────────────────────────────
        if not os.path.exists(lyrics_path) or not os.path.exists(meta_path):
            track.status = "Поиск текста и обложек..."
            db.commit()
            log.info("Поиск текста на Genius: artist=%s, title=%s", track.artist, track.title)
            
            new_lyrics, genius_artist, genius_title = fetch_lyrics(
                track.artist, track.title, base_path
            )
            
            if new_lyrics:
                lyrics_path = new_lyrics
                log.info("Текст найден: %s", lyrics_path)
                
                # Обновляем artist/title из Genius (авторитетный источник)
                if genius_artist:
                    track.artist = genius_artist
                    log.info("Artist обновлён из Genius: %s", genius_artist)
                if genius_title:
                    track.title = genius_title
                    log.info("Title обновлён из Genius: %s", genius_title)
            else:
                log.warning("Текст не найден на Genius.")
            
            track.lyrics_path = lyrics_path
            db.commit()
        else:
            log.info("Текст и обложки уже существуют — пропуск.")

        check_if_cancelled()

        # ── 3. Нейросетевая синхронизация (Whisper) ───────────────────────
        if lyrics_path and os.path.exists(lyrics_path):
            if not os.path.exists(karaoke_json_path):
                track.status = "Нейросетевая синхронизация (Whisper)..."
                db.commit()
                log.info("Запуск Whisper-синхронизации...")
                
                # Вызов СТРОГО позиционный: inst, vocals, lyrics
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

        # ── 4. Удаление оригинала (экономия места) ────────────────────────
        if track.original_path and os.path.exists(track.original_path):
            log.info("Удаляем оригинал: %s", track.original_path)
            try:
                os.remove(track.original_path)
                track.original_path = None
            except Exception as e:
                log.warning("Не удалось удалить оригинал: %s", e)

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

        # Тотальная очистка VRAM после каждой задачи
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

        log.info("GPU память сброшена.")