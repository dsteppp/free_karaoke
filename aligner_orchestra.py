import rapidfuzz
from aligner_utils import (
    calculate_word_duration, extract_rhythm_dna, check_sdr_sanity
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float) -> list:
    """
    V8.7: Stanza-Aware Paradigm. 
    Жесткая иерархия: Слово -> Строка -> Абзац.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Молекулярной Сборки V8.7...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст. Сборка отменена.")
        return canon_words
        
    # 1. Первичное натяжение пути (Fuzzy DP)
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
            # Базовые жесткие лимиты, чтобы Whisper не сцепил начало и конец трека
            is_same_line = (canon_words[prev["c_idx"]]["line_idx"] == canon_words[curr["c_idx"]]["line_idx"])
            is_same_stanza = (canon_words[prev["c_idx"]]["stanza_idx"] == canon_words[curr["c_idx"]]["stanza_idx"])
            
            if is_same_line and dur > 3.0:
                is_sane = False
            elif is_same_stanza and not is_same_line and dur > 6.0:
                is_sane = False
            else:
                is_sane, _ = check_sdr_sanity(canon_words, prev["c_idx"] + 1, curr["c_idx"] - 1, dur, False)
                
            if is_sane:
                score = dp[j] + curr["sim"]
                if score > best_score:
                    best_score = score; best_p = j
                    
        dp[i] = best_score
        parent[i] = best_p
        
    if not candidates:
        return canon_words
        
    curr_idx = dp.index(max(dp))
    raw_sequence = []
    while curr_idx != -1:
        raw_sequence.append(candidates[curr_idx])
        curr_idx = parent[curr_idx]
    raw_sequence.reverse()
    
    for match in raw_sequence:
        cw = canon_words[match["c_idx"]]
        cw["start"] = match["start"]
        cw["end"] = match["end"]

    # 2. Извлечение Законов Физики (ДНК Трека)
    dna = extract_rhythm_dna(canon_words)
    
    # 3. V8.7: Закон №1 - Целостность Строк (Эффект Домино)
    canon_words = _enforce_line_integrity(canon_words, dna)

    # 4. V8.7: Закон №2 - Целостность Абзацев (Молекулярная сборка)
    _molecular_stanza_assembly(canon_words, vad_intervals, audio_duration, dna)
    
    log.info("🧠 [Orchestra] Молекулярная сборка завершена.")
    log.info("=" * 50)
    return canon_words

def _enforce_line_integrity(words: list, dna: dict) -> list:
    """
    V8.7 Эффект Домино.
    Если строка разорвана галлюцинацией (как у Космоса/Доры), находит ядро строки, 
    убивает мусор и перестраивает строку монолитно.
    """
    lines = {}
    for w in words:
        lines.setdefault(w["line_idx"], []).append(w)
        
    healed_lines = 0
    
    for l_idx, line in lines.items():
        anchors = [w for w in line if w["start"] != -1.0]
        
        # 1. Поиск аномалий внутри строки
        if len(anchors) > 1:
            clusters = []
            curr_cluster = [anchors[0]]
            for i in range(1, len(anchors)):
                gap = anchors[i]["start"] - curr_cluster[-1]["end"]
                # Если разрыв больше допустимого по ДНК -> строка разорвана!
                if gap <= dna["max_intra_line_gap"]:
                    curr_cluster.append(anchors[i])
                else:
                    clusters.append(curr_cluster)
                    curr_cluster = [anchors[i]]
            clusters.append(curr_cluster)
            
            # Убиваем галлюцинации (оставляем самый длинный/надежный кластер)
            if len(clusters) > 1:
                clusters.sort(key=len, reverse=True)
                best_cluster = clusters[0]
                for c in clusters[1:]:
                    for w in c:
                        w["start"] = -1.0
                        w["end"] = -1.0
                anchors = best_cluster
                healed_lines += 1

        # 2. Эффект Домино: Восстанавливаем строку вокруг выживших якорей
        if anchors:
            first_a_idx = line.index(anchors[0])
            last_a_idx = line.index(anchors[-1])
            
            # Строим хвосты влево от первого якоря
            curr_end = anchors[0]["start"] - dna["micro_gap"]
            for i in range(first_a_idx - 1, -1, -1):
                w = line[i]
                dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                w["end"] = curr_end
                w["start"] = curr_end - dur
                curr_end = w["start"] - dna["micro_gap"]
                
            # Строим хвосты вправо от последнего якоря
            curr_start = anchors[-1]["end"] + dna["micro_gap"]
            for i in range(last_a_idx + 1, len(line)):
                w = line[i]
                dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                w["start"] = curr_start
                w["end"] = curr_start + dur
                curr_start = w["end"] + dna["micro_gap"]
                
            # Заполняем микро-дыры между якорями внутри кластера
            for i in range(len(anchors) - 1):
                w1 = anchors[i]
                w2 = anchors[i+1]
                idx1 = line.index(w1)
                idx2 = line.index(w2)
                if idx2 - idx1 > 1:
                    missing_count = idx2 - idx1 - 1
                    available = max(0.01, w2["start"] - w1["end"])
                    step = available / (missing_count + 1)
                    curr_s = w1["end"]
                    for k in range(idx1 + 1, idx2):
                        line[k]["start"] = curr_s + step * 0.1
                        dur = min(calculate_word_duration(line[k]["clean_text"], dna, line[k]["line_break"]), step * 0.9)
                        line[k]["end"] = line[k]["start"] + dur
                        curr_s += step

    if healed_lines > 0:
        log.info(f"   ⚕️ [Line Integrity] Эффект Домино: вылечено разорванных строк: {healed_lines}")
        
    return words

def _molecular_stanza_assembly(words: list, vad_intervals: list, audio_duration: float, dna: dict):
    """
    V8.7 Целостность Абзацев.
    Не дает проигрышу разорвать абзац пополам. Слепые зоны собираются блоками.
    """
    stanzas = {}
    for w in words:
        stanzas.setdefault(w["stanza_idx"], []).append(w)
        
    blocks_built = 0
    stanzas_healed = 0
    
    for s_idx, stanza in stanzas.items():
        anchored_words = [w for w in stanza if w["start"] != -1.0]
        
        # СЦЕНАРИЙ А: Абзац полностью слепой ("Непроизошло" 2:22)
        if not anchored_words:
            block_dur = 0
            for w in stanza:
                block_dur += calculate_word_duration(w["clean_text"], dna, w["line_break"])
                block_dur += dna["macro_gap"] if w["line_break"] and w != stanza[-1] else dna["micro_gap"]
                    
            prev_end = 0.0
            first_idx = words.index(stanza[0])
            if first_idx > 0:
                prev_end = words[first_idx - 1]["end"]
                
            next_start = audio_duration
            last_idx = words.index(stanza[-1])
            if last_idx < len(words) - 1:
                for n_w in words[last_idx + 1:]:
                    if n_w["start"] != -1.0:
                        next_start = n_w["start"]
                        break
                        
            # Ищем плотный вокал внутри этой большой дыры
            start_time = prev_end + dna["macro_gap"]
            for vs, ve in vad_intervals:
                if vs >= prev_end + 0.1 and ve <= next_start - 0.1 and (ve - vs) >= block_dur * 0.4:
                    start_time = vs
                    break
            
            # Ставим кирпич абзаца
            curr_time = start_time
            for w in stanza:
                w["start"] = curr_time
                dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                if curr_time + dur > next_start:
                    curr_time = max(prev_end, next_start - dur - 0.1)
                w["end"] = curr_time + dur
                curr_time = w["end"] + dna["micro_gap"]
                if w["line_break"]:
                    curr_time += dna["macro_gap"]
                    
            blocks_built += 1
            
        # СЦЕНАРИЙ Б: Часть абзаца есть, часть пропала ("Вот и всё" проигрыш)
        else:
            lines = {}
            for w in stanza:
                lines.setdefault(w["line_idx"], []).append(w)
            line_indices = sorted(list(lines.keys()))
            
            # Проход ВПЕРЕД: приклеиваем пропавшие строки к предыдущим подтвержденным
            for i in range(len(line_indices) - 1):
                curr_l = lines[line_indices[i]]
                next_l = lines[line_indices[i+1]]
                
                if curr_l[-1]["start"] != -1.0 and next_l[0]["start"] == -1.0:
                    curr_time = curr_l[-1]["end"] + dna["macro_gap"]
                    for w in next_l:
                        w["start"] = curr_time
                        dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                        w["end"] = curr_time + dur
                        curr_time = w["end"] + dna["micro_gap"]
                    stanzas_healed += 1
                        
            # Проход НАЗАД: приклеиваем пропавшие строки к следующим подтвержденным
            for i in range(len(line_indices) - 1, 0, -1):
                curr_l = lines[line_indices[i]]
                prev_l = lines[line_indices[i-1]]
                
                if curr_l[0]["start"] != -1.0 and prev_l[-1]["start"] == -1.0:
                    curr_time = curr_l[0]["start"] - dna["macro_gap"]
                    for w in reversed(prev_l):
                        dur = calculate_word_duration(w["clean_text"], dna, w["line_break"])
                        w["end"] = curr_time
                        w["start"] = curr_time - dur
                        curr_time = w["start"] - dna["micro_gap"]
                    stanzas_healed += 1

    if blocks_built > 0 or stanzas_healed > 0:
        log.info(f"   🧱 [Stanza Assembly] Собрано слепых абзацев: {blocks_built}. Приклеено потерянных строк: {stanzas_healed}")