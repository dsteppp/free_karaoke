import rapidfuzz
from aligner_utils import (
    calculate_word_duration, extract_rhythm_dna, check_sdr_sanity
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float, voids: list) -> list:
    """
    V8.8: Elastic Cluster Alignment + The Void Mapping.
    Умный поиск пути с вычетом Пустот и резиновая сборка (Bungee).
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Сборки V8.8 (The Void & Bungee)...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст (или полностью сожжен). Сборка отменена.")
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
                    "c_idx": c_idx, "h_idx": h_idx, "sim": sim,
                    "start": heard_words[h_idx]["start"], "end": heard_words[h_idx]["end"]
                })
                
    candidates.sort(key=lambda x: x["start"])
    
    # 2. SDR-Guard v3: Динамическое программирование с вычетом Пустот (Effective Time)
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
                
            # V8.8: Вычисляем эффективное время для певца (вычитаем стены пустот)
            eff_dur = dur
            for vs, ve in voids:
                o_s = max(prev["end"], vs)
                o_e = min(curr["start"], ve)
                if o_e > o_s:
                    eff_dur -= (o_e - o_s)
            eff_dur = max(0.01, eff_dur)
            
            is_sane = False
            if curr["c_idx"] == prev["c_idx"] + 1:
                is_same_line = not canon_words[prev["c_idx"]]["line_break"]
                # Зазор не должен превышать 2.5с (эффективного времени!)
                if is_same_line and eff_dur > 2.5:
                    is_sane = False
                else:
                    is_sane = True
            else:
                is_sane, _ = check_sdr_sanity(canon_words, prev["c_idx"] + 1, curr["c_idx"] - 1, eff_dur, False)
                
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
    
    # 3. V8.4/8.8: Cluster Filter (Убийца галлюцинаций)
    # Группируем якоря с учетом ЭФФЕКТИВНОГО времени (игнорируя пустоты)
    clusters = []
    current_cluster = []
    
    for i, match in enumerate(raw_sequence):
        if not current_cluster:
            current_cluster.append(match)
        else:
            prev_match = current_cluster[-1]
            eff_diff = match["start"] - prev_match["end"]
            
            for vs, ve in voids:
                o_s = max(prev_match["end"], vs)
                o_e = min(match["start"], ve)
                if o_e > o_s: 
                    eff_diff -= (o_e - o_s)
            
            # Если в рамках эффективного пения они близки
            if eff_diff <= 5.0:
                current_cluster.append(match)
            else:
                clusters.append(current_cluster)
                current_cluster = [match]
                
    if current_cluster:
        clusters.append(current_cluster)
        
    # Удаляем "сиротские" кластеры (1-2 слова)
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
        
    # 4. Извлекаем ДНК трека
    dna = extract_rhythm_dna(canon_words)

    # 5. V8.8: Bungee Assembly (Резиновая Сборка слепых зон в обход Пустот)
    _bungee_interpolation(canon_words, dna, voids, audio_duration)
    
    log.info("🧠 [Orchestra] Сборка V8.8 завершена.")
    log.info("=" * 50)
    return canon_words

def _jump_voids(t: float, dur: float, voids: list) -> float:
    """Перепрыгивает Стену Пустоты вперед"""
    for v_start, v_end in voids:
        if t < v_end and (t + dur) > v_start:
            t = v_end + 0.05
    return t

def _jump_voids_backwards(t: float, dur: float, voids: list) -> float:
    """Перепрыгивает Стену Пустоты назад"""
    for v_start, v_end in reversed(voids):
        if (t - dur) < v_end and t > v_start:
            t = v_start - 0.05
    return t

def _bungee_interpolation(words: list, dna: dict, voids: list, audio_duration: float):
    """
    V8.8 Резиновая Сборка.
    Заливает слепые зоны. Прижимает слова к нужным абзацам, пружиня от Стен Пустот (VOIDs).
    """
    i = 0
    n = len(words)
    blocks_built = 0
    
    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            prev_w = words[i-1] if i > 0 else None
            next_w = words[j] if j < n else None
            
            t_prev = prev_w["end"] if prev_w else 0.0
            t_next = next_w["start"] if next_w else audio_duration
            
            left_affinity = False
            right_affinity = False
            
            # Определяем, к какому абзацу магнитить потерянный текст
            if prev_w and all(w["stanza_idx"] == prev_w["stanza_idx"] for w in words[i:j]):
                left_affinity = True
            elif next_w and all(w["stanza_idx"] == next_w["stanza_idx"] for w in words[i:j]):
                right_affinity = True
                
            # Интро всегда магнитим вправо (к началу пения)
            if i == 0:
                right_affinity = True
                left_affinity = False
                
            if right_affinity and not left_affinity:
                # Строим ЗАДОМ НАПЕРЕД от правого якоря (Стягиваем к Аутро)
                gap = dna["macro_gap"] if j > 0 and words[j-1]["line_break"] else dna["micro_gap"]
                curr_t = t_next - gap
                
                for k in range(j-1, i-1, -1):
                    w = words[k]
                    dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                    
                    curr_t = _jump_voids_backwards(curr_t, dur, voids)
                    if curr_t - dur < t_prev:
                        curr_t = t_prev + dur + 0.05
                        
                    w["end"] = curr_t
                    w["start"] = curr_t - dur
                    
                    next_gap = dna["macro_gap"] if k > 0 and words[k-1]["line_break"] else dna["micro_gap"]
                    curr_t = w["start"] - next_gap
            else:
                # Строим ВПЕРЕД от левого якоря
                gap = dna["macro_gap"] if prev_w and prev_w["line_break"] else dna["micro_gap"]
                curr_t = t_prev + gap
                
                for k in range(i, j):
                    w = words[k]
                    dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                    
                    curr_t = _jump_voids(curr_t, dur, voids)
                    if curr_t + dur > t_next:
                        curr_t = max(t_prev, t_next - dur - 0.05)
                        
                    w["start"] = curr_t
                    w["end"] = curr_t + dur
                    
                    next_gap = dna["macro_gap"] if w["line_break"] else dna["micro_gap"]
                    curr_t = w["end"] + next_gap
                    
            blocks_built += 1
            i = j
        else:
            i += 1
            
    if blocks_built > 0:
        log.info(f"   🧱 [Bungee Assembly] Резинка стянула {blocks_built} слепых зон в обход Стен Пустот.")