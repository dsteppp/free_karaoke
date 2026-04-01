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

# ─── ИМПОРТЫ ИЗ НАШЕЙ НОВОЙ МОДУЛЬНОЙ СИСТЕМЫ (SYMPHONY V6.3) ─────────────────
from aligner_utils import (
    detect_language, prepare_text, get_vowel_weight, get_empirical_data,
    get_phonetic_bounds, get_safe_bounds, evaluate_alignment_quality,
    is_repetition_island
)
from aligner_acoustics import (
    build_iron_curtain, enforce_curtains, get_acoustic_maps
)
from aligner_orchestra import (
    Proposal, propose_motif_matrix, propose_inquisitor, 
    propose_harpoon, propose_loom, the_supreme_judge, diagnostic_compass
)

log = get_logger("aligner")

class KaraokeAligner:
    """
    Главный Дирижер "Symphony V6.3: The Perfect Hybrid".
    Абсолютный симбиоз Акустической Физики и Лингвистического Интеллекта.
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""
        self.all_curtains = [] 

    # ─── ЭТАП 1: ЧЕРНОВИК И ОРАКУЛ (THE DUAL ENGINE) ──────────────────────────

    def _draft_alignment(self, model, audio_data: np.ndarray, words: list, lang: str):
        log.info("📝 [Draft] Шаг 1: Формирование Черновика (model.align)...")
        text_for_whisper = " ".join([w["word"] for w in words])
        
        try:
            result = model.align(audio_data, text_for_whisper, language=lang)
            sw_words = result.all_words()
        except Exception as e:
            log.warning(f"   ⚠️ Сбой model.align: {e}")
            return
            
        valid_sw = []
        for w in sw_words:
            if (w.end - w.start) >= 0.05:
                cl = re.sub(r'[^\w]', '', w.word.lower())
                if cl: valid_sw.append({"clean": cl, "start": w.start, "end": w.end})
                
        canon_idx, sw_idx, anchors_count = 0, 0, 0
        search_window = 60
        
        while canon_idx < len(words) and sw_idx < len(valid_sw):
            best_match_len, best_c_idx = 0, -1
            for c in range(canon_idx, min(canon_idx + search_window, len(words))):
                match_len = 0
                while (c + match_len < len(words) and 
                       sw_idx + match_len < len(valid_sw) and 
                       words[c + match_len]["clean_text"] == valid_sw[sw_idx + match_len]["clean"]):
                    match_len += 1
                if match_len > best_match_len:
                    best_match_len, best_c_idx = match_len, c
                    
            is_valid = False
            if best_match_len >= 3: is_valid = True
            elif best_match_len == 2 and sum(len(words[best_c_idx + k]["clean_text"]) for k in range(2)) >= 8: 
                is_valid = True

            if is_valid:
                for k in range(best_match_len):
                    words[best_c_idx + k]["start"] = valid_sw[sw_idx + k]["start"]
                    words[best_c_idx + k]["end"] = valid_sw[sw_idx + k]["end"]
                canon_idx = best_c_idx + best_match_len
                sw_idx += best_match_len
                anchors_count += best_match_len
            else:
                sw_idx += 1
                
        log.info(f"   📋 Черновик собран: {anchors_count}/{len(words)} слов получили тайминги.")


    def _blind_oracle(self, model, audio_data: np.ndarray, lang: str) -> list:
        log.info("👁️ [Oracle] Шаг 2: Слепой Оракул слушает трек (model.transcribe)...")
        try:
            result = model.transcribe(audio_data, language=lang)
            sw_words = result.all_words()
            
            blind_words = []
            for w in sw_words:
                cl = re.sub(r'[^\w]', '', w.word.lower())
                if cl:
                    blind_words.append({"clean": cl, "start": w.start, "end": w.end})
            log.info(f"   👁️ Оракул услышал {len(blind_words)} слов.")
            return blind_words
        except Exception as e:
            log.warning(f"   ⚠️ Оракул не смог распознать трек: {e}")
            return []

    # ─── ЭТАП 2: СВЕРКА И РАДАР (THE CROSSCHECK) ──────────────────────────────

    def _crosscheck_oracle(self, words: list, blind_words: list, curtains: list):
        log.info("⚖️ [Crosscheck] Сверка Черновика со Слепым Оракулом...")
        total = len([w for w in words if w["start"] != -1.0])
        if total == 0: return
        
        rejected = 0
        original_words = copy.deepcopy(words)
        
        for w in words:
            if w["start"] == -1.0: continue
            
            match_found = False
            for bw in blind_words:
                # Окно поиска совпадений: ±1.0 сек
                if not (bw["end"] < w["start"] - 1.0 or bw["start"] > w["end"] + 1.0):
                    score = rapidfuzz.fuzz.ratio(w["clean_text"], bw["clean"])
                    if score > 75:
                        match_found = True
                        break
            
            if not match_found:
                w["start"], w["end"] = -1.0, -1.0
                rejected += 1
                
        reject_ratio = rejected / total if total > 0 else 0
        log.info(f"   📉 Оракул забраковал {rejected}/{total} слов ({(reject_ratio*100):.1f}%).")
        
        # 🚨 Blindness Failsafe (Страховка от Слепоты)
        if reject_ratio > 0.85:
            log.warning("   🚨 [Blindness Failsafe] Оракул ослеп (дисторшн/метал)! Восстановление Черновика и запуск Бульдозера.")
            for i in range(len(words)):
                ow = original_words[i]
                if ow["start"] != -1.0:
                    s, e = enforce_curtains(ow["start"], ow["end"], curtains)
                    if e - s > 0.05:
                        words[i]["start"], words[i]["end"] = s, e
                    else:
                        words[i]["start"], words[i]["end"] = -1.0, -1.0


    def _bi_directional_radar(self, words: list, curtains: list):
        log.info("📡 [Radar] Двунаправленное сканирование аномалий...")
        
        # L->R: Уничтожитель Сингулярностей и Нарушителей Занавесов
        for w in words:
            if w["start"] != -1.0:
                if w["end"] - w["start"] < 0.05:
                    w["start"], w["end"] = -1.0, -1.0
                else:
                    for cs, ce in curtains:
                        if cs + 0.1 < w["start"] < ce - 0.1 or cs + 0.1 < w["end"] < ce - 0.1:
                            w["start"], w["end"] = -1.0, -1.0
                            break

        # R->L: Убийца Фейковых Интро
        n = len(words)
        for i in range(n - 2, -1, -1):
            w1 = words[i]
            w2 = words[i+1]
            if w1["start"] != -1.0 and w2["start"] != -1.0:
                if w1["stanza_idx"] == w2["stanza_idx"]: # Внутри одной строфы
                    gap = w2["start"] - w1["end"]
                    if gap > 5.0:
                        # Проверяем, не оправдана ли дыра Железным Занавесом
                        has_curtain = any(cs >= w1["end"] and ce <= w2["start"] for cs, ce in curtains)
                        if not has_curtain:
                            log.warning(f"   🎯 [R->L Radar] Обнаружено Фейковое Интро! Разрыв {gap:.1f}s внутри строфы. Снос левой части.")
                            for k in range(i + 1):
                                words[k]["start"], words[k]["end"] = -1.0, -1.0
                            break # Уничтожив интро, радар останавливается


    def _outro_protection(self, words: list, strong_vad: list) -> bool:
        if not words or not strong_vad: return False
        last_word_end = max((w["end"] for w in words if w["start"] != -1.0), default=0)
        last_vocal_end = strong_vad[-1][1]
        
        if last_vocal_end - last_word_end > 10.0: 
            log.warning(f"   🛡️ [Outro Protection] Найден вокал после текста (разрыв {last_vocal_end - last_word_end:.1f}s). Откатываем последний куплет!")
            last_stanza = words[-1]["stanza_idx"]
            for w in words:
                if w["stanza_idx"] == last_stanza:
                    w["start"], w["end"] = -1.0, -1.0
            return True
        return False

    # ─── ЭТАП 3: АРЕНА И ОПЕРАЦИОННАЯ ──────────────────────────────────────────

    def _find_gaps(self, words: list) -> list:
        gaps, i, n = [], 0, len(words)
        while i < n:
            if words[i]["start"] == -1.0:
                j = i
                while j < n and words[j]["start"] == -1.0: j += 1
                gaps.append((i, j - 1))
                i = j
            else: i += 1
        return gaps


    def _the_arena_surgery(self, words: list, gap: tuple, audio_data: np.ndarray, model, lang: str, strong_vad: list, weak_vad: list, curtains: list, first_vocal_t: float, audio_duration: float):
        s_idx, e_idx = gap
        t_start, t_end = get_safe_bounds(words, s_idx, e_idx, audio_duration)
        if t_end - t_start < 0.1: return

        log.info(f"🏟️ [The Arena] Слова [{s_idx}-{e_idx}] выходят на Арену! Окно: {t_start:.1f}s - {t_end:.1f}s")
        proposals = []
        
        # 1. Motif Matrix (Клонатор)
        if is_repetition_island(words, s_idx, e_idx):
            prop_motif = propose_motif_matrix(words, s_idx, e_idx, audio_duration, strong_vad)
            if prop_motif: proposals.append(prop_motif)
            
        # 2. CTC Inquisitor (Фокусный Wav2Vec2)
        prop_inq = propose_inquisitor(words, s_idx, e_idx, audio_data, model, lang, t_start, t_end)
        if prop_inq: proposals.append(prop_inq)
            
        # 3. Semantic Harpoon (Фокусный Слепой Whisper)
        prop_harp = propose_harpoon(words, s_idx, e_idx, audio_data, model, lang, t_start, t_end)
        if prop_harp: proposals.append(prop_harp)
            
        # 4. Smart Elastic Loom V6.3
        prop_loom = propose_loom(words, s_idx, e_idx, t_start, t_end, strong_vad, weak_vad, first_vocal_t)
        if prop_loom: proposals.append(prop_loom)
            
        # Суд Арены
        winner = the_supreme_judge(proposals, words, s_idx, e_idx, strong_vad, weak_vad, curtains, first_vocal_t)
        
        if winner:
            for k, t in enumerate(winner.timings):
                mapped_s, mapped_e = enforce_curtains(t["start"], t["end"], curtains)
                words[s_idx + k]["start"] = mapped_s
                words[s_idx + k]["end"] = mapped_e
        else:
            log.warning(f"   ⚠️ Арена не выявила победителя для [{s_idx}-{e_idx}].")

    # ─── ЭТАП 4: ФИНАЛЬНАЯ ПОЛИРОВКА ────────────────────────────────────────────

    def _local_snapping(self, words: list, audio_duration: float):
        """Магнитит 1-2 пропущенных слова к известным соседям."""
        log.info("🧲 [Snapping] Локальное примагничивание одиночных слов...")
        n = len(words)
        i = 0
        while i < n:
            if words[i]["start"] == -1.0:
                j = i
                while j < n and words[j]["start"] == -1.0: j += 1
                
                gap_len = j - i
                if gap_len <= 2:
                    t_start = words[i-1]["end"] + 0.1 if i > 0 and words[i-1]["start"] != -1.0 else 0.0
                    t_end = words[j]["start"] - 0.1 if j < n and words[j]["start"] != -1.0 else audio_duration
                    
                    if (t_end - t_start) > 0.2:
                        step = min((t_end - t_start) / gap_len, 1.5) 
                        for k in range(gap_len):
                            s = t_start + k * step
                            e = s + step * 0.9
                            s, e = enforce_curtains(s, e, self.all_curtains)
                            words[i+k]["start"] = s
                            words[i+k]["end"] = e
                i = j
            else:
                i += 1

    def _apply_vad_guillotine(self, words: list, vad_mask: list):
        if not vad_mask: return
        log.info("🪓 [VAD-Guillotine] Отсечение фальстартов в слепых зонах...")
        for i, w in enumerate(words):
            if w["start"] == -1.0: continue
            in_vad = any(vs - 0.1 <= w["start"] <= ve + 0.1 for vs, ve in vad_mask)
            if not in_vad:
                next_vad_start = None
                for vs, ve in vad_mask:
                    if vs > w["start"]:
                        next_vad_start = vs
                        break
                if next_vad_start:
                    max_push = w["end"] - 0.05
                    if i < len(words) - 1 and words[i+1]["start"] != -1.0:
                        max_push = min(max_push, words[i+1]["start"] - 0.05)
                    new_start = min(next_vad_start, max_push)
                    if new_start > w["start"]:
                        w["start"] = new_start

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
        log.info(f"Aligner СТАРТ (Symphony V6.3: The Perfect Hybrid): {self._track_stem}")
        
        canon_words = prepare_text(raw_lyrics)
        if not canon_words:
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = detect_language(raw_lyrics)
        model = None
        
        try:
            audio_data_raw, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data_raw) / sr
            
            # Акустическая Физика
            self.all_curtains = build_iron_curtain(audio_data_raw, sr)
            strong_vad, weak_vad, onsets, is_harmonic_fn = get_acoustic_maps(audio_data_raw, sr, self.all_curtains)
            combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])
            first_vocal_t = strong_vad[0][0] if strong_vad else 0.0

            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            # Двойной Движок
            self._draft_alignment(model, audio_data_raw, canon_words, lang)
            blind_words = self._blind_oracle(model, audio_data_raw, lang)
            self._crosscheck_oracle(canon_words, blind_words, self.all_curtains)
            
            # Биометрия
            passport = get_empirical_data(canon_words)
            log.info(f"   🧬 Паспорт Песни: SDR = {passport['sdr']:.2f} слог/с, Вдох = {passport['avg_breath']:.2f}с")

            # Сканирование аномалий
            self._bi_directional_radar(canon_words, self.all_curtains)
            
            # Цикл Ковки
            max_loops = 4
            prev_gaps = []
            for loop_idx in range(max_loops):
                gaps = self._find_gaps(canon_words)
                
                # Защита Аутро (срабатывает на первом круге)
                if loop_idx == 0:
                    if self._outro_protection(canon_words, strong_vad):
                        gaps = self._find_gaps(canon_words)
                
                if not gaps:
                    log.info(f"   ✨ [The Forge] Все слова распределены (Итерация {loop_idx+1}).")
                    break
                    
                if gaps == prev_gaps:
                    log.warning("   🛑 [Stalemate] Арена зациклилась. Остановка Ковки.")
                    break
                prev_gaps = copy.deepcopy(gaps)
                
                # Слияние Островов
                merged_gaps = []
                for gap in gaps:
                    if not merged_gaps:
                        merged_gaps.append(gap)
                    else:
                        last_s, last_e = merged_gaps[-1]
                        curr_s, curr_e = gap
                        if curr_s - last_e <= 4:
                            if is_repetition_island(canon_words, last_s, curr_e):
                                for k in range(last_e + 1, curr_s):
                                    canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                                merged_gaps[-1] = (last_s, curr_e)
                                log.info(f"   🏝️ [Island Expansion] Дыры слиты в Остров Повторов: [{last_s}-{curr_e}]")
                                continue
                        merged_gaps.append(gap)
                gaps = merged_gaps
                
                for gap in gaps:
                    s_idx, e_idx = gap
                    t_start, t_end = get_safe_bounds(canon_words, s_idx, e_idx, audio_duration)
                    
                    if (e_idx - s_idx) >= 2:
                        shift_idx = diagnostic_compass(canon_words, s_idx, e_idx, audio_data_raw, t_start, t_end, model, lang)
                        if shift_idx != -1:
                            log.warning(f"   🔄 [Compass] Глобальный сдвиг. Расширяем карантин до {shift_idx} слова.")
                            for k in range(e_idx + 1, shift_idx + 1):
                                canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                            gap = (s_idx, shift_idx)
                    
                    self._the_arena_surgery(canon_words, gap, audio_data_raw, model, lang, strong_vad, weak_vad, self.all_curtains, first_vocal_t, audio_duration)
                    
                self._bi_directional_radar(canon_words, self.all_curtains) # Подчищаем галлюцинации Арены

            # Финальная полировка
            self._local_snapping(canon_words, audio_duration)
            self._apply_vad_guillotine(canon_words, combined_vad)
            self._smoothing(canon_words)

            score = evaluate_alignment_quality(canon_words, strong_vad, weak_vad, self.all_curtains)
            log.info(f"📊 Итоговая оценка качества: {score:.1f}/100")

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

        dump_debug("6_3_PerfectHybrid", final_json, self._track_stem)
        log.info(f"Aligner ГОТОВО → {output_json_path}")
        log.info("=" * 50)
        
        return output_json_path