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
    Пайплайн выравнивания "Symphony V4 (Smart Surgeon + The Tribunal & Orchestra)".
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""

    # ─── БАЗОВЫЕ УТИЛИТЫ И ЛИНГВИСТИКА ──────────────────────────────────────────
    
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
                        "dtw_tried": False
                    })
        return words_list

    def _get_vowel_weight(self, word: str, is_line_end: bool) -> float:
        """Классический метод V3 для расчёта веса гласных."""
        vowels = set("аеёиоуыэюяaeiouy")
        clean = word.lower()
        v_count = sum(1 for c in clean if c in vowels)
        weight = float(max(1, v_count))
        if is_line_end: weight *= 2.0 
        return weight

    def _get_phonetic_bounds(self, clean_text: str, is_line_end: bool) -> tuple:
        """Инструмент №3: Лингвистический Калькулятор (Физиологические лимиты для Трибунала)."""
        vowels = sum(1 for c in clean_text if c in "аеёиоуыэюяaeiouy")
        consonants = len(clean_text) - vowels
        
        min_dur = max(0.05, (vowels * 0.06) + (consonants * 0.03))
        max_dur = max(0.5, (vowels * 0.8) + (consonants * 0.15))
        if is_line_end: max_dur *= 2.0
        
        return min_dur, max_dur

    # ─── ИНСТРУМЕНТЫ АКУСТИЧЕСКОЙ ТОПОГРАФИИ (V4) ───────────────────────────────

    def _get_acoustic_maps(self, audio_data: np.ndarray, sr: int) -> tuple:
        log.info("[Orchestra] Генерация акустической топографии (VAD, Onsets, Harmonics)...")
        hop_length = 512
        times = librosa.frames_to_time(np.arange(len(audio_data)//hop_length + 1), sr=sr, hop_length=hop_length)

        # 1. Hard VAD (Энергия - старый надежный метод, перенесен сюда)
        rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
        rms_norm = rms / (np.max(rms) + 1e-8)
        vad_frames = rms_norm > 0.015 
        
        intervals, in_speech, start_t = [], False, 0.0
        for t, is_active in zip(times[:len(vad_frames)], vad_frames):
            if is_active and not in_speech:
                start_t, in_speech = t, True
            elif not is_active and in_speech:
                intervals.append((start_t, t))
                in_speech = False
        if in_speech: intervals.append((start_t, times[-1]))
            
        vad_mask = []
        for s, e in intervals:
            if not vad_mask: vad_mask.append((s, e))
            else:
                last_s, last_e = vad_mask[-1]
                if s - last_e < 0.5: vad_mask[-1] = (last_s, max(last_e, e))
                elif e - s > 0.1: vad_mask.append((s, e))

        # 2. Инструмент №1: Транзиенты (Удары)
        o_env = librosa.onset.onset_strength(y=audio_data, sr=sr)
        raw_onsets = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, units='time')
        onsets = [o_t for o_t in raw_onsets if any(vs <= o_t <= ve for (vs, ve) in vad_mask)]

        # 3. Инструмент №2: Трекер Мелодии (Spectral Flatness)
        flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length)[0]
        
        def is_harmonic(t_start, t_end):
            s_frame = librosa.time_to_frames(t_start, sr=sr, hop_length=hop_length)
            e_frame = librosa.time_to_frames(t_end, sr=sr, hop_length=hop_length)
            if s_frame >= e_frame or s_frame >= len(flatness): return False
            chunk = flatness[s_frame:e_frame]
            return np.median(chunk) < 0.05

        return vad_mask, onsets, is_harmonic

    # ─── ЭТАП 1: SKELETON (V3) ──────────────────────────────────────────────────

    def _platinum_skeleton(self, model, audio_data: np.ndarray, canon_words: list, lang: str):
        log.info("[Actor] Фаза 1: Сборка жесткого скелета (Platinum V21)...")
        text_for_whisper = " ".join([w["word"] for w in canon_words])
        
        try:
            result = model.align(audio_data, text_for_whisper, language=lang)
            sw_words = result.all_words()
            bad_count = sum(1 for w in sw_words if (w.end - w.start) < 0.05)
            if bad_count / len(sw_words) > 0.15: raise ValueError("DTW Failed")
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
                
        canon_idx, sw_idx, anchors_count = 0, 0, 0
        search_window = 60
        
        while canon_idx < len(canon_words) and sw_idx < len(valid_sw):
            best_match_len, best_c_idx = 0, -1
            for c in range(canon_idx, min(canon_idx + search_window, len(canon_words))):
                match_len = 0
                while (c + match_len < len(canon_words) and 
                       sw_idx + match_len < len(valid_sw) and 
                       canon_words[c + match_len]["clean_text"] == valid_sw[sw_idx + match_len]["clean"]):
                    match_len += 1
                if match_len > best_match_len:
                    best_match_len, best_c_idx = match_len, c
                    
            is_platinum = False
            if best_match_len >= 4: is_platinum = True
            elif best_match_len == 3:
                chars = sum(len(canon_words[best_c_idx + k]["clean_text"]) for k in range(3))
                if chars >= 12: is_platinum = True
            elif best_match_len == 2:
                chars = sum(len(canon_words[best_c_idx + k]["clean_text"]) for k in range(2))
                if chars >= 10: is_platinum = True

            if is_platinum:
                for k in range(best_match_len):
                    canon_words[best_c_idx + k]["start"] = valid_sw[sw_idx + k]["start"]
                    canon_words[best_c_idx + k]["end"] = valid_sw[sw_idx + k]["end"]
                canon_idx = best_c_idx + best_match_len
                sw_idx += best_match_len
                anchors_count += best_match_len
            else:
                sw_idx += 1

        log.info(f"[Actor] Платиновый скелет установлен: {anchors_count}/{len(canon_words)} слов.")

    # ─── ЭТАП 2: CRITIC & SURGEON (Оригинальная логика V3) ──────────────────────

    def _audit_json(self, words: list) -> list:
        bugs = []
        n = len(words)
        
        clusters = []
        curr_cluster = []
        for i in range(n):
            if words[i]["start"] != -1:
                curr_cluster.append(i)
            else:
                if curr_cluster: clusters.append(curr_cluster)
                curr_cluster = []
        if curr_cluster: clusters.append(curr_cluster)

        for cluster in clusters:
            if len(cluster) <= 3:
                first, last = cluster[0], cluster[-1]
                gap_left = words[first]["start"] - words[first-1]["end"] if first > 0 and words[first-1]["end"] != -1 else 15.0
                gap_right = words[last+1]["start"] - words[last]["end"] if last < n-1 and words[last+1]["start"] != -1 else 15.0
                
                if gap_left > 8.0 and gap_right > 8.0:
                    bugs.append({"type": "ISLAND_OF_LIES", "cluster": cluster})

        for i in range(n):
            w = words[i]
            if w["start"] == -1: continue
            dur = w["end"] - w["start"]
            
            if dur <= 0.05 or (i > 0 and words[i-1]["end"] != -1 and w["start"] < words[i-1]["start"]):
                bugs.append({"type": "BLACK_HOLE", "idx": i})
            
            vowel_w = self._get_vowel_weight(w["clean_text"], w["line_break"])
            if dur > (vowel_w * 0.8 + 0.5) and dur > 1.8:
                bugs.append({"type": "OVERSTRETCH", "idx": i})

        return bugs

    def _fix_bugs(self, words: list, bugs: list):
        for bug in bugs:
            if bug["type"] == "ISLAND_OF_LIES":
                log.warning(f"[Surgeon] Уничтожен ОСТРОВ ЛЖИ: слова {bug['cluster']}")
                for idx in bug["cluster"]:
                    words[idx]["start"], words[idx]["end"] = -1.0, -1.0
                    
            elif bug["type"] == "BLACK_HOLE":
                idx = bug["idx"]
                start_del, end_del = max(0, idx - 2), min(len(words) - 1, idx + 2)
                log.warning(f"[Surgeon] Взлом BLACK_HOLE (индексы {start_del}-{end_del}). Сброс якорей.")
                for k in range(start_del, end_del + 1):
                    words[k]["start"], words[k]["end"] = -1.0, -1.0

            elif bug["type"] == "OVERSTRETCH":
                idx = bug["idx"]
                w = words[idx]
                old_end = w["end"]
                vowel_w = self._get_vowel_weight(w["clean_text"], w["line_break"])
                w["end"] = w["start"] + vowel_w * 0.8 + 0.5
                log.warning(f"[Surgeon] Хвост OVERSTRETCH жестко обрублен: '{w['clean_text']}' ({old_end:.1f}s -> {w['end']:.1f}s)")

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
        
        t_start = words[s_idx - 1]["end"] + 0.1 if s_idx > 0 and words[s_idx - 1]["end"] != -1 else 0.0
        t_end = len(audio_data) / 16000
        for k in range(e_idx + 1, len(words)):
            if words[k]["start"] != -1:
                t_end = words[k]["start"] - 0.1
                break

        v_weights = sum(self._get_vowel_weight(words[i]["clean_text"], words[i]["line_break"]) for i in range(s_idx, e_idx + 1))
        est_dur = v_weights * 0.4
        
        window_len = t_end - t_start
        if window_len > est_dur * 3.0:
            if s_idx == 0:
                t_start = max(t_start, t_end - est_dur * 2.0)
            elif e_idx == len(words) - 1:
                t_end = min(t_end, t_start + est_dur * 2.0)

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
                words[k]["dtw_tried"] = True 
                c_clean = words[k]["clean_text"]
                best_score, best_match = 0, -1
                
                for j in range(c_ptr, min(c_ptr + 6, len(s_texts))):
                    score = rapidfuzz.fuzz.ratio(c_clean, s_texts[j])
                    if score > 75 and score > best_score:
                        best_score, best_match = score, j
                        if score == 100: break
                
                if best_match != -1:
                    dur = c_sw[best_match].end - c_sw[best_match].start
                    if 0.05 < dur < 2.0:
                        words[k]["start"] = t_start + c_sw[best_match].start
                        words[k]["end"] = t_start + c_sw[best_match].end
                        c_ptr = best_match + 1
        except Exception as e:
            log.warning(f"[Surgeon] Micro-DTW не справился ({e}).")
            for k in range(s_idx, e_idx + 1): words[k]["dtw_tried"] = True

    # ─── ЭТАП 3: ФИНАЛЬНЫЙ ТРИБУНАЛ (V4) ────────────────────────────────────────

    def _run_tribunal(self, words: list, is_harmonic_fn) -> list:
        """Инспектор V4. Ищет то, с чем не справился Surgeon."""
        quarantine_zones = []
        n = len(words)
        i = 0
        
        while i < n:
            # 1. Дыры, которые Surgeon не смог закрыть
            if words[i]["start"] == -1:
                j = i
                while j < n and words[j]["start"] == -1: j += 1
                quarantine_zones.append((i, j - 1, "UNRESOLVED_GAP"))
                i = j
                continue
                
            dur = words[i]["end"] - words[i]["start"]
            min_dur, max_dur = self._get_phonetic_bounds(words[i]["clean_text"], words[i]["line_break"])
            
            # 2. Ловим OVERSTRETCH через Трекер Мелодии
            if dur > max_dur and dur > 2.0:
                if not is_harmonic_fn(words[i]["start"] + max_dur, words[i]["end"]):
                    log.warning(f"[Tribunal] Резина найдена на '{words[i]['clean_text']}'. Обрезаем (Шум/Эхо).")
                    words[i]["end"] = words[i]["start"] + max_dur
            
            # 3. Ловим BLACK HOLE через Лингвистику (Спрессованная каша)
            if words[i]["start"] != -1:
                j = i
                cluster_min_dur = 0.0
                while j < n and words[j]["start"] != -1 and (words[j]["end"] - words[i]["start"] < 1.5):
                    mn, _ = self._get_phonetic_bounds(words[j]["clean_text"], words[j]["line_break"])
                    cluster_min_dur += mn
                    j += 1
                
                real_dur = words[j-1]["end"] - words[i]["start"] if j > i else 0
                if (j - i) >= 3 and real_dur < (cluster_min_dur * 0.7):
                    quarantine_zones.append((i, j - 1, "PHYSICAL_IMPOSSIBILITY"))
                    i = j
                    continue
            i += 1
            
        return quarantine_zones

    # ─── ЭТАП 4: ОРКЕСТР (СТРАТЕГИИ ИСЦЕЛЕНИЯ V4) ───────────────────────────────

    def _heal_by_chorus(self, words: list, s_idx: int, e_idx: int) -> bool:
        """Инструмент №4: Кросс-Корреляционный Радар"""
        target_cluster = [words[i]["clean_text"] for i in range(s_idx, e_idx + 1)]
        target_len = len(target_cluster)
        if target_len < 4: return False 
        
        for i in range(len(words) - target_len):
            if s_idx <= i <= e_idx: continue 
            
            source_cluster = [words[k]["clean_text"] for k in range(i, i + target_len)]
            if source_cluster == target_cluster:
                if all(words[k]["start"] != -1 for k in range(i, i + target_len)):
                    log.info(f"[Orchestra] Найден структурный клон (индексы {i}-{i+target_len}). Клонируем ритм!")
                    
                    src_start = words[i]["start"]
                    dst_start = words[s_idx - 1]["end"] + 0.3 if s_idx > 0 and words[s_idx - 1]["end"] != -1 else 0.0
                    
                    for k in range(target_len):
                        words[s_idx + k]["start"] = dst_start + (words[i + k]["start"] - src_start)
                        words[s_idx + k]["end"] = dst_start + (words[i + k]["end"] - src_start)
                    return True
        return False

    def _heal_blind_fuzzy(self, words: list, s_idx: int, e_idx: int, audio_data: np.ndarray, t_start: float, t_end: float, model, lang: str) -> bool:
        """Слепая транскрибация галлюцинаций"""
        log.info(f"[Orchestra] Слепой Маппинг для слов {s_idx}-{e_idx}...")
        try:
            crop_audio = audio_data[int(t_start * 16000) : int(t_end * 16000)]
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

    def _heal_with_onsets(self, words: list, s_idx: int, e_idx: int, onsets: list, t_start: float, t_end: float) -> bool:
        """Инструмент №1: Прибиваем слова к физическим ударам"""
        log.info(f"[Orchestra] Ритмический Магнит для слов {s_idx}-{e_idx}...")
        local_onsets = [o for o in onsets if t_start <= o <= t_end]
        word_count = (e_idx - s_idx) + 1
        
        if len(local_onsets) < word_count * 0.4:
            return False
            
        curr_onset_idx = 0
        for k in range(s_idx, e_idx + 1):
            if curr_onset_idx < len(local_onsets):
                start_time = local_onsets[curr_onset_idx]
                words[k]["start"] = start_time
                _, max_dur = self._get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])
                words[k]["end"] = start_time + min(0.4, max_dur)
                
                step = max(1, len(local_onsets) // word_count)
                curr_onset_idx += step
            else:
                break
        return True

    # ─── ЭТАП 5: ФИЗИКА И ГРАВИТАЦИЯ (V3 Оригинал) ──────────────────────────────

    def _apply_gravity(self, words: list, audio_duration: float, vad_mask: list):
        log.info("[Physics] Гравитационная заливка слепых зон...")
        n = len(words)
        
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
                
                total_vad_time = sum(e - s for s, e in active_vads)
                
                if total_vad_time < 0.5:
                    safe_start = t_start
                    if i == 0 and active_vads: safe_start = active_vads[-1][0] 
                    elif j == n and active_vads: safe_start = active_vads[0][0]
                    
                    curr_t = safe_start
                    for k in range(i, j):
                        w_dur = (weights[k-i] / total_w) * min(2.0, t_end - t_start)
                        words[k]["start"] = curr_t
                        words[k]["end"] = curr_t + w_dur * 0.9
                        curr_t += w_dur
                else:
                    curr_t = 0.0
                    for k in range(i, j):
                        w_logic_dur = (weights[k-i] / total_w) * total_vad_time
                        
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
        last_e = 0.0
        for w in words:
            if w["start"] < last_e:
                w["start"] = last_e + 0.01
            if w["end"] <= w["start"]:
                w["end"] = w["start"] + 0.1
            last_e = w["end"]

    # ─── MAIN ORCHESTRATOR ──────────────────────────────────────────────────────

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info(f"Aligner СТАРТ (Symphony V4): {self._track_stem}")
        
        canon_words = self._prepare_text(raw_lyrics)
        if not canon_words:
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = self._detect_language(raw_lyrics)
        model = None
        try:
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            
            # Топография
            vad_mask, onsets, is_harmonic_fn = self._get_acoustic_maps(audio_data, sr)
            
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            # ЭТАП 1: Скелет (Platinum Logic)
            self._platinum_skeleton(model, audio_data, canon_words, lang)

            # ЭТАП 2: Агентный цикл V3 (Smart Surgeon)
            for iteration in range(3):
                bugs = self._audit_json(canon_words)
                gaps = self._find_gaps(canon_words)
                
                if not bugs and not gaps:
                    log.info(f"[Critic V3] Итерация {iteration+1}: Аудит пройден.")
                    break
                    
                if bugs:
                    log.warning(f"[Critic V3] Итерация {iteration+1}: Найдено {len(bugs)} багов. Вызов хирурга...")
                    self._fix_bugs(canon_words, bugs)
                
                if gaps:
                    for gap in gaps:
                        self._micro_dtw_surgery(canon_words, gap, audio_data, model, lang)
            
            # ЭТАП 3: TRIBUNAL & ORCHESTRA V4
            for iteration in range(2):
                anomalies = self._run_tribunal(canon_words, is_harmonic_fn)
                if not anomalies:
                    break
                    
                log.warning(f"[Tribunal V4] Итерация {iteration+1}: Найдено {len(anomalies)} критических аномалий! Запуск Оркестра...")
                
                for s_idx, e_idx, reason in anomalies:
                    log.info(f"   -> Карантин [{s_idx}-{e_idx}]: {reason}. Сброс таймингов.")
                    for k in range(s_idx, e_idx + 1):
                        canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                    
                    t_start = canon_words[s_idx - 1]["end"] + 0.1 if s_idx > 0 and canon_words[s_idx - 1]["end"] != -1 else 0.0
                    t_end = audio_duration
                    for k in range(e_idx + 1, len(canon_words)):
                        if canon_words[k]["start"] != -1:
                            t_end = canon_words[k]["start"] - 0.1
                            break
                            
                    # Стратегия А: Структурный Клон (Chorus Copier)
                    if self._heal_by_chorus(canon_words, s_idx, e_idx): continue
                    # Стратегия B: Слепой Маппинг галлюцинаций
                    if self._heal_blind_fuzzy(canon_words, s_idx, e_idx, audio_data, t_start, t_end, model, lang): continue
                    # Стратегия C: Ритмический Магнит (Onsets)
                    self._heal_with_onsets(canon_words, s_idx, e_idx, onsets, t_start, t_end)
            
            # ЭТАП 4: Гравитация и Сглаживание
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

        dump_debug("4_Final_Symphony", final_json, self._track_stem)
        log.info(f"Aligner ГОТОВО → {output_json_path}")
        log.info("=" * 50)
        
        return output_json_path