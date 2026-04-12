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
    Neural Sequence Paradigm (V8.4 - Elastic Clusters)
    Абсолютная защита от орфанных якорей. Резиновое распределение слепых зон.
    """
    
    def __init__(self, model_name="medium"):
        self.model_name = model_name

        # ── Выбор устройства ─────────────────────────────────────────────
        # NVIDIA CUDA  → GPU (работает стабильно)
        # AMD ROCm     → CPU (HIP kernel error с Whisper encoder)
        # CPU          → CPU
        self.device = "cpu"  # default
        try:
            if torch.cuda.is_available():
                # Проверяем ROCm (hip) — Whisper encoder вызывает HIP error
                is_rocm = hasattr(torch.version, "hip") and torch.version.hip is not None
                if is_rocm:
                    device_name = torch.cuda.get_device_name(0)
                    log.info("🎤 Whisper: ROCm detected (%s) — используем CPU (избегаем HIP error)", device_name)
                    self.device = "cpu"
                else:
                    device_name = torch.cuda.get_device_name(0)
                    log.info("🎤 Whisper: NVIDIA GPU (%s) — используем CUDA", device_name)
                    self.device = "cuda"
        except Exception:
            pass

        base_dir = os.path.dirname(os.path.abspath(__file__))
        models_dir = os.environ.get("FK_MODELS_DIR") or os.path.join(base_dir, "models")
        self.whisper_model_dir = os.path.join(models_dir, "whisper")
        try:
            os.makedirs(self.whisper_model_dir, exist_ok=True)
        except OSError:
            pass  # Read-only filesystem (AppImage squashfs) — модель уже там
        
        self._track_stem = ""

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")
        
        log.info("=" * 60)
        log.info(f"🚀 Aligner СТАРТ (V8.4 Elastic Clusters): {self._track_stem}")
        
        # 1. Подготовка текста
        canon_words = prepare_text(raw_lyrics)
        if not canon_words:
            log.warning("⚠️ Текст пуст! Сохраняем пустой JSON.")
            with open(output_json_path, "w", encoding="utf-8") as f:
                json.dump([], f)
            return output_json_path
            
        lang = detect_language(raw_lyrics)

        model = None
        try:
            # 2. Физический анализ звука (VAD Radar)
            audio_data, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data) / sr
            
            vad_intervals = get_vocal_intervals(audio_data, sr, top_db=35.0)
            if not vad_intervals:
                log.warning("⚠️ VAD не нашел голоса в треке! Сценарий глухой тишины.")
                vad_intervals = [(0.0, audio_duration)]

            # --- ВРЕЗКА РЕДАКТОРА (Сохраняем VAD для мгновенного пересчета) ---
            vad_path = output_json_path.replace("_(Karaoke Lyrics).json", "_(VAD).json")
            try:
                with open(vad_path, "w", encoding="utf-8") as vf:
                    json.dump({"duration": audio_duration, "intervals": vad_intervals}, vf)
                log.info("   💾 VAD-кэш успешно сохранен для редактора")
            except Exception as e:
                log.warning(f"   ⚠️ Не удалось сохранить VAD-кэш: {e}")
            # ------------------------------------------------------------------

            # 3. Слух Нейросети
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

            # 4. ФИЛЬТР №1: Очистка галлюцинаций
            heard_words = filter_whisper_hallucinations(raw_heard_words, vad_intervals)

            # 5. Оркестратор (Cluster Filter + Elastic VAD)
            canon_words = execute_sequence_matching(canon_words, heard_words, vad_intervals, audio_duration)
            
            # 6. Физический Контроль (Мягкий Магнит VAD)
            log.info("🛡️ [Physics Check] Финальная шлифовка таймингов...")
            shifted_count = 0
            for w in canon_words:
                w["start"], w["end"], was_shifted = constrain_to_vad(w["start"], w["end"], vad_intervals, max_shift_sec=1.5)
                if was_shifted:
                    shifted_count += 1
                
                # Защита от нулевой длины
                if w["end"] - w["start"] < 0.05:
                    w["end"] = w["start"] + 0.1
                    
            if shifted_count > 0:
                log.info(f"   🧲 [VAD-Magnet] Сдвинуто к голосу слов: {shifted_count}")
                    
            # 7. Устранение нахлестов с микро-паузами
            self._resolve_overlaps(canon_words)

            # 8. Оценка качества
            score = evaluate_alignment_quality(canon_words, vad_intervals)

        except Exception as e:
            log.error(f"❌ Фатальная ошибка Aligner: {e}")
            raise e
        finally:
            # Освобождение памяти
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

        dump_debug("Neural_Matched_V8.4", final_json, self._track_stem)
        log.info(f"✅ Aligner УСПЕШНО ЗАВЕРШЕН → {output_json_path}")
        log.info("=" * 60)
        
        return output_json_path

    def _resolve_overlaps(self, words: list):
        """
        Создает 'Breath-gaps' (микро-паузы) и устраняет нахлесты.
        """
        resolves = 0
        micro_gap = 0.05 
        
        for i in range(len(words) - 1):
            if words[i]["end"] >= words[i+1]["start"] - micro_gap:
                midpoint = (words[i]["end"] + words[i+1]["start"]) / 2
                
                words[i]["end"] = midpoint - (micro_gap / 2)
                words[i+1]["start"] = midpoint + (micro_gap / 2)
                
                if words[i]["end"] <= words[i]["start"]:
                    words[i]["end"] = words[i]["start"] + 0.05
                if words[i+1]["end"] <= words[i+1]["start"]:
                    words[i+1]["end"] = words[i+1]["start"] + 0.05
                    
                resolves += 1
                
        if resolves > 0:
            log.info(f"   📏 [Smoothing] Исправлено нахлестов (созданы микро-паузы): {resolves}")