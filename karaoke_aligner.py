import os
import gc
import re
import json
import copy
import random
import torch
import librosa
import rapidfuzz
import stable_whisper
import numpy as np

from app_logger import get_logger, dump_debug

# ─── ИМПОРТЫ ИЗ НАШЕЙ НОВОЙ МОДУЛЬНОЙ СИСТЕМЫ (SYMPHONY V13.2) ───────────────
from aligner_utils import (
    detect_language, prepare_text, get_vowel_weight, 
    get_phonetic_bounds, get_safe_bounds, evaluate_alignment_quality,
    is_repetition_island
)
from aligner_acoustics import (
    vocal_sniper, build_iron_curtain, enforce_curtains, 
    get_acoustic_maps
)
from aligner_orchestra import (
    Proposal, propose_motif_matrix, propose_inquisitor, 
    propose_harpoon, propose_loom, the_supreme_judge, diagnostic_compass
)

log = get_logger("aligner")

class KaraokeAligner:
    """
    Главный Дирижер "Symphony V13.2: Semantic Control".
    Без слепого Авангарда. С внутристрочной Гравитацией и Wall Jump.
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""
        self.all_curtains = [] 

    # ─── ЭТАП 1: ПОДГОТОВКА И СКЕЛЕТ ──────────────────────────────────────────

    def _find_instrumental_voids(self, strong_vad: list, weak_vad: list):
        """Ищет длинные инструментальные проигрыши (>4 сек без голоса)."""
        log.info("🕳️ [Void Detector] Поиск длинных инструментальных проигрышей...")
        combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])
        if not combined_vad: return

        merged = []
        for s, e in combined_vad:
            if not merged: merged.append((s, e))
            else:
                last_s, last_e = merged[-1]
                if s - last_e < 1.0: merged[-1] = (last_s, max(last_e, e))
                else: merged.append((s, e))
        
        last_e = 0.0
        for s, e in merged:
            if s - last_e > 4.0: 
                log.info(f"   🕳️ Найден Instrumental Void: {last_e:.2f}s - {s:.2f}s. Установлен занавес.")
                self.all_curtains.append((last_e, s))
            last_e = e

    def _filter_vad_from_curtains(self, vad_list: list) -> list:
        """V4.1: Физически вырезает занавесы из VAD для создания механики Wall Jump."""
        res = []
        for vs, ve in vad_list:
            curr_s = vs
            for cs, ce in self.all_curtains:
                if ce <= curr_s: continue
                if cs >= ve: break
                if curr_s < cs: res.append((curr_s, cs))
                curr_s = max(curr_s, ce)
            if curr_s < ve: res.append((curr_s, ve))
        return res

    def _platinum_skeleton(self, model, audio_data: np.ndarray, canon_words: list, lang: str):
        log.info("[Actor] Фаза 1: Сборка жесткого скелета (Platinum DTW)...")
        text_for_whisper = " ".join([w["word"] for w in canon_words])
        
        try:
            result = model.align(audio_data, text_for_whisper, language=lang)
            sw_words = result.all_words()
            bad_count = sum(1 for w in sw_words if (w.end - w.start) < 0.05)
            if bad_count / len(sw_words) > 0.15: raise ValueError("DTW Failed")
        except Exception:
            log.warning("[Actor] DTW забракован. Переход на слепую транскрибацию...")
            result = model.transcribe(audio_data, language=lang)
            sw_words = result.all_words()

        valid_sw = []
        last_t = 0.0
        for w in sw_words:
            if (w.end - w.start) < 0.05: continue
            cl = re.sub(r'[^\w]', '', w.word.lower())
            if cl:
                start_t = max(last_t, w.start)
                end_t = max(start_t + 0.05, w.end)
                if any(c_s <= start_t <= c_e for c_s, c_e in self.all_curtains):
                    continue
                valid_sw.append({"clean": cl, "start": start_t, "end": end_t})
                last_t = end_t
                
        canon_idx, sw_idx, anchors_count = 0, 0, 0
        search_window = 60
        
        while canon_idx < len(canon_words) and sw_idx < len(valid_sw):
            best_match_len, best_c_idx = 0, -1
            for c in range(canon_idx, min(canon_idx + search_window, len(canon_words))):
                match_len = 0
                while (c + match_len < len(canon_words) and 
                       sw_idx + match_len < len(valid_sw) and 
                       canon_words[c + match_len]["clean_text"] == valid_sw[sw_idx + match_len]["clean"]):
                    match_len += 1
                if match_len > best_match_len:
                    best_match_len, best_c_idx = match_len, c
                    
            is_platinum = False
            if best_match_len >= 4: is_platinum = True
            elif best_match_len == 3:
                if sum(len(canon_words[best_c_idx + k]["clean_text"]) for k in range(3)) >= 12: is_platinum = True
            elif best_match_len == 2:
                if sum(len(canon_words[best_c_idx + k]["clean_text"]) for k in range(2)) >= 10: is_platinum = True

            if is_platinum:
                for k in range(best_match_len):
                    canon_words[best_c_idx + k]["start"] = valid_sw[sw_idx + k]["start"]
                    canon_words[best_c_idx + k]["end"] = valid_sw[sw_idx + k]["end"]
                canon_idx = best_c_idx + best_match_len
                sw_idx += best_match_len
                anchors_count += best_match_len
            else:
                sw_idx += 1

        log.info(f"[Actor] Платиновый скелет установлен: {anchors_count}/{len(canon_words)} слов.")

    # ─── ЭТАП 2: АУДИТОР И ТРИБУНАЛ ─────────────────────────────────────────────

    def _audit_json(self, words: list, audio_duration: float) -> list:
        bugs = []
        n = len(words)
        
        # 1. Сборка карты строк для Intra-line Cohesion
        lines = []
        cur_line = []
        for i, w in enumerate(words):
            cur_line.append(i)
            if w["line_break"]:
                lines.append(cur_line)
                cur_line = []
        if cur_line: lines.append(cur_line)

        line_map = {}
        for l_idx, line_indices in enumerate(lines):
            for i in line_indices:
                line_map[i] = line_indices

        # 2. Группировка подтвержденных слов в кластеры
        clusters = []
        curr_cluster = []
        for i in range(n):
            if words[i]["start"] != -1: curr_cluster.append(i)
            else:
                if curr_cluster: clusters.append(curr_cluster)
                curr_cluster = []
        if curr_cluster: clusters.append(curr_cluster)

        # 3. Island of Lies (Защита интро/аутро от болтовни)
        for cluster in clusters:
            if len(cluster) <= 4:
                first, last = cluster[0], cluster[-1]
                gap_left = words[first]["start"] - words[first-1]["end"] if first > 0 and words[first-1]["end"] != -1 else words[first]["start"]
                gap_right = words[last+1]["start"] - words[last]["end"] if last < n-1 and words[last+1]["start"] != -1 else audio_duration - words[last]["end"]
                
                is_left_isolated = (gap_left > 6.0) or (first == 0)
                is_right_isolated = (gap_right > 6.0) or (last == n - 1)
                
                if is_left_isolated and is_right_isolated and (gap_left > 6.0 or gap_right > 6.0):
                    bugs.append({"type": "ISLAND_OF_LIES", "cluster": cluster})

        for i in range(n):
            w = words[i]
            if w["start"] == -1: continue
            dur = w["end"] - w["start"]
            
            # BLACK_HOLE (Схлопывание)
            if dur <= 0.05 or (i > 0 and words[i-1]["end"] != -1 and w["start"] < words[i-1]["start"]):
                bugs.append({"type": "BLACK_HOLE", "idx": i})
            
            # OVERSTRETCH (Растягивание)
            vowel_w = get_vowel_weight(w["clean_text"], w["line_break"])
            if dur > (vowel_w * 0.8 + 0.5) and dur > 1.8:
                if i == 0 or (i > 0 and words[i-1]["start"] == -1):
                    bugs.append({"type": "BLACK_HOLE", "idx": i}) # Если это старт песни, сносим полностью
                else:
                    bugs.append({"type": "OVERSTRETCH", "idx": i})

        # 4. Внутристрочная Гравитация (TORN_LINE)
        for i in range(n - 1):
            if words[i]["end"] != -1 and words[i+1]["start"] != -1:
                gap = words[i+1]["start"] - words[i]["end"]
                # Разрыв внутри одной строки недопустим (>2.5s)
                if gap > 2.5 and not words[i]["line_break"]:
                    log.warning(f"⚖️ [Master Auditor] Порванная строка (TORN_LINE) ({gap:.1f}s) между '{words[i]['clean_text']}' и '{words[i+1]['clean_text']}'.")
                    bugs.append({"type": "TORN_LINE", "line": line_map[i]})

        return bugs

    def _fix_bugs(self, words: list, bugs: list):
        for bug in bugs:
            if bug["type"] == "ISLAND_OF_LIES":
                log.warning(f"[Surgeon] Уничтожен ОСТРОВ ЛЖИ: слова {bug['cluster']}")
                for idx in bug["cluster"]:
                    words[idx]["start"] = words[idx]["end"] = -1.0
            elif bug["type"] == "BLACK_HOLE":
                idx = bug["idx"]
                start_del, end_del = max(0, idx - 1), min(len(words) - 1, idx + 1)
                log.warning(f"[Surgeon] Взлом BLACK_HOLE (индексы {start_del}-{end_del}). Сброс якорей.")
                for k in range(start_del, end_del + 1):
                    words[k]["start"] = words[k]["end"] = -1.0
            elif bug["type"] == "OVERSTRETCH":
                idx = bug["idx"]
                w = words[idx]
                if w["start"] != -1.0:
                    vowel_w = get_vowel_weight(w["clean_text"], w["line_break"])
                    w["end"] = w["start"] + vowel_w * 0.8 + 0.5
                    log.warning(f"[Surgeon] Хвост OVERSTRETCH обрублен: '{w['clean_text']}'")
            elif bug["type"] == "TORN_LINE":
                line_indices = bug["line"]
                log.warning(f"[Surgeon] Взлом TORN_LINE: сброс целой строки {line_indices[0]}-{line_indices[-1]}")
                for idx in line_indices:
                    words[idx]["start"] = words[idx]["end"] = -1.0

    def _run_tribunal(self, words: list, is_harmonic_fn) -> list:
        quarantine_zones = []
        n, i = len(words), 0
        while i < n:
            if words[i]["start"] == -1:
                i += 1; continue
                
            dur = words[i]["end"] - words[i]["start"]
            min_dur, max_dur = get_phonetic_bounds(words[i]["clean_text"], words[i]["line_break"])
            
            if dur > max_dur and dur > 2.0:
                if not is_harmonic_fn(words[i]["start"] + max_dur, words[i]["end"]):
                    log.warning(f"[Tribunal] Резина найдена на '{words[i]['clean_text']}'. Обрезаем (Шум/Эхо).")
                    words[i]["end"] = words[i]["start"] + max_dur
            
            j = i
            cluster_min_dur = 0.0
            while j < n and words[j]["start"] != -1 and (words[j]["end"] - words[i]["start"] < 1.5):
                mn, _ = get_phonetic_bounds(words[j]["clean_text"], words[j]["line_break"])
                cluster_min_dur += mn
                j += 1
            
            real_dur = words[j-1]["end"] - words[i]["start"] if j > i else 0
            if (j - i) >= 3 and real_dur < (cluster_min_dur * 0.7):
                quarantine_zones.append((i, j - 1, "PHYSICAL_IMPOSSIBILITY"))
                i = j
                continue
            i += 1
            
        return quarantine_zones

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

    # ─── ЭТАП 3: АРЕНА (THE COLOSSEUM) ──────────────────────────────────────────

    def _the_arena_surgery(self, words: list, gap: tuple, audio_data: np.ndarray, model, lang: str, strong_vad: list, weak_vad: list, audio_duration: float):
        s_idx, e_idx = gap
        t_start, t_end = get_safe_bounds(words, s_idx, e_idx, audio_duration)
        if t_end - t_start < 0.1: return

        log.info(f"🏟️ [The Arena] Слова [{s_idx}-{e_idx}] выходят на Арену! Окно: {t_start:.1f}s - {t_end:.1f}s")
        proposals = []
        
        # 1. Motif Matrix
        if is_repetition_island(words, s_idx, e_idx):
            prop_motif = propose_motif_matrix(words, s_idx, e_idx, audio_duration, strong_vad)
            if prop_motif: proposals.append(prop_motif)
            
        # 2. CTC Inquisitor
        prop_inq = propose_inquisitor(words, s_idx, e_idx, audio_data, model, lang, t_start, t_end)
        if prop_inq: proposals.append(prop_inq)
            
        # 3. Semantic Harpoon (Выступает в роли Авангарда для Интро!)
        prop_harp = propose_harpoon(words, s_idx, e_idx, audio_data, model, lang, t_start, t_end)
        if prop_harp: proposals.append(prop_harp)
            
        # 4. Phonetic Loom (Математическая Гравитация с Wall Jump)
        prop_loom = propose_loom(words, s_idx, e_idx, t_start, t_end, strong_vad, weak_vad)
        if prop_loom: proposals.append(prop_loom)
            
        winner = the_supreme_judge(proposals, words, s_idx, e_idx, strong_vad, weak_vad)
        
        if winner:
            for k, t in enumerate(winner.timings):
                # Wall Jump: enforce_curtains сдвинет слово ЗА занавес, если оно попало внутрь
                mapped_s, mapped_e = enforce_curtains(t["start"], t["end"], self.all_curtains)
                words[s_idx + k]["start"] = mapped_s
                words[s_idx + k]["end"] = mapped_e
        else:
            log.warning(f"   ⚠️ Арена не выявила победителя для [{s_idx}-{e_idx}].")

    # ─── ЭТАП 4: ФИНАЛЬНЫЕ ШТРИХИ ──────────────────────────────────────────────

    def _apply_absolute_gravity(self, words: list, audio_duration: float, vad_mask: list):
        """V4.2: Fail-Safe с Правосторонеей гравитацией (Right-Anchor Gravity)."""
        log.info("🪐 [Absolute Gravity] Принудительное спасение всех оставшихся слов...")
        n = len(words)
        
        def get_available_vad(t_min, t_max):
            res = []
            for (vs, ve) in vad_mask:
                i_s, i_e = max(t_min, vs), min(t_max, ve)
                if i_e > i_s: res.append((i_s, i_e))
            return res

        i = 0
        healed = 0
        while i < n:
            if words[i]["start"] == -1.0:
                j = i
                while j < n and words[j]["start"] == -1.0: j += 1
                
                t_start, t_end = get_safe_bounds(words, i, j - 1, audio_duration)
                active_vads = get_available_vad(t_start, t_end)
                    
                weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
                total_w = sum(weights)
                req_time = total_w * 0.4
                
                if not active_vads: active_vads = [(t_start, t_end)]
                total_vad_time = sum(e - s for s, e in active_vads)
                
                # Right-Anchor Gravity: Если слева огромная дыра - прижимаем слова вправо к якорю
                if t_end - t_start > req_time * 2.5 and total_vad_time > req_time * 1.5:
                    trimmed_vads = []
                    accum = 0.0
                    for vs, ve in reversed(active_vads):
                        dur = ve - vs
                        if accum + dur <= req_time * 1.5:
                            trimmed_vads.insert(0, (vs, ve))
                            accum += dur
                        else:
                            trimmed_vads.insert(0, (ve - (req_time * 1.5 - accum), ve))
                            break
                    active_vads = trimmed_vads
                    total_vad_time = sum(e - s for s, e in active_vads)
                
                curr_t = 0.0
                for k in range(i, j):
                    w_logic_dur = (weights[k-i] / total_w) * total_vad_time
                    accum, mapped_s, mapped_e = 0.0, active_vads[0][0], active_vads[-1][1]
                    for (vs, ve) in active_vads:
                        dur = ve - vs
                        if curr_t <= accum + dur:
                            mapped_s = vs + (curr_t - accum)
                            break
                        accum += dur
                    accum = 0.0
                    for (vs, ve) in active_vads:
                        dur = ve - vs
                        if curr_t + w_logic_dur * 0.95 <= accum + dur:
                            mapped_e = vs + (curr_t + w_logic_dur * 0.95 - accum)
                            break
                        accum += dur
                        
                    words[k]["start"], words[k]["end"] = enforce_curtains(mapped_s, mapped_e, self.all_curtains)
                    curr_t += w_logic_dur
                    healed += 1
                i = j
            else:
                i += 1
                
        if healed > 0: log.info(f"   ✨ Абсолютная Гравитация спасла {healed} слов!")

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
                        log.info(f"   🪓 Сдвиг '{w['clean_text']}': {w['start']:.2f}s -> {new_start:.2f}s")
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
        log.info(f"Aligner СТАРТ (Symphony V13.2: Semantic Control): {self._track_stem}")
        
        canon_words_original = prepare_text(raw_lyrics)
        if not canon_words_original:
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = detect_language(raw_lyrics)
        model = None
        canon_words = []
        
        try:
            audio_data_raw, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data_raw) / sr
            
            iron_curtains = build_iron_curtain(audio_data_raw, sr)
            strong_vad, weak_vad, onsets, is_harmonic_fn = get_acoustic_maps(audio_data_raw, sr)
            self.all_curtains = sorted(iron_curtains, key=lambda x: x[0])
            
            # 1. Поиск Великих Пустот (Занавесов)
            self._find_instrumental_voids(strong_vad, weak_vad)
            self.all_curtains = sorted(self.all_curtains, key=lambda x: x[0])
            
            # 2. Wall Jump: Вырезаем занавесы из VAD
            strong_vad = self._filter_vad_from_curtains(strong_vad)
            weak_vad = self._filter_vad_from_curtains(weak_vad)
            combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])

            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            def spot_check_fn(t_start, t_end, target_phrase):
                log.info(f"   🔍 [Semantic Spot-Check] Проверка эталоном {t_start:.1f}s - {t_end:.1f}s...")
                crop = audio_data_raw[int(max(0, t_start)*sr) : int(min(audio_duration, t_end)*sr)]
                if len(crop) < sr * 0.5: return True 
                try:
                    res = model.align(crop, target_phrase, language=lang, fast_mode=True)
                    valid_words = [w for w in res.all_words() if w.end - w.start >= 0.05]
                    if len(valid_words) < len(target_phrase.split()) * 0.4: return False
                    return True
                except: return True

            best_words = []
            best_score = -1.0

            for pass_idx in range(2):
                canon_words = copy.deepcopy(canon_words_original)
                if pass_idx == 1: log.warning("⏱️ МАШИНА ВРЕМЕНИ: Суровая оценка. Запуск Aggressive Mode (Pass 2)!")

                # V4.2: Базовый скелет сразу по всему треку (без Авангарда)
                self._platinum_skeleton(model, audio_data_raw, canon_words, lang)

                for iteration in range(3):
                    bugs = self._audit_json(canon_words, audio_duration)
                    self._fix_bugs(canon_words, bugs)
                    
                    anomalies = self._run_tribunal(canon_words, is_harmonic_fn)
                    for s_idx, e_idx, reason in anomalies:
                        log.info(f"   -> Карантин [{s_idx}-{e_idx}]: {reason}. Сброс таймингов.")
                        for k in range(s_idx, e_idx + 1): canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                            
                    gaps = self._find_gaps(canon_words)
                    
                    # 4. Island Expansion (Умный лимит через подсчет строк: не более 8 строк)
                    if gaps:
                        merged_gaps = []
                        for gap in gaps:
                            if not merged_gaps:
                                merged_gaps.append(gap)
                            else:
                                last_s, last_e = merged_gaps[-1]
                                curr_s, curr_e = gap
                                
                                # Считаем количество строк внутри потенциального Острова
                                lines_count = sum(1 for k in range(last_s, curr_e + 1) if canon_words[k]["line_break"])
                                if not canon_words[curr_e]["line_break"]:
                                    lines_count += 1

                                if curr_s - last_e <= 4 and lines_count <= 8:
                                    if is_repetition_island(canon_words, last_s, curr_e):
                                        for k in range(last_e + 1, curr_s):
                                            canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                                        merged_gaps[-1] = (last_s, curr_e)
                                        log.info(f"   🏝️ [Island Expansion] Дыры слиты в Остров Повторов: [{last_s}-{curr_e}] (строк: {lines_count})")
                                        continue
                                merged_gaps.append(gap)
                        gaps = merged_gaps
                    
                    if not bugs and not anomalies and not gaps:
                        log.info(f"[Critic] Итерация {iteration+1}: Аудит пройден. Аномалий нет.")
                        break
                        
                    for gap in gaps:
                        s_idx, e_idx = gap
                        t_start, t_end = get_safe_bounds(canon_words, s_idx, e_idx, audio_duration)
                        
                        if (e_idx - s_idx) >= 2:
                            shift_idx = diagnostic_compass(canon_words, s_idx, e_idx, audio_data_raw, t_start, t_end, model, lang)
                            if shift_idx != -1:
                                log.warning(f"   🔄 [Diagnostic Compass] Найден глобальный сдвиг. Расширяем карантин до {shift_idx} слова.")
                                for k in range(e_idx + 1, shift_idx + 1):
                                    canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                                gap = (s_idx, shift_idx)
                        
                        self._the_arena_surgery(canon_words, gap, audio_data_raw, model, lang, strong_vad, weak_vad, audio_duration)
                
                self._apply_vad_guillotine(canon_words, combined_vad)
                self._smoothing(canon_words)

                score = evaluate_alignment_quality(canon_words, strong_vad, weak_vad, self.all_curtains, spot_check_fn=spot_check_fn)
                log.info(f"📊 Оценка качества после Pass {pass_idx + 1}: {score:.1f}/100")
                
                if score > best_score:
                    best_score = score
                    best_words = copy.deepcopy(canon_words)
                if score >= 85.0: break
            
            canon_words = best_words
            score = best_score

            if any(w["start"] == -1.0 for w in canon_words):
                self._apply_absolute_gravity(canon_words, audio_duration, combined_vad)
                self._apply_vad_guillotine(canon_words, combined_vad)
                self._smoothing(canon_words)

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

        dump_debug("13_2_Colosseum", final_json, self._track_stem)
        log.info(f"Aligner ГОТОВО → {output_json_path}")
        log.info("=" * 50)
        
        return output_json_path