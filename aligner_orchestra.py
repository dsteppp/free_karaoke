import re
import numpy as np
import rapidfuzz
from app_logger import get_logger
from aligner_utils import (
    get_safe_bounds, get_vowel_weight, get_phonetic_bounds, 
    calculate_overlap, is_repetition_island
)

log = get_logger("aligner_orchestra")

class Proposal:
    """Обертка для предложенных таймингов от инструмента на Арене."""
    def __init__(self, source_name: str, timings: list):
        self.source_name = source_name
        self.timings = timings  # Список dict: [{"start": 1.0, "end": 1.5}, ...]
        self.score = 0.0

# ─── АРЕНА: КАНДИДАТ 1 (MOTIF MATRIX) ───────────────────────────────────────

def propose_motif_matrix(words: list, s_idx: int, e_idx: int, audio_duration: float, strong_vad: list) -> Proposal:
    """Ищет здорового двойника (припев) и предлагает его тайминги."""
    target_phrase = " ".join([words[i]["clean_text"] for i in range(s_idx, e_idx + 1)])
    target_len = e_idx - s_idx + 1
    if target_len < 2: return None
    
    for i in range(len(words) - target_len + 1):
        if max(0, s_idx - target_len) <= i <= e_idx: continue
        
        source_phrase = " ".join([words[k]["clean_text"] for k in range(i, i + target_len)])
        if source_phrase == target_phrase:
            if all(words[k]["start"] != -1.0 for k in range(i, i + target_len)):
                twin_dur = words[i + target_len - 1]["end"] - words[i]["start"]
                if twin_dur < 0.2: continue
                
                t_start, t_end = get_safe_bounds(words, s_idx, e_idx, audio_duration)
                
                # Магнетизм к уверенному голосу (Strong VAD)
                vad_start = t_start
                for vs, ve in strong_vad:
                    if ve > t_start + 0.2:
                        vad_start = max(t_start, vs)
                        break
                        
                if vad_start + twin_dur > t_end + 1.0:
                    vad_start = max(t_start, t_end - twin_dur)
                
                src_start = words[i]["start"]
                timings = []
                for k in range(target_len):
                    rel_s = words[i + k]["start"] - src_start
                    rel_dur = words[i + k]["end"] - words[i + k]["start"]
                    new_s = vad_start + rel_s
                    new_e = new_s + rel_dur
                    timings.append({"start": new_s, "end": max(new_s + 0.05, new_e)})
                
                return Proposal("Motif Matrix", timings)
    return None

# ─── АРЕНА: КАНДИДАТ 2 (CTC INQUISITOR) ─────────────────────────────────────

def propose_inquisitor(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, model, lang: str, t_start: float, t_end: float) -> Proposal:
    """Принудительный Forced Alignment через Wav2Vec2."""
    if t_end - t_start < 0.3: return None
    sr = 16000
    crop = audio_data[int(t_start * sr) : int(t_end * sr)]
    if len(crop) < sr * 0.2: return None
    
    text = " ".join([words[i]["word"] for i in range(s_idx, e_idx + 1)])
    try:
        res = model.align(crop, text, language=lang, fast_mode=True)
        sw_words = res.all_words()
        
        valid_words = [w for w in sw_words if w.end - w.start >= 0.05]
        if len(valid_words) >= (e_idx - s_idx + 1) * 0.4:
            timings = []
            c_ptr = 0
            for k in range(s_idx, e_idx + 1):
                clean = words[k]["clean_text"]
                best_score, best_match = 0, -1
                for j in range(c_ptr, min(c_ptr + 4, len(valid_words))):
                    s_clean = re.sub(r'[^\w]', '', valid_words[j].word.lower())
                    score = rapidfuzz.fuzz.ratio(clean, s_clean)
                    if score > best_score:
                        best_score, best_match = score, j
                
                if best_match != -1 and best_score > 60:
                    timings.append({
                        "start": t_start + valid_words[best_match].start,
                        "end": t_start + valid_words[best_match].end
                    })
                    c_ptr = best_match + 1
                else:
                    return None
            return Proposal("CTC Inquisitor", timings)
    except Exception:
        pass
    return None

# ─── АРЕНА: КАНДИДАТ 3 (SEMANTIC HARPOON - АВАНГАРД АРЕНЫ) ──────────────────

def propose_harpoon(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, model, lang: str, t_start: float, t_end: float) -> Proposal:
    """Слепой Whisper на уровне слов. Отлично спасает сброшенные интро."""
    if t_end - t_start < 0.5: return None
    sr = 16000
    crop = audio_data[int(max(0, t_start - 0.2) * sr) : int(min(len(audio_data), (t_end + 0.2) * sr))]
    if len(crop) < sr * 0.5: return None
    
    try:
        result = model.transcribe(crop, language=lang)
        blind_words = result.all_words()
        if not blind_words: return None

        b_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in blind_words if w.word.strip()]
        if not b_texts: return None

        timings = []
        b_ptr = 0
        for k in range(s_idx, e_idx + 1):
            clean = words[k]["clean_text"]
            best_score, best_idx = 0, -1
            
            for j in range(b_ptr, min(b_ptr + 5, len(b_texts))):
                score = rapidfuzz.fuzz.ratio(clean, b_texts[j])
                if score > best_score:
                    best_score, best_idx = score, j
            
            if best_idx != -1 and best_score > 60:
                bw = blind_words[best_idx]
                min_dur, max_dur = get_phonetic_bounds(clean, words[k]["line_break"])
                dur = bw.end - bw.start
                if 0.05 < dur <= max_dur * 1.5:
                    timings.append({
                        "start": t_start - 0.2 + bw.start,
                        "end": t_start - 0.2 + bw.end
                    })
                    b_ptr = best_idx + 1
                else:
                    return None
            else:
                return None
        return Proposal("Semantic Harpoon", timings)
    except Exception:
        pass
    return None

# ─── АРЕНА: КАНДИДАТ 4 (LINE-FIRST PHONETIC LOOM V5.0) ──────────────────────

def propose_loom(words: list, s_idx: int, e_idx: int, t_start: float, t_end: float, strong_vad: list, weak_vad: list) -> Proposal:
    """V5.0: Line-First Loom. Сначала выделяет место Строке, затем распределяет слова внутри неё."""
    combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])
    
    valid_vads = []
    for (vs, ve) in combined_vad:
        c_s, c_e = max(t_start, vs), min(t_end, ve)
        if c_e - c_s > 0.05: valid_vads.append((c_s, c_e))
        
    if not valid_vads:
        valid_vads = [(t_start, t_end)]
        
    def _map_time(t_vad: float, vads: list) -> float:
        """Переводит VAD-время в реальное время."""
        accum = 0.0
        for (vs, ve) in vads:
            d = ve - vs
            if t_vad <= accum + d:
                return vs + (t_vad - accum)
            accum += d
        return vads[-1][1]

    # 1. Группируем слова в Строки
    lines = []
    curr_line = []
    for k in range(s_idx, e_idx + 1):
        curr_line.append(k)
        if words[k]["line_break"] or k == e_idx:
            lines.append(curr_line)
            curr_line = []
            
    total_vad_time = sum(e - s for s, e in valid_vads)
    
    # Считаем вес Строк
    line_weights = [sum(get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in line) for line in lines]
    total_w = sum(line_weights) if sum(line_weights) > 0 else 1.0
    
    timings = []
    curr_vad_t = 0.0
    
    for l_idx, line in enumerate(lines):
        lw = line_weights[l_idx]
        l_vad_dur = (lw / total_w) * total_vad_time
        
        # Получаем реальные границы короба для всей Строки
        l_start_real = _map_time(curr_vad_t, valid_vads)
        l_end_real = _map_time(curr_vad_t + l_vad_dur, valid_vads)
        
        # Вдыхаем: резервируем микро-паузу между строками (если есть место)
        if l_idx < len(lines) - 1 and (l_end_real - l_start_real) > 0.5:
            l_end_real -= 0.15  
            
        # Теперь берем только те куски VAD, которые попали в короб Строки
        line_vads = []
        for (vs, ve) in valid_vads:
            c_s, c_e = max(l_start_real, vs), min(l_end_real, ve)
            if c_e > c_s: line_vads.append((c_s, c_e))
        if not line_vads: 
            line_vads = [(l_start_real, l_end_real)]
            
        line_total_vad_time = sum(e - s for s, e in line_vads)
        w_curr_vad_t = 0.0
        
        # Распределяем слова внутри короба Строки
        for k in line:
            w_w = get_vowel_weight(words[k]["clean_text"], False) 
            w_dur = (w_w / lw) * line_total_vad_time
            
            w_s = _map_time(w_curr_vad_t, line_vads)
            w_e = _map_time(w_curr_vad_t + w_dur * 0.95, line_vads) # 5% зазор между словами
            
            timings.append({"start": w_s, "end": w_e})
            w_curr_vad_t += w_dur
            
        curr_vad_t += l_vad_dur
        
    return Proposal("Phonetic Loom", timings)


# ─── THE SUPREME JUDGE (АБСОЛЮТНЫЙ СУДЬЯ V5.0) ──────────────────────────────

def the_supreme_judge(proposals: list, words: list, s_idx: int, e_idx: int, strong_vad: list, weak_vad: list) -> Proposal:
    """V5.0: Выбирает лучшее предложение. Жестко штрафует за сжатие целых строк."""
    best_prop = None
    best_score = -99999.0
    
    if not proposals:
        return None

    clean_texts = [words[i]["clean_text"] for i in range(s_idx, e_idx + 1)]
    line_breaks = [words[i]["line_break"] for i in range(s_idx, e_idx + 1)]
    
    for prop in proposals:
        if prop is None or len(prop.timings) != (e_idx - s_idx + 1):
            continue
            
        score = 100.0
        
        # 1. Пословная оценка (Акустика и микро-физика)
        for i, t in enumerate(prop.timings):
            dur = t["end"] - t["start"]
            min_dur, max_dur = get_phonetic_bounds(clean_texts[i], line_breaks[i])
            
            if dur < 0.08:
                score -= 1000.0  # 🚨 СМЕРТНЫЙ ПРИГОВОР ЗА СИНГУЛЯРНОСТЬ
            elif dur < min_dur: 
                score -= 200.0 * (min_dur - dur)
                
            if dur > max_dur * 1.5: 
                score -= 100.0 * (dur - max_dur)
            
            overlap_strong = calculate_overlap(t["start"], t["end"], strong_vad)
            overlap_weak = calculate_overlap(t["start"], t["end"], weak_vad)
            silence_dur = dur - overlap_strong - overlap_weak
            
            if overlap_strong > 0.1: score += 5.0
            if silence_dur > 0.15: score -= (silence_dur * 200.0) 

        # 2. Макро-оценка Строки (Защита от сплющивания припевов Золото)
        lines = []
        cur_l = []
        for i in range(len(prop.timings)):
            cur_l.append(i)
            if line_breaks[i] or i == len(prop.timings) - 1:
                lines.append(cur_l)
                cur_l = []
                
        for line in lines:
            l_s = prop.timings[line[0]]["start"]
            l_e = prop.timings[line[-1]]["end"]
            l_dur = l_e - l_s
            
            # Считаем минимальную физическую массу всей строки
            l_min = sum(get_phonetic_bounds(clean_texts[k], line_breaks[k])[0] for k in line)
            
            if l_dur < l_min:
                score -= 500.0 * (l_min - l_dur) # 🚨 Штраф за коллапс всей строки
                
        prop.score = score
        log.debug(f"   ⚖️ Судья оценил {prop.source_name}: {score:.1f} баллов.")
        
        if score > best_score:
            best_score = score
            best_prop = prop
            
    if best_prop:
        log.info(f"   🏆 Победитель Арены: {best_prop.source_name} ({best_prop.score:.1f} баллов).")
        
    return best_prop


# ─── ДИАГНОСТИЧЕСКИЙ КОМПАС (ADVISORY COMPASS) ──────────────────────────────

def diagnostic_compass(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, t_start: float, t_end: float, model, lang: str) -> int:
    """Щупает будущее на предмет глобальных сдвигов. Отключается внутри Островов Повторов."""
    if is_repetition_island(words, s_idx, e_idx):
        log.debug("   🧭 [Diagnostic Compass] Обнаружен цикл (Остров). Компас отключен для защиты от ложного сдвига.")
        return -1

    if (e_idx - s_idx) < 2: return -1 
    gap_dur = t_end - t_start
    if gap_dur < 1.0: return -1
    
    acoustic_max_words = int(gap_dur * 3.5) + 2
    next_anchor_idx = len(words)
    for i in range(e_idx + 1, len(words)):
        if words[i]["start"] != -1.0:
            next_anchor_idx = i
            break
            
    lookahead_limit = min(e_idx + acoustic_max_words, next_anchor_idx, len(words))
    if lookahead_limit <= e_idx + 1: return -1

    sr = 16000
    crop = audio_data[int(t_start * sr) : int(t_end * sr)]
    try:
        result = model.transcribe(crop, language=lang)
        blind_words = result.all_words()
        if not blind_words: return -1
        
        b_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in blind_words if w.word.strip()]
        if not b_texts: return -1
        
        best_match_score = 0
        best_match_idx = -1
        
        for future_idx in range(e_idx + 1, lookahead_limit - 2):
            phrase = [words[future_idx + k]["clean_text"] for k in range(3)]
            for b_i in range(len(b_texts) - 2):
                s1 = rapidfuzz.fuzz.ratio(phrase[0], b_texts[b_i])
                s2 = rapidfuzz.fuzz.ratio(phrase[1], b_texts[b_i+1])
                s3 = rapidfuzz.fuzz.ratio(phrase[2], b_texts[b_i+2])
                avg_score = (s1 + s2 + s3) / 3.0
                if avg_score > 80 and avg_score > best_match_score:
                    best_match_score = avg_score
                    best_match_idx = future_idx
                    
        if best_match_score > 80:
            return best_match_idx
    except Exception:
        pass
    return -1