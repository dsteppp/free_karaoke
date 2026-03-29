import os
import gc
import re
import json
import torch
import difflib
import librosa
import stable_whisper
from app_logger import get_logger, dump_debug

log = get_logger("aligner")

class KaraokeAligner:
    """
    Пайплайн выравнивания "Hybrid Engine V15.0" (Восстановленная оригинальная логика).
    Возвращает 100% совместимый со script.js плоский JSON с флагом line_break.
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        # Директория для моделей (сохраняем оригинальную структуру)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""

    def _detect_language(self, text: str) -> str:
        """Определяет доминирующий язык для защиты от смены языков Whisper."""
        cyrillic = len(re.findall(r'[\u0400-\u04FFёЁ]', text))
        hangul = len(re.findall(r'[\uac00-\ud7a3]', text))
        latin = len(re.findall(r'[a-zA-Z]', text))
        
        if hangul > 10: 
            return "ko" # K-Pop
        if cyrillic > latin * 0.3: 
            return "ru" # Русские треки
        return "en"     # Зарубежные

    def _is_align_bad(self, sw_words: list, threshold=0.08) -> bool:
        """Валидатор качества DTW. Проверяет 'схлопнутые' слова."""
        if not sw_words:
            return True
        
        bad_count = 0
        for w in sw_words:
            if (w.end - w.start) < 0.05:
                bad_count += 1
                
        ratio = bad_count / len(sw_words)
        log.info("Валидатор DTW: %d/%d бракованных слов (%.1f%%)", bad_count, len(sw_words), ratio * 100)
        
        return ratio > threshold

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        """Главный метод, который вызывает ai_pipeline.py"""
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info("Aligner СТАРТ (Hybrid Engine V15.0): %s", self._track_stem)
        log.info("Vocals: %s", vocals_path)
        log.info("Device: %s", self.device)

        canon_words = self._prepare_text(raw_lyrics)
        text_for_whisper = " ".join([w["word"] for w in canon_words])
        log.info("Текст Genius: %d слов", len(canon_words))

        if not canon_words:
            log.warning("Текст пуст! Выход.")
            # Записываем пустой массив, чтобы фронтенд не упал
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
            fp16_mode = self.device == "cuda"
            
            log.info("Фаза 1: Акустическое выравнивание (DTW)...")
            try:
                result = model.align(audio_data, text_for_whisper, language=lang, fp16=fp16_mode)
                sw_raw_words = result.all_words()
                
                if self._is_align_bad(sw_raw_words):
                    log.warning("DTW забракован! Текст не совпадает с аудио. Запуск Фазы 2...")
                    raise ValueError("Bad Align Quality")
                    
            except Exception as align_err:
                log.warning("Фаза 2: Слепая Транскрибация (Transcribe-First)...")
                result = model.transcribe(audio_data, language=lang, fp16=fp16_mode)
                sw_raw_words = result.all_words()

        except RuntimeError as e:
            if "out of memory" in str(e).lower() and self.device == "cuda":
                log.warning("CUDA OOM! Переключаемся на CPU...")
                if model: del model
                torch.cuda.empty_cache()
                self.device = "cpu"
                model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device="cpu")
                
                result = model.transcribe(audio_data, language=lang, fp16=False)
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

        # NLP сшивание и интерполяция (твоя идеальная логика)
        canon_words = self._fuzzy_match_and_interpolate(canon_words, sw_raw_words, audio_duration)
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

    def _fuzzy_match_and_interpolate(self, canon_words: list, sw_words: list, total_duration: float) -> list:
        valid_sw = []
        for w in sw_words:
            if (w.end - w.start) < 0.05:
                continue
            cl = re.sub(r'[^\w]', '', w.word.lower())
            if cl:
                valid_sw.append({"word": w.word, "clean": cl, "start": w.start, "end": w.end})
                
        canon_clean = [w["clean_text"] for w in canon_words]
        sw_clean = [w["clean"] for w in valid_sw]
        
        log.info("NLP Сшивание: Поиск временных якорей...")
        sm = difflib.SequenceMatcher(None, canon_clean, sw_clean)
        anchors_count = 0
        
        for i, j, n in sm.get_matching_blocks():
            for k in range(n):
                canon_words[i+k]["start"] = valid_sw[j+k]["start"]
                canon_words[i+k]["end"] = valid_sw[j+k]["end"]
                anchors_count += 1
                
        log.info("Найдено совпадений: %d из %d слов", anchors_count, len(canon_words))

        i = 0
        while i < len(canon_words):
            if canon_words[i]["start"] == -1.0:
                start_idx = i
                while i < len(canon_words) and canon_words[i]["start"] == -1.0:
                    i += 1
                end_idx = i - 1
                
                prev_end = 0.0
                if start_idx > 0:
                    prev_end = canon_words[start_idx - 1]["end"]
                    
                next_start = total_duration
                if end_idx < len(canon_words) - 1:
                    next_start = canon_words[end_idx + 1]["start"]
                    
                if next_start <= prev_end:
                    next_start = prev_end + 0.3 * (end_idx - start_idx + 1)
                    
                gap = next_start - prev_end
                total_chars = sum(max(1, len(canon_words[k]["clean_text"])) for k in range(start_idx, end_idx + 1))
                
                curr_time = prev_end + 0.02
                for k in range(start_idx, end_idx + 1):
                    chars = max(1, len(canon_words[k]["clean_text"]))
                    w_dur = (chars / total_chars) * (gap - 0.04) 
                    canon_words[k]["start"] = curr_time
                    canon_words[k]["end"] = curr_time + w_dur * 0.9
                    curr_time += w_dur
            else:
                i += 1
                
        last_end = 0.0
        for cw in canon_words:
            if cw["start"] < last_end:
                cw["start"] = last_end + 0.01
            if cw["end"] < cw["start"] + 0.05:
                cw["end"] = cw["start"] + 0.05
            last_end = cw["end"]
            
        return canon_words

    def _apply_surgeons(self, words: list) -> list:
        for idx, cw in enumerate(words):
            c_len = max(1, len(cw["clean_text"]))
            max_dur = min(c_len * 0.4 + 0.5, 3.5)
            
            if cw["end"] - cw["start"] > max_dur:
                is_first = (idx == 0) or words[idx-1]["line_break"]
                
                if is_first:
                    cw["start"] = cw["end"] - max_dur
                else:
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