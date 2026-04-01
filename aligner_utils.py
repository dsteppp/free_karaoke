import re
import random

# ─── ЛИНГВИСТИКА И ПОДГОТОВКА ТЕКСТА (МАКРО-МАППИНГ) ──────────────────────────

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
    V6.3: Очищает текст и размечает макро-структуру (строфы и строки).
    Позволяет алгоритму понимать границы куплетов.
    """
    text = re.sub(r'[\x5B\x28].*?[\x5D\x29]', '', text)
    text = re.sub(r'([a-zA-Z\u0400-\u04FFёЁ])([\x2D\u2013\u2014]+)([a-zA-Z\u0400-\u04FFёЁ])', r'\1\2 \3', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)

    words_list = []
    stanza_idx = 0
    global_line_idx = 0

    paragraphs = text.split('\n\n')
    for p in paragraphs:
        if not p.strip(): continue
        lines = p.splitlines()
        
        for raw_line in lines:
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
                        "stanza_idx": stanza_idx,
                        "line_idx": global_line_idx,
                        "start": -1.0,
                        "end": -1.0,
                        "dtw_tried": False
                    })
            global_line_idx += 1
        stanza_idx += 1
        
    return words_list

def is_repetition_island(words: list, s_idx: int, e_idx: int) -> bool:
    """Адаптивный целевой сканер Острова Повторов (для Motif Matrix)."""
    length = e_idx - s_idx + 1
    if length < 5: return False
    
    text_chunk = [words[i]["clean_text"] for i in range(s_idx, e_idx + 1) if words[i]["clean_text"]]
    if not text_chunk: return False
    
    unique_words = set(text_chunk)
    ratio = len(unique_words) / len(text_chunk)
    max_repeats = max(text_chunk.count(w) for w in unique_words)
    
    return ratio <= 0.40 or (max_repeats >= 3 and ratio < 0.60)

# ─── V6.3: ПАСПОРТ ПЕСНИ (БИОМЕТРИЯ ПЕВЦА) ──────────────────────────────────

def get_empirical_data(words: list) -> dict:
    """
    Вычисляет SDR (Syllable Delivery Rate - слогов в секунду) 
    и средний вдох (gap) на основе 100% подтвержденных строк.
    """
    lines_stats = []
    current_line = []
    
    for w in words:
        if w["start"] != -1.0:
            current_line.append(w)
        if w["line_break"]:
            if current_line:
                lines_stats.append(current_line)
            current_line = []
            
    if not lines_stats:
        return {"sdr": 3.0, "avg_breath": 0.5}
        
    sdr_list = []
    for line in lines_stats:
        dur = line[-1]["end"] - line[0]["start"]
        if dur > 0.2:
            vowels = sum(sum(1 for c in w["clean_text"] if c in "аеёиоуыэюяaeiouy") for w in line)
            sdr_list.append(vowels / dur if vowels > 0 else 2.0)
            
    gaps = []
    for i in range(len(lines_stats) - 1):
        gap = lines_stats[i+1][0]["start"] - lines_stats[i][-1]["end"]
        if 0.1 < gap < 5.0:
            gaps.append(gap)
            
    # Берем медианные значения для устойчивости к выбросам
    sdr = sorted(sdr_list)[len(sdr_list)//2] if sdr_list else 3.0
    avg_breath = sum(gaps)/len(gaps) if gaps else 0.5
    
    return {
        "sdr": max(1.0, min(sdr, 8.0)), 
        "avg_breath": max(0.2, min(avg_breath, 2.0))
    }

# ─── ФОНЕТИЧЕСКАЯ МАТЕМАТИКА ────────────────────────────────────────────────

def get_vowel_weight(word: str, is_line_end: bool) -> float:
    """Вычисляет абстрактный фонетический вес слова."""
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

def calculate_overlap(t_start: float, t_end: float, mask: list) -> float:
    """Вычисляет, сколько времени из отрезка попадает внутрь переданной маски (VAD или Занавеса)."""
    overlap = 0.0
    for ms, me in mask:
        o_s = max(t_start, ms)
        o_e = min(t_end, me)
        if o_e > o_s:
            overlap += (o_e - o_s)
    return overlap

# ─── СЕМАНТИЧЕСКАЯ СИСТЕМА ОЦЕНКИ (ABSOLUTE JUDGE) ──────────────────────────

def evaluate_alignment_quality(words: list, strong_vad: list, weak_vad: list, curtains: list, spot_check_fn=None) -> float:
    """
    V6.3: Суровый контроль макро-структуры.
    Добавлено фатальное наказание за слова, попавшие в Железный Занавес.
    """
    score = 100.0
    total = len(words)
    if total == 0: return 0.0

    unresolved = 0
    squeezed = 0
    overstretched = 0
    torn_lines = 0
    hallucinations = 0
    curtain_violations = 0

    combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])

    for i, w in enumerate(words):
        if w["start"] == -1.0:
            unresolved += 1
            continue
        
        dur = w["end"] - w["start"]
        
        if dur < 0.06: squeezed += 1
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        if dur > max_dur * 1.5: overstretched += 1

        # 1. Штраф за слова в абсолютной тишине (VAD-Overlap)
        overlap = calculate_overlap(w["start"], w["end"], combined_vad)
        if dur > 0 and (overlap / dur) < 0.1:
            hallucinations += 1
            
        # 2. ФАТАЛЬНЫЙ ШТРАФ: Слово внутри Железного Занавеса
        curtain_overlap = calculate_overlap(w["start"], w["end"], curtains)
        if curtain_overlap > 0.1:
            curtain_violations += 1

        # 3. Мягкая проверка натяжения (Smart Line Tension)
        if i < total - 1 and not w["line_break"]:
            next_w = words[i+1]
            if next_w["start"] != -1.0:
                gap = next_w["start"] - w["end"]
                if gap > 3.0: 
                    has_curtain = any(c_s >= w["end"] and c_e <= next_w["start"] for c_s, c_e in curtains)
                    if not has_curtain:
                        vad_in_gap = calculate_overlap(w["end"], next_w["start"], combined_vad)
                        if vad_in_gap > 1.5:
                            torn_lines += 1

    # Штрафы за физические аномалии таймлайна
    score -= unresolved * 5.0
    score -= (squeezed / total) * 100 * 0.5
    score -= (overstretched / total) * 100 * 0.5 
    score -= torn_lines * 5.0 
    score -= hallucinations * 5.0
    score -= curtain_violations * 20.0 # Тяжелейший штраф за Занавес!

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