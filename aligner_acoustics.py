import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 35.0) -> list:
    """
    Сканирует изолированный вокальный стем и возвращает точные интервалы звука.
    Использует RMS энергию.
    """
    log.info("🎙️ [Acoustics] Сканирование вокального стема (VAD Radar)...")
    
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
    log.info(f"   ✅ Найдено VAD-островов: {len(merged_intervals)} (Чистый голос: {total_vocal_time:.2f}s)")
    
    # ГЛУБОКАЯ ТЕЛЕМЕТРИЯ: Выводим карту всех островов для отладки "грязных" лайвов
    if merged_intervals:
        for idx, (s, e) in enumerate(merged_intervals):
            dur = e - s
            if dur > 15.0:
                log.warning(f"      [VAD Map] Остров {idx+1}: {s:.2f}s - {e:.2f}s (АНОМАЛЬНАЯ ДЛИНА: {dur:.2f}s - возможно шум/зал!)")
            else:
                log.debug(f"      [VAD Map] Остров {idx+1}: {s:.2f}s - {e:.2f}s (Длина: {dur:.2f}s)")
    
    return merged_intervals

def filter_whisper_hallucinations(heard_words: list, vad_intervals: list) -> list:
    """
    ФИЛЬТР №1: Анти-Галлюциноген + Защита от вздохов.
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
            log.debug(f"      🗑️ [Low Prob] Убит мусор: '{w['word']}' | Prob: {prob:.2f} < 0.40 | Тайминг: {start:.2f}s - {end:.2f}s")
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
            log.debug(f"      🗑️ [Ghost VAD] Убита галлюцинация в тишине/музыке: '{w['word']}' | Перекрытие: {vad_ratio*100:.1f}% | {start:.2f}s - {end:.2f}s")
            removed_count += 1
            
    log.info(f"   ✨ Фильтр выжег {removed_count} фантомных слов. В работу идет: {len(cleaned_words)}")
    return cleaned_words

def constrain_to_vad(start: float, end: float, vad_intervals: list, word_text: str = "word", max_shift_sec: float = 1.5) -> tuple:
    """
    V8.3 Физический ограничитель.
    Обрезает хвосты слов, висящие в абсолютной тишине.
    Если слово полностью вне VAD, мягко двигает его к границе, но НЕ ДАЛЬШЕ чем на max_shift_sec.
    """
    if not vad_intervals:
        return start, end

    valid_starts = []
    valid_ends = []
    
    # 1. Если слово пересекается с VAD, просто обрезаем края, торчащие в пустоту
    for vs, ve in vad_intervals:
        if start <= ve and end >= vs:
            valid_starts.append(max(start, vs))
            valid_ends.append(min(end, ve))
            
    if valid_starts and valid_ends:
        new_s, new_e = min(valid_starts), max(valid_ends)
        # Если обрезалось слишком сильно, логгируем
        if abs(start - new_s) > 0.3 or abs(end - new_e) > 0.3:
            log.debug(f"      ✂️ [VAD-Clip] Слово '{word_text}' подрезано по краям: [{start:.2f}s->{end:.2f}s] превратилось в [{new_s:.2f}s->{new_e:.2f}s]")
        return new_s, new_e
        
    # 2. СЛОВО ПОЛНОСТЬЮ ВНЕ VAD (Лежит в тишине)
    # Пытаемся примагнитить, но с жестким лимитом, чтобы не сломать интро/аутро!
    closest_dist = float('inf')
    best_s = start
    best_e = end
    dur = end - start
    
    for vs, ve in vad_intervals:
        # Слово до VAD-блока -> нужно толкнуть вправо
        if end < vs:
            dist = vs - end
            if dist < closest_dist:
                closest_dist = dist
                best_s = vs
                best_e = min(vs + dur, ve)
        # Слово после VAD-блока -> нужно толкнуть влево
        elif start > ve:
            dist = start - ve
            if dist < closest_dist:
                closest_dist = dist
                best_e = ve
                best_s = max(ve - dur, vs)

    # Если сдвиг в пределах нормы - двигаем. Если дальше - оставляем на месте (значит VAD просто не услышал тихий голос)
    actual_shift = abs(best_s - start)
    if actual_shift <= max_shift_sec:
        log.debug(f"      🧲 [VAD-Magnet] Слово '{word_text}' мягко притянуто к вокалу (Сдвиг: {actual_shift:.2f}s): [{start:.2f}s->{end:.2f}s] => [{best_s:.2f}s->{best_e:.2f}s]")
        return best_s, best_e
    else:
        log.warning(f"      ⚠️ [VAD-Magnet] Слово '{word_text}' слишком далеко от голоса (Дистанция: {actual_shift:.2f}s > {max_shift_sec}s). Оставлено в тишине: [{start:.2f}s->{end:.2f}s]")
        return start, end