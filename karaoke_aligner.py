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
    Пайплайн выравнивания "Self-Healing Agent V1".
    Использует концепцию Actor-Critic: 
    1. Драфт-выравнивание (Actor)
    2. Поиск аномалий: BlackHole, Overstretch, Orphan (Critic)
    3. Локальная хирургия: Micro-DTW, Hard VAD, Vowel Gravity (Surgeon)
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
                        "end": -1.0
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
        """Акустический сонар. Ищет реальные границы голоса по энергии (RMS)."""
        log.info("[Сонар] Вычисление Hard VAD маски...")
        rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
        rms_norm = rms / (np.max(rms) + 1e-8)
        
        threshold = 0.015 # 1.5% от пиковой энергии
        vad_frames = rms_norm > threshold
        times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
        
        intervals = []
        in_speech = False
        start_t = 0.0
        
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
                if s - last_e < 0.4: # Склеиваем паузы до 400мс
                    merged[-1] = (last_s, max(last_e, e))
                else:
                    if e - s > 0.1: # Игнорируем щелчки короче 100мс
                        merged.append((s, e))
                        
        return merged

    # ─── АГЕНТСКАЯ АРХИТЕКТУРА ──────────────────────────────────────────────────

    def _draft_alignment(self, model, audio_data: np.ndarray, canon_words: list, lang: str):
        """Первичный слепок реальности (Actor)."""
        text_for_whisper = " ".join([w["word"] for w in canon_words])
        try:
            result = model.align(audio_data, text_for_whisper, language=lang)
            sw_words = result.all_words()
        except Exception as e:
            log.warning(f"[Actor] DTW Align упал ({e}). Фолбэк на transcribe...")
            result = model.transcribe(audio_data, language=lang)
            sw_words = result.all_words()

        # Маппинг WhisperRaw -> Canon
        # Используем нечеткий поиск, так как Whisper мог разбить слова иначе
        s_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in sw_words]
        
        s_idx = 0
        for i, c_w in enumerate(canon_words):
            if s_idx >= len(sw_words): break
            
            best_match = -1
            best_score = 0
            
            # Ищем совпадение в скользящем окне
            for j in range(s_idx, min(s_idx + 15, len(sw_words))):
                if not s_texts[j]: continue
                score = rapidfuzz.fuzz.ratio(c_w["clean_text"], s_texts[j])
                if score > best_score and score > 75:
                    best_score = score
                    best_match = j
                    if score == 100: break
            
            if best_match != -1:
                # Отбраковываем откровенный мусор шепота
                dur = sw_words[best_match].end - sw_words[best_match].start
                if dur > 0.02:
                    canon_words[i]["start"] = sw_words[best_match].start
                    canon_words[i]["end"] = sw_words[best_match].end
                    s_idx = best_match + 1

    def _audit_json(self, words: list) -> list:
        """Аудитор (Critic). Сканирует массив на предмет физических аномалий."""
        bugs = []
        n = len(words)
        
        i = 0
        while i < n:
            w = words[i]
            if w["start"] == -1 or w["end"] == -1:
                i += 1
                continue
                
            dur = w["end"] - w["start"]
            
            # 1. BLACK_HOLE (Сингулярность или сжатие)
            if dur < 0.05:
                j = i
                while j < n and words[j]["start"] != -1 and (words[j]["end"] - words[j]["start"]) < 0.1:
                    j += 1
                bugs.append({"type": "BLACK_HOLE", "start_idx": i, "end_idx": j - 1})
                i = j
                continue

            # 2. OVERSTRETCH (Резина на месте тишины)
            vowel_w = self._get_vowel_weight(w["clean_text"], w["line_break"])
            max_phys_dur = vowel_w * 0.8 + 0.5 
            if dur > max_phys_dur and dur > 2.0:
                bugs.append({"type": "OVERSTRETCH", "idx": i})

            # 3. ORPHAN (Оторванная галлюцинация)
            if i < n - 1:
                w_next = words[i+1]
                if w_next["start"] != -1:
                    gap = w_next["start"] - w["end"]
                    if gap > 8.0 and not w["line_break"]:
                        bugs.append({"type": "ORPHAN", "idx": i})
            
            i += 1
            
        return bugs

    # ─── ХИРУРГИЯ ───────────────────────────────────────────────────────────────

    def _fix_orphan(self, words: list, bug: dict):
        """Хирург В: Сброс фейкового якоря."""
        idx = bug["idx"]
        log.debug(f"[Surgeon] Удаление Orphan-якоря: '{words[idx]['clean_text']}'")
        words[idx]["start"] = -1.0
        words[idx]["end"] = -1.0

    def _fix_overstretch(self, words: list, bug: dict, vad_mask: list):
        """Хирург Б: Обрубание хвостов по Hard VAD."""
        idx = bug["idx"]
        w = words[idx]
        
        active_chunk = None
        for (vs, ve) in vad_mask:
            if vs - 0.5 <= w["start"] <= ve + 0.5:
                active_chunk = (vs, ve)
                break
                
        old_end = w["end"]
        if active_chunk:
            new_end = min(w["end"], active_chunk[1] + 0.1)
            if new_end < w["end"]:
                w["end"] = new_end
        
        # Безусловный лимит
        vowel_w = self._get_vowel_weight(w["clean_text"], w["line_break"])
        limit = w["start"] + vowel_w * 1.0 + 1.0
        if w["end"] > limit:
            w["end"] = limit
            
        log.debug(f"[Surgeon] Overstretch '{w['clean_text']}': {old_end:.1f}s -> {w['end']:.1f}s")

    def _fix_black_hole(self, words: list, bug: dict, audio_data: np.ndarray, model, lang: str):
        """Хирург А: Micro-DTW на локальном участке аудио."""
        s_idx = bug["start_idx"]
        e_idx = bug["end_idx"]
        
        # Ищем границы хирургического окна
        t_start = 0.0
        for k in range(s_idx - 1, -1, -1):
            if words[k]["end"] != -1:
                t_start = words[k]["end"]
                break
                
        t_end = len(audio_data) / 16000
        for k in range(e_idx + 1, len(words)):
            if words[k]["start"] != -1:
                t_end = words[k]["start"]
                break

        v_weights = sum(self._get_vowel_weight(words[i]["clean_text"], words[i]["line_break"]) for i in range(s_idx, e_idx + 1))
        min_req = v_weights * 0.15
        
        # Если окно слишком узкое, отпускаем слова в гравитацию (-1)
        if t_end - t_start < min_req or t_end - t_start < 1.0:
            log.debug(f"[Surgeon] BlackHole {s_idx}-{e_idx}: Сброс в гравитацию (Окно {t_end-t_start:.1f}s мало)")
            for i in range(s_idx, e_idx + 1):
                words[i]["start"] = -1.0
                words[i]["end"] = -1.0
            return

        log.debug(f"[Surgeon] BlackHole {s_idx}-{e_idx}: Micro-DTW окно [{t_start:.2f}s - {t_end:.2f}s]")
        sr = 16000
        crop_audio = audio_data[int(t_start * sr) : int(t_end * sr)]
        crop_text = " ".join([words[i]["word"] for i in range(s_idx, e_idx + 1)])
        
        try:
            res = model.align(crop_audio, crop_text, language=lang)
            c_sw = res.all_words()
            
            s_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in c_sw]
            c_ptr = 0
            for k in range(s_idx, e_idx + 1):
                c_clean = words[k]["clean_text"]
                best_score, best_match = 0, -1
                
                for j in range(c_ptr, min(c_ptr + 5, len(s_texts))):
                    score = rapidfuzz.fuzz.ratio(c_clean, s_texts[j])
                    if score > best_score and score > 70:
                        best_score, best_match = score, j
                        if score == 100: break
                
                if best_match != -1:
                    words[k]["start"] = t_start + c_sw[best_match].start
                    words[k]["end"] = t_start + c_sw[best_match].end
                    c_ptr = best_match + 1
                else:
                    words[k]["start"] = -1.0
                    words[k]["end"] = -1.0
        except Exception as e:
            log.warning(f"[Surgeon] Micro-DTW упал ({e}). Сброс.")
            for i in range(s_idx, e_idx + 1):
                words[i]["start"] = -1.0
                words[i]["end"] = -1.0

    # ─── ГРАВИТАЦИЯ (ПОЛИРОВКА) ─────────────────────────────────────────────────

    def _apply_gravity(self, words: list, audio_duration: float, vad_mask: list):
        """Заполняет слепые зоны (-1) математически, прижимаясь к Hard VAD."""
        n = len(words)
        
        def map_to_vad(t_req, t_max):
            if not vad_mask: return t_req
            for (vs, ve) in vad_mask:
                if vs <= t_req <= ve: return t_req
                if t_req < vs: return min(vs, t_max)
            return t_req

        i = 0
        while i < n:
            if words[i]["start"] == -1:
                j = i
                while j < n and words[j]["start"] == -1:
                    j += 1
                
                t_start = 0.5
                if i > 0 and words[i-1]["end"] != -1:
                    t_start = words[i-1]["end"] + 0.1
                    
                t_end = audio_duration - 0.5
                if j < n and words[j]["start"] != -1:
                    t_end = words[j]["start"] - 0.1

                if t_end <= t_start: t_end = t_start + 0.5

                weights = [self._get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
                total_w = sum(weights)
                
                opt_dur = total_w * 0.3
                actual_dur = min(t_end - t_start, opt_dur)
                
                if i == 0: 
                    t_start = max(t_start, t_end - actual_dur)
                
                curr_t = t_start
                for k in range(i, j):
                    w_ratio = weights[k-i] / total_w
                    w_dur = w_ratio * actual_dur
                    
                    st = map_to_vad(curr_t, t_end)
                    en = st + w_dur * 0.95
                    
                    words[k]["start"] = st
                    words[k]["end"] = en
                    curr_t = en
                
                i = j
            else:
                i += 1

    def _apply_surgeons(self, words: list) -> list:
        """Сглаживание микро-наложений."""
        last_e = 0.0
        for w in words:
            if w["start"] < last_e:
                w["start"] = last_e + 0.01
            if w["end"] <= w["start"]:
                w["end"] = w["start"] + 0.1
            last_e = w["end"]
        return words

    # ─── MAIN LOOP ──────────────────────────────────────────────────────────────

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info(f"Aligner СТАРТ (Self-Healing Agent V1): {self._track_stem}")
        
        canon_words = self._prepare_text(raw_lyrics)
        if not canon_words:
            log.warning("Текст пуст! Выход.")
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = self._detect_language(raw_lyrics)
        log.info(f"Язык: {lang}. Слов: {len(canon_words)}")

        model = None
        try:
            log.info("Загрузка аудио (16kHz)...")
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            
            vad_mask = self._compute_hard_vad(audio_data, sr)
            
            log.info(f"Запуск Whisper ({self.device})...")
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            # ЭТАП 1: Драфт (Actor)
            log.info("[Agent] Этап 1: Создание первичного слепка (Draft)...")
            self._draft_alignment(model, audio_data, canon_words, lang)

            # ЭТАП 2: Цикл самоисцеления (Critic & Surgeon)
            max_iters = 3
            for iteration in range(max_iters):
                bugs = self._audit_json(canon_words)
                
                if not bugs:
                    log.info(f"[Critic] Итерация {iteration+1}: Аудит пройден. JSON идеален!")
                    break
                    
                log.warning(f"[Critic] Итерация {iteration+1}: Найдено {len(bugs)} аномалий. Запуск хирургов...")
                
                for bug in bugs:
                    if bug["type"] == "ORPHAN":
                        self._fix_orphan(canon_words, bug)
                    elif bug["type"] == "OVERSTRETCH":
                        self._fix_overstretch(canon_words, bug, vad_mask)
                    elif bug["type"] == "BLACK_HOLE":
                        self._fix_black_hole(canon_words, bug, audio_data, model, lang)
            
            # ЭТАП 3: Финальная полировка (Гравитация)
            log.info("[Agent] Этап 3: Гравитационная заливка слепых зон...")
            self._apply_gravity(canon_words, audio_duration, vad_mask)
            self._apply_surgeons(canon_words)

        except RuntimeError as e:
            if "out of memory" in str(e).lower() and self.device != "cpu":
                log.error("Ускоритель упал по OOM. Перезапустите сервер с флагом CPU.")
            raise e
        finally:
            if model: del model
            if 'audio_data' in locals(): del audio_data
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            log.info("Whisper выгружен, память очищена.")

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

        dump_debug("2_Final_SelfHealed", final_json, self._track_stem)
        log.info(f"Aligner ГОТОВО → {output_json_path}")
        log.info("=" * 50)
        
        return output_json_path