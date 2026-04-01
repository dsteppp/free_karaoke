import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 25.0) -> list:
    """
    V8.7: Радар плотного вокала. Игнорирует тихие шумы, вдохи и протечки.
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
    log.info(f"   ✅ Найдено плотных VAD-островов: {len(merged_intervals)} (Голос: {total_vocal_time:.2f}s)")
    return merged_intervals

def check_vad_density(start_time: float, vad_intervals: list, window: float = 1.5) -> bool:
    """
    V8.7: Фильтр Плотности Голоса (VAD Density Check).
    Проверяет, является ли предложенный тайминг реальным вокалом или просто шумом в проигрыше.
    Если суммарный голос в окне (start_time ± window) меньше 0.3с -> это шум.
    """
    if not vad_intervals:
        return False
        
    look_start = start_time - window
    look_end = start_time + window
    
    total_overlap = 0.0
    for vs, ve in vad_intervals:
        o_s = max(look_start, vs)
        o_e = min(look_end, ve)
        if o_e > o_s:
            total_overlap += (o_e - o_s)
            
    # Если в радиусе 3 секунд вокруг слова нет хотя бы 300мс голоса - это фантом (гитара/синт)
    return total_overlap >= 0.3

def filter_whisper_hallucinations(heard_words: list, vad_intervals: list) -> list:
    """
    ФИЛЬТР №1: Удаляет мусор и галлюцинации Whisper.
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
            
        # V8.7: Жесткая проверка плотности. Если слово попало в проигрыш, мы его убиваем сразу.
        if not check_vad_density(start, vad_intervals, window=1.0):
            removed_vad += 1
            continue
            
        overlap = 0.0
        for vs, ve in vad_intervals:
            o_s = max(start, vs)
            o_e = min(end, ve)
            if o_e > o_s:
                overlap += (o_e - o_s)
                
        vad_ratio = overlap / dur if dur > 0 else 0
        if vad_ratio > 0.10: # Смягчили отношение, т.к. density check уже жесткий
            cleaned_words.append(w)
        else:
            removed_vad += 1
            
    log.info(f"   ✨ Убито галлюцинаций: {removed_prob} (Low Prob), {removed_vad} (Вне плотного VAD). Осталось: {len(cleaned_words)}")
    return cleaned_words

def constrain_to_vad(start: float, end: float, vad_intervals: list, max_shift_sec: float = 0.5) -> tuple:
    """
    V8.7 Умный Асимметричный Магнит.
    Никогда не тянет слова влево (в прошлое), чтобы не красить текст на вдохах.
    """
    if not vad_intervals:
        return start, end, False

    valid_starts = []
    valid_ends = []
    
    for vs, ve in vad_intervals:
        if start <= ve and end >= vs:
            valid_starts.append(max(start, vs))
            valid_ends.append(min(end, ve))
            
    if valid_starts and valid_ends:
        new_s = min(valid_starts)
        new_e = max(valid_ends)
        if new_e - new_s < 0.05:
            new_e = new_s + 0.1
        was_shifted = (abs(new_s - start) > 0.01 or abs(new_e - end) > 0.01)
        return new_s, new_e, was_shifted
        
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
            # Запрет сдвига влево
            pass

    if best_s != start and abs(best_s - start) <= max_shift_sec:
        return best_s, best_e, True
        
    return start, end, False