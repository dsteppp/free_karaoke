import re
import random

# ─── ЛИНГВИСТИКА И ПОДГОТОВКА ТЕКСТА ─────────────────────────────────────────

def detect_language(text: str) -> str:
    """Определяет язык текста (ru, ko, en) по количеству символов."""
    cyrillic = len(re.findall(r'[\u0400-\u04FFёЁ]', text))
    hangul = len(re.findall(r'[\uac00-\ud7a3]', text))
    latin = len(re.findall(r'[a-zA-Z]', text))
    
    if hangul > 10: return "ko" 
    if cyrillic > latin * 0.3: return "ru" 
    return "en"     

def prepare_text(text: str) -> list:
    """Очищает текст и превращает его в список словарей-якорей."""
    text = re.sub(r'[\x5B\x28].*?[\x5D\x29]', '', text)
    text = re.sub(r'([a-zA-Z\u0400-\u04FFёЁ])([\x2D\u2013\u2014]+)([a-zA-Z\u0400-\u04FFёЁ])', r'\1\2 \3', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    words_list = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line: continue
            
        tokens = line.split()
        for idx, token in enumerate(tokens):
            has_punct = bool(re.search(r'[\x2C\x2E\x3A\x3B\x3F\x21\x2D]$', token))
            is_last_in_line = (idx == len(tokens) - 1)
            clean = re.sub(r'[^\w]', '', token.lower())
            if clean:
                words_list.append({
                    "word": token,
                    "clean_text": clean,
                    "has_punct": has_punct,
                    "line_break": is_last_in_line,
                    "start": -1.0,
                    "end": -1.0,
                    "dtw_tried": False,
                    "is_island": False # Флаг для изоляции повторов
                })
    return words_list

def find_repetition_islands(words: list) -> list:
    """
    V13: Сканирует текст ЗАРАНЕЕ и находит блоки зацикленных фраз (от 10 слов).
    Эти Острова будут изолированы от нейросети, чтобы не сломать общую матрицу выравнивания.
    """
    islands = []
    n = len(words)
    i = 0
    
    while i < n:
        best_island = None
        # Ищем сверху-вниз: от самых больших блоков к минимальным (10 слов)
        for j in range(n - 1, i + 9, -1):
            chunk = [words[k]["clean_text"] for k in range(i, j + 1) if len(words[k]["clean_text"]) > 1]
            if not chunk: continue
            
            unique = set(chunk)
            ratio = len(unique) / len(chunk)
            max_repeats = max([chunk.count(u) for u in unique]) if unique else 0
            
            # Если уникальных слов меньше 35% ИЛИ одно слово повторяется 3+ раза (при соотношении < 50%)
            if ratio < 0.35 or (max_repeats >= 3 and ratio < 0.5):
                best_island = (i, j)
                break
        
        if best_island:
            islands.append(best_island)
            # Помечаем слова флагом
            for k in range(best_island[0], best_island[1] + 1):
                words[k]["is_island"] = True
            i = best_island[1] + 1
        else:
            i += 1
            
    return islands

# ─── ФОНЕТИЧЕСКАЯ МАТЕМАТИКА ────────────────────────────────────────────────

def get_vowel_weight(word: str, is_line_end: bool) -> float:
    """Вычисляет фонетический вес слова (длительность произношения)."""
    vowels = set("аеёиоуыэюяaeiouy")
    clean = word.lower()
    v_count = sum(1 for c in clean if c in vowels)
    c_count = len(clean) - v_count
    
    weight = float(max(1, v_count))
    if c_count >= 3:
        weight += 0.5 * (c_count / 3.0)  
        
    if is_line_end: 
        weight *= 2.0 
        
    return weight

def get_phonetic_bounds(clean_text: str, is_line_end: bool) -> tuple:
    """Возвращает минимально и максимально возможную физическую длину слова в секундах."""
    vowels = sum(1 for c in clean_text if c in "аеёиоуыэюяaeiouy")
    consonants = len(clean_text) - vowels
    
    min_dur = max(0.05, (vowels * 0.06) + (consonants * 0.04))
    max_dur = max(0.5, (vowels * 0.8) + (consonants * 0.20))
    if is_line_end: max_dur *= 2.0
    
    return min_dur, max_dur

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

# ─── V13: СЕМАНТИЧЕСКАЯ СИСТЕМА ОЦЕНКИ (SEMANTIC EVALUATOR) ────────────────

def evaluate_alignment_quality(words: list, vad_mask: list, curtains: list, spot_check_fn=None) -> float:
    """
    V13: "Master Plan" Evaluator.
    Суровый контроль:
    - Void Penalty (каждое ненайденное слово -5 баллов).
    - Orphan VAD Penalty (штраф за куски голоса > 3сек без текста).
    """
    score = 100.0
    total = len(words)
    if total == 0: return 0.0

    unresolved = 0
    squeezed = 0
    overstretched = 0
    torn_lines = 0
    hallucinations = 0

    for i, w in enumerate(words):
        if w["start"] == -1.0:
            unresolved += 1
            continue
        
        dur = w["end"] - w["start"]
        
        # 1. Физическая деформация
        if dur < 0.06:
            squeezed += 1
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        if dur > max_dur * 1.5: 
            overstretched += 1

        # 2. Галлюцинации (VAD-Overlap)
        overlap = 0.0
        for vs, ve in vad_mask:
            o_s = max(w["start"], vs)
            o_e = min(w["end"], ve)
            if o_e > o_s:
                overlap += (o_e - o_s)
        
        if dur > 0 and (overlap / dur) < 0.1:
            hallucinations += 1

        # 3. Мягкая проверка натяжения (Smart Line Tension)
        if i < total - 1 and not w["line_break"]:
            next_w = words[i+1]
            if next_w["start"] != -1.0:
                gap = next_w["start"] - w["end"]
                
                if gap > 3.0: 
                    has_curtain = any(c_s >= w["end"] and c_e <= next_w["start"] for c_s, c_e in curtains)
                    if not has_curtain:
                        vad_in_gap = sum((min(next_w["start"], ve) - max(w["end"], vs)) 
                                         for vs, ve in vad_mask if min(next_w["start"], ve) > max(w["end"], vs))
                        if vad_in_gap > 1.5: 
                            torn_lines += 1

    # 4. V13: Поиск Брошенного Голоса (Orphan VAD Penalty - Защита Доры)
    orphan_vad_time = 0.0
    for vs, ve in vad_mask:
        has_words = False
        for w in words:
            if w["start"] != -1.0 and min(w["end"], ve) - max(w["start"], vs) > 0:
                has_words = True
                break
        
        vad_dur = ve - vs
        if not has_words and vad_dur > 2.0:
            orphan_vad_time += vad_dur
            
    # За каждые 1.5 секунды брошенного вокала - минус 10 баллов
    if orphan_vad_time > 1.5:
        score -= (orphan_vad_time * 10.0)

    # 5. V13: Жестокий Оценщик Пустот (Void Penalty)
    score -= unresolved * 5.0
    
    score -= (squeezed / total) * 100 * 0.5
    score -= (overstretched / total) * 100 * 0.5 
    score -= torn_lines * 5.0 
    score -= hallucinations * 5.0

    # 6. V13: Смысловой Аудитор (Spot-Check с использованием Forced Alignment)
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
                score -= 30.0 # Семантический рассинхрон

    return max(0.0, score)