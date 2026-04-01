import os
import gc
import json
import torch
import librosa
import stable_whisper

from app_logger import get_logger, dump_debug
from aligner_utils import detect_language, prepare_text, clean_word, evaluate_alignment_quality
from aligner_acoustics import get_vocal_intervals, constrain_to_vad, filter_whisper_hallucinations
from aligner_orchestra import execute_sequence_matching

log = get_logger("aligner")

class KaraokeAligner:
    """
    Neural Sequence Paradigm (V8.3 - Magnetic Island)
    Математическая точность таймингов. Отказ от резинового растяжения.
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
        log.info(f"🚀 Aligner СТАРТ (V8.3 Magnetic Island): {self._track_stem}")
        log.info(f"🖥️ Устройство: {self.device.upper()}, Модель: {self.model_name}")
        
        # 1. Подготовка идеального текста (Genius)
        canon_words = prepare_text(raw_lyrics)
        if not canon_words:
            log.warning("⚠️ Текст пуст! Сохраняем пустой JSON.")
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            return output_json_path
            
        lang = detect_language(raw_lyrics)
        log.info(f"📖 Эталонный текст: {len(canon_words)} слов. Язык: {lang.upper()}")

        model = None
        try:
            # 2. Физический анализ звука (VAD Radar)
            log.info("🎵 Загрузка вокального стема (librosa)...")
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            log.info(f"⏱️ Длительность трека: {audio_duration:.2f}s")
            
            vad_intervals = get_vocal_intervals(audio_data, sr, top_db=35.0)
            if not vad_intervals:
                log.warning("⚠️ VAD не нашел голоса в треке! Сценарий глухой тишины.")
                vad_intervals = [(0.0, audio_duration)]

            # 3. Слепой слух Нейросети (Stable-Whisper)
            log.info("🧠 Загрузка модели Stable-Whisper...")
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            log.info("🎧 Нейросеть слушает трек...")
            result = model.transcribe(
                audio_data, 
                language=lang, 
                word_timestamps=True,
                vad=True # Встроенный первичный фильтр
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
                        
            log.info(f"🗣️ Нейросеть услышала {len(raw_heard_words)} сырых слов.")

            # 4. ФИЛЬТР №1: Очистка галлюцинаций (Анти-вздох)
            heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

            # 5. Оркестратор (Левенштейн + SDR-Guard v2 + Magnetic Island)
            # Оркестратор теперь сам собирает ВСЕ слепые зоны. _force_fill_gaps удален.
            canon_words = execute_sequence_matching(canon_words, heard_words, vad_intervals, audio_duration)
            
            # 6. Физический Контроль (Мягкий Магнит VAD)
            log.info("🛡️ [Physics Check] Финальная шлифовка таймингов по VAD-контуру...")
            for w in canon_words:
                old_s, old_e = w["start"], w["end"]
                
                # Магнит мягко подтягивает слова к голосу, лимит сдвига = 1.5 секунды
                w["start"], w["end"] = constrain_to_vad(w["start"], w["end"], vad_intervals, w["clean_text"], max_shift_sec=1.5)
                
                # Защита от нулевой длины после обрезки
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1
                    
            # 7. Устранение нахлестов с микро-паузами (Breath-gaps)
            self._resolve_overlaps(canon_words)

            # 8. Оценка качества
            score = evaluate_alignment_quality(canon_words, vad_intervals)

        except Exception as e:
            log.error(f"❌ Фатальная ошибка Aligner: {e}")
            raise e
        finally:
            # Освобождение памяти (Критично для видеокарт)
            if model: del model
            if 'audio_data' in locals(): del audio_data
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()

        # Формирование JSON
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

        dump_debug("Neural_Matched_V8.3", final_json, self._track_stem)
        log.info(f"✅ Aligner УСПЕШНО ЗАВЕРШЕН → {output_json_path}")
        log.info("=" * 60)
        
        return output_json_path

    def _resolve_overlaps(self, words: list):
        """
        Убеждаемся, что тайминги не наезжают друг на друга.
        V8.3: Внедрение микро-паузы 50мс (0.05s) для дыхания караоке-плеера.
        """
        log.info("📏 [Smoothing] Устранение нахлестов слов и создание микро-пауз...")
        resolves = 0
        micro_gap = 0.05 
        
        for i in range(len(words) - 1):
            # Если конец первого слова наезжает на начало второго (или они встык)
            if words[i]["end"] >= words[i+1]["start"] - micro_gap:
                midpoint = (words[i]["end"] + words[i+1]["start"]) / 2
                
                words[i]["end"] = midpoint - (micro_gap / 2)
                words[i+1]["start"] = midpoint + (micro_gap / 2)
                
                # Защита от выворачивания слова наизнанку (если оно стало отрицательной длины)
                if words[i]["end"] <= words[i]["start"]:
                    words[i]["end"] = words[i]["start"] + 0.05
                if words[i+1]["end"] <= words[i+1]["start"]:
                    words[i+1]["end"] = words[i+1]["start"] + 0.05
                    
                resolves += 1
                
        if resolves > 0:
            log.debug(f"   -> Исправлено нахлестов: {resolves}")