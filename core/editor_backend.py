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
LIBRARY_DIR = os.environ.get("FK_LIBRARY_DIR") or os.path.join(BASE_DIR, "library")

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

def estimate_phonetic_duration(word: str) -> float:
    """Оценивает вокальную длительность слова на основе количества гласных."""
    vowels = "aeiouyаеёиоуыэюя"
    count = sum(1 for char in word.lower() if char in vowels)
    if count == 0: 
        count = 1
    return count * 0.25  # 250мс на слог (оптимально для пения)

@router.post("/api/tracks/{track_id}/edit_lyrics")
async def apply_lyrics_edit(track_id: str, payload: EditPayload, db: Session = Depends(get_db)):
    track = db.query(Track).filter(Track.id == track_id).first()
    if not track:
        raise HTTPException(status_code=404, detail="Трек не найден")

    # Вычисляем путь к JSON из filename если поле пустое (старые треки)
    json_path = track.karaoke_json_path
    if not json_path:
        base_name = os.path.splitext(track.filename)[0]
        json_path = os.path.join(LIBRARY_DIR, f"{base_name}_(Karaoke Lyrics).json")

    if not os.path.exists(json_path):
        log.error("JSON субтитров не найден: %s", json_path)
        raise HTTPException(status_code=400, detail="JSON субтитров не найден")

    # Обновляем поле в БД на будущее
    if not track.karaoke_json_path:
        track.karaoke_json_path = json_path
        db.commit()

    log.info(f"✏️ [Editor] Применение ручных правок для трека: {track.original_name}")

    # 1. Загрузка VAD
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

    # 3. Фонетическая коррекция полу-якорей и Хронологическая Зачистка
    valid_cursor = 0.0
    
    for i in range(len(words_data)):
        w = words_data[i]
        
        # Если юзер задал только Старт или только Конец - защищаем длительность фонетикой
        if w["is_manual_start"] and not w["is_manual_end"]:
            est = estimate_phonetic_duration(w["clean_text"])
            if w["end"] <= w["start"] + 0.15:  # Если слово сплющено
                w["end"] = w["start"] + est
                
        if w["is_manual_end"] and not w["is_manual_start"]:
            est = estimate_phonetic_duration(w["clean_text"])
            if w["start"] >= w["end"] - 0.15:
                w["start"] = max(0.0, w["end"] - est)

        # Ищем следующий ручной якорь в будущем
        next_anchor_start = audio_duration
        for j in range(i + 1, len(words_data)):
            if words_data[j]["is_manual_start"] or words_data[j]["is_manual_end"]:
                if words_data[j]["start"] != -1.0:
                    next_anchor_start = words_data[j]["start"]
                break

        if w["is_manual_start"] or w["is_manual_end"]:
            # Защита от парадоксов ручных якорей
            if w["start"] < valid_cursor and w["start"] != -1.0:
                w["start"] = valid_cursor
            
            if w["end"] > next_anchor_start:
                w["end"] = next_anchor_start - 0.05
                
            if w["end"] <= w["start"] and w["end"] != -1.0:
                w["end"] = w["start"] + 0.1
                
            valid_cursor = w["end"] if w["end"] != -1.0 else w["start"] + 0.1
        else:
            # Автоматические слова: если раздавлены - обнуляем
            if w["start"] < valid_cursor or w["end"] > next_anchor_start or w["end"] <= w["start"]:
                w["start"] = -1.0
                w["end"] = -1.0
            else:
                valid_cursor = w["end"]

    # 4. Вызов эластичной сборки
    log.info("   🧲 Запуск эластичной заливки для пересчета таймингов...")
    _elastic_vad_assembly(words_data, vad_intervals, audio_duration)

    # 5. Сохранение итогового результата
    final_json = []
    for w in words_data:
        final_json.append({
            "word": w["word"],
            "start": round(w["start"], 3),
            "end": round(w["end"], 3),
            "line_break": w["line_break"]
        })

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, ensure_ascii=False, indent=2)
        log.info(f"   ✅ Файл успешно обновлен: {json_path}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения файла: {e}")

    return {"status": "success", "message": "Тайминги успешно пересчитаны"}