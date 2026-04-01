import os
import json
import librosa
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from database import get_db, Track
from aligner_utils import clean_word
from aligner_acoustics import get_vocal_intervals
from aligner_orchestra import _elastic_vad_assembly
from app_logger import get_logger

log = get_logger("editor")
router = APIRouter()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIBRARY_DIR = os.path.join(BASE_DIR, "library")

class EditorWord(BaseModel):
    word: str
    start: float
    end: float
    line_break: bool
    is_manual_start: Optional[bool] = False
    is_manual_end: Optional[bool] = False
    is_manual_text: Optional[bool] = False

class EditPayload(BaseModel):
    words: List[EditorWord]

@router.post("/api/tracks/{track_id}/edit_lyrics")
async def apply_lyrics_edit(track_id: str, payload: EditPayload, db: Session = Depends(get_db)):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")

    if not track.karaoke_json_path or not os.path.exists(track.karaoke_json_path):
        raise HTTPException(status_code=400, detail="JSON субтитров не найден")

    log.info(f"✏️ [Editor] Применение ручных правок для трека: {track.original_name}")

    # 1. Загрузка VAD (кэш или рекалькуляция)
    base_name = os.path.splitext(track.filename)[0]
    vad_path = os.path.join(LIBRARY_DIR, f"{base_name}_(VAD).json")
    vocals_path = track.vocals_path
    
    vad_intervals = []
    audio_duration = 0.0

    if os.path.exists(vad_path):
        try:
            with open(vad_path, "r", encoding="utf-8") as f:
                vad_data = json.load(f)
                vad_intervals = vad_data.get("intervals", [])
                audio_duration = vad_data.get("duration", 0.0)
            log.info("   ✓ VAD загружен из кэша")
        except Exception as e:
            log.warning(f"   ⚠️ Ошибка чтения кэша VAD: {e}")

    if not vad_intervals and vocals_path and os.path.exists(vocals_path):
        log.info("   ⚙️ Кэш VAD не найден. Быстрое сканирование аудио...")
        try:
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            vad_intervals = get_vocal_intervals(audio_data, sr, top_db=35.0)
            if not vad_intervals:
                vad_intervals = [(0.0, audio_duration)]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка анализа аудио: {e}")

    # 2. Подготовка массива слов
    words_data = []
    for w in payload.words:
        words_data.append({
            "word": w.word,
            "clean_text": clean_word(w.word),
            "start": w.start,
            "end": w.end,
            "line_break": w.line_break,
            "is_manual_start": w.is_manual_start,
            "is_manual_end": w.is_manual_end
        })

    # 3. Хронологическая зачистка (Сбрасываем автоматические слова, которые раздавили ручными якорями)
    # Идем слева направо и сбрасываем всё, что нарушает поток времени
    valid_cursor = 0.0
    for i in range(len(words_data)):
        w = words_data[i]
        
        # Если слово автоматическое и нарушает тайминги - сбрасываем его
        if not w["is_manual_start"] and w["start"] < valid_cursor:
            w["start"] = -1.0
            
        if not w["is_manual_end"] and w["end"] <= w["start"]:
            w["end"] = -1.0
            
        if w["start"] == -1.0 or w["end"] == -1.0:
            w["start"] = -1.0
            w["end"] = -1.0
        else:
            valid_cursor = w["end"]

    # Идем справа налево, чтобы убедиться, что автоматические слова не залезают на следующие ручные
    valid_cursor = audio_duration
    for i in range(len(words_data) - 1, -1, -1):
        w = words_data[i]
        
        if w["end"] != -1.0:
            if not w["is_manual_end"] and w["end"] > valid_cursor:
                w["start"] = -1.0
                w["end"] = -1.0
            elif not w["is_manual_start"] and w["start"] > valid_cursor:
                w["start"] = -1.0
                w["end"] = -1.0
            else:
                valid_cursor = w["start"]

    # 4. Вызов эластичной сборки для заполнения дыр
    log.info("   🧲 Запуск эластичной заливки для пересчета таймингов...")
    _elastic_vad_assembly(words_data, vad_intervals, audio_duration)

    # 5. Сохранение итогового результата
    final_json = []
    for w in words_data:
        # Убираем системные флаги перед сохранением
        final_json.append({
            "word": w["word"],
            "start": round(w["start"], 3),
            "end": round(w["end"], 3),
            "line_break": w["line_break"]
        })

    try:
        with open(track.karaoke_json_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, ensure_ascii=False, indent=2)
        log.info(f"   ✅ Файл успешно обновлен: {track.karaoke_json_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e}")

    return {"status": "success", "message": "Тайминги успешно пересчитаны"}