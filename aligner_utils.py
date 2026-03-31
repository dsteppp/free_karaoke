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
    """
    V5.0: Очищает текст и добавляет 'line_num' для Строкового Мышления (Line-First Alignment).
    """
    text = re.sub(r'[\x5B\x28].*?[\x5D\x29]', '', text)
    text = re.sub(r'([a-zA-Z\u0400-\u04FFёЁ])([\x2D\u2013\u2014]+)([a-zA-Z\u0400-\u04FFёЁ])', r'\1\2 \3', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    words_list = []
    line_num = 0
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
                    "line_num": line_num,  # 🧱 Привязка слова к монолитной строке
                    "start": -1.0,
                    "end": -1.0,
                    "dtw_tried": False
                })
        line_num += 1
    return words_list

def is_repetition_island(words: list, s_idx: int, e_idx: int) -> bool:
    """Адаптивный целевой сканер Острова Повторов."""
    length = e_idx - s_idx + 1
    if length < 5: return False
    
    text_chunk = [words[i]["clean_text"] for i in range(s_idx, e_idx + 1) if words[i]["clean_text"]]
    if not text_chunk: return False
    
    unique_words = set(text_chunk)
    ratio = len(unique_words) / len(text_chunk)
    max_repeats = max(text_chunk.count(w) for w in unique_words)
    
    return ratio <= 0.40 or (max_repeats >= 3 and ratio < 0.60)

# ─── ФОНЕТИЧЕСКАЯ МАТЕМАТИКА И ПЛОТНОСТИ (V5.0) ─────────────────────────────

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

def get_line_phonetic_bounds(words: list, s_idx: int, e_idx: int) -> tuple:
    """
    V5.0: Вычисляет Фонетическую Массу целой фразы/строки.
    Используется для оценки Баланса Масс при сдвигах и растяжениях.
    """
    total_min = 0.0
    total_max = 0.0
    for i in range(s_idx, e_idx + 1):
        min_d, max_d = get_phonetic_bounds(words[i]["clean_text"], words[i]["line_break"])
        total_min += min_d
        total_max += max_d
    return total_min, total_max

def calculate_phrase_density(words: list, s_idx: int, e_idx: int, t_start: float, t_end: float) -> float:
    """
    V5.0: Вычисляет Плотность (Density) отрезка.
    Если плотность << 1.0 (например, 0.1), значит текст размазан по тишине или болтовне (False Start).
    """
    if t_end <= t_start: return 0.0
    mass_min, _ = get_line_phonetic_bounds(words, s_idx, e_idx)
    return mass_min / (t_end - t_start)

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
        if o_e > o_s:
            overlap += (o_e - o_s)
    return overlap

def get_vad_capacity(t_start: float, t_end: float, combined_vad: list) -> float:
    """
    V5.0: Семантическая обертка для расчета Емкости VAD.
    Показывает, сколько физического голоса есть в "Дыре" для вставки текста.
    """
    return calculate_overlap(t_start, t_end, combined_vad)

# ─── СЕМАНТИЧЕСКАЯ СИСТЕМА ОЦЕНКИ (SEMANTIC EVALUATOR) ──────────────────────

def evaluate_alignment_quality(words: list, strong_vad: list, weak_vad: list, curtains: list, spot_check_fn=None) -> float:
    """
    V5.0: Динамический контроль за макро-структурой (без жестких секундных констант).
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

        # Галлюцинации (VAD-Overlap) - штраф за слова, поставленные в абсолютную тишину
        overlap = calculate_overlap(w["start"], w["end"], combined_vad)
        if dur > 0 and (overlap / dur) < 0.1:
            hallucinations += 1

        # V5.0: Динамическая проверка разрыва строки (Intra-line Cohesion)
        # Штрафуем только если слова принадлежат одной строке, но между ними огромная пауза.
        if i < total - 1 and w["line_num"] == words[i+1]["line_num"]:
            next_w = words[i+1]
            if next_w["start"] != -1.0:
                gap = next_w["start"] - w["end"]
                # Допустимая пауза внутри строки зависит от длины самого слова, а не равна жестким 3.0с
                allowed_pause = max(1.5, max_dur * 2.0) 
                
                if gap > allowed_pause: 
                    has_curtain = any(c_s >= w["end"] and c_e <= next_w["start"] for c_s, c_e in curtains)
                    if not has_curtain:
                        vad_in_gap = calculate_overlap(w["end"], next_w["start"], combined_vad)
                        if vad_in_gap > 1.0: # Если в паузе есть чужой голос - это 100% разрыв
                            torn_lines += 1

    # Штрафы за физические аномалии таймлайна
    score -= unresolved * 5.0
    score -= (squeezed / total) * 100 * 0.5
    score -= (overstretched / total) * 100 * 0.5 
    score -= torn_lines * 5.0 
    score -= hallucinations * 5.0

    # Семантический Аудитор (Сверка текста и аудио эталоном Whisper)
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