import rapidfuzz
import numpy as np
from aligner_utils import (
    get_phonetic_bounds, get_vowel_weight, check_sdr_sanity, AnomalyInspector
)
from aligner_acoustics import snap_to_onsets
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, onsets: np.ndarray, audio_duration: float) -> list:
    """
    V9.0 Anchor-Constrained Alignment & Self-Healing.
    Использует магнитную сетку атак (Onsets) и модуль аудита.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт V9.0 Sequence Matching (Self-Healing)...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст. Sequence Matching отменен.")
        _elastic_vad_assembly(canon_words, vad_intervals, onsets, audio_duration)
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
                
            is_same_line = False
            if curr["c_idx"] == prev["c_idx"] + 1:
                is_same_line = not canon_words[prev["c_idx"]]["line_break"]
                
            is_sane, _ = check_sdr_sanity(canon_words, prev["c_idx"] + 1, curr["c_idx"] - 1, dur, is_same_line)
                
            if is_sane:
                score = dp[j] + curr["sim"]
                if score > best_score:
                    best_score = score
                    best_p = j
                    
        dp[i] = best_score
        parent[i] = best_p
        
    if not candidates:
        log.warning("   ⚠️ Нет ни одного валидного совпадения текста.")
        _elastic_vad_assembly(canon_words, vad_intervals, onsets, audio_duration)
        return canon_words
        
    max_idx = dp.index(max(dp))
    curr_idx = max_idx
    raw_sequence = []
    
    while curr_idx != -1:
        raw_sequence.append(candidates[curr_idx])
        curr_idx = parent[curr_idx]
        
    raw_sequence.reverse()
    
    # 3. V8.4 Cluster Filter (Убийца галлюцинаций в интро/аутро)
    clusters = []
    current_cluster = []
    
    for match in raw_sequence:
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
        log.info(f"   🗑️ [Cluster Filter] Убито сиротских якорей: {orphans_removed}")
        
    # 4. Утверждение Якорей + Snap to Onsets (Магнит ритма)
    snapped_anchors = 0
    for match in valid_sequence:
        cw = canon_words[match["c_idx"]]
        # Магнитим начало слова к акустической атаке (допуск 80мс)
        s, e = snap_to_onsets(match["start"], match["end"], onsets, max_snap_dist=0.08)
        if s != match["start"]:
            snapped_anchors += 1
            
        cw["start"] = s
        cw["end"] = e
        cw["locked"] = True # Железобетонный якорь
        
    log.info(f"   🔗 Утверждено жестких якорей: {len(valid_sequence)} (К ритму примагничено: {snapped_anchors})")
    
    # 5. Elastic VAD Assembly (Заливка слепых зон)
    _elastic_vad_assembly(canon_words, vad_intervals, onsets, audio_duration)
    
    # 6. V9.0 Модуль Самоисцеления (Self-Healing Loop)
    _run_healing_loop(canon_words, vad_intervals, onsets, audio_duration)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words

def _elastic_vad_assembly(words: list, vad_intervals: list, onsets: np.ndarray, audio_duration: float):
    """
    ФИЛЬТР №3: Elastic VAD Assembly (V9.0).
    Распределяет слова по слогам внутри VAD-островов с привязкой к пикам энергии.
    """
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
            
            # Собираем доступные VAD-интервалы
            available_vads = []
            for vs, ve in vad_intervals:
                if ve > anchor_prev_end + 0.05 and vs < anchor_next_start - 0.05:
                    o_s = max(anchor_prev_end + 0.05, vs)
                    o_e = min(anchor_next_start - 0.05, ve)
                    if o_e - o_s > 0.1:
                        available_vads.append((o_s, o_e))
                        
            # Сценарии позиционирования (Интро / Аутро / Центр)
            if i == 0 and available_vads:
                target_vad = available_vads[-1]
                t_start, t_end = target_vad[0], target_vad[1]
            elif j == n and available_vads:
                target_vad = available_vads[0]
                t_start, t_end = target_vad[0], target_vad[1]
            else:
                if available_vads:
                    t_start = available_vads[0][0]
                    t_end = available_vads[-1][1]
                else:
                    t_start = anchor_prev_end + 0.05
                    t_end = anchor_next_start - 0.05

            if t_start >= t_end:
                t_start = max(anchor_prev_end + 0.01, t_end - 0.1)
                
            # Распределение по слогам (Vowel Weights -> Syllable Weights V9.0)
            weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
            total_weight = sum(weights)
            total_time = t_end - t_start
            
            current_time = t_start
            micro_gap = 0.05
            
            for k in range(i, j):
                w = words[k]
                word_share = (weights[k-i] / total_weight) * total_time
                
                min_p, max_p = get_phonetic_bounds(w["clean_text"], w["line_break"])
                actual_dur = min(max(word_share, min_p), max_p * 1.5)
                
                s = current_time
                e = min(current_time + actual_dur, t_end)
                
                # V9.0: Примагничиваем восстановленные слова к ритму (если они не слишком искажаются)
                s_snap, _ = snap_to_onsets(s, e, onsets, max_snap_dist=0.06)
                if s_snap >= anchor_prev_end: 
                    s = s_snap
                
                w["start"] = s
                w["end"] = max(s + 0.1, e)
                w["locked"] = False # Восстановленные слова можно двигать при лечении
                
                current_time = w["end"] + micro_gap
                healed_count += 1
                
            zones_processed += 1
            i = j
        else:
            i += 1
            
    if healed_count > 0:
        log.info(f"   🧲 [Elastic Assembly] Заполнено {zones_processed} слепых зон ({healed_count} слов).")

def _run_healing_loop(words: list, vad_intervals: list, onsets: np.ndarray, audio_duration: float):
    """
    V9.0 Цикл самоисцеления.
    Находит аномалии и микро-пересобирает только их, опираясь на соседние Якоря.
    """
    max_loops = 2
    for loop in range(max_loops):
        anomalies = AnomalyInspector.scan(words, vad_intervals)
        if not anomalies:
            break
            
        log.info(f"   💊 [Self-Healing] Запуск цикла лечения {loop + 1} ({len(anomalies)} зон)...")
        
        for anom in anomalies:
            s_idx = anom["start_idx"]
            e_idx = anom["end_idx"]
            
            # Поиск безопасных границ
            prev_end = 0.0
            for k in range(s_idx - 1, -1, -1):
                if words[k]["locked"]:
                    prev_end = words[k]["end"]
                    break
                    
            next_start = audio_duration
            for k in range(e_idx + 1, len(words)):
                if words[k]["locked"]:
                    next_start = words[k]["start"]
                    break
                    
            # Снимаем тайминги с "больных" слов (включая не-locked соседей в промежутке)
            # Это дает алгоритму больше свободного пространства для маневра
            heal_s = s_idx
            while heal_s > 0 and not words[heal_s-1]["locked"] and words[heal_s-1]["start"] > prev_end:
                heal_s -= 1
                
            heal_e = e_idx
            while heal_e < len(words) - 1 and not words[heal_e+1]["locked"] and words[heal_e+1]["end"] < next_start:
                heal_e += 1
                
            for k in range(heal_s, heal_e + 1):
                words[k]["start"] = -1.0
                words[k]["end"] = -1.0
                words[k]["locked"] = False
                
            # Запускаем хирургическую сборку конкретно этого куска
            _elastic_vad_assembly(words, vad_intervals, onsets, audio_duration)