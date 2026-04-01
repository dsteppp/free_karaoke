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
    Neural Sequence Paradigm (V8.1)
    Полный отказ от кастомной математики в пользу машинного слуха + VAD-фильтрации.
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
        log.info(f"🚀 Aligner СТАРТ (Neural Sequence V8.1): {self._track_stem}")
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
            # 2. Физический анализ звука (VAD)
            log.info("🎵 Загрузка вокального стема (librosa)...")
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            log.info(f"⏱️ Длительность трека: {audio_duration:.2f}s")
            
            # Получаем жесткие рамки, где физически есть голос
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
                vad=True # Встроенный VAD виспера как первичный фильтр
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
                            "probability": w.probability # Важный параметр для фильтрации вздохов!
                        })
                        
            log.info(f"🗣️ Нейросеть услышала {len(raw_heard_words)} сырых слов.")

            # 4. ФИЛЬТР №1 + №2: Очистка галлюцинаций (вздохи, гитарные соло)
            heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

            # 5. Neural Sequence Matching (Оркестратор + Левенштейн)
            canon_words = execute_sequence_matching(canon_words, heard_words, vad_intervals)
            
            # 6. Заполнение мертвых зон (если Левенштейн и Мотивы не справились)
            log.info("🔧 [Cleanup] Линейная интерполяция оставшихся слепых зон...")
            self._force_fill_gaps(canon_words, audio_duration, vad_intervals)
            
            # 7. Физический Контроль (Жесткая привязка к VAD)
            log.info("🛡️ [Physics Check] Финальная шлифовка таймингов по VAD-контуру...")
            for w in canon_words:
                old_s, old_e = w["start"], w["end"]
                
                # Слово не имеет права висеть в тишине
                w["start"], w["end"] = constrain_to_vad(w["start"], w["end"], vad_intervals)
                
                if abs(old_s - w["start"]) > 0.5:
                    log.debug(f"      [VAD-Shift] '{w['word']}' сдвинуто из тишины ({old_s:.2f}s -> {w['start']:.2f}s)")
                
                # Защита от нулевой длины
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1
                    
            # 8. Устранение нахлестов (одно слово не может звучать поверх другого)
            self._resolve_overlaps(canon_words)

            # 9. Оценка качества
            score = evaluate_alignment_quality(canon_words, vad_intervals)
            log.info(f"📊 Итоговая оценка физического совпадения: {score:.1f}/100")

        except Exception as e:
            log.error(f"❌ Фатальная ошибка Aligner: {e}")
            raise e
        finally:
            # Освобождение памяти (Критично для AMD ROCm)
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

        dump_debug("Neural_Matched_V8.1", final_json, self._track_stem)
        log.info(f"✅ Aligner УСПЕШНО ЗАВЕРШЕН → {output_json_path}")
        log.info("=" * 60)
        
        return output_json_path

    def _force_fill_gaps(self, words: list, audio_duration: float, vad_intervals: list):
        """
        Если Оркестратор оставил дыры (-1.0), мы принудительно распределяем слова.
        ВАЖНО: Защита от 0.0s! Текст не может начаться раньше первого звука голоса.
        """
        n = len(words)
        i = 0
        first_vocal_start = vad_intervals[0][0] if vad_intervals else 0.0
        
        while i < n:
            if words[i]["start"] == -1.0:
                j = i
                while j < n and words[j]["start"] == -1.0:
                    j += 1
                
                gap_size = j - i
                log.debug(f"   ⚠️ Обработка глухой зоны: пропущены слова [{i}-{j-1}]. Принудительная интерполяция.")
                
                # Защита от старта с 0.0s
                if i == 0:
                    t_start = first_vocal_start
                else:
                    t_start = words[i-1]["end"] + 0.05 if words[i-1]["start"] != -1.0 else first_vocal_start
                    
                t_end = words[j]["start"] - 0.05 if j < n and words[j]["start"] != -1.0 else (vad_intervals[-1][1] if vad_intervals else audio_duration)
                
                # Если окно схлопнулось (слова спрессовались)
                if t_start >= t_end:
                    t_start = max(first_vocal_start, t_end - (0.2 * gap_size)) 
                    
                # Линейное распределение в доступном окне
                step = (t_end - t_start) / gap_size
                for k in range(i, j):
                    words[k]["start"] = t_start + (k - i) * step
                    words[k]["end"] = words[k]["start"] + (step * 0.9)
                i = j
            else:
                i += 1

    def _resolve_overlaps(self, words: list):
        """Убеждаемся, что тайминги не наезжают друг на друга."""
        log.info("📏 [Smoothing] Устранение нахлестов слов...")
        resolves = 0
        for i in range(len(words) - 1):
            if words[i]["end"] > words[i+1]["start"]:
                midpoint = (words[i]["end"] + words[i+1]["start"]) / 2
                words[i]["end"] = midpoint - 0.01
                words[i+1]["start"] = midpoint + 0.01
                resolves += 1
        if resolves > 0:
            log.debug(f"   -> Исправлено нахлестов: {resolves}")