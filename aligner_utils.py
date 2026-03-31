import re
import random
import rapidfuzz
import numpy as np

# ─── ЛИНГВИСТИКА И ПОДГОТОВКА ТЕКСТА (V5.2: MACRO-MAPPING) ───────────────────

def detect_language(text: str) -> str:
    """Определяет язык текста (ru, ko, en) по количеству символов."""
    cyrillic = len(re.findall(r'[\u0400-\u04FFёЁ]', text))
    hangul = len(re.findall(r'[\uac00-\ud7a3]', text))
    latin = len(re.findall(r'[a-zA-Z]', text))
    
    if hangul > 10: return "ko" 
    if cyrillic > latin * 0.3: return "ru" 
    return "en"     

def prepare_text(text: str) -> list:
    """
    V5.2: Очищает текст и размечает Макро-Структуру:
    - line_num: Привязка к строке.
    - stanza_num: Привязка к строфе (куплет/припев).
    - homologous_id: Привязка к фонетически подобным строкам (для эмпирических якорей).
    """
    text = re.sub(r'[\x5B\x28].*?[\x5D\x29]', '', text)
    text = re.sub(r'([a-zA-Z\u0400-\u04FFёЁ])([\x2D\u2013\u2014]+)([a-zA-Z\u0400-\u04FFёЁ])', r'\1\2 \3', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # Нормализуем блоки (строфы) по двойному переносу
    text = re.sub(r'\n{3,}', '\n\n', text)

    words_list = []
    stanzas = text.split('\n\n')
    
    line_global_idx = 0
    lines_text_map = {}
    
    for stanza_num, stanza in enumerate(stanzas):
        for raw_line in stanza.splitlines():
            line = raw_line.strip()
            if not line: continue
                
            tokens = line.split()
            line_clean_words = []
            
            for idx, token in enumerate(tokens):
                has_punct = bool(re.search(r'[\x2C\x2E\x3A\x3B\x3F\x21\x2D]$', token))
                is_last_in_line = (idx == len(tokens) - 1)
                clean = re.sub(r'[^\w]', '', token.lower())
                if clean:
                    line_clean_words.append(clean)
                    words_list.append({
                        "word": token,
                        "clean_text": clean,
                        "has_punct": has_punct,
                        "line_break": is_last_in_line,
                        "line_num": line_global_idx,
                        "stanza_num": stanza_num,
                        "homologous_id": -1, # Заполнится ниже
                        "start": -1.0,
                        "end": -1.0,
                        "dtw_tried": False
                    })
                    
            if line_clean_words:
                line_str = " ".join(line_clean_words)
                vowels = sum(1 for c in line_str if c in "аеёиоуыэюяaeiouy")
                lines_text_map[line_global_idx] = {"text": line_str, "vowels": max(1, vowels)}
                line_global_idx += 1

    # Homologous Lines Detection (Поиск подобных строк для базы эталонов)
    homologous_groups = []
    for l_idx, l_data in lines_text_map.items():
        placed = False
        for group in homologous_groups:
            rep_idx = group[0]
            rep_data = lines_text_map[rep_idx]
            
            # Совпадение по вокальной массе (+- 2 слога) и тексту (>80%)
            if abs(l_data["vowels"] - rep_data["vowels"]) <= 2:
                score = rapidfuzz.fuzz.ratio(l_data["text"], rep_data["text"])
                if score > 80:
                    group.append(l_idx)
                    placed = True
                    break
        if not placed:
            homologous_groups.append([l_idx])
            
    l_to_h = {}
    for h_id, group in enumerate(homologous_groups):
        for l_idx in group:
            l_to_h[l_idx] = h_id
            
    for w in words_list:
        w["homologous_id"] = l_to_h[w["line_num"]]

    return words_list

def is_repetition_island(words: list, s_idx: int, e_idx: int) -> bool:
    """Адаптивный сканер Острова Повторов."""
    length = e_idx - s_idx + 1
    if length < 5: return False
    
    text_chunk = [words[i]["clean_text"] for i in range(s_idx, e_idx + 1) if words[i]["clean_text"]]
    if not text_chunk: return False
    
    unique_words = set(text_chunk)
    ratio = len(unique_words) / len(text_chunk)
    max_repeats = max(text_chunk.count(w) for w in unique_words)
    
    return ratio <= 0.40 or (max_repeats >= 3 and ratio < 0.60)

# ─── ФОНЕТИЧЕСКАЯ МАТЕМАТИКА И ЭМПИРИКА (V5.2) ──────────────────────────────

def get_vowel_weight(word: str, is_line_end: bool) -> float:
    """Вычисляет фонетический вес слова (абстрактный)."""
    vowels = set("аеёиоуыэюяaeiouy")
    clean = word.lower()
    v_count = sum(1 for c in clean if c in vowels)
    c_count = len(clean) - v_count
    
    weight = float(max(1, v_count))
    if c_count >= 3: weight += 0.5 * (c_count / 3.0)  
    if is_line_end: weight *= 2.0 
    return weight

def get_phonetic_bounds(clean_text: str, is_line_end: bool) -> tuple:
    """Абстрактные границы слова (Fallback, если эмпирика недоступна)."""
    vowels = sum(1 for c in clean_text if c in "аеёиоуыэюяaeiouy")
    consonants = len(clean_text) - vowels
    
    min_dur = max(0.05, (vowels * 0.06) + (consonants * 0.04))
    max_dur = max(0.5, (vowels * 0.8) + (consonants * 0.20))
    if is_line_end: max_dur *= 2.0
    return min_dur, max_dur

def get_line_phonetic_bounds(words: list, s_idx: int, e_idx: int) -> tuple:
    """Абстрактная Фонетическая Масса отрезка."""
    total_min, total_max = 0.0, 0.0
    for i in range(s_idx, e_idx + 1):
        min_d, max_d = get_phonetic_bounds(words[i]["clean_text"], words[i]["line_break"])
        total_min += min_d
        total_max += max_d
    return total_min, total_max

def calculate_sdr(words: list, s_idx: int, e_idx: int, t_start: float, t_end: float) -> float:
    """
    V5.2: Считает Syllable Delivery Rate (Темп слогов/сек) для отрезка.
    Используется для обнаружения ложного растяжения (Монеточка).
    """
    dur = t_end - t_start
    if dur <= 0: return 0.0
    vowels = sum(1 for k in range(s_idx, e_idx + 1) for c in words[k]["clean_text"] if c in "аеёиоуыэюяaeiouy")
    return max(1, vowels) / dur

def get_empirical_data(words: list) -> dict:
    """
    V5.2 (ЯДРО СТРУКТУРАЛИЗМА): Изучает ЗДОРОВУЮ часть песни и создает эталон.
    Возвращает:
    - global_sdr: Средний темп по всему треку.
    - stanza_sdr: Темп для каждого куплета/припева отдельно.
    - homo_durations: Физическая длина (сек) для конкретных повторяющихся строк.
    - avg_breath_gap: Естественная пауза певца на вдох между строками.
    """
    stanza_stats = {}
    homo_stats = {}
    gaps = []
    
    lines = {}
    for w in words:
        if w["start"] != -1.0 and w["end"] != -1.0:
            l_num = w["line_num"]
            if l_num not in lines: lines[l_num] = []
            lines[l_num].append(w)
            
    last_line_end = -1.0
    
    for l_num, l_words in sorted(lines.items()):
        if not l_words: continue
        
        s_num = l_words[0]["stanza_num"]
        h_id = l_words[0]["homologous_id"]
        
        t_start = l_words[0]["start"]
        t_end = l_words[-1]["end"]
        dur = t_end - t_start
        
        # Защита от мусора (исключаем аномально сжатые строки из статистики)
        if dur <= 0.4: continue 
        
        vowels = max(1, sum(1 for w in l_words for c in w["clean_text"] if c in "аеёиоуыэюяaeiouy"))
        
        # Сбор пауз между строками
        if last_line_end != -1.0 and t_start > last_line_end:
            gap = t_start - last_line_end
            # Если пауза < 4 сек, это вдох/пауза. Если больше - это гитарное соло, его не берем.
            if gap < 4.0: gaps.append(gap)
        
        last_line_end = t_end
        
        # Статистика по куплетам
        if s_num not in stanza_stats:
            stanza_stats[s_num] = {"vowels": 0, "dur": 0.0}
        stanza_stats[s_num]["vowels"] += vowels
        stanza_stats[s_num]["dur"] += dur
        
        # Статистика по одинаковым строкам
        if h_id not in homo_stats:
            homo_stats[h_id] = []
        homo_stats[h_id].append(dur)
        
    sdr_by_stanza = {}
    total_vowels = sum(s["vowels"] for s in stanza_stats.values())
    total_dur = sum(s["dur"] for s in stanza_stats.values())
    global_sdr = total_vowels / total_dur if total_dur > 0 else 3.0 # Fallback
    
    for s_num, st in stanza_stats.items():
        sdr_by_stanza[s_num] = st["vowels"] / st["dur"] if st["dur"] > 0 else global_sdr
        
    dur_by_homo = {}
    for h_id, durs in homo_stats.items():
        # Медиана позволяет отсечь редкие ошибки и найти реальный эталон длины строки
        dur_by_homo[h_id] = float(np.median(durs))
        
    avg_gap = float(np.median(gaps)) if gaps else 1.0
    
    return {
        "global_sdr": global_sdr,
        "stanza_sdr": sdr_by_stanza,
        "homo_durations": dur_by_homo,
        "avg_breath_gap": avg_gap
    }

def get_safe_bounds(words: list, s_idx: int, e_idx: int, audio_duration: float) -> tuple:
    """Ищет жесткие границы времени, между которыми находится слепая зона."""
    t_start = 0.0
    for i in range(s_idx - 1, -1, -1):
        if words[i]["end"] != -1.0:
            t_start = words[i]["end"] + 0.1
            break
            
    t_end = audio_duration
    for i in range(e_idx + 1, len(words)):
        if words[i]["start"] != -1.0:
            t_end = words[i]["start"] - 0.1
            break
            
    if t_end <= t_start:
        t_end = min(t_start + 1.0, audio_duration)
        
    return t_start, t_end

def calculate_overlap(t_start: float, t_end: float, mask: list) -> float:
    """Вычисляет, сколько времени из отрезка попадает внутрь переданной маски VAD."""
    overlap = 0.0
    for ms, me in mask:
        o_s = max(t_start, ms)
        o_e = min(t_end, me)
        if o_e > o_s: overlap += (o_e - o_s)
    return overlap

def get_vad_capacity(t_start: float, t_end: float, combined_vad: list) -> float:
    """Сколько физического голоса есть в "Дыре"."""
    return calculate_overlap(t_start, t_end, combined_vad)

# ─── СЕМАНТИЧЕСКАЯ СИСТЕМА ОЦЕНКИ (SEMANTIC EVALUATOR) ──────────────────────

def evaluate_alignment_quality(words: list, strong_vad: list, weak_vad: list, curtains: list, spot_check_fn=None) -> float:
    """
    V5.2: Динамический контроль за макро-структурой.
    """
    score = 100.0
    total = len(words)
    if total == 0: return 0.0

    unresolved = 0
    squeezed = 0
    overstretched = 0
    torn_lines = 0
    hallucinations = 0

    combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])

    for i, w in enumerate(words):
        if w["start"] == -1.0:
            unresolved += 1
            continue
        
        dur = w["end"] - w["start"]
        
        if dur < 0.06: squeezed += 1
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        if dur > max_dur * 1.5: overstretched += 1

        overlap = calculate_overlap(w["start"], w["end"], combined_vad)
        if dur > 0 and (overlap / dur) < 0.1:
            hallucinations += 1

        if i < total - 1 and w["line_num"] == words[i+1]["line_num"]:
            next_w = words[i+1]
            if next_w["start"] != -1.0:
                gap = next_w["start"] - w["end"]
                allowed_pause = max(1.5, max_dur * 2.0) 
                
                if gap > allowed_pause: 
                    has_curtain = any(c_s >= w["end"] and c_e <= next_w["start"] for c_s, c_e in curtains)
                    if not has_curtain:
                        vad_in_gap = calculate_overlap(w["end"], next_w["start"], combined_vad)
                        if vad_in_gap > 1.0: 
                            torn_lines += 1

    score -= unresolved * 5.0
    score -= (squeezed / total) * 100 * 0.5
    score -= (overstretched / total) * 100 * 0.5 
    score -= torn_lines * 5.0 
    score -= hallucinations * 5.0

    if score >= 80.0 and spot_check_fn is not None:
        valid_indices = [i for i, w in enumerate(words) if w["start"] != -1.0 and (w["end"] - w["start"]) > 0.2]
        if len(valid_indices) >= 10:
            check_points = random.sample(valid_indices[5:-5], min(2, len(valid_indices) - 10))
            failed_checks = 0
            for idx in check_points:
                w = words[idx]
                t_start = max(0.0, w["start"] - 0.5)
                t_end = w["end"] + 0.5
                target_phrase = " ".join([words[k]["clean_text"] for k in range(max(0, idx-1), min(total, idx+2))])
                if not spot_check_fn(t_start, t_end, target_phrase):
                    failed_checks += 1
            if failed_checks > 0:
                score -= 30.0 

    return max(0.0, score)