import re
import numpy as np
import rapidfuzz
from app_logger import get_logger
from aligner_utils import get_safe_bounds, get_vowel_weight, get_phonetic_bounds

log = get_logger("aligner_orchestra")

# ─── V9: SEMANTIC SCOUT (ПОИСК БОЛТОВНИ ВНЕ ТЕКСТА ПЕСНИ) ───────────────────

def semantic_scout(audio_data: np.ndarray, model, lang: str, words: list) -> list:
    """
    V9: Быстрая слепая транскрибация всего трека.
    Сравнивает услышанную речь с текстом Genius. 
    Все участки речи, которых НЕТ в песне (болтовня, выкрики залу),
    помечаются как Semantic Curtains (Семантические занавесы),
    чтобы DTW не привязывал к ним настоящие слова песни.
    """
    log.info("🕵️‍♂️ [Semantic Scout] Разведка трека на предмет лишней болтовни...")
    
    semantic_curtains = []
    
    # Берем весь чистый текст Genius для сравнения
    genius_text = " ".join([w["clean_text"] for w in words])
    
    try:
        # Слепая транскрибация всего аудио (fast mode)
        result = model.transcribe(audio_data, language=lang)
        blind_segments = result.segments
        
        if not blind_segments:
            return semantic_curtains
            
        for segment in blind_segments:
            seg_text = segment.text.strip()
            if not seg_text: continue
                
            clean_seg = re.sub(r'[^\w]', '', seg_text.lower())
            if len(clean_seg) < 3: continue # Игнорируем микро-вздохи
            
            # Ищем, есть ли услышанная фраза в тексте Genius
            match_score = rapidfuzz.fuzz.partial_ratio(clean_seg, genius_text)
            
            if match_score < 60:
                # Если совпадение меньше 60%, значит артист говорит что-то отсебятину
                log.warning(f"   🎙️ [Scout] Найдена болтовня: '{seg_text}' ({segment.start:.2f}s - {segment.end:.2f}s)")
                # Создаем Семантический Занавес (плюс небольшой паддинг)
                start_c = max(0.0, segment.start - 0.2)
                end_c = segment.end + 0.2
                semantic_curtains.append((start_c, end_c))
                
        return semantic_curtains
        
    except Exception as e:
        log.error(f"   ❌ Ошибка Семантического Скаута: {e}")
        return []

# ─── V9: MACRO-COMPASS (ДЕТЕКТОР ГЛОБАЛЬНОГО РАССИНХРОНА) ───────────────────

def macro_compass(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, t_start: float, t_end: float, model, lang: str) -> bool:
    """
    V9: Слепая транскрибация для починки 'Порванных строк'.
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
        
        # Ищем совпадения из "будущих" строк
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
            
            # Обнуляем якоря до будущей строки (ломаем кость)
            for k in range(s_idx, best_match_idx):
                words[k]["start"] = words[k]["end"] = -1.0
                
            # И саму будущую строку сбрасываем, чтобы она пере-выровнялась (вправили сустав)
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
            # Двойник должен быть 100% здоров
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

def heal_by_chorus(words: list, s_idx: int, e_idx: int, vad_mask: list) -> bool:
    """Копирует тайминги, но предварительно проверяет, не ложатся ли клонируемые слова в тишину (VAD)."""
    target_cluster = [words[i]["clean_text"] for i in range(s_idx, e_idx + 1)]
    target_len = len(target_cluster)
    if target_len < 4: return False 
    
    for i in range(len(words) - target_len):
        if s_idx <= i <= e_idx: continue 
        
        source_cluster = [words[k]["clean_text"] for k in range(i, i + target_len)]
        if source_cluster == target_cluster:
            if all(words[k]["start"] != -1 for k in range(i, i + target_len)):
                src_start = words[i]["start"]
                dst_start, _ = get_safe_bounds(words, s_idx, e_idx, 9999.0)
                
                mapped_timings = []
                for k in range(target_len):
                    ns = dst_start + (words[i + k]["start"] - src_start)
                    ne = dst_start + (words[i + k]["end"] - src_start)
                    mapped_timings.append((ns, ne))
                    
                overlap = 0.0
                total_dur = 0.0
                for ms, me in mapped_timings:
                    dur = me - ms
                    total_dur += dur
                    for vs, ve in vad_mask:
                        o_s, o_e = max(ms, vs), min(me, ve)
                        if o_e > o_s: overlap += (o_e - o_s)
                
                # Если клон слишком сильно вылезает за пределы вокала - бракуем
                if total_dur > 0 and (overlap / total_dur) < 0.4:
                    continue
                    
                log.info(f"[Orchestra] Найден структурный клон (индексы {i}-{i+target_len}). Клонируем ритм!")
                for k in range(target_len):
                    words[s_idx + k]["start"] = mapped_timings[k][0]
                    words[s_idx + k]["end"] = mapped_timings[k][1]
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

def heal_blind_fuzzy(words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, t_start: float, t_end: float, model, lang: str, aggressive: bool, vad_mask: list, apply_vad_deafness_fn) -> bool:
    """Слепой маппинг. Транскрибируем звук без субтитров и пытаемся найти наши слова в результате."""
    if t_end - t_start < 0.2: return False
    
    log.info(f"[Orchestra] Слепой Маппинг для слов {s_idx}-{e_idx}...")
    try:
        sr = 16000
        crop_audio = audio_data[int(t_start * sr) : int(t_end * sr)]
        if len(crop_audio) < sr * 0.2: return False

        if aggressive and vad_mask:
            crop_audio = apply_vad_deafness_fn(crop_audio, sr, t_start, vad_mask)

        result = model.transcribe(crop_audio, language=lang)
        blind_words = result.all_words()
        
        if not blind_words: return False

        b_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in blind_words]
        healed = 0
        b_ptr = 0
        
        for k in range(s_idx, e_idx + 1):
            clean = words[k]["clean_text"]
            best_score, best_idx = 0, -1
            for j in range(b_ptr, min(b_ptr + 5, len(b_texts))):
                if not b_texts[j]: continue
                score = rapidfuzz.fuzz.ratio(clean, b_texts[j])
                if score > best_score:
                    best_score, best_idx = score, j
            
            if best_idx != -1 and best_score > 60:
                bw = blind_words[best_idx]
                words[k]["start"] = t_start + bw.start
                words[k]["end"] = t_start + bw.end
                b_ptr = best_idx + 1
                healed += 1
        
        return healed > (e_idx - s_idx) * 0.4
    except Exception as e:
        log.warning(f"[Orchestra] Слепой маппинг не удался: {e}")
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

def heal_with_onsets(words: list, s_idx: int, e_idx: int, onsets: list, t_start: float, t_end: float) -> bool:
    """Сажает слова на пики звука (Onset)."""
    local_onsets = [o for o in onsets if t_start <= o <= t_end]
    word_count = (e_idx - s_idx) + 1
    
    if len(local_onsets) < word_count * 0.4:
        return False
        
    curr_onset_idx = 0
    for k in range(s_idx, e_idx + 1):
        if curr_onset_idx < len(local_onsets):
            start_time = local_onsets[curr_onset_idx]
            words[k]["start"] = start_time
            _, max_dur = get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])
            words[k]["end"] = start_time + min(0.4, max_dur)
            
            step = max(1, len(local_onsets) // word_count)
            curr_onset_idx += step
        else:
            break
    return True