import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 35.0) -> list:
    """
    Сканирует изолированный вокальный стем и возвращает точные интервалы звука.
    Использует RMS энергию.
    """
    log.info("🎙️ [Acoustics] Сканирование вокального стема на наличие энергии (VAD)...")
    
    # Очищаем сигнал от низкочастотного гула (DC offset и rumble)
    audio_clean = librosa.effects.preemphasis(audio_data)
    
    # Находим интервалы, где звук превышает порог
    intervals_samples = librosa.effects.split(audio_clean, top_db=top_db, frame_length=2048, hop_length=512)
    
    intervals_sec = []
    for start_s, end_s in intervals_samples:
        intervals_sec.append((start_s / sr, end_s / sr))
        
    # Склеиваем микро-паузы (меньше 0.4 секунд), так как это дыхание/смыкание губ
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
    
    if merged_intervals:
        log.debug(f"      [VAD Map] Первый блок: {merged_intervals[0][0]:.2f}s - {merged_intervals[0][1]:.2f}s")
        log.debug(f"      [VAD Map] Последний блок: {merged_intervals[-1][0]:.2f}s - {merged_intervals[-1][1]:.2f}s")
    
    return merged_intervals

def filter_whisper_hallucinations(heard_words: list, vad_intervals: list) -> list:
    """
    ФИЛЬТР №1: Анти-Галлюциноген + Защита от вздохов.
    Удаляет слова из транскрипта Whisper, если они физически попадают в тишину
    или если нейросеть в них сильно не уверена (prob < 0.40).
    """
    log.info("🧹 [VAD Filter] Старт очистки галлюцинаций Whisper...")
    cleaned_words = []
    removed_count = 0
    
    for w in heard_words:
        start = w["start"]
        end = w["end"]
        dur = end - start
        
        if dur <= 0:
            continue
            
        # 1. Проверка уверенности нейросети
        prob = w.get("probability", 1.0)
        if prob < 0.40:
            log.debug(f"      🗑️ [Low Prob] Удален мусор/вздох: '{w['word']}' | Prob: {prob:.2f} < 0.40 | {start:.2f}s-{end:.2f}s")
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
        vad_ratio = overlap / dur if dur > 0 else 0
        if vad_ratio > 0.15:
            cleaned_words.append(w)
        else:
            log.debug(f"      🗑️ [Ghost VAD] Удалена галлюцинация в тишине: '{w['word']}' | VAD-Перекрытие: {vad_ratio*100:.1f}% | {start:.2f}s-{end:.2f}s")
            removed_count += 1
            
    log.info(f"   ✨ Фильтр удалил {removed_count} фантомных слов. Осталось доверенных: {len(cleaned_words)}")
    return cleaned_words

def constrain_to_vad(start: float, end: float, vad_intervals: list, word_text: str = "word") -> tuple:
    """
    Жестко ограничивает тайминг слова рамками вокальной активности.
    Если слово висит в тишине, оно выталкивается в ближайший VAD.
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
        # Слово уже частично или полностью в VAD, просто обрезаем края, торчащие в тишину
        return min(valid_starts), max(valid_ends)
        
    # СЛОВО ВНЕ VAD: Примагничиваем его к ближайшему звуку
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

    log.debug(f"      🧲 [VAD-Magnet] Слово '{word_text}' вытолкнуто из тишины: [{start:.2f}s->{end:.2f}s] превратилось в [{best_s:.2f}s->{best_e:.2f}s]")
    return best_s, best_e