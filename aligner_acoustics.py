import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 25.0) -> list:
    """
    V8.6: Сканирует вокальный стем. Порог top_db снижен с 35.0 до 25.0.
    Радар стал "глухим" к вдохам, эху и скрипам. Ищет только плотный вокал.
    """
    log.info("🎙️ [Acoustics] Сканирование вокального стема (VAD Radar)...")
    
    audio_clean = librosa.effects.preemphasis(audio_data)
    # Используем более грубый фильтр, чтобы отсечь мусор
    intervals_samples = librosa.effects.split(audio_clean, top_db=top_db, frame_length=2048, hop_length=512)
    
    intervals_sec = [(s / sr, e / sr) for s, e in intervals_samples]
        
    merged_intervals = []
    for start, end in intervals_sec:
        if not merged_intervals:
            merged_intervals.append((start, end))
        else:
            last_start, last_end = merged_intervals[-1]
            # Склеиваем острова, если между ними микро-пауза меньше 0.4с
            if start - last_end <= 0.4:
                merged_intervals[-1] = (last_start, end)
            else:
                merged_intervals.append((start, end))
                
    total_vocal_time = sum(e - s for s, e in merged_intervals)
    log.info(f"   ✅ Найдено плотных VAD-островов: {len(merged_intervals)} (Голос: {total_vocal_time:.2f}s)")
    return merged_intervals

def filter_whisper_hallucinations(heard_words: list, vad_intervals: list) -> list:
    """
    ФИЛЬТР №1: Удаляет мусор и галлюцинации Whisper.
    Теперь, когда VAD стал строже, этот фильтр убьет больше ложных слов.
    """
    log.info("🧹 [VAD Filter] Очистка галлюцинаций Whisper...")
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
            
    log.info(f"   ✨ Убито галлюцинаций: {removed_prob} (Low Prob), {removed_vad} (Вне VAD). Осталось: {len(cleaned_words)}")
    return cleaned_words

def constrain_to_vad(start: float, end: float, vad_intervals: list, max_shift_sec: float = 0.5) -> tuple:
    """
    V8.6 Умный Асимметричный Магнит (Ювелирная доводка).
    - Никогда не тянет слова влево (в прошлое), чтобы не красить текст на вдохах.
    - Обрезает хвосты, если они вылезли за остров (в музыку).
    - Толкает слова вправо МАКСИМУМ на 0.5с (доводка до транзиента).
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
            # V8.6: Мы запрещаем тянуть его ВЛЕВО (в прошлое). 
            pass

    # Применяем сдвиг вправо, только если он в пределах безопасного лимита (0.5с)
    if best_s != start and abs(best_s - start) <= max_shift_sec:
        return best_s, best_e, True
        
    return start, end, False