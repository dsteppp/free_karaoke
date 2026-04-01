import re
import random
import rapidfuzz
import numpy as np
from app_logger import get_logger

# 🛠️ Единый логгер для всей симфонии
log = get_logger("aligner")

# ─── ЛИНГВИСТИКА И ПОДГОТОВКА ТЕКСТА (V6.1: MACRO-MAPPING) ───────────────────

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
    V6.0: Очищает текст и размечает Макро-Структуру.
    Добавлен флаг `locked` для защиты здоровых строк в Цикле Ковки.
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
                        "locked": False,     # 🔒 V6.0: Бетонная защита
                        "dtw_tried": False
                    })
                    
            if line_clean_words:
                line_str = " ".join(line_clean_words)
                vowels = sum(1 for c in line_str if c in "аеёиоуыэюяaeiouy")
                lines_text_map[line_global_idx] = {"text": line_str, "vowels": max(1, vowels)}
                line_global_idx += 1

    # Homologous Lines Detection (Поиск подобных строк для Клонатора и Паспорта)
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

# ─── ФОНЕТИЧЕСКАЯ МАТЕМАТИКА И ЭМПИРИКА ──────────────────────────────

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
    """Считает Syllable Delivery Rate (Темп слогов/сек) для отрезка."""
    dur = t_end - t_start
    if dur <= 0: return 0.0
    vowels = sum(1 for k in range(s_idx, e_idx + 1) for c in words[k]["clean_text"] if c in "аеёиоуыэюяaeiouy")
    return max(1, vowels) / dur

def get_empirical_data(words: list) -> dict:
    """
    V6.0: ЭМПИРИЧЕСКИЙ ПАСПОРТ.
    Создает паспорт физики певца только на основе здоровых строк.
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
    valid_lines_count = 0
    
    for l_num, l_words in sorted(lines.items()):
        if not l_words: continue
        
        s_num = l_words[0]["stanza_num"]
        h_id = l_words[0]["homologous_id"]
        
        t_start = l_words[0]["start"]
        t_end = l_words[-1]["end"]
        dur = t_end - t_start
        
        # Защита от мусора
        if dur <= 0.4: continue 
        valid_lines_count += 1
        
        vowels = max(1, sum(1 for w in l_words for c in w["clean_text"] if c in "аеёиоуыэюяaeiouy"))
        
        # Сбор пауз между строками
        if last_line_end != -1.0 and t_start > last_line_end:
            gap = t_start - last_line_end
            if gap < 4.0: gaps.append(gap)
        
        last_line_end = t_end
        
        if s_num not in stanza_stats:
            stanza_stats[s_num] = {"vowels": 0, "dur": 0.0}
        stanza_stats[s_num]["vowels"] += vowels
        stanza_stats[s_num]["dur"] += dur
        
        if h_id not in homo_stats:
            homo_stats[h_id] = []
        homo_stats[h_id].append(dur)
        
    sdr_by_stanza = {}
    total_vowels = sum(s["vowels"] for s in stanza_stats.values())
    total_dur = sum(s["dur"] for s in stanza_stats.values())
    global_sdr = total_vowels / total_dur if total_dur > 0 else 3.0
    
    for s_num, st in stanza_stats.items():
        sdr_by_stanza[s_num] = st["vowels"] / st["dur"] if st["dur"] > 0 else global_sdr
        
    dur_by_homo = {}
    for h_id, durs in homo_stats.items():
        dur_by_homo[h_id] = float(np.median(durs))
        
    avg_gap = float(np.median(gaps)) if gaps else 1.0
    
    log.info(f"🛂 [Passport] Сгенерирован на базе {valid_lines_count} здоровых строк.")
    log.info(f"   -> Темп: {global_sdr:.2f} слог/сек. Вдох: {avg_gap:.2f}s.")
    
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

# ─── ДЕТЕКТОР ЛЖИ И АБСОЛЮТНЫЙ СУДЬЯ (V6.3) ──────────────────────────────────

def crosscheck_oracle(draft_text: str, t_start: float, t_end: float, blind_words: list) -> bool:
    """
    V6.3: Детектор Лжи (The Crosscheck).
    Сравнивает черновик (align) со Слепым Оракулом (transcribe).
    """
    oracle_chunk = [bw["clean"] for bw in blind_words if bw["end"] >= t_start - 0.5 and bw["start"] <= t_end + 0.5]
    oracle_text = "".join(oracle_chunk)
    
    clean_draft = re.sub(r'[^\w]', '', draft_text.lower())
    if not clean_draft: return True
    
    if not oracle_text:
        # V6.3 ЗАЩИТА ИНТРО: Оракул не прощает глухоту в самом начале.
        if t_start < 2.0:
            return False 
        
        # В середине трека прощаем только очень короткие обрывки (< 1.5s)
        if t_end - t_start > 1.5: 
            return False 
        return True 
        
    score = rapidfuzz.fuzz.partial_ratio(clean_draft, oracle_text)
    return score >= 40

def evaluate_alignment_quality(words: list, strong_vad: list, weak_vad: list, curtains: list) -> float:
    """
    V6.3: АБСОЛЮТНЫЙ СУДЬЯ.
    Оценивает выравнивание по строгим правилам.
    Использует ДИНАМИЧЕСКИЙ поиск фальстартов для длинных интро!
    """
    score = 100.0
    total = len(words)
    if total == 0: return 0.0

    unresolved = 0
    hallucinations = 0
    singularities = 0
    overstretched = 0
    stanza_tears = 0
    false_starts = 0 

    combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])
    
    # V6.3: Ищем абсолютное начало голоса в треке (первый чистый VAD)
    first_vocal_t = combined_vad[0][0] if combined_vad else 0.0

    for i, w in enumerate(words):
        if w["start"] == -1.0:
            unresolved += 1
            continue
            
        dur = w["end"] - w["start"]
        
        # 1. Сингулярность
        if dur < 0.06:
            singularities += 1
            
        # 2. Галлюцинация в тишине
        overlap = calculate_overlap(w["start"], w["end"], combined_vad)
        if dur > 0 and (overlap / dur) < 0.1:
            hallucinations += 1
            
        # V6.3: ДИНАМИЧЕСКИЙ СМЕРТНЫЙ ПРИГОВОР ЗА ФАЛЬСТАРТ (Защита длинных интро)
        # Если слово начинается раньше первого реального вокала ИЛИ в самом начале трека
        if w["start"] < first_vocal_t - 0.5 or w["start"] < 2.0:
            s_overlap = calculate_overlap(w["start"], w["end"], strong_vad)
            if s_overlap / dur < 0.5:
                false_starts += 1
            
        # 3. Перерастяжение (Резиновый эффект)
        _, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        if dur > max_dur * 1.5:
            strong_overlap = calculate_overlap(w["start"], w["end"], strong_vad)
            if dur > 0 and (strong_overlap / dur) < 0.8:
                overstretched += 1
            
        # 4. Разрыв строфы (Stanza Tear)
        if i < total - 1:
            next_w = words[i+1]
            if next_w["start"] != -1.0 and w["stanza_num"] == next_w["stanza_num"]:
                gap = next_w["start"] - w["end"]
                
                if gap > 5.0:
                    has_curtain = any(c_s >= w["end"] and c_e <= next_w["start"] for c_s, c_e in curtains)
                    if not has_curtain:
                        stanza_tears += 1

    # Применяем штрафы
    penalty_unresolved = unresolved * 2.0
    penalty_hallucinations = hallucinations * 5.0
    penalty_singularities = singularities * 3.0
    penalty_overstretch = overstretched * 1.0 
    penalty_tears = stanza_tears * 10.0
    penalty_false_starts = false_starts * 50.0 # Огромный штраф за фальстарт (в интро или до голоса)

    score -= (penalty_unresolved + penalty_hallucinations + penalty_singularities + penalty_overstretch + penalty_tears + penalty_false_starts)

    log.info(f"⚖️ [Absolute Judge] Телеметрия Штрафов:")
    log.info(f"   -> Нераспределенные слова ({unresolved}): -{penalty_unresolved:.1f}")
    log.info(f"   -> Галлюцинации ({hallucinations}): -{penalty_hallucinations:.1f}")
    log.info(f"   -> Сингулярности ({singularities}): -{penalty_singularities:.1f}")
    log.info(f"   -> Резина вне голоса ({overstretched}): -{penalty_overstretch:.1f}")
    log.info(f"   -> Разрывы Строф ({stanza_tears}): -{penalty_tears:.1f}")
    if false_starts > 0:
        log.info(f"   -> ФАЛЬСТАРТЫ ВО ВСТУПЛЕНИИ ({false_starts}): -{penalty_false_starts:.1f}")
    log.info(f"⚖️ [Absolute Judge] ИТОГОВЫЙ БАЛЛ ТРЕКА: {max(0.0, score):.1f} / 100.0")

    return max(0.0, score)