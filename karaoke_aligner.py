import os
import gc
import json
import torch
import librosa
import numpy as np
import stable_whisper

from app_logger import get_logger, dump_debug
from aligner_utils import detect_language, prepare_text, clean_word, evaluate_alignment_quality
from aligner_acoustics import get_vocal_intervals, get_clean_onsets, constrain_to_vad, filter_whisper_hallucinations
from aligner_orchestra import execute_sequence_matching

log = get_logger("aligner")

class KaraokeAligner:
    """
    V10.0 Atomic & Monolithic Paradigm
    Инструментальный Анти-Маскинг, Строгая монотонность времени, Атомарные строки.
    """
    
    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")
        
        log.info("=" * 60)
        log.info(f"🚀 Aligner СТАРТ (V10.0 Monolithic Core): {self._track_stem}")
        
        # 1. Подготовка текста (С мгновенным расчетом физики слова)
        canon_words = prepare_text(raw_lyrics)
        if not canon_words:
            log.warning("⚠️ Текст пуст! Сохраняем пустой JSON.")
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            return output_json_path
            
        lang = detect_language(raw_lyrics)
        model = None
        
        try:
            # 2. V10 Anti-Masking: Загрузка вокала и инструментала
            inst_path = vocals_path.replace("_(Vocals).mp3", "_(Instrumental).mp3")
            
            log.info("🎧 Загрузка аудио-стемов для DSP-анализа...")
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            
            if os.path.exists(inst_path):
                inst_data, _ = librosa.load(inst_path, sr=16000, mono=True)
                # Защита от рассинхрона длины файлов на пару семплов
                if len(inst_data) != len(audio_data):
                    min_len = min(len(inst_data), len(audio_data))
                    inst_data = inst_data[:min_len]
                    audio_data = audio_data[:min_len]
            else:
                log.warning("⚠️ Инструментал не найден! Анти-Маскинг работает в слепом режиме.")
                inst_data = np.zeros_like(audio_data)
            
            # 3. Физический анализ звука (V10 VAD & Clean Onsets)
            vad_intervals = get_vocal_intervals(audio_data, inst_data, sr, top_db=35.0)
            if not vad_intervals:
                log.warning("⚠️ VAD не нашел голоса! Сценарий глухой тишины.")
                vad_intervals = [(0.0, audio_duration)]

            onsets = get_clean_onsets(audio_data, inst_data, sr)

            # 4. Слух Нейросети
            log.info("🧠 Транскрибация Stable-Whisper...")
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            result = model.transcribe(
                audio_data, 
                language=lang, 
                word_timestamps=True,
                vad=True 
            )
            
            raw_heard_words = []
            for segment in result.segments:
                for w in segment.words:
                    cw = clean_word(w.word)
                    if cw:
                        raw_heard_words.append({
                            "word": w.word,
                            "clean": cw,
                            "start": w.start,
                            "end": w.end,
                            "probability": w.probability
                        })

            # 5. ФИЛЬТР №1: Очистка галлюцинаций (Жесткий контроль вероятности)
            heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

            # 6. Оркестратор V10.0 (Атомарная сборка строк и монотонная матрица)
            canon_words = execute_sequence_matching(canon_words, heard_words, vad_intervals, onsets, audio_duration)
            
            # 7. Физический Контроль
            log.info("🛡️ [Physics Check] Финальная шлифовка таймингов...")
            shifted_count = 0
            for w in canon_words:
                w["start"], w["end"], was_shifted = constrain_to_vad(w["start"], w["end"], vad_intervals, max_shift_sec=0.5)
                if was_shifted:
                    shifted_count += 1
                
                # Защита от нулевой длины с использованием расчетной физики V10
                dur = w["end"] - w["start"]
                if dur < w["min_dur"]:
                    w["end"] = w["start"] + w["min_dur"]
                    
            if shifted_count > 0:
                log.info(f"   🧲 [VAD-Magnet] Сдвинуто к голосу слов: {shifted_count}")
                    
            # 8. V10 Монотонность времени
            self._enforce_strict_monotonicity(canon_words)

            # 9. Строгая оценка качества
            score = evaluate_alignment_quality(canon_words, vad_intervals)

        except Exception as e:
            log.error(f"❌ Фатальная ошибка Aligner: {e}")
            raise e
        finally:
            # Абсолютная зачистка VRAM
            if model: del model
            if 'audio_data' in locals(): del audio_data
            if 'inst_data' in locals(): del inst_data
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()

        # Формирование итогового JSON
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

        dump_debug("Neural_Matched_V10.0", final_json, self._track_stem)
        log.info(f"✅ Aligner УСПЕШНО ЗАВЕРШЕН → {output_json_path}")
        log.info("=" * 60)
        
        return output_json_path

    def _enforce_strict_monotonicity(self, words: list):
        """
        V10.0 Жесткая Монотонность.
        Ни одно слово физически не может начаться раньше, чем закончится предыдущее.
        Ликвидирует парадоксы путешествий во времени.
        """
        resolves = 0
        micro_gap = 0.05 
        
        # Проход 1: Сдвиг границ нахлеста
        for i in range(len(words) - 1):
            curr_w = words[i]
            next_w = words[i+1]
            
            if curr_w["end"] >= next_w["start"] - micro_gap:
                midpoint = (curr_w["end"] + next_w["start"]) / 2
                
                curr_w["end"] = midpoint - (micro_gap / 2)
                next_w["start"] = midpoint + (micro_gap / 2)
                
                # Защита от выворачивания слов наизнанку
                if curr_w["end"] <= curr_w["start"]:
                    curr_w["end"] = curr_w["start"] + curr_w["min_dur"]
                    next_w["start"] = curr_w["end"] + micro_gap
                    
                if next_w["end"] <= next_w["start"]:
                    next_w["end"] = next_w["start"] + next_w["min_dur"]
                    
                resolves += 1
                
        # Проход 2: Эффект домино (Проталкивание времени вперед)
        for i in range(len(words) - 1):
            if words[i]["end"] > words[i+1]["start"]:
                words[i+1]["start"] = words[i]["end"] + 0.01
                if words[i+1]["end"] <= words[i+1]["start"]:
                     words[i+1]["end"] = words[i+1]["start"] + words[i+1]["min_dur"]
                     
        if resolves > 0:
            log.info(f"   📏 [Monotonicity] Устранено временных парадоксов (нахлестов): {resolves}")