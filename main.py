from fastapi import FastAPI, Depends, UploadFile, File, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List
import aiofiles
import os
import traceback

from database import get_db, Track
from tasks import process_audio_task
from huey_config import huey
from ai_pipeline import get_audio_metadata
from app_logger import get_logger

log = get_logger("api")

app = FastAPI(title="AI-Karaoke Pro")


# ── Анти-кэш прослойка ────────────────────────────────────────────────────────
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"]        = "no-cache"
    response.headers["Expires"]       = "0"
    return response


BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, "library")
STATIC_DIR  = os.path.join(BASE_DIR, "static")

os.makedirs(LIBRARY_DIR, exist_ok=True)
os.makedirs(STATIC_DIR,  exist_ok=True)

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
        elif fname.endswith("_meta.json"):
            base  = fname.replace("_meta.json", "")
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
        m_path = os.path.join(LIBRARY_DIR, f"{base_name}_meta.json")

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

    for path in [track.karaoke_json_path, track.lyrics_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    if track.id in LYRICS_CACHE:
        del LYRICS_CACHE[track.id]

    track.karaoke_json_path = None
    track.lyrics_path       = None
    track.status            = "pending"
    track.error_message     = None
    db.commit()
    process_audio_task(track.id)
    log.info("Reset text: track=%s", track_id)
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# DELETE /api/tracks/{track_id}  — удалить один трек
# ──────────────────────────────────────────────────────────────────────────────
@app.delete("/api/tracks/{track_id}")
async def delete_single_track(track_id: str, db: Session = Depends(get_db)):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")

    meta_path = None
    if track.karaoke_json_path:
        meta_path = track.karaoke_json_path.replace(
            "_(Karaoke Lyrics).json", "_meta.json"
        )

    paths = [
        track.original_path,
        track.vocals_path,
        track.instrumental_path,
        track.lyrics_path,
        track.karaoke_json_path,
        meta_path,
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
