import re
import numpy as np
import rapidfuzz
from app_logger import get_logger
from aligner_utils import get_safe_bounds, get_vowel_weight, get_phonetic_bounds

log = get_logger("aligner_orchestra")

# ─── V11: СЕМАНТИЧЕСКИЙ ГАРПУН (SEMANTIC HARPOON) ──────────────────────────

def semantic_harpoon(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, t_start: float, t_end: float, model, lang: str) -> bool:
    """
    V11: Умная Точечная Реставрация через слепое прослушивание (Transcribe).
    Вместо принудительного размазывания слов (Align), Гарпун слушает аудио,
    ищет в нем наши потерянные слова и прибивает их только при хорошем совпадении.
    Остальное (паузы, соло, шум) игнорируется.
    """
    if t_end - t_start < 0.5: return False
    
    log.info(f"🎯 [Semantic Harpoon] Точечная реставрация слепым прослушиванием для слов [{s_idx}-{e_idx}]...")
    
    sr = 16000
    crop = audio_data[int(max(0, t_start - 0.2) * sr) : int(min(len(audio_data), (t_end + 0.2) * sr))]
    if len(crop) < sr * 0.5: return False
    
    try:
        # 1. Слепая транскрибация куска аудио (Vanilla)
        result = model.transcribe(crop, language=lang)
        blind_words = result.all_words()
        
        if not blind_words:
            log.warning("   ❌ Гарпун не услышал ни одного слова в зоне.")
            return False

        b_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in blind_words if w.word.strip()]
        
        if not b_texts:
            return False

        healed = 0
        b_ptr = 0
        
        # 2. Нечеткий поиск (Fuzzy Match)
        for k in range(s_idx, e_idx + 1):
            clean = words[k]["clean_text"]
            best_score, best_idx = 0, -1
            
            # Ищем совпадение в небольшом окне (защита от сдвигов)
            for j in range(b_ptr, min(b_ptr + 5, len(b_texts))):
                score = rapidfuzz.fuzz.ratio(clean, b_texts[j])
                if score > best_score:
                    best_score, best_idx = score, j
            
            # Если слово совпало хотя бы на 60%
            if best_idx != -1 and best_score > 60:
                bw = blind_words[best_idx]
                
                # Фильтр от сумасшедших таймингов (Whisper может выдавать слова по 0.02 сек или по 5 сек)
                dur = bw.end - bw.start
                _, max_dur = get_phonetic_bounds(clean, words[k]["line_break"])
                
                if 0.05 < dur <= max_dur * 1.5:
                    mapped_s = t_start - 0.2 + bw.start
                    mapped_e = t_start - 0.2 + bw.end
                    
                    # Прибиваем слово намертво
                    words[k]["start"] = mapped_s
                    words[k]["end"] = mapped_e
                    words[k]["dtw_tried"] = True
                    b_ptr = best_idx + 1
                    healed += 1
                else:
                    log.warning(f"   ⚠️ Слово '{clean}' найдено, но забраковано из-за длины ({dur:.2f}s).")
                    
        if healed > 0:
            log.info(f"   ✅ Гарпун восстановил {healed}/{(e_idx - s_idx + 1)} слов.")
            return True
            
    except Exception as e:
        log.warning(f"   ❌ Ошибка Гарпуна: {e}")
        
    return False

# ─── V11: MACRO-COMPASS (ДЕТЕКТОР ГЛОБАЛЬНОГО РАССИНХРОНА) ───────────────────

def macro_compass(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, t_start: float, t_end: float, model, lang: str) -> bool:
    """
    Слепая транскрибация для починки 'Порванных строк'.
    Если алгоритм слышит слова из "будущего", он сдвигает указатель текста вперед.
    """
    if (e_idx - s_idx) < 2: return False 
    if t_end - t_start < 1.0: return False
    
    log.info(f"🧭 [Macro-Compass] Проверка глобального рассинхрона [{s_idx}-{e_idx}]...")
    sr = 16000
    crop = audio_data[int(t_start * sr) : int(t_end * sr)]
    if len(crop) < sr * 0.2: return False
    
    try:
        result = model.transcribe(crop, language=lang)
        blind_words = result.all_words()
        if not blind_words: return False
        
        b_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in blind_words if w.word.strip()]
        if not b_texts: return False
        
        lookahead_limit = min(len(words), e_idx + 25)
        best_match_score = 0
        best_match_idx = -1
        
        for future_idx in range(e_idx + 1, lookahead_limit - 2):
            phrase = [words[future_idx + k]["clean_text"] for k in range(3)]
            for b_i in range(len(b_texts) - 2):
                score1 = rapidfuzz.fuzz.ratio(phrase[0], b_texts[b_i])
                score2 = rapidfuzz.fuzz.ratio(phrase[1], b_texts[b_i+1])
                score3 = rapidfuzz.fuzz.ratio(phrase[2], b_texts[b_i+2])
                
                avg_score = (score1 + score2 + score3) / 3.0
                if avg_score > 75 and avg_score > best_match_score:
                    best_match_score = avg_score
                    best_match_idx = future_idx
                    
        if best_match_score > 75:
            shift_amount = best_match_idx - s_idx
            log.warning(f"   🚨 [Macro-Compass] РАССИНХРОН! Артист поет '{words[best_match_idx]['clean_text']}', а мы ищем '{words[s_idx]['clean_text']}'")
            log.warning(f"   🔄 Сдвиг якорей на {shift_amount} слов вперед.")
            
            for k in range(s_idx, best_match_idx):
                words[k]["start"] = words[k]["end"] = -1.0
                
            for k in range(best_match_idx, min(len(words), best_match_idx + len(blind_words))):
                words[k]["start"] = words[k]["end"] = -1.0
            return True
            
    except Exception as e:
        log.warning(f"   ❌ Ошибка Компаса: {e}")
        
    return False

# ─── ИНСТРУМЕНТЫ ИСЦЕЛЕНИЯ (HEALERS) ────────────────────────────────────────

def heal_by_motif_matrix(words: list, s_idx: int, e_idx: int, audio_duration: float) -> bool:
    """Ищет идентичные здоровые строки-двойники во всем тексте и клонирует их тайминги."""
    target_phrase = " ".join([words[i]["clean_text"] for i in range(s_idx, e_idx + 1)])
    target_len = e_idx - s_idx + 1
    if target_len < 2: return False
    
    for i in range(len(words) - target_len + 1):
        if max(0, s_idx - target_len) <= i <= e_idx: continue
        
        source_phrase = " ".join([words[k]["clean_text"] for k in range(i, i + target_len)])
        if source_phrase == target_phrase:
            if all(words[k]["start"] != -1.0 for k in range(i, i + target_len)):
                twin_dur = words[i + target_len - 1]["end"] - words[i]["start"]
                if twin_dur < 0.2: continue
                
                log.info(f"🧬 [Motif Matrix] Найден здоровый двойник. Копирование матрицы для [{s_idx}-{e_idx}]!")
                t_start, _ = get_safe_bounds(words, s_idx, e_idx, audio_duration)
                src_start = words[i]["start"]
                
                for k in range(target_len):
                    rel_s = words[i + k]["start"] - src_start
                    rel_dur = words[i + k]["end"] - words[i + k]["start"]
                    
                    new_s = t_start + rel_s
                    new_e = new_s + rel_dur
                    words[s_idx + k]["start"] = new_s
                    words[s_idx + k]["end"] = max(new_s + 0.05, new_e)
                return True
    return False

def ctc_inquisitor(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, model, lang: str, t_start: float, t_end: float) -> bool:
    """Принудительный forced alignment на битом участке (допрос с пристрастием)."""
    if t_end - t_start < 0.3: return False
    log.info(f"⚔️ [CTC Inquisitor] Принудительный допрос (Forced Alignment) слов [{s_idx}-{e_idx}]...")
    sr = 16000
    crop = audio_data[int(t_start * sr) : int(t_end * sr)]
    if len(crop) < sr * 0.2: return False
    
    text = " ".join([words[i]["word"] for i in range(s_idx, e_idx + 1)])
    try:
        res = model.align(crop, text, language=lang, fast_mode=True)
        sw_words = res.all_words()
        
        valid_words = [w for w in sw_words if w.end - w.start >= 0.05]
        if len(valid_words) >= (e_idx - s_idx + 1) * 0.4:
            log.info("   ✅ Инквизитор успешно восстановил участок.")
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
                    words[k]["start"] = t_start + valid_words[best_match].start
                    words[k]["end"] = t_start + valid_words[best_match].end
                    c_ptr = best_match + 1
            return True
    except Exception as e:
        log.warning(f"   ❌ Ошибка Инквизитора: {e}")
    return False

def heal_phonetic_loom(words: list, s_idx: int, e_idx: int, t_start: float, t_end: float, vad_mask: list) -> bool:
    """Эластичный Ткацкий станок. Ограничивает растягивание слов по пустому VAD (когда нет других вариантов)."""
    log.info(f"[Orchestra] Ткацкий станок (The Loom) для слов {s_idx}-{e_idx}...")
    
    valid_vads = []
    for (vs, ve) in vad_mask:
        c_s, c_e = max(t_start, vs), min(t_end, ve)
        if c_e - c_s > 0.05: valid_vads.append((c_s, c_e))
        
    if not valid_vads:
        valid_vads = [(t_start, t_end)]
        
    weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(s_idx, e_idx + 1)]
    total_w = sum(weights)
    
    required_time = total_w * 0.3
    total_vad_time = sum(e - s for s, e in valid_vads)
    
    if total_vad_time > required_time * 1.5:
        allowed_time = required_time * 1.2
        trimmed_vads = []
        accum = 0.0
        for vs, ve in valid_vads:
            dur = ve - vs
            if accum + dur <= allowed_time:
                trimmed_vads.append((vs, ve))
                accum += dur
            else:
                trimmed_vads.append((vs, vs + (allowed_time - accum)))
                break
        valid_vads = trimmed_vads
        total_vad_time = sum(e - s for s, e in valid_vads)
        
    curr_t = 0.0
    for k in range(s_idx, e_idx + 1):
        w_logic_dur = (weights[k-s_idx] / total_w) * total_vad_time
        
        accum, mapped_s, mapped_e = 0.0, valid_vads[0][0], valid_vads[-1][1]
        
        for (vs, ve) in valid_vads:
            dur = ve - vs
            if curr_t <= accum + dur:
                mapped_s = vs + (curr_t - accum)
                break
            accum += dur
            
        accum = 0.0
        for (vs, ve) in valid_vads:
            dur = ve - vs
            if curr_t + w_logic_dur * 0.95 <= accum + dur:
                mapped_e = vs + (curr_t + w_logic_dur * 0.95 - accum)
                break
            accum += dur
            
        words[k]["start"] = mapped_s
        words[k]["end"] = mapped_e
        curr_t += w_logic_dur
        
    return True