import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 35.0) -> list:
    """
    Сканирует изолированный вокальный стем и возвращает точные интервалы звука.
    Использует librosa.effects.split, который базируется на RMS энергии.
    
    top_db - порог в децибелах ниже пика. Всё, что тише - считается тишиной.
    Возвращает список кортежей: [(start_sec, end_sec), ...]
    """
    log.info("🎙️ [Acoustics] Сканирование вокального стема на наличие энергии...")
    
    # Очищаем сигнал от низкочастотного гула (DC offset и rumble)
    audio_clean = librosa.effects.preemphasis(audio_data)
    
    # Находим интервалы, где звук превышает порог тишины
    intervals_samples = librosa.effects.split(audio_clean, top_db=top_db, frame_length=2048, hop_length=512)
    
    intervals_sec = []
    for start_s, end_s in intervals_samples:
        intervals_sec.append((start_s / sr, end_s / sr))
        
    # Склеиваем микро-паузы (меньше 0.3 секунд), так как это обычно дыхание или смыкание губ
    merged_intervals = []
    for start, end in intervals_sec:
        if not merged_intervals:
            merged_intervals.append((start, end))
        else:
            last_start, last_end = merged_intervals[-1]
            if start - last_end <= 0.3:
                merged_intervals[-1] = (last_start, end)
            else:
                merged_intervals.append((start, end))
                
    total_vocal_time = sum(e - s for s, e in merged_intervals)
    log.info(f"   ✅ Найдено вокальных блоков: {len(merged_intervals)} (общая длительность: {total_vocal_time:.2f}s)")
    
    return merged_intervals

def constrain_to_vad(start: float, end: float, vad_intervals: list) -> tuple:
    """
    Жестко ограничивает тайминг слова рамками вокальной активности.
    Слово физически не может существовать вне этих интервалов.
    """
    if not vad_intervals:
        return start, end

    # Ищем пересечения с вокальными интервалами
    valid_starts = []
    valid_ends = []
    
    for vs, ve in vad_intervals:
        # Если слово пересекается с интервалом
        if start <= ve and end >= vs:
            valid_starts.append(max(start, vs))
            valid_ends.append(min(end, ve))
            
    if valid_starts and valid_ends:
        # Возвращаем самую широкую рамку из доступных
        return min(valid_starts), max(valid_ends)
        
    # Если слово вообще не попало в VAD (аномалия), примагничиваем его к ближайшему звуку
    closest_dist = float('inf')
    best_s = start
    best_e = end
    
    for vs, ve in vad_intervals:
        # Слово до VAD-блока
        if end < vs:
            dist = vs - end
            if dist < closest_dist:
                closest_dist = dist
                best_s = vs
                best_e = min(vs + (end - start), ve)
        # Слово после VAD-блока
        elif start > ve:
            dist = start - ve
            if dist < closest_dist:
                closest_dist = dist
                best_e = ve
                best_s = max(ve - (end - start), vs)

    return best_s, best_e

def is_in_silence(start: float, end: float, vad_intervals: list, threshold: float = 0.8) -> bool:
    """
    Проверяет, находится ли слово по большей части в абсолютной тишине.
    threshold = 0.8 означает, что если 80% слова в тишине - это галлюцинация.
    """
    if not vad_intervals:
        return False
        
    dur = end - start
    if dur <= 0:
        return True
        
    overlap = 0.0
    for vs, ve in vad_intervals:
        o_s = max(start, vs)
        o_e = min(end, ve)
        if o_e > o_s:
            overlap += (o_e - o_s)
            
    silence_ratio = 1.0 - (overlap / dur)
    return silence_ratio >= threshold