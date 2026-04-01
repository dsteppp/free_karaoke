import rapidfuzz
from aligner_utils import (
    get_phonetic_bounds, get_vowel_weight, check_sdr_sanity
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float) -> list:
    """
    Neural Sequence Alignment с внедренным SDR-Guard.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Neural Sequence Matching + SDR-Guard...")
    
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
                
    # Сортируем кандидатов строго по времени (чтобы не было путешествий в прошлое)
    candidates.sort(key=lambda x: x["start"])
    
    # 2. SDR-Guard: Поиск оптимального физического пути (Dynamic Programming)
    # Наша цель - набрать максимальный score, не нарушая физику чтения.
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
                # Пауза между соседними словами не может быть больше 3 секунд
                # Иначе это ложный якорь (галлюцинация)
                is_sane = (dur <= 3.0)
            else:
                # Если между якорями есть пропущенные слова, проверяем,
                # реально ли их спеть за время dur
                is_sane, sdr = check_sdr_sanity(canon_words, prev["c_idx"] + 1, curr["c_idx"] - 1, dur)
                
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
        
    # 4. Phonetic Fluid Interpolation (Заливка пустых зон)
    _phonetic_fluid_snapping(canon_words, vad_intervals, audio_duration)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words

def _phonetic_fluid_snapping(words: list, vad_intervals: list, audio_duration: float):
    """
    ФИЛЬТР №3: Phonetic Fluid.
    Берет нераспознанные слова и буквально "вливает" их в доступные VAD-интервалы
    строго пропорционально их фонетическому весу.
    """
    log.info("   🌊 [Phonetic Fluid] Запуск фонетической заливки пустот...")
    
    n = len(words)
    i = 0
    healed_count = 0
    
    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            gap_size = j - i
            
            # Определяем временные границы дыры
            t_start = words[i-1]["end"] + 0.05 if i > 0 else 0.0
            t_end = words[j]["start"] - 0.05 if j < n else (vad_intervals[-1][1] if vad_intervals else audio_duration)
            
            # Вычисляем, сколько В РЕАЛЬНОСТИ времени нужно на произнесение этих слов
            avg_needed_dur = sum((get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])[0] + 
                                  get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])[1]) / 2 
                                 for k in range(i, j))
            
            # Собираем доступный VAD
            available_vads = []
            for vs, ve in vad_intervals:
                if ve > t_start and vs < t_end:
                    o_s = max(t_start, vs)
                    o_e = min(t_end, ve)
                    if o_e - o_s > 0.05:
                        available_vads.append((o_s, o_e))
                        
            if not available_vads:
                log.debug(f"         ⚠️ Окно [{i}:{j-1}] полностью в тишине. Оставляем Финальному Интерполятору.")
                i = j
                continue
                
            # SMART INTRO PACKING (Решение для Монеточки)
            if i == 0 and available_vads:
                log.debug(f"         ⬅️ [Smart Intro Packing] Прижимаем {gap_size} слов к первому якорю на {t_end:.2f}s")
                packed_vads = []
                accumulated = 0.0
                for vs, ve in reversed(available_vads):
                    dur = ve - vs
                    if accumulated + dur >= avg_needed_dur:
                        needed_s = ve - (avg_needed_dur - accumulated)
                        packed_vads.append((needed_s, ve))
                        break
                    else:
                        packed_vads.append((vs, ve))
                        accumulated += dur
                available_vads = list(reversed(packed_vads))
                
            # SMART OUTRO PACKING
            elif j == n and available_vads:
                log.debug(f"         ➡️ [Smart Outro Packing] Прижимаем {gap_size} слов к последнему якорю на {t_start:.2f}s")
                packed_vads = []
                accumulated = 0.0
                for vs, ve in available_vads:
                    dur = ve - vs
                    if accumulated + dur >= avg_needed_dur:
                        needed_e = vs + (avg_needed_dur - accumulated)
                        packed_vads.append((vs, needed_e))
                        break
                    else:
                        packed_vads.append((vs, ve))
                        accumulated += dur
                available_vads = packed_vads

            total_available_vad = sum(e - s for s, e in available_vads)
            if total_available_vad <= 0:
                i = j
                continue
                
            # ФИЛЬТР №4: Line Integrity (Неразрывность)
            has_line_break = any(words[k]["line_break"] for k in range(i, j - 1))
            if not has_line_break and len(available_vads) > 1:
                largest_vad = max(available_vads, key=lambda x: x[1] - x[0])
                if largest_vad[1] - largest_vad[0] >= total_available_vad * 0.4:
                    available_vads = [largest_vad]
                    total_available_vad = largest_vad[1] - largest_vad[0]
                    log.debug(f"         🔒 [Line Integrity] Фраза неразрывна. Наливаем в единый VAD.")

            # Считаем суммарный фонетический вес
            weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
            total_weight = sum(weights)
            
            current_time_in_vad = 0.0
            
            for k in range(i, j):
                w = words[k]
                word_vad_share = (weights[k-i] / total_weight) * total_available_vad
                
                min_p_dur, max_p_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
                actual_dur = min(max(word_vad_share, min_p_dur), max_p_dur)
                
                accumulated = 0.0
                placed_start, placed_end = -1.0, -1.0
                
                for vs, ve in available_vads:
                    vad_len = ve - vs
                    if current_time_in_vad < accumulated + vad_len:
                        offset = current_time_in_vad - accumulated
                        placed_start = vs + offset
                        placed_end = min(ve, placed_start + actual_dur)
                        break
                    accumulated += vad_len
                    
                if placed_start != -1.0:
                    w["start"] = placed_start
                    w["end"] = placed_end
                    healed_count += 1
                
                current_time_in_vad += word_vad_share
                
            i = j
        else:
            i += 1
            
    if healed_count > 0:
        log.info(f"   🌊 [Phonetic Fluid] Успешно залито в VAD {healed_count} слов!")