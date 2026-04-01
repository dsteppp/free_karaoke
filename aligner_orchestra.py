import re
import numpy as np
import rapidfuzz
from app_logger import get_logger
from aligner_utils import (
    get_safe_bounds, get_vowel_weight, get_phonetic_bounds, 
    calculate_overlap, is_repetition_island
)

log = get_logger("aligner")

class Proposal:
    """Обертка для предложенных таймингов от инструмента на Арене."""
    def __init__(self, source_name: str, timings: list):
        self.source_name = source_name
        self.timings = timings  
        self.score = 0.0

# ─── АРЕНА: КАНДИДАТ 1 (MOTIF MATRIX) ───────────────────────────────────────

def propose_motif_matrix(words: list, s_idx: int, e_idx: int, audio_duration: float, strong_vad: list) -> Proposal:
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

# ─── АРЕНА: КАНДИДАТ 3 (SEMANTIC HARPOON) ───────────────────────────────────

def propose_harpoon(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, model, lang: str, t_start: float, t_end: float) -> Proposal:
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

# ─── АРЕНА: КАНДИДАТ 4 (SMART ELASTIC LOOM V6.2) ────────────────────────────

def propose_loom(words: list, s_idx: int, e_idx: int, t_start: float, t_end: float, strong_vad: list, weak_vad: list, empirical_data: dict = None) -> Proposal:
    """
    V6.2: Умный Гибкий Короб (Smart Elastic Box).
    + VAD-Seeker: не прижимает коробку к левому краю, если там нет голоса.
    """
    combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])
    
    # V6.2 VAD-SEEKER: Ищем ПЕРВЫЙ настоящий голос в этой дыре. Безопасные границы!
    actual_start = t_start
    # Включаем сканер, если это начало песни ИЛИ дыра огромная (>4 секунд)
    if s_idx == 0 or (t_end - t_start) > 4.0:
        for vs, ve in strong_vad:
            # Ищем вокал строго ВНУТРИ нашей дыры
            if vs >= t_start and vs < t_end - 0.5:
                actual_start = vs
                log.debug(f"   [Loom] VAD-Seeker сдвинул старт с {t_start:.1f}s на {actual_start:.1f}s")
                break
            # Если голос уже идет с прошлой дыры - всё ок, стартуем сразу
            elif vs < t_start and ve > t_start + 0.2:
                actual_start = t_start
                break
    
    valid_vads = []
    for (vs, ve) in combined_vad:
        c_s, c_e = max(actual_start, vs), min(t_end, ve)
        if c_e - c_s > 0.05: valid_vads.append((c_s, c_e))
        
    if not valid_vads:
        valid_vads = [(actual_start, max(actual_start + 0.1, t_end))]
        
    def _map_time(t_vad: float, vads: list) -> float:
        accum = 0.0
        for (vs, ve) in vads:
            d = ve - vs
            if t_vad <= accum + d:
                return vs + (t_vad - accum)
            accum += d
        return vads[-1][1]

    lines = []
    curr_line = []
    for k in range(s_idx, e_idx + 1):
        curr_line.append(k)
        if words[k]["line_break"] or k == e_idx:
            lines.append(curr_line)
            curr_line = []
            
    total_vad_time = sum(e - s for s, e in valid_vads)

    req_durs = []
    for line in lines:
        if empirical_data:
            w_sample = words[line[0]]
            h_id = w_sample.get("homologous_id", -1)
            s_num = w_sample.get("stanza_num", -1)
            
            if h_id != -1 and h_id in empirical_data["homo_durations"]:
                dur = empirical_data["homo_durations"][h_id]
            else:
                vowels = sum(1 for k in line for c in words[k]["clean_text"] if c in "аеёиоуыэюяaeiouy")
                sdr = empirical_data["stanza_sdr"].get(s_num, empirical_data.get("global_sdr", 3.0))
                dur = max(1, vowels) / sdr
        else:
            dur = sum(get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in line) * 0.3
        req_durs.append(dur)

    total_req = sum(req_durs)
    breath_gap = min(empirical_data.get("avg_breath_gap", 0.5), 1.0) if empirical_data else 0.4

    # V6.2 ELASTICITY
    if total_req < total_vad_time and len(lines) > 0:
        for i, L in enumerate(req_durs):
            pseudo_s = sum(req_durs[:i]) + (i * breath_gap)
            pseudo_e = pseudo_s + L
            
            real_s = _map_time(pseudo_s, valid_vads)
            real_e = _map_time(pseudo_e, valid_vads)
            
            strong_capacity = calculate_overlap(real_s, real_e + 2.0, strong_vad) 
            
            if strong_capacity > L * 1.2:
                req_durs[i] = min(strong_capacity, L * 1.5)
                
        total_req = sum(req_durs)

    if total_req > total_vad_time and total_req > 0:
        scale = total_vad_time / total_req
        req_durs = [d * scale for d in req_durs]
        breath_gap = 0.1 
        log.debug(f"   [Loom] Окно мало ({total_vad_time:.1f}s < {total_req:.1f}s). Сжатие коробок.")

    line_boxes = []
    curr_vad_t = 0.0

    for L in req_durs:
        if curr_vad_t + L > total_vad_time:
            L = max(0.1, total_vad_time - curr_vad_t)
            
        line_boxes.append((curr_vad_t, curr_vad_t + L))
        curr_vad_t += L + breath_gap

    timings = []
    for l_idx, line in enumerate(lines):
        l_logic_s, l_logic_e = line_boxes[l_idx]
        
        l_real_s = _map_time(l_logic_s, valid_vads)
        l_real_e = _map_time(l_logic_e, valid_vads)

        line_vads = []
        for (vs, ve) in valid_vads:
            c_s, c_e = max(l_real_s, vs), min(l_real_e, ve)
            if c_e > c_s: line_vads.append((c_s, c_e))
        if not line_vads: 
            line_vads = [(l_real_s, l_real_e)]
            
        line_total_vad = sum(e - s for s, e in line_vads)
        w_curr_vad_t = 0.0
        
        lw_total = sum(get_vowel_weight(words[k]["clean_text"], False) for k in line)
        if lw_total == 0: lw_total = 1.0

        for k in line:
            w_w = get_vowel_weight(words[k]["clean_text"], False) 
            w_dur = (w_w / lw_total) * line_total_vad
            
            w_s = _map_time(w_curr_vad_t, line_vads)
            w_e = _map_time(w_curr_vad_t + w_dur * 0.95, line_vads)
            
            timings.append({"start": w_s, "end": w_e})
            w_curr_vad_t += w_dur
            
    return Proposal("Smart Elastic Loom", timings)


# ─── THE SUPREME JUDGE (АБСОЛЮТНЫЙ СУДЬЯ АРЕНЫ V6.2) ─────────────────────────

def the_supreme_judge(proposals: list, words: list, s_idx: int, e_idx: int, strong_vad: list, weak_vad: list, curtains: list, empirical_data: dict = None) -> Proposal:
    """
    V6.2: Штрафует за попадание в Мертвые Зоны (Curtains),
    Использует VAD-Индульгенцию для растянутых слов.
    УНИЧТОЖАЕТ ФАЛЬСТАРТЫ (Смертный приговор для интро).
    """
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
        
        # 1. Пословная оценка (Микро-акустика и Нарушение Мертвых Зон)
        for i, t in enumerate(prop.timings):
            dur = t["end"] - t["start"]
            min_dur, max_dur = get_phonetic_bounds(clean_texts[i], line_breaks[i])
            
            if dur < 0.08:
                score -= 1000.0  # СМЕРТНЫЙ ПРИГОВОР ЗА СИНГУЛЯРНОСТЬ
            elif dur < min_dur: 
                score -= 200.0 * (min_dur - dur)
                
            # ЗАПРЕТ НА МЕРТВЫЕ ЗОНЫ (Iron Curtains)
            overlap_curtain = calculate_overlap(t["start"], t["end"], curtains)
            if overlap_curtain > 0.05:
                score -= 2000.0 * overlap_curtain
                
            overlap_strong = calculate_overlap(t["start"], t["end"], strong_vad)
            overlap_weak = calculate_overlap(t["start"], t["end"], weak_vad)
            silence_dur = dur - overlap_strong - overlap_weak
            
            if overlap_strong > 0.1: score += 5.0
            
            # V6.2 VAD-ИНДУЛЬГЕНЦИЯ НА ПЕРЕРАСТЯЖЕНИЕ
            if dur > max_dur * 1.5: 
                if (overlap_strong / dur) < 0.8: # Если резина легла не на вокал
                    score -= 100.0 * (dur - max_dur)
            
            # V6.2 СМЕРТНЫЙ ПРИГОВОР ЗА ФАЛЬСТАРТ (Защита интро от Лома)
            w_abs_idx = s_idx + i
            if w_abs_idx < 3 and t["start"] < 2.0:
                if dur > 0 and (overlap_strong / dur) < 0.5:
                    score -= 5000.0
                    log.debug(f"   🚫 Судья убил предложение {prop.source_name} за Фальстарт в интро.")
            
            if silence_dur > 0.15: 
                score -= (silence_dur * 200.0) 

        # 2. Макро-оценка Строки (Эмпирическая защита)
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
            
            if empirical_data:
                w_abs_idx = s_idx + line[0]
                h_id = words[w_abs_idx].get("homologous_id", -1)
                s_num = words[w_abs_idx].get("stanza_num", -1)
                
                if h_id != -1 and h_id in empirical_data["homo_durations"]:
                    l_min = empirical_data["homo_durations"][h_id] * 0.75 
                else:
                    vowels = sum(1 for k in line for c in clean_texts[k] if c in "аеёиоуыэюяaeiouy")
                    sdr = empirical_data["stanza_sdr"].get(s_num, empirical_data.get("global_sdr", 3.0))
                    l_min = (max(1, vowels) / sdr) * 0.7 
            else:
                l_min = sum(get_phonetic_bounds(clean_texts[k], line_breaks[k])[0] for k in line)
            
            if l_dur < l_min:
                # WALL EXEMPTION (Индульгенция перед Стеной)
                hit_the_wall = any(abs(c_s - l_e) < 0.5 for c_s, c_e in curtains)
                
                if not hit_the_wall:
                    score -= 500.0 * (l_min - l_dur) 
                else:
                    log.debug(f"   🛡️ Судья простил сжатие строки (упор в Железный Занавес на {l_e:.1f}s).")
                
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
    """Щупает будущее на предмет глобальных сдвигов."""
    if is_repetition_island(words, s_idx, e_idx):
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