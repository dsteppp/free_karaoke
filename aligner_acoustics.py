import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 35.0) -> list:
    """
    Сканирует изолированный вокальный стем и возвращает точные интервалы звука.
    Использует RMS энергию. Сводный лог.
    """
    log.info("🎙️ [Acoustics] Сканирование вокального стема (VAD Radar)...")
    
    audio_clean = librosa.effects.preemphasis(audio_data)
    intervals_samples = librosa.effects.split(audio_clean, top_db=top_db, frame_length=2048, hop_length=512)
    
    intervals_sec = [(s / sr, e / sr) for s, e in intervals_samples]
        
    merged_intervals = []
    for start, end in intervals_sec:
        if not merged_intervals:
            merged_intervals.append((start, end))
        else:
            last_start, last_end = merged_intervals[-1]
            if start - last_end <= 0.4:
                merged_intervals[-1] = (last_start, end)
            else:
                merged_intervals.append((start, end))
                
    total_vocal_time = sum(e - s for s, e in merged_intervals)
    log.info(f"   ✅ Найдено VAD-островов: {len(merged_intervals)} (Чистый голос: {total_vocal_time:.2f}s)")
    return merged_intervals

def filter_whisper_hallucinations(heard_words: list, vad_intervals: list) -> list:
    """
    ФИЛЬТР №1: Удаляет мусор и галлюцинации Whisper.
    """
    log.info("🧹 [VAD Filter] Старт очистки галлюцинаций Whisper...")
    cleaned_words = []
    removed_prob = 0
    removed_vad = 0
    
    for w in heard_words:
        start = w["start"]
        end = w["end"]
        dur = end - start
        
        if dur <= 0:
            continue
            
        prob = w.get("probability", 1.0)
        if prob < 0.40:
            removed_prob += 1
            continue
            
        overlap = 0.0
        for vs, ve in vad_intervals:
            o_s = max(start, vs)
            o_e = min(end, ve)
            if o_e > o_s:
                overlap += (o_e - o_s)
                
        vad_ratio = overlap / dur if dur > 0 else 0
        if vad_ratio > 0.15:
            cleaned_words.append(w)
        else:
            removed_vad += 1
            
    log.info(f"   ✨ Фильтр удалил {removed_prob} слов (Low Prob) и {removed_vad} слов (Вне VAD). Осталось: {len(cleaned_words)}")
    return cleaned_words

def constrain_to_vad(start: float, end: float, vad_intervals: list, max_shift_sec: float = 1.5) -> tuple:
    """
    V8.5 Асимметричный Физический Ограничитель.
    НИКОГДА не тянет слова влево (в прошлое), чтобы не красить текст на вдохах.
    Обрезает хвосты или толкает слова вправо (в будущее) к началу вокала.
    """
    if not vad_intervals:
        return start, end, False

    valid_starts = []
    valid_ends = []
    
    # 1. Слово пересекается с VAD (Режим Ножниц)
    for vs, ve in vad_intervals:
        if start <= ve and end >= vs:
            # max(start, vs) гарантирует, что start никогда не уменьшится (не уйдет влево)
            valid_starts.append(max(start, vs))
            # min(end, ve) обрезает хвост, висящий в тишине
            valid_ends.append(min(end, ve))
            
    if valid_starts and valid_ends:
        new_s = min(valid_starts)
        new_e = max(valid_ends)
        # Защита от схлопывания слова в 0
        if new_e - new_s < 0.05:
            new_e = new_s + 0.1
            
        was_shifted = (abs(new_s - start) > 0.01 or abs(new_e - end) > 0.01)
        return new_s, new_e, was_shifted
        
    # 2. Слово полностью вне VAD (Лежит в тишине)
    closest_dist = float('inf')
    best_s = start
    best_e = end
    dur = end - start
    
    for vs, ve in vad_intervals:
        if end < vs:
            # Слово стоит ДО голоса. Толкаем его ВПРАВО (в будущее) к началу острова.
            dist = vs - end
            if dist < closest_dist:
                closest_dist = dist
                best_s = vs
                best_e = min(vs + dur, ve)
        elif start > ve:
            # Слово стоит ПОСЛЕ голоса. 
            # V8.5: Мы запрещаем тянуть его ВЛЕВО (в прошлое). 
            # Если потянем - текст закрасится раньше звука. Оставляем на месте.
            pass

    # Применяем сдвиг вправо, только если он в пределах лимита
    if best_s != start and abs(best_s - start) <= max_shift_sec:
        return best_s, best_e, True
        
    return start, end, False