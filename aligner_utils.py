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
                    "dtw_tried": False
                })
    return words_list

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
    """
    Ищет жесткие границы времени, между которыми находится "слепая зона".
    Гарантирует, что поиск не упадет в 0.0 секунду из-за локальной ошибки.
    """
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

# ─── V11: СЕМАНТИЧЕСКАЯ СИСТЕМА ОЦЕНКИ (SEMANTIC EVALUATOR) ────────────────

def evaluate_alignment_quality(words: list, vad_mask: list, curtains: list, spot_check_fn=None) -> float:
    """
    V11: Оценивает качество, объединяя физику (VAD) и семантику (Смысловой Аудит).
    Если передан spot_check_fn, делает точечную транскрибацию для проверки на рассинхрон.
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
        
        # 1. Проверка на физическую деформацию
        if dur < 0.06:
            squeezed += 1
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        if dur > max_dur * 1.5: 
            overstretched += 1

        # 2. Проверка на галлюцинации (VAD-Overlap)
        overlap = 0.0
        for vs, ve in vad_mask:
            o_s = max(w["start"], vs)
            o_e = min(w["end"], ve)
            if o_e > o_s:
                overlap += (o_e - o_s)
        
        if dur > 0 and (overlap / dur) < 0.1:
            hallucinations += 1

        # 3. V11: Мягкая проверка натяжения строки (Smart Line Tension)
        if i < total - 1 and not w["line_break"]:
            next_w = words[i+1]
            if next_w["start"] != -1.0:
                gap = next_w["start"] - w["end"]
                
                if gap > 3.0: # V11: Увеличили допуск до 3-х секунд (было 2.5)
                    has_curtain = any(c_s >= w["end"] and c_e <= next_w["start"] for c_s, c_e in curtains)
                    
                    if not has_curtain:
                        vad_in_gap = sum((min(next_w["start"], ve) - max(w["end"], vs)) 
                                         for vs, ve in vad_mask if min(next_w["start"], ve) > max(w["end"], vs))
                        if vad_in_gap > 1.5: # V11: Наказываем, только если в дыре > 1.5 сек реального вокала
                            torn_lines += 1

    # Расчет физических штрафов
    score -= (unresolved / total) * 100 * 1.5
    score -= (squeezed / total) * 100 * 0.5
    score -= (overstretched / total) * 100 * 0.5 
    score -= torn_lines * 5.0 # V11: Снизили штраф за порванную строку (было 15.0)
    score -= hallucinations * 5.0

    # 4. V11: Семантический Аудит (Semantic Spot-Check)
    # Запускаем, только если физика говорит, что трек нормальный (> 80 баллов)
    if score >= 80.0 and spot_check_fn is not None:
        valid_indices = [i for i, w in enumerate(words) if w["start"] != -1.0 and (w["end"] - w["start"]) > 0.2]
        
        if len(valid_indices) >= 10:
            # Выбираем 2 случайных слова из середины трека для проверки
            check_points = random.sample(valid_indices[5:-5], min(2, len(valid_indices) - 10))
            
            failed_checks = 0
            for idx in check_points:
                w = words[idx]
                # Просим функцию послушать 2 секунды вокруг этого слова
                t_start = max(0.0, w["start"] - 0.5)
                t_end = w["end"] + 0.5
                
                # Формируем целевую фразу (само слово + соседи)
                target_phrase = " ".join([words[k]["clean_text"] for k in range(max(0, idx-1), min(total, idx+2))])
                
                # Функция вернет True, если услышит эту фразу, и False, если там звучит совсем другое
                if not spot_check_fn(t_start, t_end, target_phrase):
                    failed_checks += 1
                    
            if failed_checks > 0:
                score -= 30.0 # Огромный штраф за семантический рассинхрон (Сдвиг скелета)

    return max(0.0, score)