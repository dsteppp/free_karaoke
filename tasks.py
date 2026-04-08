from huey_config import huey
from database import SessionLocal, Track
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
        base_path         = os.path.join("library", base_name)
        vocals_path       = f"{base_path}_(Vocals).mp3"
        instrumental_path = f"{base_path}_(Instrumental).mp3"
        lyrics_path       = f"{base_path}_(Genius Lyrics).txt"
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

        log.info("=" * 50)
        log.info("PARTIAL RESCAN: трек %s, start_word_index=%d, anchor_time=%.2f", track_id, start_word_index, anchor_time)

        # Формируем читаемое имя трека
        display_name = track.title or track.original_name or track.filename
        if track.artist:
            display_name = f"{track.artist} — {display_name}"

        base_name = os.path.splitext(track.filename)[0]
        base_path = os.path.join("library", base_name)
        vocals_path = f"{base_path}_(Vocals).mp3"
        lyrics_path = f"{base_path}_(Genius Lyrics).txt"
        karaoke_json_path = f"{base_path}_(Karaoke Lyrics).json"
        vad_path = f"{base_path}_(VAD).json"

        # Устанавливаем статус (блокировка UI)
        set_status(f"🔄 {display_name} | Рескан таймингов от слова {start_word_index + 1} ({anchor_time:.0f}с)…", progress=None)

        # Загружаем текст песни
        if not lyrics_path or not os.path.exists(lyrics_path):
            raise FileNotFoundError(f"Файл текста не найден: {lyrics_path}")

        with open(lyrics_path, "r", encoding="utf-8") as f:
            lyrics_text = f.read()

        # Загружаем существующие тайминги (старые)
        if not karaoke_json_path or not os.path.exists(karaoke_json_path):
            raise FileNotFoundError(f"Файл караоке JSON не найден: {karaoke_json_path}")

        with open(karaoke_json_path, "r", encoding="utf-8") as f:
            old_karaoke_data = json.load(f)

        log.info("Загружено %d слов из существующего JSON", len(old_karaoke_data))

        if start_word_index >= len(old_karaoke_data):
            log.warning("start_word_index=%d >= всего слов=%d — рескан невозможен", start_word_index, len(old_karaoke_data))
            set_status(f"❌ {display_name} | Ошибка: индекс слова вне диапазона")
            return

        # ── КЛЮЧЕВОЙ ЭТАП: обрезаем аудио и VAD по anchor_time ───────────────
        # Буфер перед якорем (0.5с) — чтобы захватить начало слога
        ANCHOR_BUFFER = 0.5
        audio_start_time = max(0.0, anchor_time - ANCHOR_BUFFER)

        log.info("✂️ Обрезка аудио: начинаем анализ с %.2fс (якорь=%.2f, буфер=%.2f)",
                 audio_start_time, anchor_time, ANCHOR_BUFFER)

        # Загружаем полное аудио
        audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
        full_duration = len(audio_data) / sr

        # Обрезаем аудио-массив: берём только от anchor_time - buffer до конца
        start_sample = int(audio_start_time * sr)
        audio_partial = audio_data[start_sample:]
        partial_duration = len(audio_partial) / sr

        log.info("   📊 Полное аудио: %.2fс, обрезанное: %.2fс (с %.2f до конца)",
                 full_duration, partial_duration, audio_start_time)

        # Загружаем или вычисляем VAD
        vad_intervals = None
        if os.path.exists(vad_path):
            try:
                with open(vad_path, "r", encoding="utf-8") as f:
                    vad_data = json.load(f)
                all_vad = vad_data.get("intervals", [])
                log.info("VAD загружен из кэша: %d интервалов", len(all_vad))
            except Exception as e:
                log.warning("Не удалось загрузить VAD из кэша: %s", e)
                all_vad = []
        else:
            from aligner_acoustics import get_vocal_intervals
            all_vad = get_vocal_intervals(audio_data, sr, top_db=35.0)
            if not all_vad:
                all_vad = [(0.0, full_duration)]

        # Обрезаем VAD-интервалы: только те, что пересекаются с [audio_start_time, full_duration]
        vad_intervals = []
        for vs, ve in all_vad:
            # Интервал должен хотя бы частично быть после audio_start_time
            if ve > audio_start_time:
                # Обрезаем начало интервала, если оно раньше audio_start_time
                clipped_start = max(vs, audio_start_time)
                vad_intervals.append((clipped_start, ve))

        log.info("   ✂️ VAD обрезан: было %d, осталось %d интервалов от %.2fс",
                 len(all_vad), len(vad_intervals), audio_start_time)

        # ── Транскрипция через Whisper ТОЛЬКО обрезанного аудио ──────────────
        log.info("🎤 Запуск Whisper-транскрипции (обрезанное аудио от %.2fс)…", audio_start_time)
        from stable_whisper import load_model
        from aligner_utils import detect_language, prepare_text, clean_word
        from karaoke_aligner import KaraokeAligner

        lang = detect_language(lyrics_text)
        aligner = KaraokeAligner()
        model = load_model("medium", download_root=aligner.whisper_model_dir, device=aligner.device)

        result = model.transcribe(
            audio_partial,
            language=lang,
            word_timestamps=True,
            vad=True,
        )

        log.info("Транскрипция завершена")

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

        # Фильтрация галлюцинаций — по обрезанным VAD
        from aligner_acoustics import filter_whisper_hallucinations
        heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

        log.info("После фильтрации галлюцинаций: %d слов (от %.2fс до конца)", len(heard_words), audio_start_time)

        # Sequence Matching — с partial rescan
        log.info("Сопоставление текста с аудио (partial rescan от слова %d, якорь=%.2fс)…", start_word_index, anchor_time)

        from aligner_orchestra import execute_sequence_matching
        canon_words = prepare_text(lyrics_text)

        # ВАЖНО: canon_words — это полный массив, включая старые тайминги
        # execute_sequence_matching с start_word_index > 0 обработает только часть
        canon_words = execute_sequence_matching(
            canon_words, heard_words, vad_intervals, full_duration, start_word_index, anchor_time
        )

        # Физический контроль (VAD-Magnet) — только для новых слов
        from aligner_acoustics import constrain_to_vad
        for idx, w in enumerate(canon_words):
            if idx >= start_word_index and w["start"] >= 0:
                w["start"], w["end"], _ = constrain_to_vad(w["start"], w["end"], vad_intervals, max_shift_sec=1.5)
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1

        # Устранение нахлёстов — только для новых слов
        from karaoke_aligner import KaraokeAligner
        temp_aligner = KaraokeAligner()
        temp_aligner._resolve_overlaps(canon_words[start_word_index:])

        # Формируем JSON
        log.info("Сохранение результатов…")

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

        log.info("Partial rescan завершён для трека %s: %d слов обработано (из %d)",
                 track_id, len(canon_words) - start_word_index, len(canon_words))

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

        log.info("GPU память сброшена после partial rescan.")
        log.info("=" * 50)

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
