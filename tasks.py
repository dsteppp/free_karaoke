import os
import logging
import traceback
from huey_config import huey
from database import SessionLocal, Track
from ai_pipeline import AIPipeline
from app_logger import get_logger

log = get_logger("worker")

# Жестко фиксируем папку библиотеки, чтобы не зависеть от пустых путей в БД
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, "library")

@huey.task()
def process_audio_task(track_id: str):
    """
    Фоновая задача для обработки аудио. 
    Берется воркером Huey из очереди Redis.
    """
    log.info(f"[Huey Worker] Picked up task for track ID: {track_id}")
    
    # Открываем независимую сессию БД для фонового процесса
    db = SessionLocal()
    
    try:
        # Ищем трек в базе
        track = db.query(Track).filter(Track.id == track_id).first()
        if not track:
            log.error(f"[Huey Worker] Track {track_id} not found in DB! Aborting.")
            return

        # Обновляем статус: Пользователь видит "Обработка..."
        track.status = "processing"
        track.error_message = None
        db.commit()

        # Инициализируем наш умный пайплайн
        pipeline = AIPipeline()
        
        # Берем стабильную директорию
        output_dir = LIBRARY_DIR
        base_name = os.path.splitext(track.filename)[0]
        
        # Запускаем магию (Разделение -> Текст -> Выравнивание)
        result_paths = pipeline.run_pipeline(
            track_id=track_id,
            audio_path=track.original_path,  # Может быть None, пайплайн с этим справится
            artist=track.artist,
            title=track.title,
            output_dir=output_dir,
            base_name=base_name
        )

        # Сохраняем пути к готовым файлам в БД
        track.vocals_path = result_paths.get("vocal")
        track.instrumental_path = result_paths.get("instrumental")
        track.karaoke_json_path = result_paths.get("json")
        track.lyrics_path = result_paths.get("lyrics")
        
        # Если пайплайн сам нашел артиста и название
        if result_paths.get("artist"):
            track.artist = result_paths.get("artist")
        if result_paths.get("title"):
            track.title = result_paths.get("title")

        track.status = "done"
        
        db.commit()
        log.info(f"[Huey Worker] Track {track_id} COMPLETED successfully.")

    except Exception as e:
        error_msg = str(e)
        log.error(f"[Huey Worker] FATAL ERROR in track {track_id}: {error_msg}")
        log.error(traceback.format_exc())
        
        db.rollback()
        
        try:
            track = db.query(Track).filter(Track.id == track_id).first()
            if track:
                track.status = "error"
                track.error_message = error_msg
                db.commit()
        except Exception as db_err:
            log.error(f"[Huey Worker] Failed to write error status to DB for track {track_id}: {db_err}")
            
    finally:
        db.close()
        log.info(f"[Huey Worker] DB session closed for track {track_id}.")
