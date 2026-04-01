import numpy as np
import librosa
from app_logger import get_logger

log = get_logger("aligner_acoustics")

# ==============================================================================
# V10.0 Acoustic Anti-Masking VAD (Броня от фантомов на проигрышах)
# ==============================================================================
def get_vocal_intervals(vocals_data: np.ndarray, inst_data: np.ndarray, sr: int, top_db: float = 35.0) -> list:
    """
    V10: Вычисляет VAD, используя инструментал как негативную маску.
    Убивает ложные срабатывания на барабаны и гитарные соло.
    """
    log.info("🎙️ [Acoustics] Сканирование вокала с Анти-Маскингом (V10 VAD)...")
    
    # DSP Магия: Вычитаем долю инструментала из вокала. 
    # Если звук в вокале - это протечка барабана, то в инструментале этот же удар в 10 раз громче. 
    # Вычитание мгновенно обнулит эту протечку, оставив только чистый голос.
    anti_mask_signal = np.clip(np.abs(vocals_data) - (np.abs(inst_data) * 0.3), 0.0, None)
    
    # Легкая компрессия для выделения тихих, но чистых окончаний слов
    anti_mask_signal = librosa.effects.preemphasis(anti_mask_signal)
    
    intervals_samples = librosa.effects.split(anti_mask_signal, top_db=top_db, frame_length=2048, hop_length=512)
    intervals_sec = [(s / sr, e / sr) for s, e in intervals_samples]
        
    merged_intervals = []
    for start, end in intervals_sec:
        if not merged_intervals:
            merged_intervals.append((start, end))
        else:
            last_start, last_end = merged_intervals[-1]
            # Склеиваем микро-паузы внутри фраз (до 400мс)
            if start - last_end <= 0.4:
                merged_intervals[-1] = (last_start, max(last_end, end))
            else:
                merged_intervals.append((start, end))
                
    total_vocal_time = sum(e - s for s, e in merged_intervals)
    log.info(f"   ✅ Найдено VAD-островов: {len(merged_intervals)} (Абсолютно чистый голос: {total_vocal_time:.2f}s)")
    return merged_intervals


# ==============================================================================
# V10.0 True Vocal Onsets (Магнит ритма без барабанов)
# ==============================================================================
def get_clean_onsets(vocals_data: np.ndarray, inst_data: np.ndarray, sr: int) -> np.ndarray:
    """
    V10: Извлекает пики энергии (атаки согласных), отсеивая удары барабанов.
    """
    log.info("🥁 [Acoustics] Извлечение магнитной сетки ритма (V10 Onsets)...")
    
    # Огибающие атак обоих стемов
    voc_env = librosa.onset.onset_strength(y=vocals_data, sr=sr, aggregate=np.median)
    inst_env = librosa.onset.onset_strength(y=inst_data, sr=sr, aggregate=np.median)
    
    # Вычитаем барабанные атаки из вокальных атак
    clean_env = np.clip(voc_env - (inst_env * 0.5), 0.0, None)
    
    # Ищем пики на очищенной огибающей
    onsets_frames = librosa.onset.onset_detect(onset_envelope=clean_env, sr=sr, backtrack=True)
    onsets_sec = librosa.frames_to_time(onsets_frames, sr=sr)
    
    log.info(f"   🎯 Извлечено чистых фонетических атак: {len(onsets_sec)}")
    return onsets_sec

def snap_to_onsets(start: float, end: float, onsets: np.ndarray, max_snap_dist: float = 0.06) -> tuple:
    """
    Примагничивает начало слова к ближайшей атаке, если она рядом.
    """
    if len(onsets) == 0:
        return start, end
        
    start_dist = np.abs(onsets - start)
    best_idx = np.argmin(start_dist)
    
    if start_dist[best_idx] <= max_snap_dist:
        start = float(onsets[best_idx])
        
    # Защита от схлопывания
    if start >= end:
        end = start + 0.1
        
    return start, end


# ==============================================================================
# V10.0 Жесткие фильтры
# ==============================================================================
def filter_whisper_hallucinations(heard_words: list, vad_intervals: list) -> list:
    """
    V10 БЕСПОЩАДНЫЙ ФИЛЬТР.
    Удаляет слова Whisper, если они лежат вне VAD или имеют низкую вероятность.
    Никаких компромиссов.
    """
    log.info("🧹 [VAD Filter] Старт очистки галлюцинаций транскрипции...")
    cleaned_words = []
    removed_prob = 0
    removed_vad = 0
    
    for w in heard_words:
        start = w["start"]
        end = w["end"]
        dur = end - start
        
        if dur <= 0:
            continue
            
        # 1. Порог уверенности нейросети
        prob = w.get("probability", 1.0)
        if prob < 0.45:
            removed_prob += 1
            continue
            
        # 2. Пересечение с железным VAD
        overlap = 0.0
        for vs, ve in vad_intervals:
            o_s = max(start, vs)
            o_e = min(end, ve)
            if o_e > o_s:
                overlap += (o_e - o_s)
                
        vad_ratio = overlap / dur if dur > 0 else 0
        
        # Слово должно как минимум на 15% лежать на реальном голосе
        if vad_ratio >= 0.15:
            cleaned_words.append(w)
        else:
            removed_vad += 1
            
    log.info(f"   ✨ Уничтожено фантомов: {removed_prob} (Low Prob) | {removed_vad} (Вне голоса). Выжило: {len(cleaned_words)}")
    return cleaned_words

def constrain_to_vad(start: float, end: float, vad_intervals: list, max_shift_sec: float = 0.5) -> tuple:
    """
    V10 Физический ограничитель.
    Если слово вылезло за пределы голоса, мы его обрезаем или сдвигаем.
    Возвращает (new_start, new_end, was_shifted_flag).
    """
    if not vad_intervals:
        return start, end, False

    valid_starts = []
    valid_ends = []
    
    for vs, ve in vad_intervals:
        # Ищем пересечения слова с островами VAD
        if start <= ve and end >= vs:
            valid_starts.append(max(start, vs))
            valid_ends.append(min(end, ve))
            
    if valid_starts and valid_ends:
        return min(valid_starts), max(valid_ends), True
        
    # Если слово полностью висит в тишине, ищем ближайший остров
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

    # В V10 мы не двигаем слова дальше, чем на 0.5 секунды!
    # Если остров далеко - значит это слово-инвалид, пусть останется на месте,
    # оркестратор его потом обработает.
    if abs(best_s - start) <= max_shift_sec:
        return best_s, best_e, True
        
    return start, end, False