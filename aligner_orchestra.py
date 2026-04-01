import rapidfuzz
from aligner_utils import (
    calculate_word_duration, extract_rhythm_dna, check_sdr_sanity
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float) -> list:
    """
    V8.6 Rhythm DNA & Anchor Healing.
    Извлекаем физику трека, лечим разорванные строки, собираем монолиты.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Rhythm DNA Sequence Matching...")
    
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
            
            if curr["c_idx"] <= prev["c_idx"]: continue
                
            dur = curr["start"] - prev["end"]
            if dur < -0.1: continue
                
            is_sane = False
            if curr["c_idx"] == prev["c_idx"] + 1:
                is_same_line = not canon_words[prev["c_idx"]]["line_break"]
                if is_same_line and dur > 3.0: # Повысили порог разрыва строки
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
    
    # 3. Фиксация сырых якорей
    for match in raw_sequence:
        cw = canon_words[match["c_idx"]]
        cw["start"] = match["start"]
        cw["end"] = match["end"]

    # 4. Извлечение ДНК Ритма
    dna = extract_rhythm_dna(canon_words)
    
    # 5. V8.6 Anchor Healing (Лечение разорванных строк)
    canon_words = _heal_broken_lines(canon_words, dna)

    # 6. Monolithic Block Assembly (Жесткая сборка слепых зон)
    _monolithic_block_assembly(canon_words, vad_intervals, audio_duration, dna)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words

def _heal_broken_lines(words: list, dna: dict) -> list:
    """
    V8.6: Ищет внутристрочные аномалии. Если якоря в одной строке разорваны
    физически невозможной паузой, удаляет ложный якорь.
    """
    healed_count = 0
    current_line = []
    
    for i, w in enumerate(words):
        current_line.append((i, w))
        
        if w["line_break"] or i == len(words) - 1:
            anchors = [(idx, word) for idx, word in current_line if word["start"] != -1.0]
            
            if len(anchors) >= 2:
                for k in range(len(anchors) - 1):
                    idx1, w1 = anchors[k]
                    idx2, w2 = anchors[k+1]
                    
                    gap = w2["start"] - w1["end"]
                    # Если разрыв внутри строки больше 3х секунд (аномалия, как у "Вот и всё" на 7 сек)
                    if gap > 3.0:
                        # Ищем, какой якорь "правильный" (ближе к остальному тексту)
                        # Простая эвристика: если w2 ближе к концу трека, а w1 где-то в начале один - w1 ложный
                        w1["start"] = -1.0
                        w1["end"] = -1.0
                        healed_count += 1
                        
            current_line = []
            
    if healed_count > 0:
        log.info(f"   ⚕️ [Anchor Healing] Уничтожено {healed_count} ложных внутристрочных якорей.")
        
    return words

def _monolithic_block_assembly(words: list, vad_intervals: list, audio_duration: float, dna: dict):
    """
    V8.6: Жесткая монолитная сборка.
    Прекращает размазывать текст. Строит плотные блоки по ДНК и кладет их на голос.
    """
    log.info("   🧱 [Monolithic Assembly] Сборка слепых зон по ДНК ритма...")
    
    n = len(words)
    i = 0
    blocks_built = 0
    
    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            anchor_prev_end = words[i-1]["end"] if i > 0 and words[i-1]["start"] != -1.0 else 0.0
            anchor_next_start = words[j]["start"] if j < n and words[j]["start"] != -1.0 else audio_duration
            
            # Строим "идеальный блок" в вакууме
            block_duration = 0.0
            for k in range(i, j):
                w = words[k]
                block_duration += calculate_word_duration(w["clean_text"], dna, w["line_break"])
                if w["line_break"] and k != j - 1:
                    block_duration += dna["macro_gap"]
                else:
                    block_duration += dna["micro_gap"]
                    
            # Ищем, куда положить этот блок (Ищем первый VAD)
            start_time = anchor_prev_end + dna["macro_gap"]
            
            # Сценарий 1: Интро
            if i == 0:
                start_time = anchor_next_start - block_duration - 0.05
                start_time = max(0.0, start_time)
            # Сценарий 2: Между якорями или Аутро
            else:
                for vs, ve in vad_intervals:
                    # Ищем первый VAD-остров, который влезает в дыру
                    if vs >= anchor_prev_end + 0.1 and vs < anchor_next_start - 0.5:
                        start_time = vs
                        break
            
            # Укладываем слова жестко, как кирпичи
            current_time = start_time
            for k in range(i, j):
                w = words[k]
                dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                
                # Защита от наезда на следующий якорь
                if current_time + dur > anchor_next_start:
                    current_time = max(anchor_prev_end, anchor_next_start - dur - 0.05)
                
                w["start"] = current_time
                w["end"] = current_time + dur
                
                current_time = w["end"] + dna["micro_gap"]
                if w["line_break"]:
                    current_time += dna["macro_gap"] # Вздох
                    
            blocks_built += 1
            i = j
        else:
            i += 1
            
    if blocks_built > 0:
        log.info(f"   🧱 [Monolithic Assembly] Собрано {blocks_built} монолитных блоков.")