import rapidfuzz
import numpy as np
from aligner_utils import (
    get_phonetic_bounds, check_sdr_sanity
)
from aligner_acoustics import snap_to_onsets
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, onsets: np.ndarray, audio_duration: float) -> list:
    """
    V10.0 Atomic & Monolithic Sequence Matching.
    Никаких прыжков во времени, полная защита структуры строк.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт V10.0 Sequence Matching (Monolithic Core)...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст. Выполняется слепая сборка.")
        _monolithic_assembly(canon_words, vad_intervals, onsets, audio_duration)
        return canon_words
        
    # V10 ОПТИМИЗАЦИЯ: Префиксные суммы для мгновенной оценки физики (O(1))
    prefix_syllables = [0] * (n_canon + 1)
    for idx in range(n_canon):
        prefix_syllables[idx + 1] = prefix_syllables[idx] + canon_words[idx]["syllables"]
        
    # 1. Формируем пул кандидатов с ЗАПРЕТОМ НА ТЕЛЕПОРТАЦИЮ (Time-Distance Penalty)
    candidates = []
    for c_idx in range(n_canon):
        for h_idx in range(n_heard):
            c_text = canon_words[c_idx]["clean_text"]
            h_text = heard_words[h_idx]["clean"]
            sim = rapidfuzz.fuzz.ratio(c_text, h_text)
            
            if sim >= 60:
                # Ожидаемое время слова = пропорция его позиции в тексте
                expected_time = (c_idx / n_canon) * audio_duration
                actual_time = heard_words[h_idx]["start"]
                
                # Штраф: -100% совпадения за смещение на всю длину песни
                time_diff_ratio = abs(expected_time - actual_time) / audio_duration
                penalty = time_diff_ratio * 100.0
                sim_adjusted = sim - penalty
                
                # Защита от привязки Куплета 1 к Куплету 2
                if sim_adjusted >= 40.0:
                    candidates.append({
                        "c_idx": c_idx,
                        "h_idx": h_idx,
                        "sim": sim_adjusted, # Используем оштрафованный вес!
                        "start": heard_words[h_idx]["start"],
                        "end": heard_words[h_idx]["end"]
                    })
                
    candidates.sort(key=lambda x: x["start"])
    
    # 2. DP Путь: ЖЕЛЕЗНАЯ МОНОТОННОСТЬ (Strict Monotonicity)
    num_cand = len(candidates)
    dp = [c["sim"] for c in candidates]
    parent = [-1] * num_cand
    
    for i in range(1, num_cand):
        best_score = dp[i]
        best_p = -1
        curr = candidates[i]
        
        for j in range(i - 1, -1, -1):
            prev = candidates[j]
            
            # Текст и Время должны идти ТОЛЬКО ВПЕРЕД!
            if curr["c_idx"] <= prev["c_idx"]: continue
            
            dur = curr["start"] - prev["end"]
            if dur < 0.05: # Меньше 50мс паузы - это нахлест (Time Travel). Отсекаем.
                continue
                
            is_same_line = False
            if curr["c_idx"] == prev["c_idx"] + 1:
                is_same_line = not canon_words[prev["c_idx"]]["line_break"]
                
            start_idx = prev["c_idx"] + 1
            end_idx = curr["c_idx"] - 1
            
            if start_idx <= end_idx:
                total_sylls = prefix_syllables[end_idx + 1] - prefix_syllables[start_idx]
            else:
                total_sylls = 0
                
            # Проверка, возможно ли физически произнести слова между якорями за это время
            is_sane = check_sdr_sanity(total_sylls, dur, is_same_line)
                
            if is_sane:
                score = dp[j] + curr["sim"]
                if score > best_score:
                    best_score = score
                    best_p = j
                    
        dp[i] = best_score
        parent[i] = best_p
        
    if not candidates:
        log.warning("   ⚠️ Нет валидных совпадений. Выполняется слепая сборка.")
        _monolithic_assembly(canon_words, vad_intervals, onsets, audio_duration)
        return canon_words
        
    max_idx = dp.index(max(dp))
    curr_idx = max_idx
    raw_sequence = []
    
    while curr_idx != -1:
        raw_sequence.append(candidates[curr_idx])
        curr_idx = parent[curr_idx]
        
    raw_sequence.reverse()
    
    # 3. V10 Cluster Filter (Убийца случайных шумов)
    clusters = []
    current_cluster = []
    for match in raw_sequence:
        if not current_cluster:
            current_cluster.append(match)
        else:
            prev_match = current_cluster[-1]
            time_diff = match["start"] - prev_match["end"]
            if time_diff <= 6.0: # Разрыв внутри кластера не больше 6 сек
                current_cluster.append(match)
            else:
                clusters.append(current_cluster)
                current_cluster = [match]
                
    if current_cluster:
        clusters.append(current_cluster)
        
    valid_sequence = []
    orphans = 0
    for cluster in clusters:
        if len(cluster) >= 3: # Кластер < 3 слов — это галлюцинация
            valid_sequence.extend(cluster)
        else:
            orphans += len(cluster)
            
    if orphans > 0:
        log.info(f"   🗑️ [Cluster Filter] Отсечено случайных якорей: {orphans}")
        
    # 4. Утверждение железобетонных Якорей + Магнит ритма
    snapped = 0
    for match in valid_sequence:
        cw = canon_words[match["c_idx"]]
        s, e = snap_to_onsets(match["start"], match["end"], onsets, max_snap_dist=0.06)
        if s != match["start"]: snapped += 1
            
        cw["start"] = s
        cw["end"] = e
        cw["is_anchor"] = True
        
    log.info(f"   🔗 Утверждено монолитных якорей: {len(valid_sequence)} (В ритм примагничено: {snapped})")
    
    # 5. V10 Monolithic Assembly (Атомарная сборка слепых зон)
    _monolithic_assembly(canon_words, vad_intervals, onsets, audio_duration)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words


def _monolithic_assembly(words: list, vad_intervals: list, onsets: np.ndarray, audio_duration: float):
    """
    V10.0 Атомарная сборка.
    Заменяет "Эластичную заливку". Не позволяет словам рваться на соло и 
    жестко упаковывает строки, сохраняя структуру.
    """
    n = len(words)
    i = 0
    zones_healed = 0
    
    while i < n:
        if not words[i]["is_anchor"]:
            j = i
            while j < n and not words[j]["is_anchor"]:
                j += 1
                
            # Границы слепой зоны
            t_start = words[i-1]["end"] + 0.05 if i > 0 else 0.5
            t_end = words[j]["start"] - 0.05 if j < n else audio_duration - 0.5
            
            if t_start >= t_end:
                t_start = max(0.0, t_end - 0.1)
                
            available_time = t_end - t_start
            gap_words = words[i:j]
            total_sylls = sum(w["syllables"] for w in gap_words)
            total_max_dur = sum(w["max_dur"] + 0.05 for w in gap_words)
            
            # АНАЛИЗ ЗОНЫ: Если места слишком много (например, 30 сек соло)
            # Мы не будем растягивать 5 слов на полминуты. Мы их компактно упакуем.
            if available_time > total_max_dur + 1.5:
                curr_t = t_start
                for k in range(i, j):
                    w = words[k]
                    
                    # Начало новой строки? Ищем безопасный остров, чтобы перепрыгнуть яму.
                    if k == i or w["line_idx"] != words[k-1]["line_idx"]:
                        island_s = curr_t
                        for vs, ve in vad_intervals:
                            if ve > curr_t and vs < t_end:
                                island_s = max(curr_t, vs)
                                break
                        # Телепортация к острову, но оставляем место для остатка слов
                        safe_end = t_end - sum(words[x]["min_dur"] + 0.05 for x in range(k, j))
                        curr_t = min(island_s, safe_end)
                        curr_t, _ = snap_to_onsets(curr_t, curr_t+0.1, onsets)
                        
                    dur = min(w["max_dur"] * 0.8, w["min_dur"] * 2.0)
                    w["start"] = curr_t
                    w["end"] = curr_t + dur
                    curr_t = w["end"] + 0.05
                    
            # АНАЛИЗ ЗОНЫ: Места мало или впритык. Распределяем пропорционально.
            else:
                curr_t = t_start
                for k in range(i, j):
                    w = words[k]
                    share = (w["syllables"] / total_sylls) * available_time
                    dur = min(max(w["min_dur"], share), w["max_dur"])
                    
                    # Последнее слово может занять остаток (если он не огромный)
                    if k == j - 1 and curr_t + dur < t_end:
                        dur = max(w["min_dur"], t_end - curr_t)
                        
                    w["start"] = curr_t
                    w["end"] = min(curr_t + dur, t_end)
                    curr_t = w["end"] + 0.05
                    
            zones_healed += 1
            i = j
        else:
            i += 1
            
    if zones_healed > 0:
        log.info(f"   🧱 [Monolithic Assembly] Упаковано слепых зон: {zones_healed}.")