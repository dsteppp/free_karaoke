import rapidfuzz
from aligner_utils import (
    get_phonetic_bounds, get_vowel_weight, check_sdr_sanity, calculate_line_breaks_pause
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float) -> list:
    """
    V8.5 Anchor-Centric Paradigm.
    Строгая синхронизация от якорей с учетом пауз между строками.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Anchor-Centric Sequence Matching...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст. Sequence Matching отменен.")
        return canon_words
        
    # 1. Формируем пул кандидатов (совпадения > 60%)
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
                
    candidates.sort(key=lambda x: x["start"])
    
    # 2. SDR-Guard v2: Динамическое программирование пути
    num_cand = len(candidates)
    dp = [c["sim"] for c in candidates]
    parent = [-1] * num_cand
    
    for i in range(1, num_cand):
        best_score = dp[i]
        best_p = -1
        curr = candidates[i]
        
        for j in range(i - 1, -1, -1):
            prev = candidates[j]
            
            if curr["c_idx"] <= prev["c_idx"]:
                continue
                
            dur = curr["start"] - prev["end"]
            if dur < -0.1: 
                continue
                
            is_sane = False
            
            if curr["c_idx"] == prev["c_idx"] + 1:
                is_same_line = not canon_words[prev["c_idx"]]["line_break"]
                if is_same_line and dur > 2.5:
                    is_sane = False
                else:
                    is_sane = True
            else:
                is_sane, _ = check_sdr_sanity(canon_words, prev["c_idx"] + 1, curr["c_idx"] - 1, dur, False)
                
            if is_sane:
                score = dp[j] + curr["sim"]
                if score > best_score:
                    best_score = score
                    best_p = j
                    
        dp[i] = best_score
        parent[i] = best_p
        
    if not candidates:
        log.warning("   ⚠️ Нет ни одного валидного совпадения текста.")
        return canon_words
        
    max_idx = dp.index(max(dp))
    curr_idx = max_idx
    raw_sequence = []
    
    while curr_idx != -1:
        raw_sequence.append(candidates[curr_idx])
        curr_idx = parent[curr_idx]
        
    raw_sequence.reverse()
    
    # 3. Cluster Filter (Убийца галлюцинаций)
    clusters = []
    current_cluster = []
    
    for i, match in enumerate(raw_sequence):
        if not current_cluster:
            current_cluster.append(match)
        else:
            prev_match = current_cluster[-1]
            time_diff = match["start"] - prev_match["end"]
            if time_diff <= 5.0:
                current_cluster.append(match)
            else:
                clusters.append(current_cluster)
                current_cluster = [match]
                
    if current_cluster:
        clusters.append(current_cluster)
        
    valid_sequence = []
    orphans_removed = 0
    for cluster in clusters:
        if len(cluster) >= 3:
            valid_sequence.extend(cluster)
        else:
            orphans_removed += len(cluster)
            
    if orphans_removed > 0:
        log.info(f"   🗑️ [Cluster Filter] Убито сиротских якорей (галлюцинаций): {orphans_removed}")
        
    log.info(f"   🔗 Утверждено жестких якорей: {len(valid_sequence)}")
    
    for match in valid_sequence:
        cw = canon_words[match["c_idx"]]
        cw["start"] = match["start"]
        cw["end"] = match["end"]
        
    # 4. Elastic Anchor Assembly
    _elastic_vad_assembly(canon_words, vad_intervals, audio_duration)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words

def _elastic_vad_assembly(words: list, vad_intervals: list, audio_duration: float):
    """
    ФИЛЬТР №3: Anchor-Centric Assembly (V8.5).
    Умные паузы для переноса строк и математический отсчет интро (без VAD).
    """
    log.info("   🧲 [Anchor Assembly] Старт эластичной сборки слепых зон...")
    
    n = len(words)
    i = 0
    healed_count = 0
    zones_processed = 0
    
    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            anchor_prev_end = words[i-1]["end"] if i > 0 and words[i-1]["start"] != -1.0 else 0.0
            anchor_next_start = words[j]["start"] if j < n and words[j]["start"] != -1.0 else audio_duration
            
            # СЦЕНАРИЙ 1: ИНТРО (До первого якоря)
            # V8.5: Полный отказ от VAD в интро! Математический отсчет назад.
            if i == 0:
                needed_dur = sum((get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])[0] + 
                                  get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])[1]) / 2 
                                 for k in range(i, j))
                pauses_dur = calculate_line_breaks_pause(words, i, j)
                total_needed = needed_dur + pauses_dur
                
                t_start = anchor_next_start - total_needed - 0.05
                t_start = max(0.0, t_start)
                t_end = anchor_next_start - 0.05
                
            # СЦЕНАРИЙ 2: АУТРО (После последнего якоря)
            elif j == n:
                # В аутро прыгаем на последний вокальный остров
                target_vad = None
                for vs, ve in vad_intervals:
                    if vs >= anchor_prev_end + 0.05:
                        target_vad = (vs, ve)
                        break
                
                if target_vad:
                    t_start = target_vad[0]
                    t_end = target_vad[1]
                else:
                    t_start = anchor_prev_end + 0.05
                    t_end = audio_duration
                    
            # СЦЕНАРИЙ 3: ДЫРА В СЕРЕДИНЕ (Между якорями)
            else:
                available_vads = []
                for vs, ve in vad_intervals:
                    if ve > anchor_prev_end + 0.05 and vs < anchor_next_start - 0.05:
                        o_s = max(anchor_prev_end + 0.05, vs)
                        o_e = min(anchor_next_start - 0.05, ve)
                        if o_e - o_s > 0.1:
                            available_vads.append((o_s, o_e))
                            
                if available_vads:
                    t_start = available_vads[0][0]
                    t_end = available_vads[-1][1]
                else:
                    t_start = anchor_prev_end + 0.05
                    t_end = anchor_next_start - 0.05

            if t_start >= t_end:
                t_start = max(anchor_prev_end + 0.01, t_end - 0.1)
                
            # ELASTIC PACKING С УЧЕТОМ ПАУЗ (Решение для "Непроизошло")
            weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
            total_weight = sum(weights)
            
            # Вычитаем время, необходимое на паузы между строками
            pauses_dur = calculate_line_breaks_pause(words, i, j)
            available_time_for_words = max(0.1, (t_end - t_start) - pauses_dur)
            
            current_time = t_start
            micro_gap = 0.05
            
            for k in range(i, j):
                w = words[k]
                word_share = (weights[k-i] / total_weight) * available_time_for_words
                
                min_p, max_p = get_phonetic_bounds(w["clean_text"], w["line_break"])
                actual_dur = min(max(word_share, min_p), max_p * 1.5) 
                
                w["start"] = current_time
                w["end"] = min(current_time + actual_dur, t_end)
                
                current_time = w["end"] + micro_gap
                healed_count += 1
                
                # V8.5 ВАЖНО: Если это конец строки - принудительно делаем паузу на вдох (0.4с)
                if w["line_break"]:
                    current_time += 0.4
                    
            zones_processed += 1
            i = j
        else:
            i += 1
            
    if healed_count > 0:
        log.info(f"   🧲 [Anchor Assembly] Заполнено {zones_processed} слепых зон ({healed_count} слов).")