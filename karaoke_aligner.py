import os
import gc
import re
import json
import torch
import librosa
import numpy as np
import stable_whisper
import rapidfuzz
from app_logger import get_logger, dump_debug

log = get_logger("aligner")

class KaraokeAligner:
    """
    Пайплайн выравнивания "Ensemble Agent V2".
    Архитектура:
    1. Skeleton: Жесткая V21 платиновая логика (база).
    2. Critic: Аудит JSON на аномалии (BlackHole, Orphan, Overstretch).
    3. Surgeon: Разрушение ложных якорей и Micro-DTW.
    4. Physics: Hard VAD + Музыкальная гравитация для остатков.
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""

    # ─── БАЗОВЫЕ УТИЛИТЫ ────────────────────────────────────────────────────────
    
    def _detect_language(self, text: str) -> str:
        cyrillic = len(re.findall(r'[\u0400-\u04FFёЁ]', text))
        hangul = len(re.findall(r'[\uac00-\ud7a3]', text))
        latin = len(re.findall(r'[a-zA-Z]', text))
        
        if hangul > 10: return "ko" 
        if cyrillic > latin * 0.3: return "ru" 
        return "en"     

    def _prepare_text(self, text: str) -> list:
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
                        "dtw_tried": False # Флаг агента
                    })
        return words_list

    def _get_vowel_weight(self, word: str, is_line_end: bool) -> float:
        vowels = set("аеёиоуыэюяaeiouy")
        clean = word.lower()
        v_count = sum(1 for c in clean if c in vowels)
        weight = float(max(1, v_count))
        if is_line_end:
            weight *= 2.5 
        return weight

    # ─── ФИЗИКА (HARD VAD) ──────────────────────────────────────────────────────

    def _compute_hard_vad(self, audio_data: np.ndarray, sr: int, hop_length=512) -> list:
        log.info("[Physics] Сканирование Hard VAD (RMS Energy)...")
        rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
        rms_norm = rms / (np.max(rms) + 1e-8)
        
        threshold = 0.015 # 1.5% от пиковой громкости (отсекает шумы и тихие гитары)
        vad_frames = rms_norm > threshold
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
        
        intervals, in_speech, start_t = [], False, 0.0
        
        for t, is_active in zip(times, vad_frames):
            if is_active and not in_speech:
                start_t = t
                in_speech = True
            elif not is_active and in_speech:
                intervals.append((start_t, t))
                in_speech = False
        if in_speech:
            intervals.append((start_t, times[-1]))
            
        merged = []
        for s, e in intervals:
            if not merged:
                merged.append((s, e))
            else:
                last_s, last_e = merged[-1]
                if s - last_e < 0.5: # Склеиваем дыхание до 500мс
                    merged[-1] = (last_s, max(last_e, e))
                else:
                    if e - s > 0.1: # Игнор микро-щелчков
                        merged.append((s, e))
                        
        return merged

    # ─── ЭТАП 1: SKELETON (V21 PLATINUM LOGIC) ──────────────────────────────────

    def _platinum_skeleton(self, model, audio_data: np.ndarray, canon_words: list, lang: str):
        log.info("[Actor] Фаза 1: Сборка жесткого скелета (Platinum V21)...")
        text_for_whisper = " ".join([w["word"] for w in canon_words])
        
        try:
            result = model.align(audio_data, text_for_whisper, language=lang)
            sw_words = result.all_words()
            # Проверка откровенного мусора
            bad_count = sum(1 for w in sw_words if (w.end - w.start) < 0.05)
            if bad_count / len(sw_words) > 0.15:
                raise ValueError("DTW Failed")
        except Exception:
            log.warning("[Actor] DTW забракован. Переход на слепую транскрибацию...")
            result = model.transcribe(audio_data, language=lang)
            sw_words = result.all_words()

        valid_sw = []
        last_t = 0.0
        for w in sw_words:
            if (w.end - w.start) < 0.05: continue
            cl = re.sub(r'[^\w]', '', w.word.lower())
            if cl:
                start_t = max(last_t, w.start)
                end_t = max(start_t + 0.05, w.end)
                valid_sw.append({"clean": cl, "start": start_t, "end": end_t})
                last_t = end_t
                
        canon_idx, sw_idx = 0, 0
        last_anchored_idx, last_anchored_time = -1, 0.0
        anchors_count, search_window = 0, 60
        
        while canon_idx < len(canon_words) and sw_idx < len(valid_sw):
            best_match_len, best_c_idx = 0, -1
            
            for c in range(canon_idx, min(canon_idx + search_window, len(canon_words))):
                match_len = 0
                while (c + match_len < len(canon_words) and 
                       sw_idx + match_len < len(valid_sw) and 
                       canon_words[c + match_len]["clean_text"] == valid_sw[sw_idx + match_len]["clean"]):
                    match_len += 1
                
                if match_len > best_match_len:
                    best_match_len = match_len
                    best_c_idx = c
                    
            is_platinum = False
            if best_match_len >= 3: is_platinum = True
            elif best_match_len == 2:
                w1 = canon_words[best_c_idx]["clean_text"]
                w2 = canon_words[best_c_idx+1]["clean_text"]
                if len(w1) + len(w2) >= 7: is_platinum = True
            elif best_match_len == 1:
                w1 = canon_words[best_c_idx]["clean_text"]
                if len(w1) >= 8: is_platinum = True

            # Физика Архимеда (Защита от сдвигов)
            if is_platinum:
                if last_anchored_idx != -1:
                    prev_words = canon_words[last_anchored_idx + 1 : best_c_idx]
                    avail_time = valid_sw[sw_idx]["start"] - last_anchored_time
                    if prev_words:
                        min_req_time = sum(self._get_vowel_weight(w["clean_text"], w["line_break"]) for w in prev_words) * 0.15
                        if avail_time < min_req_time:
                            is_platinum = False
                        
            if is_platinum:
                for k in range(best_match_len):
                    canon_words[best_c_idx + k]["start"] = valid_sw[sw_idx + k]["start"]
                    canon_words[best_c_idx + k]["end"] = valid_sw[sw_idx + k]["end"]
                
                last_anchored_idx = best_c_idx + best_match_len - 1
                last_anchored_time = valid_sw[sw_idx + best_match_len - 1]["end"]
                canon_idx = best_c_idx + best_match_len
                sw_idx += best_match_len
                anchors_count += best_match_len
            else:
                sw_idx += 1

        log.info(f"[Actor] Платиновый скелет установлен: {anchors_count}/{len(canon_words)} слов.")

    # ─── ЭТАП 2: CRITIC & SURGEON (AGENT LOOP) ──────────────────────────────────

    def _audit_json(self, words: list) -> list:
        bugs = []
        n = len(words)
        
        for i in range(n):
            w = words[i]
            if w["start"] == -1: continue
            dur = w["end"] - w["start"]
            
            # 1. СИНГУЛЯРНОСТЬ (BLACK_HOLE)
            if dur <= 0.05:
                bugs.append({"type": "BLACK_HOLE", "idx": i})
            
            # 2. РЕЗИНА (OVERSTRETCH)
            vowel_w = self._get_vowel_weight(w["clean_text"], w["line_break"])
            if dur > (vowel_w * 0.9 + 0.6) and dur > 2.0:
                bugs.append({"type": "OVERSTRETCH", "idx": i})
                
            # 3. ОТОРВАННЫЙ ОСТРОВ (ORPHAN)
            if i < n - 1 and words[i+1]["start"] != -1:
                gap = words[i+1]["start"] - w["end"]
                # Если слова из одной строчки разорваны > 6 сек - это галлюцинация
                if gap > 6.0 and not w["line_break"]:
                    bugs.append({"type": "ORPHAN", "idx": i})

        return bugs

    def _fix_bugs(self, words: list, bugs: list, vad_mask: list):
        for bug in bugs:
            idx = bug["idx"]
            w = words[idx]
            
            if bug["type"] == "ORPHAN":
                log.warning(f"[Surgeon] Удален фальшивый якорь ORPHAN: '{w['clean_text']}'")
                w["start"], w["end"] = -1.0, -1.0
                
            elif bug["type"] == "BLACK_HOLE":
                # Ломаем стену! Сносим якоря вокруг сингулярности, чтобы дать воздуху
                start_del = max(0, idx - 1)
                end_del = min(len(words) - 1, idx + 1)
                log.warning(f"[Surgeon] Взлом BLACK_HOLE (индексы {start_del}-{end_del}). Сброс якорей.")
                for k in range(start_del, end_del + 1):
                    words[k]["start"], words[k]["end"] = -1.0, -1.0

            elif bug["type"] == "OVERSTRETCH":
                # Применяем хирургический Hard VAD
                active_chunk = None
                for (vs, ve) in vad_mask:
                    if vs - 0.5 <= w["start"] <= ve + 0.5:
                        active_chunk = (vs, ve)
                        break
                
                old_end = w["end"]
                if active_chunk:
                    w["end"] = min(w["end"], active_chunk[1] + 0.2)
                
                # Физический потолок
                vowel_w = self._get_vowel_weight(w["clean_text"], w["line_break"])
                w["end"] = min(w["end"], w["start"] + vowel_w * 1.0 + 1.0)
                log.warning(f"[Surgeon] Хвост OVERSTRETCH обрублен: '{w['clean_text']}' ({old_end:.1f}s -> {w['end']:.1f}s)")

    def _find_gaps(self, words: list) -> list:
        gaps, i, n = [], 0, len(words)
        while i < n:
            if words[i]["start"] == -1 and not words[i]["dtw_tried"]:
                j = i
                while j < n and words[j]["start"] == -1: j += 1
                gaps.append((i, j - 1))
                i = j
            else: i += 1
        return gaps

    def _micro_dtw_surgery(self, words: list, gap: tuple, audio_data: np.ndarray, model, lang: str):
        s_idx, e_idx = gap
        
        # Определяем окно хирургии
        t_start = words[s_idx - 1]["end"] + 0.1 if s_idx > 0 and words[s_idx - 1]["end"] != -1 else 0.0
        t_end = len(audio_data) / 16000
        for k in range(e_idx + 1, len(words)):
            if words[k]["start"] != -1:
                t_end = words[k]["start"] - 0.1
                break

        # Защита от нулевых окон
        if t_end <= t_start + 0.5:
            for k in range(s_idx, e_idx + 1): words[k]["dtw_tried"] = True
            return

        log.info(f"[Surgeon] Micro-DTW для слов [{s_idx}-{e_idx}] в окне {t_start:.1f}s - {t_end:.1f}s")
        
        sr = 16000
        crop_audio = audio_data[int(t_start * sr) : int(t_end * sr)]
        crop_text = " ".join([words[i]["word"] for i in range(s_idx, e_idx + 1)])
        
        try:
            res = model.align(crop_audio, crop_text, language=lang)
            c_sw = res.all_words()
            
            s_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in c_sw]
            c_ptr = 0
            for k in range(s_idx, e_idx + 1):
                words[k]["dtw_tried"] = True # Отмечаем, что пытались
                c_clean = words[k]["clean_text"]
                best_score, best_match = 0, -1
                
                for j in range(c_ptr, min(c_ptr + 5, len(s_texts))):
                    score = rapidfuzz.fuzz.ratio(c_clean, s_texts[j])
                    if score > 75 and score > best_score:
                        best_score, best_match = score, j
                        if score == 100: break
                
                if best_match != -1 and (c_sw[best_match].end - c_sw[best_match].start) > 0.05:
                    words[k]["start"] = t_start + c_sw[best_match].start
                    words[k]["end"] = t_start + c_sw[best_match].end
                    c_ptr = best_match + 1
        except Exception as e:
            log.warning(f"[Surgeon] Micro-DTW не справился ({e}). Будет применена гравитация.")
            for k in range(s_idx, e_idx + 1): words[k]["dtw_tried"] = True

    # ─── ЭТАП 3: ФИЗИКА И ГРАВИТАЦИЯ (ПОСЛЕДНЯЯ НАДЕЖДА) ────────────────────────

    def _apply_gravity(self, words: list, audio_duration: float, vad_mask: list):
        log.info("[Physics] Гравитационная заливка слепых зон...")
        n = len(words)
        
        # Получаем живые интервалы VAD
        def get_available_vad(t_min, t_max):
            res = []
            for (vs, ve) in vad_mask:
                i_s, i_e = max(t_min, vs), min(t_max, ve)
                if i_e > i_s: res.append((i_s, i_e))
            return res

        i = 0
        while i < n:
            if words[i]["start"] == -1:
                j = i
                while j < n and words[j]["start"] == -1: j += 1
                
                t_start = words[i-1]["end"] + 0.1 if i > 0 and words[i-1]["end"] != -1 else 0.5
                t_end = words[j]["start"] - 0.1 if j < n and words[j]["start"] != -1 else audio_duration - 0.5
                if t_end <= t_start: t_end = t_start + 0.5

                active_vads = get_available_vad(t_start, t_end)
                weights = [self._get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
                total_w = sum(weights)
                
                # Если в этой зоне вообще нет голоса (соло/тишина) -> спрессовываем текст в 1 сек (защита от размазывания)
                total_vad_time = sum(e - s for s, e in active_vads)
                
                if total_vad_time < 0.5:
                    # Режим карантина!
                    safe_start = t_start
                    if i == 0 and active_vads: safe_start = active_vads[-1][0] # Интро жмем к началу
                    
                    curr_t = safe_start
                    for k in range(i, j):
                        w_dur = (weights[k-i] / total_w) * min(2.0, t_end - t_start)
                        words[k]["start"] = curr_t
                        words[k]["end"] = curr_t + w_dur * 0.9
                        curr_t += w_dur
                else:
                    # Размещаем СТРОГО внутри VAD
                    curr_t = 0.0
                    for k in range(i, j):
                        w_logic_dur = (weights[k-i] / total_w) * total_vad_time
                        
                        # Маппинг виртуального времени на реальный VAD
                        accum, mapped_s, mapped_e = 0.0, active_vads[0][0], active_vads[-1][1]
                        
                        for (vs, ve) in active_vads:
                            dur = ve - vs
                            if curr_t <= accum + dur:
                                mapped_s = vs + (curr_t - accum)
                                break
                            accum += dur
                            
                        accum = 0.0
                        for (vs, ve) in active_vads:
                            dur = ve - vs
                            if curr_t + w_logic_dur * 0.95 <= accum + dur:
                                mapped_e = vs + (curr_t + w_logic_dur * 0.95 - accum)
                                break
                            accum += dur
                            
                        words[k]["start"] = mapped_s
                        words[k]["end"] = mapped_e
                        curr_t += w_logic_dur
                i = j
            else:
                i += 1

    def _smoothing(self, words: list):
        """Защита от наложения таймингов."""
        last_e = 0.0
        for w in words:
            if w["start"] < last_e:
                w["start"] = last_e + 0.01
            if w["end"] <= w["start"]:
                w["end"] = w["start"] + 0.1
            last_e = w["end"]

    # ─── MAIN ───────────────────────────────────────────────────────────────────

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info(f"Aligner СТАРТ (Ensemble Agent V2): {self._track_stem}")
        
        canon_words = self._prepare_text(raw_lyrics)
        if not canon_words:
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = self._detect_language(raw_lyrics)
        model = None
        try:
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            
            vad_mask = self._compute_hard_vad(audio_data, sr)
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            # ЭТАП 1: Скелет (Platinum Logic)
            self._platinum_skeleton(model, audio_data, canon_words, lang)

            # ЭТАП 2: Агентный цикл
            for iteration in range(3):
                bugs = self._audit_json(canon_words)
                gaps = self._find_gaps(canon_words)
                
                if not bugs and not gaps:
                    log.info(f"[Critic] Итерация {iteration+1}: Аудит пройден. Скелет идеален.")
                    break
                    
                if bugs:
                    log.warning(f"[Critic] Итерация {iteration+1}: Найдено {len(bugs)} аномалий. Вызов хирурга...")
                    self._fix_bugs(canon_words, bugs, vad_mask)
                
                if gaps:
                    # Если хирург сбросил якоря, они станут gaps
                    for gap in gaps:
                        self._micro_dtw_surgery(canon_words, gap, audio_data, model, lang)
            
            # ЭТАП 3: Гравитация и Сглаживание
            self._apply_gravity(canon_words, audio_duration, vad_mask)
            self._smoothing(canon_words)

        except Exception as e:
            log.error(f"Ошибка Aligner: {e}")
            raise e
        finally:
            if model: del model
            if 'audio_data' in locals(): del audio_data
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()

        # Финализация
        final_json = []
        for w in canon_words:
            final_json.append({
                "word": w["word"], 
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "line_break": w["line_break"],
                "letters": [] 
            })
            
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, ensure_ascii=False, indent=2)

        dump_debug("2_Final_Ensemble", final_json, self._track_stem)
        log.info(f"Aligner ГОТОВО → {output_json_path}")
        log.info("=" * 50)
        
        return output_json_path