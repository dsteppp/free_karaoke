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
    
    # Очищаем сигнал от низкочастотного гула (DC offset и rumble) для точности
    audio_clean = librosa.effects.preemphasis(audio_data)
    
    # Находим интервалы, где звук превышает порог тишины
    intervals_samples = librosa.effects.split(audio_clean, top_db=top_db, frame_length=2048, hop_length=512)
    
    intervals_sec = []
    for start_s, end_s in intervals_samples:
        intervals_sec.append((start_s / sr, end_s / sr))
        
    # Склеиваем микро-паузы (меньше 0.4 секунд), так как это обычно дыхание или смыкание губ
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
    log.info(f"   ✅ Найдено вокальных блоков: {len(merged_intervals)} (общая длительность: {total_vocal_time:.2f}s)")
    
    return merged_intervals

def filter_whisper_hallucinations(heard_words: list, vad_intervals: list) -> list:
    """
    ФИЛЬТР №1: Анти-Галлюциноген + Защита от вздохов.
    Удаляет слова из транскрипта Whisper, если они физически попадают в тишину (гитарное соло)
    или если нейросеть в них сильно не уверена (вероятность < 40%).
    """
    log.info("🧹 [VAD Filter] Очистка галлюцинаций Whisper...")
    cleaned_words = []
    removed_count = 0
    
    for w in heard_words:
        start = w["start"]
        end = w["end"]
        dur = end - start
        
        if dur <= 0:
            continue
            
        # 1. Проверка уверенности нейросети (Probability)
        prob = w.get("probability", 1.0)
        if prob < 0.40:
            log.debug(f"      🗑️ [Low Prob] Удален мусор/вздох: '{w['word']}' (Prob: {prob:.2f})")
            removed_count += 1
            continue
            
        # 2. Проверка физического пересечения с VAD
        overlap = 0.0
        for vs, ve in vad_intervals:
            o_s = max(start, vs)
            o_e = min(end, ve)
            if o_e > o_s:
                overlap += (o_e - o_s)
                
        # Если слово хотя бы на 15% попадает в вокальный блок - оставляем
        if (overlap / dur) > 0.15:
            cleaned_words.append(w)
        else:
            log.debug(f"      🗑️ [Ghost VAD] Удалена галлюцинация в тишине: '{w['word']}' ({start:.2f}s - {end:.2f}s)")
            removed_count += 1
            
    log.info(f"   ✨ Фильтр удалил {removed_count} фантомных слов. Осталось: {len(cleaned_words)}")
    return cleaned_words

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
        if start <= ve and end >= vs:
            valid_starts.append(max(start, vs))
            valid_ends.append(min(end, ve))
            
    if valid_starts and valid_ends:
        return min(valid_starts), max(valid_ends)
        
    # Если слово вообще не попало в VAD, примагничиваем его к ближайшему звуку
    closest_dist = float('inf')
    best_s = start
    best_e = end
    dur = end - start
    
    for vs, ve in vad_intervals:
        # Слово до VAD-блока -> толкаем вправо
        if end < vs:
            dist = vs - end
            if dist < closest_dist:
                closest_dist = dist
                best_s = vs
                best_e = min(vs + dur, ve)
        # Слово после VAD-блока -> толкаем влево
        elif start > ve:
            dist = start - ve
            if dist < closest_dist:
                closest_dist = dist
                best_e = ve
                best_s = max(ve - dur, vs)

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