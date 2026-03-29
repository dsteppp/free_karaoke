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
    Пайплайн выравнивания "Monotonic Aligner V18" (Acoustic-Textual Cartography).
    Полный отказ от difflib. Строгая топология времени и скользящее окно.
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
        
        if hangul > 10: 
            return "ko" 
        if cyrillic > latin * 0.3: 
            return "ru" 
        return "en"     

    def _is_align_bad(self, sw_words: list, threshold=0.08) -> bool:
        if not sw_words:
            return True
        bad_count = sum(1 for w in sw_words if (w.end - w.start) < 0.05)
        ratio = bad_count / len(sw_words)
        log.info("Валидатор DTW: %d/%d бракованных слов (%.1f%%)", bad_count, len(sw_words), ratio * 100)
        return ratio > threshold

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info("Aligner СТАРТ (Monotonic V18): %s", self._track_stem)
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
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
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

        # Вызов НОВОГО математического ядра (Строгая хронология)
        canon_words = self._elastic_sliding_alignment(canon_words, sw_raw_words)
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
            if not line:
                continue
                
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

    def _distribute_block(self, words: list, start_idx: int, end_idx: int, t_start: float, t_end: float):
        """Эластичное распределение массы букв строго внутри заданного окна."""
        if start_idx > end_idx: return
        if t_end <= t_start: 
            t_end = t_start + 0.1 * (end_idx - start_idx + 1)
            
        total_chars = sum(max(1, len(words[k]["clean_text"])) for k in range(start_idx, end_idx + 1))
        gap = t_end - t_start
        
        curr_time = t_start
        for k in range(start_idx, end_idx + 1):
            chars = max(1, len(words[k]["clean_text"]))
            w_dur = (chars / total_chars) * gap
            words[k]["start"] = curr_time
            words[k]["end"] = curr_time + w_dur * 0.95  # 5% зазор между словами
            curr_time += w_dur

    def _elastic_sliding_alignment(self, canon_words: list, sw_words: list) -> list:
        # 1. Стерилизация сырых данных (запрещаем Whisper ехать в прошлое)
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
                
        # 2. Установка Железных Якорей (СКОЛЬЗЯЩЕЕ ОКНО)
        # Этот блок решает баг "Улетающего припева Доры"
        log.info("Картография: Установка железных якорей (Forward-Only)...")
        canon_idx = 0
        anchors_count = 0
        
        for sw in valid_sw:
            if canon_idx >= len(canon_words): 
                break
            
            sw_c = sw["clean"]
            
            # Динамическое окно: ищем совпадение только в пределах следующих 25 слов.
            # Если слово не найдено, мы его игнорируем (защита от галлюцинаций Whisper).
            window_size = 25 
            
            for i in range(canon_idx, min(canon_idx + window_size, len(canon_words))):
                if sw_c == canon_words[i]["clean_text"]:
                    # Защита от ложных якорей на коротких словах (я, и, а)
                    if len(sw_c) < 3 and (i - canon_idx) > 3:
                        continue 
                        
                    canon_words[i]["start"] = sw["start"]
                    canon_words[i]["end"] = sw["end"]
                    canon_idx = i + 1 # Двигаем границу невозврата
                    anchors_count += 1
                    break
                    
        log.info("Приколото бусин (Якорей): %d из %d", anchors_count, len(canon_words))
        anchors = [i for i, w in enumerate(canon_words) if w["start"] != -1.0]

        # Если нейросеть совсем оглохла
        if not anchors:
            log.warning("Полная слепота! Равномерная заливка.")
            self._distribute_block(canon_words, 0, len(canon_words)-1, 1.0, 10.0 + len(canon_words))
            return canon_words

        # 3. Эластичная заливка Интро (Баг Кристины Си)
        first_a = anchors[0]
        if first_a > 0:
            anchor_time = canon_words[first_a]["start"]
            chars = sum(len(canon_words[i]["clean_text"]) for i in range(first_a))
            # Вычисляем естественную длину интро
            req_time = chars * 0.12 + (first_a * 0.05)
            # Прижимаем вправо к первому слову
            start_time = max(0.1, anchor_time - req_time - 0.2)
            self._distribute_block(canon_words, 0, first_a - 1, start_time, anchor_time - 0.05)

        # 4. Эластичная заливка пустот и проигрышей (Баг Золото)
        for k in range(len(anchors) - 1):
            i1, i2 = anchors[k], anchors[k+1]
            if i2 - i1 == 1: continue 
                
            t1, t2 = canon_words[i1]["end"], canon_words[i2]["start"]
            start_idx, end_idx = i1 + 1, i2 - 1
            
            if t2 <= t1: t2 = t1 + 0.1
            gap = t2 - t1
            
            chars = sum(len(canon_words[i]["clean_text"]) for i in range(start_idx, end_idx + 1))
            req_time = chars * 0.12 + ((end_idx - start_idx + 1) * 0.05)
            
            # Детектор гитарного соло (если дыра больше 4 секунд и сильно больше нужного времени)
            if gap > 4.0 and gap > req_time * 2.0:
                log.debug("Обнаружен проигрыш: gap=%.1fs, req=%.1fs", gap, req_time)
                # Определяем, куда "прилипнет" текст, основываясь на строках поэзии
                stick_left = not canon_words[start_idx - 1]["line_break"]
                stick_right = not canon_words[end_idx]["line_break"]
                
                if stick_left and not stick_right:
                    self._distribute_block(canon_words, start_idx, end_idx, t1 + 0.1, t1 + req_time + 0.1)
                elif stick_right and not stick_left:
                    self._distribute_block(canon_words, start_idx, end_idx, t2 - req_time - 0.1, t2 - 0.1)
                else:
                    # Если это отдельная строка, прижимаем ее ближе к левому краю, но с отступом
                    self._distribute_block(canon_words, start_idx, end_idx, t1 + 0.5, t1 + req_time + 0.5)
            else:
                # Обычная дыра - эластично натягиваем
                self._distribute_block(canon_words, start_idx, end_idx, t1 + 0.05, t2 - 0.05)

        # 5. Фантомное Аутро / Fade-out (Баг Ягоды)
        last_a = anchors[-1]
        if last_a < len(canon_words) - 1:
            t1 = canon_words[last_a]["end"]
            chars = sum(len(canon_words[i]["clean_text"]) for i in range(last_a + 1, len(canon_words)))
            req_time = chars * 0.15 + ((len(canon_words) - last_a - 1) * 0.1)
            # Текст просто элегантно уходит в будущее за пределы песни
            self._distribute_block(canon_words, last_a + 1, len(canon_words) - 1, t1 + 0.2, t1 + req_time + 0.2)

        return canon_words

    def _apply_surgeons(self, words: list) -> list:
        """
        Умный хирург. Понимает вокальную распевку и переносы строк.
        """
        for idx, cw in enumerate(words):
            c_len = max(1, len(cw["clean_text"]))
            is_line_end = cw["line_break"] or idx == len(words) - 1
            
            # Разрешаем словам на концах строк тянуться до 8 секунд (защита от обрывов гласных)
            max_dur = min(c_len * 0.6 + 2.0, 8.0) if is_line_end else min(c_len * 0.3 + 1.0, 4.0)
            
            if cw["end"] - cw["start"] > max_dur:
                cw["end"] = cw["start"] + max_dur

        # Гарантийная защита от схлопывания времени
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