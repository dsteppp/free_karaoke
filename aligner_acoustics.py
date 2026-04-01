import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 35.0) -> list:
    """
    Сканирует изолированный вокальный стем и возвращает точные интервалы звука.
    Использует RMS энергию. Минимальный лог.
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
            # Склеиваем паузы меньше 400мс
            if start - last_end <= 0.4:
                merged_intervals[-1] = (last_start, end)
            else:
                merged_intervals.append((start, end))
                
    total_vocal_time = sum(e - s for s, e in merged_intervals)
    log.info(f"   ✅ Найдено VAD-островов: {len(merged_intervals)} (Чистый голос: {total_vocal_time:.2f}s)")
    return merged_intervals


# ==============================================================================
# V9.0 Energy Onsets (Радар атак и ритма)
# ==============================================================================

def get_vocal_onsets(audio_data: np.ndarray, sr: int) -> np.ndarray:
    """
    V9.0 Извлекает точные тайминги пиков энергии (начало слогов/согласных).
    Служит магнитной сеткой для хирургического выравнивания слов.
    """
    log.info("🥁 [Acoustics] Сканирование пиков энергии (Onsets Radar)...")
    
    # Вычисляем огибающую энергии звука
    onset_env = librosa.onset.onset_strength(y=audio_data, sr=sr, aggregate=np.median)
    
    # Ищем пики (backtrack=True сдвигает тайминг точно к началу атаки, а не к её пику)
    onsets_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, backtrack=True)
    onsets_sec = librosa.frames_to_time(onsets_frames, sr=sr)
    
    log.info(f"   🎯 Извлечено фонетических атак (якорей ритма): {len(onsets_sec)}")
    return onsets_sec

def snap_to_onsets(start: float, end: float, onsets: np.ndarray, max_snap_dist: float = 0.08) -> tuple:
    """
    V9.0 Магнитный прицел.
    Если начало слова находится рядом с акустическим всплеском (атакой), 
    оно примагничивается к нему для идеального попадания в ритм.
    """
    if len(onsets) == 0:
        return start, end
        
    # Ищем ближайший всплеск энергии к началу слова
    start_dist = np.abs(onsets - start)
    best_start_idx = np.argmin(start_dist)
    
    # Если всплеск близко (в пределах max_snap_dist), примагничиваем
    if start_dist[best_start_idx] <= max_snap_dist:
        start = float(onsets[best_start_idx])
        
    # Конец слова обычно угасающий, его не магнитим к атакам, 
    # но следим, чтобы слово не схлопнулось
    if start >= end:
        end = start + 0.1
        
    return start, end


# ==============================================================================
# Фильтры и ограничители
# ==============================================================================

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
        # Усиливаем порог вероятности для более чистых якорей
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
        
        # Слово должно хотя бы на 15% лежать на реальном звуке
        if vad_ratio > 0.15:
            cleaned_words.append(w)
        else:
            removed_vad += 1
            
    log.info(f"   ✨ Фильтр удалил {removed_prob} слов (Low Prob) и {removed_vad} слов (Вне VAD). Осталось: {len(cleaned_words)}")
    return cleaned_words

def constrain_to_vad(start: float, end: float, vad_intervals: list, max_shift_sec: float = 1.0) -> tuple:
    """
    V8.4/V9.0 Физический ограничитель.
    Обрезает хвосты слов или мягко притягивает их к голосу, если они съехали в тишину.
    Возвращает (new_start, new_end, was_shifted_flag).
    """
    if not vad_intervals:
        return start, end, False

    valid_starts = []
    valid_ends = []
    
    for vs, ve in vad_intervals:
        if start <= ve and end >= vs:
            valid_starts.append(max(start, vs))
            valid_ends.append(min(end, ve))
            
    # Слово полностью внутри звука или пересекает его
    if valid_starts and valid_ends:
        return min(valid_starts), max(valid_ends), True
        
    # Слово висит в тишине. Ищем ближайший VAD-остров.
    closest_dist = float('inf')
    best_s = start
    best_e = end
    dur = end - start
    
    for vs, ve in vad_intervals:
        if end < vs:
            dist = vs - end
            if dist < closest_dist:
                closest_dist = dist
                best_s = vs
                best_e = min(vs + dur, ve)
        elif start > ve:
            dist = start - ve
            if dist < closest_dist:
                closest_dist = dist
                best_e = ve
                best_s = max(ve - dur, vs)

    # Притягиваем только если остров не слишком далеко
    if abs(best_s - start) <= max_shift_sec:
        return best_s, best_e, True
        
    return start, end, False