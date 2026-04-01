import os
import gc
import re
import json
import copy
import torch
import librosa
import rapidfuzz
import stable_whisper
import numpy as np

from app_logger import get_logger, dump_debug

# ─── ИМПОРТЫ ИЗ НАШЕЙ НОВОЙ МОДУЛЬНОЙ СИСТЕМЫ (SYMPHONY V6.0) ───────────────
from aligner_utils import (
    detect_language, prepare_text, get_vowel_weight, 
    get_phonetic_bounds, get_vad_capacity,
    get_empirical_data, get_safe_bounds, evaluate_alignment_quality,
    is_repetition_island, calculate_overlap
)
from aligner_acoustics import (
    enforce_curtains, get_acoustic_maps
)
from aligner_orchestra import (
    propose_motif_matrix, propose_inquisitor, 
    propose_harpoon, propose_loom, the_supreme_judge
)

log = get_logger("aligner")

class KaraokeAligner:
    """
    Главный Дирижер "Symphony V6.0: Bi-Directional Solid-State Pipeline".
    Слепой Оракул, Цикл Ковки, Великая Сверка.
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""
        self.all_curtains = [] 
        self.blind_words = [] # Слепок реальности

    # ─── ЭТАП 2 и 3: СЛЕПОЙ ОРАКУЛ И МАТРИЦА (V6.0) ─────────────────────────────

    def _blind_oracle_and_matrix(self, model, audio_data: np.ndarray, canon_words: list, lang: str):
        """Создает слепок физической реальности и накладывает Идеальный Текст (Матрица)."""
        log.info("🔮 [Oracle] Запуск Слепого Оракула (чистая транскрипция)...")
        
        result = model.transcribe(audio_data, language=lang)
        self.blind_words = []
        for w in result.all_words():
            c = re.sub(r'[^\w]', '', w.word.lower())
            if c and (w.end - w.start) > 0.05: 
                self.blind_words.append({"clean": c, "start": w.start, "end": w.end})
                
        log.info(f"   -> Распознано {len(self.blind_words)} слепых фрагментов.")

        log.info("🧬 [Matrix] Стыковка Идеального Текста со Слепым Оракулом...")
        lines = {}
        for i, w in enumerate(canon_words):
            lines.setdefault(w["line_num"], []).append(i)
            
        b_idx = 0
        anchored_count = 0
        
        for l_num, w_indices in sorted(lines.items()):
            line_clean = "".join([canon_words[i]["clean_text"] for i in w_indices])
            best_score = 0
            best_match = None
            
            # Скользим окном Слепого Оракула для поиска строки
            search_limit = min(b_idx + 40, len(self.blind_words))
            for i in range(b_idx, search_limit):
                for j in range(i + 1, min(i + len(w_indices) + 6, len(self.blind_words) + 1)):
                    b_text = "".join([bw["clean"] for bw in self.blind_words[i:j]])
                    score = rapidfuzz.fuzz.ratio(line_clean, b_text)
                    if score > 85: # Железобетонный порог цементирования
                        if score > best_score:
                            best_score = score
                            best_match = (i, j)
                            
            if best_match:
                match_s, match_e = best_match
                t_s = self.blind_words[match_s]["start"]
                t_e = self.blind_words[match_e - 1]["end"]
                
                # Распределяем слова внутри найденного блока по фонетическому весу
                lw_total = sum(get_vowel_weight(canon_words[k]["clean_text"], False) for k in w_indices)
                if lw_total == 0: lw_total = 1.0
                
                curr_t = t_s
                for k in w_indices:
                    w_dur = (get_vowel_weight(canon_words[k]["clean_text"], False) / lw_total) * (t_e - t_s)
                    canon_words[k]["start"] = curr_t
                    canon_words[k]["end"] = curr_t + w_dur
                    canon_words[k]["locked"] = True # 🔒 Защита от сдвига
                    curr_t += w_dur
                    
                b_idx = match_e
                anchored_count += len(w_indices)
                
        log.info(f"   -> Матрица зацементировала {anchored_count}/{len(canon_words)} слов.")

    # ─── ЭТАП 5: ДВУНАПРАВЛЕННЫЙ РАДАР (V6.0) ───────────────────────────────────

    def _bi_directional_radar(self, words: list, empirical_data: dict):
        log.info("🔄 [Radar] Двунаправленный аудит аномалий...")
        
        # 1. L->R: Точечная микрохирургия (Без эффекта домино!)
        isolated = 0
        for w in words:
            if w["start"] != -1.0:
                dur = w["end"] - w["start"]
                if dur < 0.05:
                    w["start"] = w["end"] = -1.0
                    w["locked"] = False
                    isolated += 1
        if isolated > 0:
            log.info(f"   -> [L->R] Сингулярности устранены: {isolated} слов изолировано.")

        # 2. R->L: Разрывы Строф (Защита от фейкового интро Монеточки)
        emp_gap = empirical_data.get("avg_breath_gap", 0.5)
        critical_gap = max(5.0, emp_gap * 10)
        
        for i in range(len(words)-1, 0, -1):
            curr_w = words[i]
            prev_w = words[i-1]
            
            if curr_w["start"] != -1 and prev_w["end"] != -1 and curr_w["stanza_num"] == prev_w["stanza_num"]:
                gap = curr_w["start"] - prev_w["end"]
                if gap > critical_gap:
                    has_curtain = any(c_s >= prev_w["end"] and c_e <= curr_w["start"] for c_s, c_e in self.all_curtains)
                    if not has_curtain:
                        log.warning(f"   -> [R->L] АНОМАЛИЯ: Разрыв в строфе №{curr_w['stanza_num']} ({gap:.1f}s). Сброс мусора слева.")
                        # Всё, что левее разрыва в этой же строфе - это мусор, натянутый на бит
                        for k in range(i):
                            if words[k]["stanza_num"] == curr_w["stanza_num"]:
                                words[k]["start"] = words[k]["end"] = -1.0
                                words[k]["locked"] = False
                        break # Один крупный сброс за итерацию

    # ─── ЭТАП 8: ВЕЛИКАЯ СВЕРКА (THE GRAND VERIFICATION) ────────────────────────

    def _grand_verification(self, words: list, audio_duration: float) -> int:
        log.info("👁️ [Verification] ВЕЛИКАЯ СВЕРКА со Слепым Оракулом...")
        braks = 0
        
        # 1. Forward Check (Проверка наложенного текста на реальность)
        lines = {}
        for i, w in enumerate(words):
            if w["start"] != -1: lines.setdefault(w["line_num"], []).append(i)
            
        for l_num, idxs in lines.items():
            l_s = words[idxs[0]]["start"]
            l_e = words[idxs[-1]]["end"]
            
            oracle_text = "".join([bw["clean"] for bw in self.blind_words if bw["end"] > l_s and bw["start"] < l_e])
            my_text = "".join([words[i]["clean_text"] for i in idxs])
            
            if not oracle_text and (l_e - l_s > 1.0): 
                log.debug(f"   -> [L->R] Строка {l_num} ({l_s:.1f}s): Оракул слышит тишину! БРАК.")
                for i in idxs: 
                    words[i]["start"] = words[i]["end"] = -1.0
                    words[i]["locked"] = False
                braks += 1
            elif oracle_text:
                score = rapidfuzz.fuzz.partial_ratio(my_text, oracle_text)
                if score < 30 and len(my_text) > 5:
                    log.debug(f"   -> [L->R] Строка {l_num} ({l_s:.1f}s): Текст не совпадает (Score: {score:.1f}). БРАК.")
                    for i in idxs: 
                        words[i]["start"] = words[i]["end"] = -1.0
                        words[i]["locked"] = False
                    braks += 1

        # 2. Reverse Check (Поиск съехавшего Аутро / Эффект Золото)
        last_word_time = 0.0
        for w in reversed(words):
            if w["start"] != -1:
                last_word_time = w["end"]
                break
                
        oracle_last_time = 0.0
        if self.blind_words: oracle_last_time = self.blind_words[-1]["end"]
        
        if oracle_last_time - last_word_time > 10.0:
            log.warning(f"   -> [R->L] Оракул слышит вокал до {oracle_last_time:.1f}s, а текст кончился на {last_word_time:.1f}s! Сброс финала.")
            # Разблокируем последние 2 строфы для сдвига вправо
            target_stanzas = set(w["stanza_num"] for w in words[-15:])
            for w in words:
                if w["stanza_num"] in target_stanzas:
                    w["start"] = w["end"] = -1.0
                    w["locked"] = False
            braks += 1
            
        return braks

    # ─── ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ──────────────────────────────────────────────

    def _find_gaps(self, words: list) -> list:
        gaps, i, n = [], 0, len(words)
        while i < n:
            if words[i]["start"] == -1:
                j = i
                while j < n and words[j]["start"] == -1: j += 1
                gaps.append((i, j - 1))
                i = j
            else: i += 1
        return gaps

    def _the_arena_surgery(self, words: list, gap: tuple, audio_data: np.ndarray, model, lang: str, strong_vad: list, weak_vad: list, audio_duration: float, empirical_data: dict):
        s_idx, e_idx = gap
        t_start, t_end = get_safe_bounds(words, s_idx, e_idx, audio_duration)
        if t_end - t_start < 0.1: return

        log.info(f"🏟️ [The Arena] Слова [{s_idx}-{e_idx}] выходят на Арену! Окно: {t_start:.1f}s - {t_end:.1f}s")
        proposals = []
        
        if is_repetition_island(words, s_idx, e_idx):
            prop_motif = propose_motif_matrix(words, s_idx, e_idx, audio_duration, strong_vad)
            if prop_motif: proposals.append(prop_motif)
            
        prop_inq = propose_inquisitor(words, s_idx, e_idx, audio_data, model, lang, t_start, t_end)
        if prop_inq: proposals.append(prop_inq)
            
        prop_harp = propose_harpoon(words, s_idx, e_idx, audio_data, model, lang, t_start, t_end)
        if prop_harp: proposals.append(prop_harp)
            
        prop_loom = propose_loom(words, s_idx, e_idx, t_start, t_end, strong_vad, weak_vad, empirical_data)
        if prop_loom: proposals.append(prop_loom)
            
        winner = the_supreme_judge(proposals, words, s_idx, e_idx, strong_vad, weak_vad, self.all_curtains, empirical_data)
        
        if winner:
            for k, t in enumerate(winner.timings):
                # Прогоняем через Железный Занавес (Бульдозер)
                mapped_s, mapped_e = enforce_curtains(t["start"], t["end"], self.all_curtains)
                words[s_idx + k]["start"] = mapped_s
                words[s_idx + k]["end"] = mapped_e
        else:
            log.warning(f"   ⚠️ Арена не выявила победителя для [{s_idx}-{e_idx}].")

    def _local_snapping(self, words: list, empirical_data: dict):
        """V6.0: Магнитная доводка остатков. Больше не раскидывает мусор по треку."""
        log.info("🧲 [Magnet] Локальная Магнитная Доводка остатков...")
        n = len(words)
        bg = min(empirical_data.get("avg_breath_gap", 0.5), 1.0) if empirical_data else 0.4
        
        i = 0
        while i < n:
            if words[i]["start"] == -1.0:
                j = i
                while j < n and words[j]["start"] == -1.0: j += 1
                
                left_anchor = words[i-1]["end"] if i > 0 and words[i-1]["end"] != -1 else 0.0
                right_anchor = words[j]["start"] if j < n and words[j]["start"] != -1 else left_anchor + 10.0
                
                curr_t = left_anchor + (bg if i > 0 and words[i]["line_num"] != words[i-1]["line_num"] else 0.05)
                
                for k in range(i, j):
                    w_min, w_max = get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])
                    w_dur = (w_min + w_max) / 2.0
                    
                    if curr_t + w_dur > right_anchor: 
                        w_dur = max(0.1, (right_anchor - curr_t) / (j - k))
                        
                    words[k]["start"] = curr_t
                    words[k]["end"] = curr_t + w_dur
                    curr_t += w_dur + 0.05
                i = j
            else:
                i += 1

    def _smoothing(self, words: list):
        last_e = 0.0
        for w in words:
            if w["start"] < last_e: w["start"] = last_e + 0.01
            if w["end"] <= w["start"]: w["end"] = w["start"] + 0.1
            w["start"], w["end"] = enforce_curtains(w["start"], w["end"], self.all_curtains)
            last_e = w["end"]

    # ─── MAIN ORCHESTRATOR ──────────────────────────────────────────────────────

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info(f"Aligner СТАРТ (Symphony V6.0: Bi-Directional Solid-State): {self._track_stem}")
        
        canon_words = prepare_text(raw_lyrics)
        if not canon_words:
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = detect_language(raw_lyrics)
        model = None
        
        try:
            audio_data_raw, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data_raw) / sr
            
            # ЭТАП 1: Истинная Вокальная Карта
            strong_vad, weak_vad, iron_curtains, onsets, is_harmonic_fn = get_acoustic_maps(audio_data_raw, sr)
            self.all_curtains = sorted(iron_curtains, key=lambda x: x[0])
            combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])

            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)

            # ЭТАП 2 и 3: Слепой Оракул и Матрица Якорей
            self._blind_oracle_and_matrix(model, audio_data_raw, canon_words, lang)

            # ЭТАП 4: Паспорт Песни
            empirical_data = get_empirical_data(canon_words)

            # ЭТАП 9: ЦИКЛ КОВКИ (The Cyclic Forge)
            history_hashes = set()
            for iteration in range(4): # Максимум 4 круга ковки
                
                # ЭТАП 5: Двунаправленный Радар
                self._bi_directional_radar(canon_words, empirical_data)
                
                gaps = self._find_gaps(canon_words)
                if not gaps: break
                
                log.info(f"♻️ [Forge] Цикл Ковки {iteration+1}/4. Найдено дыр: {len(gaps)}")
                
                # ЭТАП 7: Арена и Станок
                for gap in gaps:
                    self._the_arena_surgery(canon_words, gap, audio_data_raw, model, lang, strong_vad, weak_vad, audio_duration, empirical_data)
                    
                # ЭТАП 8: Великая Сверка
                braks = self._grand_verification(canon_words, audio_duration)
                
                # Защита от бесконечного цикла (Stalemate)
                current_hash = hash(tuple(w["start"] for w in canon_words))
                if current_hash in history_hashes:
                    log.warning("   -> [Forge] Stalemate detected! Арена повторяет ошибки. Заморозка состояния (Fallback).")
                    break
                history_hashes.add(current_hash)
                
                if braks == 0:
                    log.info("   -> [Forge] Великая Сверка пройдена без брака. Идеальное выравнивание достигнуто.")
                    for w in canon_words:
                        if w["start"] != -1: w["locked"] = True
                    break

            # ЭТАП 11: Локальный Магнит и Полировка
            if any(w["start"] == -1.0 for w in canon_words):
                self._local_snapping(canon_words, empirical_data)
                
            self._smoothing(canon_words)

            # ЭТАП 10: Финальный Абсолютный Судья
            score = evaluate_alignment_quality(canon_words, strong_vad, weak_vad, self.all_curtains)
            
        except Exception as e:
            log.error(f"Ошибка Aligner: {e}")
            raise e
        finally:
            if model: del model
            if 'audio_data_raw' in locals(): del audio_data_raw
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()

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

        dump_debug("14_0_Symphony", final_json, self._track_stem)
        log.info(f"Aligner ГОТОВО → {output_json_path}")
        log.info("=" * 50)
        
        return output_json_path