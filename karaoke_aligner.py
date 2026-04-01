import os
import gc
import json
import torch
import librosa
import stable_whisper
import numpy as np

from app_logger import get_logger, dump_debug
from aligner_utils import detect_language, prepare_text, clean_word, evaluate_alignment_quality
from aligner_acoustics import get_vocal_intervals, constrain_to_vad, is_in_silence
from aligner_orchestra import execute_sequence_matching

log = get_logger("aligner")

class KaraokeAligner:
    """
    Neural Sequence Paradigm.
    Индустриальный стандарт привязки текста к вокалу: 
    Слушаем -> Сравниваем (Sequence Matching) -> Ограничиваем физикой (VAD).
    """
    
    def __init__(self, model_name="medium"):
        self.model_name = model_name
        # В ROCm PyTorch видит видеокарту AMD как 'cuda'
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")
        
        log.info("=" * 60)
        log.info(f"🚀 Aligner СТАРТ (Neural Sequence Paradigm): {self._track_stem}")
        log.info(f"🖥️ Устройство: {self.device.upper()}, Модель: {self.model_name}")
        
        # 1. Подготовка текста
        canon_words = prepare_text(raw_lyrics)
        if not canon_words:
            log.warning("⚠️ Текст пуст! Сохраняем пустой JSON.")
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            return output_json_path
            
        lang = detect_language(raw_lyrics)
        log.info(f"📖 Загружен эталонный текст: {len(canon_words)} слов. Определен язык: {lang.upper()}")

        model = None
        try:
            # 2. Акустический анализ
            log.info("🎵 Загрузка вокального стема (librosa)...")
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            log.info(f"⏱️ Длительность трека: {audio_duration:.2f}s")
            
            # Получаем ЖЕСТКИЕ физические интервалы вокала
            vad_intervals = get_vocal_intervals(audio_data, sr, top_db=35.0)
            if not vad_intervals:
                log.warning("⚠️ VAD не нашел голоса в треке! Сценарий тишины.")
                vad_intervals = [(0.0, audio_duration)]

            # 3. Слух Нейросети (Слепая транскрибация)
            log.info("🧠 Загрузка модели Stable-Whisper...")
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            log.info("🎧 Нейросеть слушает трек в слепом режиме (transcribe)...")
            # Используем transcribe, чтобы получить то, что РЕАЛЬНО поется (с идеальными таймингами stable-ts)
            result = model.transcribe(
                audio_data, 
                language=lang, 
                word_timestamps=True,
                vad=True # Включаем встроенный VAD стабильного виспера как подстраховку
            )
            
            heard_words = []
            for segment in result.segments:
                for w in segment.words:
                    cw = clean_word(w.word)
                    if cw:
                        heard_words.append({
                            "word": w.word,
                            "clean": cw,
                            "start": w.start,
                            "end": w.end
                        })
                        
            log.info(f"🗣️ Нейросеть услышала {len(heard_words)} слов.")

            # 4. Neural Sequence Matching (Сопоставление)
            # Приклеиваем услышанное к эталонному тексту Гениуса
            canon_words = execute_sequence_matching(canon_words, heard_words, vad_intervals)
            
            # 5. Финальная полировка и линейная интерполяция дыр
            log.info("🔧 [Cleanup] Финальная зачистка и интерполяция пропущенных слов...")
            self._force_fill_gaps(canon_words, audio_duration, vad_intervals)
            
            # 6. Валидация физики (Никаких слов в пустоте!)
            log.info("🛡️ [Physics Check] Ограничение слов физическим VAD-контуром...")
            for w in canon_words:
                old_s, old_e = w["start"], w["end"]
                # Жестко примагничиваем к ближайшему вокальному блоку
                w["start"], w["end"] = constrain_to_vad(w["start"], w["end"], vad_intervals)
                
                if abs(old_s - w["start"]) > 1.0:
                    log.debug(f"      [VAD-Shift] '{w['word']}' сдвинуто из тишины ({old_s:.2f}s -> {w['start']:.2f}s)")
                
                # Минимальная длительность (защита от сломанных таймингов)
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1
                    
            # 7. Разрешение нахлестов (Один тайминг не может наезжать на другой)
            self._resolve_overlaps(canon_words)

            score = evaluate_alignment_quality(canon_words, vad_intervals)
            log.info(f"📊 Итоговая оценка физического совпадения: {score:.1f}/100")

        except Exception as e:
            log.error(f"❌ Фатальная ошибка Aligner: {e}")
            raise e
        finally:
            # Жесткая очистка памяти (крайне важно для AMD ROCm)
            if model: del model
            if 'audio_data' in locals(): del audio_data
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

        dump_debug("Neural_Matched", final_json, self._track_stem)
        log.info(f"✅ Aligner УСПЕШНО ЗАВЕРШЕН → {output_json_path}")
        log.info("=" * 60)
        
        return output_json_path

    def _force_fill_gaps(self, words: list, audio_duration: float, vad_intervals: list):
        """
        Если Sequence Matcher не смог сопоставить какие-то слова (остались -1.0), 
        мы линейно интерполируем их в доступное окно. Вкупе с _smart_vad_snapping из Оркестратора
        это гарантирует 100% покрытие текста.
        """
        n = len(words)
        i = 0
        while i < n:
            if words[i]["start"] == -1.0:
                j = i
                while j < n and words[j]["start"] == -1.0:
                    j += 1
                
                gap_size = j - i
                log.debug(f"   ⚠️ Обработка глухой зоны: пропущены слова [{i}-{j-1}]. Принудительная интерполяция.")
                
                # Ищем безопасные границы для вставки
                t_start = words[i-1]["end"] + 0.05 if i > 0 and words[i-1]["start"] != -1.0 else (vad_intervals[0][0] if vad_intervals else 0.0)
                t_end = words[j]["start"] - 0.05 if j < n and words[j]["start"] != -1.0 else (vad_intervals[-1][1] if vad_intervals else audio_duration)
                
                if t_start >= t_end:
                    t_start = t_end - (0.2 * gap_size) # Сдвигаем влево, если окно схлопнулось
                    
                # Равномерно делим доступное время
                step = (t_end - t_start) / gap_size
                for k in range(i, j):
                    words[k]["start"] = t_start + (k - i) * step
                    words[k]["end"] = words[k]["start"] + (step * 0.9)
                i = j
            else:
                i += 1

    def _resolve_overlaps(self, words: list):
        """Убеждаемся, что конец предыдущего слова строго не позже начала следующего."""
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