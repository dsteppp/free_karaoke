from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
import aiofiles
import os
import json
import traceback
import gc
import torch
from datetime import datetime

from database import get_db, Track
from tasks import process_audio_task, partial_rescan_task
from huey_config import huey
from ai_pipeline import get_audio_metadata, url_to_base64
from app_status import read_status
from app_logger import get_logger
from library_io import export_library, import_library, IMPORT_LOG_PATH

# --- ВРЕЗКА РЕДАКТОРА ---
from editor_backend import router as editor_router
# ------------------------

log = get_logger("api")

app = FastAPI(title="AI-Karaoke Pro")

# --- ПОДКЛЮЧЕНИЕ РОУТЕРА РЕДАКТОРА ---
app.include_router(editor_router)
# -------------------------------------


# ── Анти-кэш прослойка ────────────────────────────────────────────────────────
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"]        = "no-cache"
    response.headers["Expires"]       = "0"
    return response


# ── Portable-режим: переменные окружения FK_* ────────────────────────────────
# Устанавливаются bootstrap-скриптами для Windows/Linux portable
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LIBRARY_DIR = os.environ.get("FK_LIBRARY_DIR") or os.path.join(BASE_DIR, "library")
STATIC_DIR  = os.path.join(BASE_DIR, "static")
CONFIG_DIR  = os.environ.get("FK_CONFIG_DIR") or BASE_DIR
CACHE_DIR   = os.environ.get("FK_CACHE_DIR") or os.path.join(BASE_DIR, "cache")
LOGS_DIR    = os.environ.get("FK_LOGS_DIR") or os.path.join(BASE_DIR, "debug_logs")
MODELS_DIR  = os.environ.get("FK_MODELS_DIR") or os.path.join(BASE_DIR, "models")

os.makedirs(LIBRARY_DIR, exist_ok=True)
os.makedirs(STATIC_DIR,  exist_ok=True)
os.makedirs(CACHE_DIR,   exist_ok=True)
os.makedirs(LOGS_DIR,    exist_ok=True)

app.mount("/static",  StaticFiles(directory=STATIC_DIR),  name="static")
app.mount("/library", StaticFiles(directory=LIBRARY_DIR), name="library")

VALID_AUDIO_EXTENSIONS = (".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac", ".alac", ".wma")

# Кэш текстов для быстрого полнотекстового поиска
LYRICS_CACHE: dict = {}


class OffsetRequest(BaseModel):
    offset: float


# ──────────────────────────────────────────────────────────────────────────────
# GET /
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/status
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/status")
async def get_status(db: Session = Depends(get_db)):
    tracks = db.query(Track).order_by(Track.original_name.asc()).all()
    track_list = []

    for t in tracks:
        lyrics_text = ""
        if t.status == "done" and t.lyrics_path and os.path.exists(t.lyrics_path):
            if t.id not in LYRICS_CACHE:
                try:
                    with open(t.lyrics_path, "r", encoding="utf-8") as f:
                        LYRICS_CACHE[t.id] = f.read()
                except Exception:
                    LYRICS_CACHE[t.id] = ""
            lyrics_text = LYRICS_CACHE[t.id]

        track_list.append({
            "id":            t.id,
            "original_name": t.original_name or t.filename,
            "filename":      t.filename,
            "status":        t.status,
            "offset":        t.offset or 0.0,
            "title":         t.title,
            "artist":        t.artist,
            "error_message": t.error_message,
            "lyrics_text":   lyrics_text,
        })

    return {"status": "ok", "tracks": track_list}


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/app-status  —  Общий статус приложения (для строки состояния)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/app-status")
async def get_app_status():
    return read_status()


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/tracks/{track_id}/offset
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/api/tracks/{track_id}/offset")
async def update_offset(
    track_id: str,
    req: OffsetRequest,
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")
    track.offset = req.offset
    db.commit()
    log.debug("Offset updated: track=%s, offset=%.3f", track_id, req.offset)
    return {"status": "success", "offset": track.offset}


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/upload
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/api/upload")
async def upload_tracks(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="Нет файлов для загрузки")

    log.info("Upload: %d файлов", len(files))
    responses = []
    for file in files:
        if not file.filename:
            continue

        safe_filename = file.filename.replace(" ", "_")
        upload_path   = os.path.join(LIBRARY_DIR, safe_filename)

        try:
            async with aiofiles.open(upload_path, "wb") as out_file:
                while chunk := await file.read(1024 * 1024):
                    await out_file.write(chunk)
        except Exception as e:
            log.error("Ошибка сохранения %s: %s", file.filename, e)
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка сохранения {file.filename}: {e}",
            )
        finally:
            await file.close()

        existing = db.query(Track).filter(
            (Track.original_name == file.filename) | (Track.filename == safe_filename)
        ).first()

        if existing:
            existing.filename      = safe_filename
            existing.original_name = file.filename
            existing.original_path = upload_path
            existing.status        = "pending"
            existing.error_message = None
            db.commit()
            db.refresh(existing)
            if existing.id in LYRICS_CACHE:
                del LYRICS_CACHE[existing.id]
            process_audio_task(existing.id)
            log.info("Re-queued: %s (id=%s)", file.filename, existing.id)
            responses.append({"filename": file.filename, "status": "re-queued"})
        else:
            new_track = Track(
                filename=safe_filename,
                original_name=file.filename,
                original_path=upload_path,
                status="pending",
            )
            db.add(new_track)
            db.commit()
            db.refresh(new_track)
            process_audio_task(new_track.id)
            log.info("Queued: %s (id=%s)", file.filename, new_track.id)
            responses.append({"filename": file.filename, "status": "queued"})

    return {"status": "ok", "details": responses}


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/upload-from-paths — загрузка по путям (нативный диалог)
# ──────────────────────────────────────────────────────────────────────────────
class UploadFromPaths(BaseModel):
    paths: List[str]


@app.post("/api/upload-from-paths")
async def upload_from_paths(req: UploadFromPaths, db: Session = Depends(get_db)):
    """Копирует файлы по абсолютным путям в library и ставит в очередь."""
    if not req.paths:
        raise HTTPException(status_code=400, detail="Нет файлов для загрузки")

    log.info("Upload from paths: %d файлов", len(req.paths))
    responses = []

    for file_path in req.paths:
        if not os.path.exists(file_path):
            log.warning("Файл не найден: %s", file_path)
            continue

        safe_filename = os.path.basename(file_path).replace(" ", "_")
        upload_path = os.path.join(LIBRARY_DIR, safe_filename)

        # Копируем файл в library
        try:
            import shutil
            shutil.copy2(file_path, upload_path)
        except Exception as e:
            log.error("Ошибка копирования %s: %s", file_path, e)
            continue

        original_name = os.path.basename(file_path)

        existing = db.query(Track).filter(
            (Track.original_name == original_name) | (Track.filename == safe_filename)
        ).first()

        if existing:
            existing.filename = safe_filename
            existing.original_name = original_name
            existing.original_path = upload_path
            existing.status = "pending"
            existing.error_message = None
            db.commit()
            db.refresh(existing)
            if existing.id in LYRICS_CACHE:
                del LYRICS_CACHE[existing.id]
            process_audio_task(existing.id)
            log.info("Re-queued: %s (id=%s)", original_name, existing.id)
            responses.append({"filename": original_name, "status": "re-queued"})
        else:
            new_track = Track(
                filename=safe_filename,
                original_name=original_name,
                original_path=upload_path,
                status="pending",
            )
            db.add(new_track)
            db.commit()
            db.refresh(new_track)
            process_audio_task(new_track.id)
            log.info("Queued: %s (id=%s)", original_name, new_track.id)
            responses.append({"filename": original_name, "status": "queued"})

    return {"status": "ok", "details": responses}


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/scan  — сканирование папки library и восстановление БД
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/api/scan")
async def scan_library(db: Session = Depends(get_db)):
    log.info("Scan library started")
    queued_count = 0
    all_files    = os.listdir(LIBRARY_DIR)
    file_groups: dict = {}

    # ── Группируем файлы по base_name ─────────────────────────────────────
    for fname in all_files:
        path = os.path.join(LIBRARY_DIR, fname)
        if not os.path.isfile(path):
            continue

        base  = None
        ftype = None

        if fname.endswith("_(Vocals).mp3"):
            base  = fname.replace("_(Vocals).mp3", "")
            ftype = "vocals"
        elif fname.endswith("_(Instrumental).mp3"):
            base  = fname.replace("_(Instrumental).mp3", "")
            ftype = "inst"
        elif fname.endswith("_(Genius Lyrics).txt"):
            base  = fname.replace("_(Genius Lyrics).txt", "")
            ftype = "lyrics"
        elif fname.endswith("_(Karaoke Lyrics).json"):
            base  = fname.replace("_(Karaoke Lyrics).json", "")
            ftype = "json"
        elif fname.endswith("_library.json"):
            base  = fname.replace("_library.json", "")
            ftype = "meta"
        else:
            matched = False
            for ext in VALID_AUDIO_EXTENSIONS:
                if fname.lower().endswith(ext):
                    base    = fname[: -(len(ext))]
                    ftype   = "orig"
                    matched = True
                    break
            if not matched:
                try:
                    os.remove(path)
                except Exception:
                    pass
                continue

        if base not in file_groups:
            file_groups[base] = {}
        file_groups[base][ftype] = path

    existing_tracks = db.query(Track).all()
    db_by_base = {os.path.splitext(t.filename)[0]: t for t in existing_tracks}
    db_by_meta = {
        f"{t.artist}_{t.title}".lower(): t
        for t in existing_tracks
        if t.artist and t.title
    }

    # ── Регистрируем новые треки из файловой системы ───────────────────────
    for base_name, files in file_groups.items():
        has_orig  = "orig"   in files
        has_stems = "vocals" in files and "inst" in files

        # Если есть и оригинал, и стемы — удаляем оригинал
        if has_stems and has_orig:
            try:
                os.remove(files["orig"])
                del files["orig"]
                has_orig = False
            except Exception:
                pass

        if not has_orig and not has_stems:
            for p in files.values():
                try:
                    os.remove(p)
                except Exception:
                    pass
            continue

        if base_name in db_by_base:
            continue

        # Трек не в БД — пробуем прочитать метаданные
        # Используем base_name как имя файла для парсинга (без суффиксов стемов)
        artist, title = "", base_name
        clean_name = f"{base_name}.mp3"
        audio_path = files.get("orig") or files.get("vocals")
        if audio_path:
            try:
                a, tt = get_audio_metadata(audio_path, clean_name)
                if a:
                    artist = a
                if tt:
                    title = tt
            except Exception:
                pass

        meta_key = f"{artist}_{title}".lower()
        if artist and title and meta_key in db_by_meta:
            # Дубликат по метаданным — удаляем файлы
            for p in files.values():
                try:
                    os.remove(p)
                except Exception:
                    pass
            continue

        orig_path  = files.get("orig")
        orig_fname = os.path.basename(orig_path) if orig_path else f"{base_name}.mp3"

        # filename всегда base_name.mp3 — это ключ для построения путей стемов
        new_track = Track(
            filename=f"{base_name}.mp3",
            original_name=orig_fname,
            original_path=orig_path,
            artist=artist or None,
            title=title  or None,
            status="pending",
        )
        db.add(new_track)
        db.commit()
        db.refresh(new_track)
        db_by_base[base_name] = new_track
        if artist and title:
            db_by_meta[meta_key] = new_track
        log.info("Scan: новый трек %s (artist=%s, title=%s)", base_name, artist, title)

    # ── Обновляем пути и статусы всех треков в БД ─────────────────────────
    all_tracks = db.query(Track).all()
    for t in all_tracks:
        base_name = os.path.splitext(t.filename)[0]

        v_path = os.path.join(LIBRARY_DIR, f"{base_name}_(Vocals).mp3")
        i_path = os.path.join(LIBRARY_DIR, f"{base_name}_(Instrumental).mp3")
        l_path = os.path.join(LIBRARY_DIR, f"{base_name}_(Genius Lyrics).txt")
        k_path = os.path.join(LIBRARY_DIR, f"{base_name}_(Karaoke Lyrics).json")
        m_path = os.path.join(LIBRARY_DIR, f"{base_name}_library.json")

        # Ищем оригинал по всем поддерживаемым расширениям
        o_path = t.original_path
        if not o_path or not os.path.exists(o_path):
            o_path = None
            for ext in VALID_AUDIO_EXTENSIONS:
                alt = os.path.join(LIBRARY_DIR, f"{base_name}{ext}")
                if os.path.exists(alt):
                    o_path = alt
                    break

        t.original_path     = o_path
        t.vocals_path       = v_path if os.path.exists(v_path) else None
        t.instrumental_path = i_path if os.path.exists(i_path) else None
        t.lyrics_path       = l_path if os.path.exists(l_path) else None
        t.karaoke_json_path = k_path if os.path.exists(k_path) else None

        needs_work = False
        can_work   = True

        if not t.vocals_path or not t.instrumental_path:
            if not t.original_path:
                can_work = False
            else:
                needs_work = True
        elif not t.lyrics_path or not t.karaoke_json_path or not os.path.exists(m_path):
            needs_work = True

        if needs_work and can_work:
            t.status        = "pending"
            t.error_message = None
            db.commit()
            if t.id in LYRICS_CACHE:
                del LYRICS_CACHE[t.id]
            process_audio_task(t.id)
            queued_count += 1
        elif not can_work:
            t.status        = "error"
            t.error_message = "Исходные файлы утеряны с диска"
            db.commit()
        else:
            if t.status != "done":
                t.status        = "done"
                t.error_message = None
                if not t.title or not t.artist:
                    try:
                        clean_name = f"{base_name}.mp3"
                        a, tt = get_audio_metadata(t.vocals_path, clean_name)
                        t.artist = a  or t.artist
                        t.title  = tt or t.title
                    except Exception:
                        pass
                db.commit()

    log.info("Scan finished: queued=%d", queued_count)

    # ── Ремонт: обновляем _library.json из БД + удаляем _meta.json ────────
    from ai_pipeline import repair_all_library_meta
    try:
        repair_all_library_meta(LIBRARY_DIR, db_path=os.path.join(BASE_DIR, "karaoke.db"))
    except Exception as e:
        log.warning("Ремонт _library.json пропущен: %s", e)

    return {"status": "ok", "queued": queued_count}


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/cancel  — остановить всю очередь
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/api/cancel")
async def cancel_processing(db: Session = Depends(get_db)):
    try:
        huey.storage.flush_queue()
        pending = db.query(Track).filter(
            ~Track.status.in_(["done", "error"])
        ).all()
        for t in pending:
            t.status        = "error"
            t.error_message = "Отменено пользователем"
        db.commit()
        log.info("Cancel: %d задач отменено", len(pending))
        return {"status": "ok", "message": "Очередь очищена."}
    except Exception as e:
        log.error("Cancel error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/tracks/{track_id}/reset_text  — пересинхронизировать текст
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/api/tracks/{track_id}/reset_text")
async def reset_track_text(track_id: str, db: Session = Depends(get_db)):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")

    # Сохраняем artist/title из БД — они НЕ должны быть перезаписаны из Genius
    saved_artist = track.artist
    saved_title = track.title

    # Удаляем JSON и lyrics — полный перескан с Genius
    for path in [track.karaoke_json_path, track.lyrics_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    if track.id in LYRICS_CACHE:
        del LYRICS_CACHE[track_id]

    track.karaoke_json_path = None
    track.lyrics_path       = None
    track.status            = "pending"
    track.error_message     = None
    # Восстанавливаем artist/title ДО запуска задачи — чтобы tasks.py их не перезаписал
    track.artist = saved_artist
    track.title = saved_title
    db.commit()

    process_audio_task(track.id)
    log.info("Reset text: track=%s (artist/title сохранены: %s — %s)", track_id, saved_artist, saved_title)
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /api/tracks/{track_id}  — удалить один трек
# ──────────────────────────────────────────────────────────────────────────────
@app.delete("/api/tracks/{track_id}")
async def delete_single_track(track_id: str, db: Session = Depends(get_db)):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")

    library_meta_path = None
    if track.filename:
        library_meta_path = os.path.join(LIBRARY_DIR, track.filename.rsplit(".", 1)[0] + "_library.json")

    # VAD файл (кэш voice activity detection)
    vad_path = None
    if track.vocals_path:
        base = os.path.splitext(track.vocals_path)[0]
        vad_path = f"{base}_(VAD).json"

    paths = [
        track.original_path,
        track.vocals_path,
        track.instrumental_path,
        track.lyrics_path,
        track.karaoke_json_path,
        library_meta_path,
        vad_path,
    ]
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    if track.id in LYRICS_CACHE:
        del LYRICS_CACHE[track.id]

    db.delete(track)
    db.commit()
    log.info("Deleted track: %s", track_id)
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /api/clear  — очистить всю библиотеку
# ──────────────────────────────────────────────────────────────────────────────
@app.delete("/api/clear")
async def clear_library(db: Session = Depends(get_db)):
    try:
        db.query(Track).delete()
        db.commit()
        LYRICS_CACHE.clear()

        for fname in os.listdir(LIBRARY_DIR):
            path = os.path.join(LIBRARY_DIR, fname)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except Exception:
                    pass

        log.info("Library cleared")
        return {"status": "ok", "message": "Библиотека очищена"}
    except Exception as e:
        db.rollback()
        log.error("Clear error: %s", e)
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/tracks/{track_id}/cover_genius — возврат оригинальной обложки Genius
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/tracks/{track_id}/cover_genius")
async def get_cover_genius(track_id: str, db: Session = Depends(get_db)):
    """Возвращает оригинальную обложку от Genius для кнопки сброса."""
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")

    if not track.karaoke_json_path:
        raise HTTPException(status_code=404, detail="Метаданные не найдены")

    lib_path = track.karaoke_json_path.replace("_(Karaoke Lyrics).json", "_library.json")
    if not os.path.exists(lib_path):
        raise HTTPException(status_code=404, detail="_library.json не найден")

    try:
        with open(lib_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        genius_url = meta.get("cover_genius") or meta.get("cover_url")
        if genius_url:
            return {"url": genius_url}
        return {"url": None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/tracks/{track_id}/edit_metadata — редактирование метаданных
# ──────────────────────────────────────────────────────────────────────────────
class EditMetadataRequest(BaseModel):
    artist: str
    title: str
    lyrics: str
    rescan: bool = False
    cover_url: Optional[str] = None
    cover_base64: Optional[str] = None
    background_url: Optional[str] = None
    background_base64: Optional[str] = None


@app.post("/api/tracks/{track_id}/edit_metadata")
async def edit_track_metadata(
    track_id: str,
    req: EditMetadataRequest,
    db: Session = Depends(get_db),
):
    """
    Редактирование метаданных трека: название, артист, текст, обложки.
    Если rescan=True — запускает Whisper-пайплайн с новым текстом.
    """
    log.info("📝 [edit_metadata] track_id=%s, artist='%s', title='%s', rescan=%s",
             track_id, req.artist, req.title, req.rescan)
    log.info("   cover_url=%s, cover_base64=%s",
             req.cover_url[:80] if req.cover_url else None,
             f"base64({len(req.cover_base64)})" if req.cover_base64 else None)
    log.info("   bg_url=%s, bg_base64=%s",
             req.background_url[:80] if req.background_url else None,
             f"base64({len(req.background_base64)})" if req.background_base64 else None)

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        log.error("   ❌ Трек не найден: %s", track_id)
        raise HTTPException(status_code=404, detail="Трек не найден")
    if track.status != "done":
        log.error("   ❌ Трек не готов: %s (status=%s)", track_id, track.status)
        raise HTTPException(status_code=400, detail="Трек не готов к редактированию")

    base_name = os.path.splitext(track.filename)[0]
    base_path = os.path.join(LIBRARY_DIR, base_name)
    lyrics_path = f"{base_path}_(Genius Lyrics).txt"
    lib_path = f"{base_path}_library.json"
    karaoke_json_path = f"{base_path}_(Karaoke Lyrics).json"

    try:
        # 1. Обновляем название и артиста в БД (файлы не переименовываем)
        track.artist = req.artist or None
        track.title = req.title or None
        db.commit()

        # 2. Сохраняем новый текст
        if req.lyrics:
            with open(lyrics_path, "w", encoding="utf-8") as f:
                f.write(req.lyrics)
            if track_id in LYRICS_CACHE:
                del LYRICS_CACHE[track_id]
            log.info("Текст обновлён для трека %s", track_id)

        # 3. Обновляем _library.json с обложками и метаданными
        meta = {}
        if os.path.exists(lib_path):
            try:
                with open(lib_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                meta = {}

        # Обновляем artist/title из запроса
        if req.artist:
            meta["artist"] = req.artist
        if req.title:
            meta["title"] = req.title

        # Обновляем текст
        if req.lyrics:
            meta["lyrics"] = req.lyrics

        # Обложка трека: скачиваем URL → base64
        if req.cover_base64:
            meta["cover"] = req.cover_base64
        elif req.cover_url:
            b64 = url_to_base64(req.cover_url)
            meta["cover"] = b64 or req.cover_url

        # Сохраняем оригинальную обложку Genius (если ещё не сохранена)
        if "cover_genius" not in meta and meta.get("cover"):
            meta["cover_genius"] = meta["cover"]

        # Фон плеера: скачиваем URL → base64
        if req.background_base64:
            meta["bg"] = req.background_base64
        elif req.background_url:
            b64 = url_to_base64(req.background_url)
            meta["bg"] = b64 or req.background_url

        # Сохраняем оригинальный фон Genius
        if "bg_genius" not in meta and meta.get("bg"):
            meta["bg_genius"] = meta["bg"]

        with open(lib_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        log.info("💾 Метаданные сохранены в %s", lib_path)

        # 4. Если rescan — запускаем Whisper-пайплайн
        if req.rescan:
            log.info("Запуск перескана таймингов для трека %s", track_id)
            from karaoke_aligner import KaraokeAligner
            from aligner_acoustics import get_vocal_intervals
            from aligner_orchestra import _elastic_vad_assembly
            import librosa
            import numpy as np

            vocals_path = f"{base_path}_(Vocals).mp3"
            instrumental_path = f"{base_path}_(Instrumental).mp3"
            vad_path = f"{base_path}_(VAD).json"
            new_karaoke_path = karaoke_json_path

            # Загружаем VAD из кэша
            vad_intervals = None
            audio_duration = None
            if os.path.exists(vad_path):
                try:
                    with open(vad_path, "r", encoding="utf-8") as f:
                        vad_data = json.load(f)
                    vad_intervals = vad_data.get("intervals", [])
                    audio_duration = vad_data.get("duration", 0)
                    log.info("VAD загружен из кэша: %d интервалов", len(vad_intervals))
                except Exception as e:
                    log.warning("Не удалось загрузить VAD из кэша: %s", e)

            # Если VAD нет в кэше — сканируем заново
            if not vad_intervals:
                log.info("VAD не найден в кэше — сканирование вокального стема…")
                audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
                audio_duration = len(audio_data) / sr
                vad_intervals = get_vocal_intervals(audio_data, sr, top_db=35.0)
                if not vad_intervals:
                    vad_intervals = [(0.0, audio_duration)]

                # Сохраняем VAD в кэш
                try:
                    with open(vad_path, "w", encoding="utf-8") as f:
                        json.dump({"duration": audio_duration, "intervals": vad_intervals}, f)
                except Exception:
                    pass

            # Запускаем Aligner с существующими стемами и новым текстом
            log.info("Запуск Aligner для перескана…")

            aligner = KaraokeAligner()

            # Загружаем аудио (если ещё не загружено при сканировании VAD)
            if 'audio_data' not in locals() or audio_data is None:
                audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
                audio_duration = len(audio_data) / sr

            from stable_whisper import load_model
            from aligner_utils import detect_language, prepare_text, clean_word
            lang = detect_language(req.lyrics)
            model = load_model("medium", download_root=aligner.whisper_model_dir, device=aligner.device)

            result = model.transcribe(
                audio_data,
                language=lang,
                word_timestamps=True,
                vad=True,
            )

            log.info("Транскрипция завершена")

            raw_heard_words = []
            for segment in result.segments:
                for w in segment.words:
                    cw = clean_word(w.word)
                    if cw:
                        raw_heard_words.append({
                            "word": w.word,
                            "clean": cw,
                            "start": w.start,
                            "end": w.end,
                            "probability": w.probability,
                        })

            from aligner_acoustics import filter_whisper_hallucinations
            heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

            # Sequence Matching
            log.info("Сопоставление текста с аудио…")

            from aligner_orchestra import execute_sequence_matching
            canon_words = prepare_text(req.lyrics)
            canon_words = execute_sequence_matching(canon_words, heard_words, vad_intervals, audio_duration)

            # Elastic Assembly
            log.info("Точное выравнивание таймингов…")

            _elastic_vad_assembly(canon_words, vad_intervals, audio_duration)

            # Физический контроль
            from aligner_acoustics import constrain_to_vad
            for w in canon_words:
                w["start"], w["end"], _ = constrain_to_vad(w["start"], w["end"], vad_intervals, max_shift_sec=1.5)
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1

            # Устранение нахлёстов
            aligner._resolve_overlaps(canon_words)

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

            with open(new_karaoke_path, "w", encoding="utf-8") as f:
                json.dump(final_json, f, ensure_ascii=False, indent=2)

            # Освобождение памяти
            if 'model' in locals() and model:
                del model
            if 'audio_data' in locals():
                del audio_data
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()

            log.info("Перескан завершён для трека %s", track_id)

        log.info("Метаданные обновлены для трека %s", track_id)
        return {"status": "ok", "rescanned": req.rescan}

    except Exception as e:
        log.error("❌ Ошибка при редактировании метаданных: %s", e)
        log.error("Traceback:\n%s", traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/tracks/{track_id}/partial_rescan — частичный перескан таймингов
# ──────────────────────────────────────────────────────────────────────────────
class PartialRescanRequest(BaseModel):
    start_word_index: int  # Индекс слова, с которого начинать рескан (0-based)
    anchor_time: float     # Точное время (секунды) ручного якоря — точка начала поиска


@app.post("/api/tracks/{track_id}/partial_rescan")
async def partial_rescan_endpoint(
    track_id: str,
    req: PartialRescanRequest,
    db: Session = Depends(get_db),
):
    """
    Частичный перескан таймингов от указанного слова до конца песни.
    Слова до start_word_index НЕ изменяются — их тайминги сохраняются как есть.
    anchor_time — точная точка начала вокала, установленная пользователем.
    Запускается через Huey очередь (асинхронно).
    """
    log.info("🔄 [partial_rescan] track_id=%s, start_word_index=%d, anchor_time=%.2f", track_id, req.start_word_index, req.anchor_time)

    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        log.error("   ❌ Трек не найден: %s", track_id)
        raise HTTPException(status_code=404, detail="Трек не найден")
    if track.status != "done":
        log.error("   ❌ Трек не готов: %s (status=%s)", track_id, track.status)
        raise HTTPException(status_code=400, detail="Трек не готов к рескану")

    if req.start_word_index < 0:
        log.error("   ❌ start_word_index=%d < 0", req.start_word_index)
        raise HTTPException(status_code=400, detail="Индекс слова не может быть отрицательным")

    if req.anchor_time < 0:
        log.error("   ❌ anchor_time=%.2f < 0", req.anchor_time)
        raise HTTPException(status_code=400, detail="Время якоря не может быть отрицательным")

    # Загружаем JSON чтобы проверить диапазон
    # Приоритет: путь из БД (импорт), fallback: LIBRARY_DIR
    karaoke_json_path = track.karaoke_json_path
    if not karaoke_json_path or not os.path.isabs(karaoke_json_path) or not os.path.exists(karaoke_json_path):
        base_name = os.path.splitext(track.filename)[0]
        karaoke_json_path = os.path.join(LIBRARY_DIR, f"{base_name}_(Karaoke Lyrics).json")

    if not os.path.exists(karaoke_json_path):
        log.error("   ❌ Караоке JSON не найден: %s", karaoke_json_path)
        raise HTTPException(status_code=404, detail="Караоке JSON не найден")

    try:
        with open(karaoke_json_path, "r", encoding="utf-8") as f:
            karaoke_data = json.load(f)
    except Exception as e:
        log.error("   ❌ Ошибка чтения JSON: %s", e)
        raise HTTPException(status_code=500, detail="Ошибка чтения караоке JSON")

    if req.start_word_index >= len(karaoke_data):
        log.error("   ❌ start_word_index=%d >= всего слов=%d", req.start_word_index, len(karaoke_data))
        raise HTTPException(status_code=400, detail="Индекс слова вне диапазона")

    # ── КРИТИЧЕСКОЕ: устанавливаем статус ДО запуска задачи ──────────────
    # Иначе polling в frontend увидит active=false и сразу закроет оверлей
    # (между постановкой задачи в очередь и её выполнением есть задержка)
    from app_status import set_status as app_set_status
    display_name_for_status = track.title or track.original_name or track.filename
    if track.artist:
        display_name_for_status = f"{track.artist} — {display_name_for_status}"
    app_set_status(f"🔄 {display_name_for_status} | Рескан таймингов от слова {req.start_word_index + 1} ({req.anchor_time:.0f}с)…", progress=None)
    log.info("   ✅ Статус установлен ДО запуска задачи — оверлей не закроется раньше времени")

    # Запускаем задачу в Huey очередь
    partial_rescan_task(track_id, req.start_word_index, req.anchor_time)

    display_name = track.title or track.original_name or track.filename
    if track.artist:
        display_name = f"{track.artist} — {display_name}"

    log.info("✅ Partial rescan запущен для трека %s (от слова %d из %d, anchor=%.2f)",
             track_id, req.start_word_index + 1, len(karaoke_data), req.anchor_time)

    return {
        "status": "ok",
        "message": f"Рескан таймингов запущен для «{display_name}» от слова {req.start_word_index + 1}",
        "start_word_index": req.start_word_index,
        "total_words": len(karaoke_data),
    }


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/library/export  — экспорт библиотеки в ZIP
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/api/library/export")
async def export_library_endpoint():
    """Экспорт всей библиотеки в ZIP-архив."""
    try:
        zip_bytes = export_library(LIBRARY_DIR)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="karaoke_library_{datetime.now().strftime("%Y%m%d_%H%M")}.zip"',
            },
        )
    except Exception as e:
        log.error("Ошибка экспорта: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/library/import  — импорт библиотеки из ZIP
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/api/library/import")
async def import_library_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Импорт библиотеки из ZIP-архива."""
    if not file.filename or not file.filename.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Требуется ZIP-файл")

    try:
        zip_bytes = await file.read()
        result = import_library(zip_bytes, LIBRARY_DIR, db, Track)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        log.error("Ошибка импорта: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/library/import-from-path  — импорт по пути к файлу (без передачи bytes через JS)
# ──────────────────────────────────────────────────────────────────────────────
class ImportFromPathRequest(BaseModel):
    path: str


@app.post("/api/library/import-from-path")
async def import_library_from_path(
    req: ImportFromPathRequest,
    db: Session = Depends(get_db),
):
    """Импорт библиотеки из ZIP по пути к файлу. Python сам читает файл."""
    if not os.path.exists(req.path):
        raise HTTPException(status_code=404, detail="Файл не найден")
    if not req.path.endswith('.zip'):
        raise HTTPException(status_code=400, detail="Требуется ZIP-файл")

    try:
        with open(req.path, 'rb') as f:
            zip_bytes = f.read()
        result = import_library(zip_bytes, LIBRARY_DIR, db, Track)
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        log.error("Ошибка импорта: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/import-log  — получить лог последнего импорта
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/import-log")
async def get_import_log():
    """Вернуть содержимое лога импорта."""
    try:
        if os.path.exists(IMPORT_LOG_PATH):
            with open(IMPORT_LOG_PATH, 'r', encoding='utf-8') as f:
                return {"log": f.read()}
        return {"log": ""}
    except Exception as e:
        return {"log": f"Ошибка чтения лога: {e}"}


# ──────────────────────────────────────────────────────────────────────────────
# Глобальный обработчик необработанных исключений
# ──────────────────────────────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_msg = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    log.error("Необработанное исключение: %s\n%s", request.url, error_msg)
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера", "error_trace": error_msg},
    )