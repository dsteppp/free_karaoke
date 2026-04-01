import os
import gc
import json
import torch
import librosa
import stable_whisper

from app_logger import get_logger, dump_debug
from aligner_utils import detect_language, prepare_text, clean_word, evaluate_alignment_quality, get_phonetic_bounds
from aligner_acoustics import get_vocal_intervals, constrain_to_vad, filter_whisper_hallucinations
from aligner_orchestra import execute_sequence_matching

log = get_logger("aligner")

class KaraokeAligner:
    """
    Neural Sequence Paradigm (V8.2 - Phonetic Fluid & SDR-Guard)
    Абсолютная защита от галлюцинаций и пустых интро/аутро.
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
        log.info(f"🚀 Aligner СТАРТ (V8.2 Phonetic Fluid): {self._track_stem}")
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

            # 4. ФИЛЬТР №1: Очистка галлюцинаций
            heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

            # 5. Оркестратор (Левенштейн + SDR-Guard + Phonetic Fluid)
            canon_words = execute_sequence_matching(canon_words, heard_words, vad_intervals, audio_duration)
            
            # 6. Экстренный Fallback (Сжатие оставшихся дыр без резины)
            log.info("🔧 [Fallback] Экстренная проверка слепых зон...")
            self._force_fill_gaps(canon_words, audio_duration, vad_intervals)
            
            # 7. Физический Контроль (Магнит VAD)
            log.info("🛡️ [Physics Check] Финальная шлифовка таймингов по VAD-контуру...")
            for w in canon_words:
                old_s, old_e = w["start"], w["end"]
                
                # Слово не имеет права висеть в абсолютной тишине
                w["start"], w["end"] = constrain_to_vad(w["start"], w["end"], vad_intervals, w["clean_text"])
                
                # Защита от нулевой длины после обрезки
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1
                    
            # 8. Устранение нахлестов
            self._resolve_overlaps(canon_words)

            # 9. Оценка качества
            score = evaluate_alignment_quality(canon_words, vad_intervals)

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

        dump_debug("Neural_Matched_V8.2", final_json, self._track_stem)
        log.info(f"✅ Aligner УСПЕШНО ЗАВЕРШЕН → {output_json_path}")
        log.info("=" * 60)
        
        return output_json_path

    def _force_fill_gaps(self, words: list, audio_duration: float, vad_intervals: list):
        """
        Если Оркестратор оставил дыры (-1.0), мы принудительно распределяем слова.
        V8.2: Защита от резинового растяжения! Слова сбиваются в плотный ком возле якоря.
        """
        n = len(words)
        i = 0
        first_vocal_start = vad_intervals[0][0] if vad_intervals else 0.0
        healed = 0
        
        while i < n:
            if words[i]["start"] == -1.0:
                j = i
                while j < n and words[j]["start"] == -1.0:
                    j += 1
                
                gap_size = j - i
                
                # Считаем, сколько времени ФИЗИЧЕСКИ нужно на эти слова
                needed_dur = sum((get_phonetic_bounds(words[k]["clean_text"])[0] + get_phonetic_bounds(words[k]["clean_text"])[1]) / 2 for k in range(i, j))
                
                # Ищем рамки
                t_start = words[i-1]["end"] + 0.05 if i > 0 and words[i-1]["start"] != -1.0 else first_vocal_start
                t_end = words[j]["start"] - 0.05 if j < n and words[j]["start"] != -1.0 else audio_duration
                
                if t_start >= t_end:
                    t_start = max(first_vocal_start, t_end - needed_dur) 
                    
                actual_gap_dur = t_end - t_start
                
                # ЕСЛИ ЭТО ИНТРО (Монеточка) - прижимаем вправо к первому слову
                if i == 0 and actual_gap_dur > needed_dur:
                    t_start = t_end - needed_dur
                    log.debug(f"   ⚠️ [Fallback] Интро: прижимаем {gap_size} слов к отметке {t_end:.2f}s (Окно: {needed_dur:.2f}s)")
                
                # ЕСЛИ ЭТО АУТРО - прижимаем влево к последнему слову
                elif j == n and actual_gap_dur > needed_dur:
                    t_end = t_start + needed_dur
                    log.debug(f"   ⚠️ [Fallback] Аутро: прижимаем {gap_size} слов к отметке {t_start:.2f}s (Окно: {needed_dur:.2f}s)")
                
                # Если дыра в середине слишком большая - сжимаем по центру
                elif actual_gap_dur > needed_dur * 2:
                    center = (t_start + t_end) / 2
                    t_start = center - (needed_dur / 2)
                    t_end = center + (needed_dur / 2)
                    log.debug(f"   ⚠️ [Fallback] Центр: сжатие {gap_size} слов в окно {t_start:.2f}s - {t_end:.2f}s")
                else:
                    log.debug(f"   ⚠️ [Fallback] Стандартное распределение {gap_size} слов в окно {t_start:.2f}s - {t_end:.2f}s")

                # Линейное распределение в подготовленном окне
                step = (t_end - t_start) / gap_size
                for k in range(i, j):
                    words[k]["start"] = t_start + (k - i) * step
                    words[k]["end"] = words[k]["start"] + (step * 0.9)
                    healed += 1
                i = j
            else:
                i += 1
                
        if healed > 0:
            log.info(f"   ✅ [Fallback] Принудительно сжато и распределено: {healed} слов.")

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