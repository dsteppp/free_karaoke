import os
import gc
import re
import json
import torch
import librosa
import stable_whisper
from app_logger import get_logger, dump_debug

log = get_logger("aligner")

class KaraokeAligner:
    """
    Пайплайн выравнивания "Musical Logic V20 (Platinum Skeleton)".
    Основан на Гравитации Гласных, Платиновых цепочках и отсечении иллюзий.
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""

    def _detect_language(self, text: str) -> str:
        cyrillic = len(re.findall(r'[\u0400-\u04FFёЁ]', text))
        hangul = len(re.findall(r'[\uac00-\ud7a3]', text))
        latin = len(re.findall(r'[a-zA-Z]', text))
        
        if hangul > 10: return "ko" 
        if cyrillic > latin * 0.3: return "ru" 
        return "en"     

    def _is_align_bad(self, sw_words: list, threshold=0.08) -> bool:
        if not sw_words: return True
        bad_count = sum(1 for w in sw_words if (w.end - w.start) < 0.05)
        ratio = bad_count / len(sw_words)
        log.info("Валидатор DTW: %d/%d бракованных слов (%.1f%%)", bad_count, len(sw_words), ratio * 100)
        return ratio > threshold

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info("Aligner СТАРТ (Musical V20): %s", self._track_stem)
        log.info("Vocals: %s", vocals_path)
        log.info("Device: %s", self.device)

        canon_words = self._prepare_text(raw_lyrics)
        text_for_whisper = " ".join([w["word"] for w in canon_words])
        log.info("Текст Genius: %d слов", len(canon_words))

        if not canon_words:
            log.warning("Текст пуст! Выход.")
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            return output_json_path

        lang = self._detect_language(raw_lyrics)
        log.info("Определен язык: %s", lang)

        model = None
        sw_raw_words = []
        audio_duration = 0.0

        try:
            log.info("Загрузка аудио в ОЗУ (librosa, sr=16000)...")
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            log.info("Аудио загружено: %.2f сек. Запуск Whisper (%s)...", audio_duration, self.device)

            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            log.info("Фаза 1: Акустическое выравнивание (DTW)...")
            try:
                result = model.align(audio_data, text_for_whisper, language=lang)
                sw_raw_words = result.all_words()
                
                if self._is_align_bad(sw_raw_words):
                    log.warning("DTW забракован! Текст не совпадает с аудио. Запуск Фазы 2...")
                    raise ValueError("Bad Align Quality")
                    
            except Exception:
                log.warning("Фаза 2: Слепая Транскрибация (Transcribe-First)...")
                result = model.transcribe(audio_data, language=lang)
                sw_raw_words = result.all_words()

        except RuntimeError as e:
            if "out of memory" in str(e).lower() and self.device != "cpu":
                log.warning("Ускоритель не справился! Мягкий фолбэк на CPU...")
                if model: del model
                if torch.cuda.is_available(): torch.cuda.empty_cache()
                self.device = "cpu"
                model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device="cpu")
                
                result = model.transcribe(audio_data, language=lang)
                sw_raw_words = result.all_words()
            else:
                raise e
        finally:
            if model: del model
            if 'audio_data' in locals(): del audio_data
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            log.info("Whisper выгружен, память очищена.")

        dump_debug("1_WhisperRaw", [{"word": w.word, "start": w.start, "end": w.end} for w in sw_raw_words], self._track_stem)

        # Вызов Платинового Ядра V20
        canon_words = self._platinum_sequence_alignment(canon_words, sw_raw_words, audio_duration)
        canon_words = self._apply_surgeons(canon_words)
        final_json = self._finalize_json(canon_words)
        
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, ensure_ascii=False, indent=2)

        dump_debug("2_Final", final_json, self._track_stem)
        log.info("Aligner ГОТОВО → %s (%d слов)", output_json_path, len(final_json))
        log.info("=" * 50)
        
        return output_json_path

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
                        "end": -1.0
                    })
        return words_list

    def _get_vowel_weight(self, word: str, is_line_end: bool) -> float:
        """Музыкальная логика: тянутся только гласные. Конец строки тянется сильнее."""
        vowels = set("аеёиоуыэюяaeiouy")
        clean = word.lower()
        v_count = sum(1 for c in clean if c in vowels)
        weight = float(max(1, v_count))
        if is_line_end:
            weight *= 2.5 # Вокалист всегда тянет последнюю ноту фразы
        return weight

    def _extract_vad_mask(self, sw_words: list) -> list:
        mask = []
        for w in sw_words:
            if w.end - w.start > 0.05:
                mask.append((w.start, w.end))
        if not mask: return []
        
        merged = []
        for m in sorted(mask):
            if not merged:
                merged.append(m)
            else:
                ps, pe = merged[-1]
                if m[0] <= pe + 0.5:
                    merged[-1] = (ps, max(pe, m[1]))
                else:
                    merged.append(m)
        return merged

    def _distribute_fallback(self, words: list, start_idx: int, end_idx: int, t_start: float, t_end: float):
        """Естественная гравитация. Используется в инструменталах и Fade-Out."""
        if start_idx > end_idx: return
        gap = t_end - t_start
        if gap <= 0: gap = 0.1
        
        weights = [self._get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(start_idx, end_idx + 1)]
        total_weight = sum(weights)
        
        # Физическое время, необходимое для произнесения этой массы букв (0.25с на 1 гласную)
        req_dur = total_weight * 0.25
        
        is_intro = (start_idx == 0)
        is_outro = (end_idx == len(words) - 1)
        
        stick_left = (not is_intro) and (not words[start_idx - 1]["line_break"])
        stick_right = (not is_outro) and (not words[end_idx]["line_break"])
        
        if is_intro: stick_right, stick_left = True, False
        if is_outro: stick_left, stick_right = True, False
        
        if gap > req_dur * 1.5 and gap > 3.0:
            if stick_left and not stick_right:
                actual_gap, curr_t = req_dur, t_start + 0.1
            elif stick_right and not stick_left:
                actual_gap, curr_t = req_dur, t_end - req_dur - 0.1
            else:
                actual_gap, curr_t = req_dur, t_start + (gap - req_dur) / 2.0
        else:
            actual_gap, curr_t = gap, t_start
            
        for i, k in enumerate(range(start_idx, end_idx + 1)):
            w_dur = (weights[i] / total_weight) * actual_gap
            words[k]["start"] = curr_t
            words[k]["end"] = curr_t + w_dur * 0.95
            curr_t += w_dur

    def _map_vad_time(self, t: float, vads: list) -> float:
        accum = 0.0
        for s, e in vads:
            dur = e - s
            if t <= accum + dur:
                return s + (t - accum)
            accum += dur
        return vads[-1][1]

    def _fill_gap_with_vad(self, words: list, start_idx: int, end_idx: int, t_start: float, t_end: float, merged_vad: list):
        if start_idx > end_idx: return
        if t_end <= t_start: t_end = t_start + 0.1
        
        active_vads = []
        for vs, ve in merged_vad:
            i_s = max(t_start, vs)
            i_e = min(t_end, ve)
            if i_e - i_s > 0.05:
                active_vads.append((i_s, i_e))
                
        if not active_vads:
            self._distribute_fallback(words, start_idx, end_idx, t_start, t_end)
            return
            
        total_vad_dur = sum(e - s for s, e in active_vads)
        weights = [self._get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(start_idx, end_idx + 1)]
        total_weight = sum(weights)
        
        t_cursor = 0.0
        for i, k in enumerate(range(start_idx, end_idx + 1)):
            w_logic_dur = (weights[i] / total_weight) * total_vad_dur
            words[k]["start"] = self._map_vad_time(t_cursor, active_vads)
            words[k]["end"] = self._map_vad_time(t_cursor + w_logic_dur * 0.95, active_vads)
            t_cursor += w_logic_dur

    def _platinum_sequence_alignment(self, canon_words: list, sw_words: list, audio_duration: float) -> list:
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
                
        merged_vad = self._extract_vad_mask(sw_words)
        
        log.info("V20: Установка Платиновых Якорей (Блокировка иллюзий)...")
        canon_idx = 0
        sw_idx = 0
        last_anchored_canon_idx = -1
        last_anchored_time = 0.0
        anchors_count = 0
        search_window = 60 # Только вперед! Никаких прыжков в прошлые припевы
        
        while canon_idx < len(canon_words) and sw_idx < len(valid_sw):
            best_match_len = 0
            best_c_idx = -1
            
            for c in range(canon_idx, min(canon_idx + search_window, len(canon_words))):
                match_len = 0
                while (c + match_len < len(canon_words) and 
                       sw_idx + match_len < len(valid_sw) and 
                       canon_words[c + match_len]["clean_text"] == valid_sw[sw_idx + match_len]["clean"]):
                    match_len += 1
                
                if match_len > best_match_len:
                    best_match_len = match_len
                    best_c_idx = c
                    
            # АБСОЛЮТНАЯ ЗАЩИТА: Фильтр платиновых якорей
            is_platinum = False
            if last_anchored_canon_idx == -1:
                # САМЫЙ ПЕРВЫЙ ЯКОРЬ: Жесточайший фильтр. Обязано быть >= 3 слов подряд. 
                # (Блокирует эхо "розовый зефир" на 2-й секунде у Zoloto)
                if best_match_len >= 3:
                    is_platinum = True
            else:
                # ПОСЛЕДУЮЩИЕ ЯКОРЯ: 
                if best_match_len >= 3:
                    is_platinum = True
                elif best_match_len == 2:
                    w1 = canon_words[best_c_idx]["clean_text"]
                    w2 = canon_words[best_c_idx+1]["clean_text"]
                    if len(w1) + len(w2) >= 7: 
                        is_platinum = True
                elif best_match_len == 1:
                    w1 = canon_words[best_c_idx]["clean_text"]
                    # Блокировка одиночных галлюцинаций (типа "ничего" с 11с дырой). Одиночки берем только огромные.
                    if len(w1) >= 8: 
                        is_platinum = True

            # Проверка адекватности BPM (если Whisper нашел слово, но до него неадекватная скорость пения)
            if is_platinum and last_anchored_canon_idx != -1:
                w_diff = best_c_idx - last_anchored_canon_idx
                t_diff = valid_sw[sw_idx]["start"] - last_anchored_time
                if w_diff > 0 and (t_diff / w_diff) < 0.08: 
                    # Быстрее 12 слов в секунду? Это бред/сэмпл, пропускаем.
                    is_platinum = False
                    
            if is_platinum:
                for k in range(best_match_len):
                    canon_words[best_c_idx + k]["start"] = valid_sw[sw_idx + k]["start"]
                    canon_words[best_c_idx + k]["end"] = valid_sw[sw_idx + k]["end"]
                
                last_anchored_canon_idx = best_c_idx + best_match_len - 1
                last_anchored_time = valid_sw[sw_idx + best_match_len - 1]["end"]
                
                canon_idx = best_c_idx + best_match_len
                sw_idx += best_match_len
                anchors_count += best_match_len
            else:
                sw_idx += 1 # Whisper нагаллюцинировал болтовню или эхо - идем дальше
                
        log.info("Установлено платиновых якорей: %d из %d", anchors_count, len(canon_words))
        anchors = [i for i, w in enumerate(canon_words) if w["start"] != -1.0]

        if not anchors:
            log.warning("Полная слепота! Используем резервную гравитацию.")
            self._distribute_fallback(canon_words, 0, len(canon_words)-1, 1.0, audio_duration - 1.0)
            return canon_words

        # 3. ЗАЛИВКА ПУСТОТ С УЧЕТОМ ГЛАСНЫХ
        if anchors[0] > 0:
            self._fill_gap_with_vad(canon_words, 0, anchors[0] - 1, 0.0, canon_words[anchors[0]]["start"], merged_vad)
            
        for k in range(len(anchors) - 1):
            i1, i2 = anchors[k], anchors[k+1]
            if i2 - i1 > 1:
                t1 = canon_words[i1]["end"]
                t2 = canon_words[i2]["start"]
                self._fill_gap_with_vad(canon_words, i1 + 1, i2 - 1, t1, t2, merged_vad)
                
        # 4. ОТСЕЧЕНИЕ МЕРТВОЙ ТКАНИ (Fade-out Ягоды / Доры)
        if anchors[-1] < len(canon_words) - 1:
            t_start = canon_words[anchors[-1]]["end"]
            # Выкидываем текст далеко в будущее (плеер его просто проигнорирует, т.к. аудио кончилось)
            fake_end_time = max(t_start + 10.0, audio_duration + 10.0)
            self._distribute_fallback(canon_words, anchors[-1] + 1, len(canon_words) - 1, t_start + 0.5, fake_end_time)

        return canon_words

    def _apply_surgeons(self, words: list) -> list:
        for idx, cw in enumerate(words):
            v_weight = self._get_vowel_weight(cw["clean_text"], cw["line_break"])
            # Защита от экстремальных аномалий (1 гласная = макс 2.5 сек, 3 гласных = 5.5 сек)
            max_dur = v_weight * 1.5 + 1.0 
            if cw["end"] - cw["start"] > max_dur:
                cw["end"] = cw["start"] + max_dur

        last_end = 0.0
        for cw in words:
            if cw["start"] < last_end:
                cw["start"] = last_end + 0.01
            if cw["end"] < cw["start"] + 0.05:
                cw["end"] = cw["start"] + 0.05
            last_end = cw["end"]
                
        return words

    def _finalize_json(self, canon_words: list) -> list:
        final_json = []
        for w in canon_words:
            final_json.append({
                "word": w["word"], 
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "line_break": w["line_break"],
                "letters": [] 
            })
        return final_json