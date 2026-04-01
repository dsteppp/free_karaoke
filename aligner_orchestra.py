import rapidfuzz
from aligner_utils import (
    get_phonetic_bounds, get_vowel_weight, check_sdr_sanity, calculate_phonetic_duration
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float) -> list:
    """
    V8.3 Magnetic Island Alignment.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Magnetic Sequence Matching + SDR-Guard v2...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст. Sequence Matching отменен.")
        return canon_words
        
    # 1. Формируем пул кандидатов (все совпадения > 60%)
    candidates = []
    for c_idx in range(n_canon):
        for h_idx in range(n_heard):
            c_text = canon_words[c_idx]["clean_text"]
            h_text = heard_words[h_idx]["clean"]
            sim = rapidfuzz.fuzz.ratio(c_text, h_text)
            if sim >= 60:
                candidates.append({
                    "c_idx": c_idx,
                    "h_idx": h_idx,
                    "sim": sim,
                    "start": heard_words[h_idx]["start"],
                    "end": heard_words[h_idx]["end"]
                })
                
    # Сортируем кандидатов строго по времени
    candidates.sort(key=lambda x: x["start"])
    
    # 2. SDR-Guard v2: Поиск оптимального физического пути (Dynamic Programming)
    num_cand = len(candidates)
    dp = [c["sim"] for c in candidates]
    parent = [-1] * num_cand
    
    for i in range(1, num_cand):
        best_score = dp[i]
        best_p = -1
        curr = candidates[i]
        
        for j in range(i - 1, -1, -1):
            prev = candidates[j]
            
            # Слова не могут идти в обратном порядке в тексте
            if curr["c_idx"] <= prev["c_idx"]:
                continue
                
            dur = curr["start"] - prev["end"]
            if dur < -0.1: # Жесткий нахлест таймингов
                continue
                
            is_sane = False
            sdr = 0.0
            
            # Если это соседние слова в тексте (между ними нет пропусков)
            if curr["c_idx"] == prev["c_idx"] + 1:
                # ВАЖНО V8.3: Проверяем, находятся ли эти два слова в одной строке
                is_same_line = not canon_words[prev["c_idx"]]["line_break"]
                
                # Если они в одной строке, пауза между ними не может быть больше 2.5с (иначе это галлюцинация)
                if is_same_line and dur > 2.5:
                    is_sane = False
                    log.debug(f"         🚫 [Intro-Guard] Убит ложный путь: '{canon_words[prev['c_idx']]['word']}' -> '{canon_words[curr['c_idx']]['word']}' (Пауза {dur:.1f}s внутри одной строки)")
                else:
                    is_sane = True
            else:
                # Если между якорями есть пропущенные слова, проверяем SDR
                is_sane, sdr = check_sdr_sanity(canon_words, prev["c_idx"] + 1, curr["c_idx"] - 1, dur, False)
                
            if is_sane:
                score = dp[j] + curr["sim"]
                if score > best_score:
                    best_score = score
                    best_p = j
                    
        dp[i] = best_score
        parent[i] = best_p
        
    # 3. Восстановление идеального пути
    if not candidates:
        log.warning("   ⚠️ Нет ни одного валидного совпадения текста.")
        return canon_words
        
    max_idx = dp.index(max(dp))
    curr_idx = max_idx
    valid_sequence = []
    
    while curr_idx != -1:
        valid_sequence.append(candidates[curr_idx])
        curr_idx = parent[curr_idx]
        
    valid_sequence.reverse()
    log.info(f"   🔗 Одобрено SDR-Гвардией: {len(valid_sequence)} жестких якорей.")
    
    for match in valid_sequence:
        cw = canon_words[match["c_idx"]]
        cw["start"] = match["start"]
        cw["end"] = match["end"]
        log.debug(f"      [Anchor] '{cw['word']}' | {cw['start']:.2f}s - {cw['end']:.2f}s | Sim: {match['sim']}%")
        
    # 4. Magnetic Island Assembly (Заливка пустых зон)
    _magnetic_island_assembly(canon_words, vad_intervals, audio_duration)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words

def _magnetic_island_assembly(words: list, vad_intervals: list, audio_duration: float):
    """
    ФИЛЬТР №3: Magnetic Islands (V8.3).
    Уничтожитель раннего закрашивания. Жестко примагничивает слова к ближайшему якорю, игнорируя VAD-шумы.
    """
    log.info("   🧲 [Magnetic Assembly] Старт островной сборки слепых зон...")
    
    n = len(words)
    i = 0
    healed_count = 0
    
    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            gap_size = j - i
            needed_dur = calculate_phonetic_duration(words, i, j)
            
            # Определяем якоря вокруг дыры
            anchor_prev_end = words[i-1]["end"] if i > 0 and words[i-1]["start"] != -1.0 else 0.0
            anchor_next_start = words[j]["start"] if j < n and words[j]["start"] != -1.0 else audio_duration
            
            # Добавляем микро-паузы 30мс (0.03s) между восстанавливаемыми словами
            micro_gap = 0.03 
            total_needed_dur = needed_dur + (micro_gap * (gap_size - 1))
            
            available_time = anchor_next_start - anchor_prev_end
            
            log.debug(f"         🕳️ Дыра [{i}:{j-1}]: {gap_size} слов. Доступно: {available_time:.2f}s, Нужно: {total_needed_dur:.2f}s")
            
            # СЦЕНАРИЙ 1: RIGHT-ALIGNED PACKING (Убивает раннее закрашивание)
            # Если дыра большая (доступного времени больше чем нужно), а за ней стоит якорь - прижимаем слова ВПРАВО к якорю.
            if j < n and available_time > total_needed_dur:
                # Отсчитываем время назад от следующего якоря
                t_start = anchor_next_start - total_needed_dur - 0.05 # 50мс отступ от якоря
                # Защита от наезда на предыдущий якорь
                t_start = max(t_start, anchor_prev_end + 0.05)
                
                log.debug(f"         ⬅️ [Right-Aligned] Слова [{i}:{j-1}] прижаты влево от якоря на {t_start:.2f}s")
                
                current_time = t_start
                for k in range(i, j):
                    w = words[k]
                    min_p, max_p = get_phonetic_bounds(w["clean_text"], w["line_break"])
                    dur = (min_p + max_p) / 2
                    
                    w["start"] = current_time
                    w["end"] = w["start"] + dur
                    current_time = w["end"] + micro_gap
                    healed_count += 1
            
            # СЦЕНАРИЙ 2: VAD ISLAND HOPPING (Аутро с проигрышем)
            elif j == n and available_time > total_needed_dur:
                # В конце песни текст должен лечь только на реальный голос, перепрыгнув музыку.
                # Ищем последний вокальный остров, в который влезут эти слова
                best_vad_start = anchor_prev_end + 0.05
                best_vad_end = audio_duration
                
                # Ищем остров с конца
                for vs, ve in reversed(vad_intervals):
                    if ve > anchor_prev_end and ve - vs >= (total_needed_dur * 0.5):
                        best_vad_end = ve
                        best_vad_start = max(anchor_prev_end + 0.05, ve - total_needed_dur)
                        log.debug(f"         🏝️ [Island Hopping] Найден вокальный остров: {best_vad_start:.2f}s - {best_vad_end:.2f}s. Пропуск {best_vad_start - anchor_prev_end:.2f}s соло.")
                        break
                        
                current_time = best_vad_start
                for k in range(i, j):
                    w = words[k]
                    min_p, max_p = get_phonetic_bounds(w["clean_text"], w["line_break"])
                    dur = (min_p + max_p) / 2
                    
                    w["start"] = current_time
                    w["end"] = w["start"] + dur
                    current_time = w["end"] + micro_gap
                    healed_count += 1
            
            # СЦЕНАРИЙ 3: ТЕСНОЕ ОКНО (Слов больше, чем времени)
            else:
                # В окне мало времени (реп или быстрая читка). 
                # Равномерно сжимаем слова в доступном окне с микро-паузами.
                log.debug(f"         🗜️ [Compression] Сжатие {gap_size} слов в окно {anchor_prev_end:.2f}s - {anchor_next_start:.2f}s")
                
                t_start = anchor_prev_end + 0.05
                t_end = anchor_next_start - 0.05
                if t_start >= t_end:
                    t_start = t_end - 0.1 # Аварийное схлопывание
                    
                # Вычисляем масштаб сжатия
                scale = (t_end - t_start - (micro_gap * (gap_size - 1))) / needed_dur if needed_dur > 0 else 1.0
                scale = max(0.1, scale) # Нельзя сжимать до 0
                
                current_time = t_start
                for k in range(i, j):
                    w = words[k]
                    min_p, max_p = get_phonetic_bounds(w["clean_text"], w["line_break"])
                    dur = ((min_p + max_p) / 2) * scale
                    
                    w["start"] = current_time
                    w["end"] = w["start"] + dur
                    current_time = w["end"] + micro_gap
                    healed_count += 1
            
            i = j
        else:
            i += 1
            
    if healed_count > 0:
        log.info(f"   🧲 [Magnetic Assembly] Примагничено {healed_count} слов!")