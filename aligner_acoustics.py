import numpy as np
import librosa
from app_logger import get_logger
from aligner_utils import get_semantic_similarity

log = get_logger("aligner_acoustics")

def get_vocal_intervals(audio_data: np.ndarray, sr: int, top_db: float = 35.0) -> list:
    """
    V8.4/V8.8: Радар плотного вокала.
    Использует надежный порог 35dB, который отсекает вдохи, эхо и тихий шум.
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

def build_void_map(heard_words: list, vad_intervals: list, canon_words: list, audio_duration: float) -> tuple:
    """
    V8.8: The Void Matrix (Комбайн Пустот).
    Суд присяжных для Whisper: группирует слова в Острова и проверяет их
    на плотность звука и семантический смысл.
    """
    log.info("🌪️ [Void Matrix] Запуск Многофакторного Комбайна Пустот...")
    
    if not heard_words:
        return [], [(0.0, audio_duration)]
        
    # Пре-фильтр: сразу сносим слова с уверенностью < 40%, чтобы они не формировали ложные Острова
    high_prob_words = [w for w in heard_words if w.get("probability", 1.0) >= 0.40]
    removed_prob = len(heard_words) - len(high_prob_words)
    
    canon_text_full = " ".join([w["clean_text"] for w in canon_words])
    
    # 1. Группируем слова во Временные Острова (зазор <= 2.5 сек)
    islands = []
    curr_island = []
    for w in high_prob_words:
        if not curr_island:
            curr_island.append(w)
        else:
            if w["start"] - curr_island[-1]["end"] <= 2.5:
                curr_island.append(w)
            else:
                islands.append(curr_island)
                curr_island = [w]
    if curr_island:
        islands.append(curr_island)
        
    surviving_islands = []
    killed_vad = 0
    killed_semantics = 0
    
    # 2. Суд Присяжных для каждого Острова
    for i, island in enumerate(islands):
        i_start = island[0]["start"]
        i_end = island[-1]["end"]
        i_dur = i_end - i_start
        i_text = " ".join([w["clean"] for w in island])
        
        # ТЕСТ 1: Дыхательный Тест (VAD Sustenance)
        # Окно поиска чуть шире самого острова (-0.5s / +0.5s), чтобы захватить хвосты
        overlap = 0.0
        for vs, ve in vad_intervals:
            o_s = max(i_start - 0.5, vs)
            o_e = min(i_end + 0.5, ve)
            if o_e > o_s:
                overlap += (o_e - o_s)
                
        # Если звука суммарно меньше 0.6 сек и он занимает малую часть времени — это шум
        if overlap < 0.6 and (overlap / max(0.1, i_dur + 1.0)) < 0.3:
            log.debug(f"   🔥 [Burn] Остров {i} убит VAD: Гитарное соло/Шум ({i_text})")
            killed_vad += len(island)
            continue
            
        # ТЕСТ 2: Семантика (Фильтр Болтовни)
        # Короткие выкрики (1-2 слова) вроде "Yeah!" пропускаем, если VAD плотный.
        # А вот длинные фразы строго сверяем с текстом Genius.
        if len(island) >= 3 or i_dur >= 1.5:
            sem_score = get_semantic_similarity(i_text, canon_text_full)
            if sem_score < 30.0:
                log.debug(f"   🔥 [Burn] Остров {i} убит Семантикой: Болтовня ({sem_score:.0f}%) -> {i_text}")
                killed_semantics += len(island)
                continue
                
        surviving_islands.append({
            "start": i_start,
            "end": i_end,
            "words": island
        })

    # 3. Формируем очищенный список слов
    cleaned_words = []
    for island in surviving_islands:
        cleaned_words.extend(island["words"])
        
    # 4. Строим Карту Абсолютных Пустот (VOIDs)
    # Пустота - это участок тишины/проигрыша между выжившими Островами, который > 4.0 секунд
    voids = []
    prev_end = 0.0
    
    for island in surviving_islands:
        gap = island["start"] - prev_end
        if gap >= 4.0:
            voids.append((prev_end, island["start"]))
        prev_end = island["end"]
        
    # Пустота от последнего слова до конца трека
    if audio_duration - prev_end >= 4.0:
        voids.append((prev_end, audio_duration))

    log.info(f"   ✅ Выжило Островов: {len(surviving_islands)} (Слова: {len(cleaned_words)})")
    log.info(f"   🔥 Сожжено слов: {removed_prob} (Low Prob), {killed_vad} (Вне VAD), {killed_semantics} (Болтовня)")
    log.info(f"   🧱 Построено Железобетонных Пустот (VOIDs): {len(voids)}")
    
    return cleaned_words, voids

def constrain_to_vad(start: float, end: float, vad_intervals: list, max_shift_sec: float = 1.5) -> tuple:
    """
    V8.4: Физический ограничитель (Soft Magnet).
    Притягивает слова к голосу, если они слегка промахнулись.
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
        return min(valid_starts), max(valid_ends), True
        
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

    if abs(best_s - start) <= max_shift_sec:
        return best_s, best_e, True
        
    return start, end, False