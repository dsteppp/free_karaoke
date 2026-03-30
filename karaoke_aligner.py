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

# ─── ИМПОРТЫ ИЗ НАШЕЙ НОВОЙ МОДУЛЬНОЙ СИСТЕМЫ (SYMPHONY V11) ─────────────────
from aligner_utils import (
    detect_language, prepare_text, get_vowel_weight, 
    get_phonetic_bounds, get_safe_bounds, evaluate_alignment_quality
)
from aligner_acoustics import (
    vocal_sniper, build_iron_curtain, enforce_curtains, 
    get_acoustic_maps, apply_vad_deafness
)
from aligner_orchestra import (
    macro_compass, heal_by_motif_matrix, ctc_inquisitor, 
    heal_phonetic_loom, semantic_harpoon
)

log = get_logger("aligner")

class KaraokeAligner:
    """
    Главный Дирижер "Symphony V11: Semantic Pivot".
    Использует Авангард, Семантический Аудит и Точечную Реставрацию (Гарпун).
    """

    def __init__(self, model_name="medium"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.whisper_model_dir = os.path.join(base_dir, "models", "whisper")
        os.makedirs(self.whisper_model_dir, exist_ok=True)
        
        self._track_stem = ""
        self.all_curtains = [] 

    # ─── ЭТАП 1: СМЫСЛОВОЙ АВАНГАРД И СКЕЛЕТ ────────────────────────────────────

    def _vanguard_protocol(self, model, audio_data: np.ndarray, words: list, lang: str):
        """
        V11: Авангард. Ищет первую строчку песни в первых 45 секундах аудио.
        Если перед ней есть болтовня - ставит на нее абсолютный Занавес.
        """
        if not words: return
        log.info("🛡️ [Vanguard] Поиск истинного начала песни (защита от ранней болтовни)...")
        sr = 16000
        crop_dur = min(45.0, len(audio_data) / sr)
        crop = audio_data[:int(crop_dur * sr)]
        
        try:
            res = model.transcribe(crop, language=lang)
            blind_words = res.all_words()
            if not blind_words: return
            
            first_line_clean = " ".join([w["clean_text"] for w in words[:4]])
            b_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in blind_words]
            
            best_score = 0
            best_t = 0.0
            
            # Скользящее окно по транскрибации
            for i in range(len(b_texts) - 3):
                chunk = " ".join([t for t in b_texts[i:i+4] if t])
                score = rapidfuzz.fuzz.partial_ratio(first_line_clean, chunk)
                if score > best_score:
                    best_score = score
                    best_t = blind_words[i].start
                    
            if best_score > 75 and best_t > 3.0:
                log.info(f"   🚩 Истинное начало найдено на {best_t:.2f}s. Установка абсолютного Занавеса на болтовню.")
                self.all_curtains.append((0.0, best_t - 0.2))
            else:
                log.info("   ✅ Ранняя болтовня не обнаружена (либо текст начинается сразу).")
                
        except Exception as e:
            log.warning(f"   ❌ Ошибка Авангарда: {e}")

    def _platinum_skeleton(self, model, audio_data: np.ndarray, canon_words: list, lang: str):
        log.info("[Actor] Фаза 1: Сборка жесткого скелета (Platinum)...")
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
                
                # Защита через Занавесы (включая занавес Авангарда)
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
                chars = sum(len(canon_words[best_c_idx + k]["clean_text"]) for k in range(3))
                if chars >= 12: is_platinum = True
            elif best_match_len == 2:
                chars = sum(len(canon_words[best_c_idx + k]["clean_text"]) for k in range(2))
                if chars >= 10: is_platinum = True

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

    # ─── ЭТАП 2: CRITIC & SURGEON ───────────────────────────────────────────────

    def _audit_json(self, words: list) -> list:
        bugs = []
        n = len(words)
        
        clusters = []
        curr_cluster = []
        for i in range(n):
            if words[i]["start"] != -1:
                curr_cluster.append(i)
            else:
                if curr_cluster: clusters.append(curr_cluster)
                curr_cluster = []
        if curr_cluster: clusters.append(curr_cluster)

        for cluster in clusters:
            if len(cluster) <= 3:
                first, last = cluster[0], cluster[-1]
                gap_left = words[first]["start"] - words[first-1]["end"] if first > 0 and words[first-1]["end"] != -1 else 15.0
                gap_right = words[last+1]["start"] - words[last]["end"] if last < n-1 and words[last+1]["start"] != -1 else 15.0
                
                if gap_left > 8.0 and gap_right > 8.0:
                    bugs.append({"type": "ISLAND_OF_LIES", "cluster": cluster})

        for i in range(n):
            w = words[i]
            if w["start"] == -1: continue
            dur = w["end"] - w["start"]
            
            if dur <= 0.05 or (i > 0 and words[i-1]["end"] != -1 and w["start"] < words[i-1]["start"]):
                bugs.append({"type": "BLACK_HOLE", "idx": i})
            
            vowel_w = get_vowel_weight(w["clean_text"], w["line_break"])
            if dur > (vowel_w * 0.8 + 0.5) and dur > 1.8:
                bugs.append({"type": "OVERSTRETCH", "idx": i})

        for i in range(n - 1):
            if words[i]["end"] != -1 and words[i+1]["start"] != -1:
                gap = words[i+1]["start"] - words[i]["end"]
                # V11: Увеличен допуск до 3-х секунд
                if gap > 3.0 and not words[i]["line_break"]:
                    has_curtain = any(c_s >= words[i]["end"] and c_e <= words[i+1]["start"] for c_s, c_e in self.all_curtains)
                    if not has_curtain:
                        log.warning(f"⚖️ [Master Auditor] Порванная строка (TORN_LINE) ({gap:.1f}s) между '{words[i]['clean_text']}' и '{words[i+1]['clean_text']}'.")
                        bugs.append({"type": "TORN_LINE", "idx": i+1})

        return bugs

    def _fix_bugs(self, words: list, bugs: list):
        for bug in bugs:
            if bug["type"] == "ISLAND_OF_LIES":
                log.warning(f"[Surgeon] Уничтожен ОСТРОВ ЛЖИ: слова {bug['cluster']}")
                for idx in bug["cluster"]:
                    words[idx]["start"], words[idx]["end"] = -1.0, -1.0
                    
            elif bug["type"] == "BLACK_HOLE":
                idx = bug["idx"]
                start_del, end_del = max(0, idx - 2), min(len(words) - 1, idx + 2)
                log.warning(f"[Surgeon] Взлом BLACK_HOLE (индексы {start_del}-{end_del}). Сброс якорей.")
                for k in range(start_del, end_del + 1):
                    words[k]["start"], words[k]["end"] = -1.0, -1.0

            elif bug["type"] == "OVERSTRETCH":
                idx = bug["idx"]
                w = words[idx]
                old_end = w["end"]
                vowel_w = get_vowel_weight(w["clean_text"], w["line_break"])
                w["end"] = w["start"] + vowel_w * 0.8 + 0.5
                log.warning(f"[Surgeon] Хвост OVERSTRETCH жестко обрублен: '{w['clean_text']}' ({old_end:.1f}s -> {w['end']:.1f}s)")
                
            elif bug["type"] == "TORN_LINE":
                idx = bug["idx"]
                log.warning(f"[Surgeon] Взлом TORN_LINE: сброс слов {idx-1} и {idx}")
                words[idx-1]["start"], words[idx-1]["end"] = -1.0, -1.0
                words[idx]["start"], words[idx]["end"] = -1.0, -1.0

    def _find_gaps(self, words: list) -> list:
        gaps, i, n = [], 0, len(words)
        while i < n:
            if words[i]["start"] == -1 and not words[i].get("dtw_tried", False):
                j = i
                while j < n and words[j]["start"] == -1: j += 1
                gaps.append((i, j - 1))
                i = j
            else: i += 1
        return gaps

    def _micro_dtw_surgery(self, words: list, gap: tuple, audio_data: np.ndarray, model, lang: str, aggressive: bool, vad_mask: list):
        s_idx, e_idx = gap
        audio_duration = len(audio_data) / 16000.0
        
        t_start, t_end = get_safe_bounds(words, s_idx, e_idx, audio_duration)

        v_weights = sum(get_vowel_weight(words[i]["clean_text"], words[i]["line_break"]) for i in range(s_idx, e_idx + 1))
        est_dur = v_weights * 0.4
        
        window_len = t_end - t_start
        if window_len > est_dur * 3.0:
            if s_idx == 0:
                t_start = max(t_start, t_end - est_dur * 2.0)
            elif e_idx == len(words) - 1:
                t_end = min(t_end, t_start + est_dur * 2.0)

        if t_end - t_start < 0.2:
            for k in range(s_idx, e_idx + 1): words[k]["dtw_tried"] = True
            return

        log.info(f"[Surgeon] Micro-DTW для слов [{s_idx}-{e_idx}] в окне {t_start:.1f}s - {t_end:.1f}s")
        
        sr = 16000
        crop_audio = audio_data[int(t_start * sr) : int(t_end * sr)]
        
        if len(crop_audio) < sr * 0.2:
            for k in range(s_idx, e_idx + 1): words[k]["dtw_tried"] = True
            return

        if aggressive and vad_mask:
            crop_audio = apply_vad_deafness(crop_audio, sr, t_start, vad_mask)

        crop_text = " ".join([words[i]["word"] for i in range(s_idx, e_idx + 1)])
        
        try:
            res = model.align(crop_audio, crop_text, language=lang)
            c_sw = res.all_words()
            
            s_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in c_sw]
            c_ptr = 0
            for k in range(s_idx, e_idx + 1):
                words[k]["dtw_tried"] = True 
                c_clean = words[k]["clean_text"]
                best_score, best_match = 0, -1
                
                for j in range(c_ptr, min(c_ptr + 6, len(s_texts))):
                    score = rapidfuzz.fuzz.ratio(c_clean, s_texts[j])
                    if score > 75 and score > best_score:
                        best_score, best_match = score, j
                        if score == 100: break
                
                if best_match != -1:
                    dur = c_sw[best_match].end - c_sw[best_match].start
                    if 0.05 < dur < 2.0:
                        mapped_s = t_start + c_sw[best_match].start
                        mapped_e = t_start + c_sw[best_match].end
                        
                        if not any(c_s <= mapped_s <= c_e for c_s, c_e in self.all_curtains):
                            words[k]["start"] = mapped_s
                            words[k]["end"] = mapped_e
                        
                        c_ptr = best_match + 1
        except Exception as e:
            log.warning(f"[Surgeon] Micro-DTW не справился ({e}).")
            for k in range(s_idx, e_idx + 1): words[k]["dtw_tried"] = True

    # ─── ЭТАП 3: ФИНАЛЬНЫЙ ТРИБУНАЛ ─────────────────────────────────────────────

    def _run_tribunal(self, words: list, is_harmonic_fn) -> list:
        quarantine_zones = []
        n = len(words)
        i = 0
        
        while i < n:
            if words[i]["start"] == -1:
                j = i
                while j < n and words[j]["start"] == -1: j += 1
                quarantine_zones.append((i, j - 1, "UNRESOLVED_GAP"))
                i = j
                continue
                
            dur = words[i]["end"] - words[i]["start"]
            min_dur, max_dur = get_phonetic_bounds(words[i]["clean_text"], words[i]["line_break"])
            
            if dur > max_dur and dur > 2.0:
                if not is_harmonic_fn(words[i]["start"] + max_dur, words[i]["end"]):
                    log.warning(f"[Tribunal] Резина найдена на '{words[i]['clean_text']}'. Обрезаем (Шум/Эхо).")
                    words[i]["end"] = words[i]["start"] + max_dur
            
            if words[i]["start"] != -1:
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

    # ─── ЭТАП 5: ФИЗИКА И ГРАВИТАЦИЯ ────────────────────────────────────────────

    def _apply_gravity(self, words: list, audio_duration: float, vad_mask: list):
        log.info("[Physics] Гравитационная заливка слепых зон...")
        n = len(words)
        
        def get_available_vad(t_min, t_max):
            res = []
            for (vs, ve) in vad_mask:
                i_s, i_e = max(t_min, vs), min(t_max, ve)
                if i_e > i_s: res.append((i_s, i_e))
            return res

        i = 0
        while i < n:
            if words[i]["start"] == -1:
                j = i
                while j < n and words[j]["start"] == -1: j += 1
                
                # V11: Smart Gravity. Отказываемся размазывать куплеты.
                if j - i > 4:
                    log.warning(f"   🛑 [Smart Gravity] Дыра слишком большая ({j-i} слов). Гравитация отменена.")
                    i = j
                    continue
                    
                t_start, t_end = get_safe_bounds(words, i, j - 1, audio_duration)

                active_vads = get_available_vad(t_start, t_end)
                weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
                total_w = sum(weights)
                
                total_vad_time = sum(e - s for s, e in active_vads)
                
                if total_vad_time < 0.5:
                    safe_start = t_start
                    if i == 0 and active_vads: safe_start = active_vads[-1][0] 
                    elif j == n and active_vads: safe_start = active_vads[0][0]
                    
                    curr_t = safe_start
                    for k in range(i, j):
                        w_dur = (weights[k-i] / total_w) * min(2.0, t_end - t_start)
                        words[k]["start"] = curr_t
                        words[k]["end"] = curr_t + w_dur * 0.9
                        words[k]["start"], words[k]["end"] = enforce_curtains(words[k]["start"], words[k]["end"], self.all_curtains)
                        curr_t += w_dur
                else:
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
                            
                        words[k]["start"] = mapped_s
                        words[k]["end"] = mapped_e
                        words[k]["start"], words[k]["end"] = enforce_curtains(words[k]["start"], words[k]["end"], self.all_curtains)
                        curr_t += w_logic_dur
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
                        log.info(f"   🪓 Сдвиг '{w['clean_text']}': {w['start']:.2f}s -> {new_start:.2f}s")
                        w["start"] = new_start

    def _smoothing(self, words: list):
        last_e = 0.0
        for w in words:
            if w["start"] < last_e:
                w["start"] = last_e + 0.01
            if w["end"] <= w["start"]:
                w["end"] = w["start"] + 0.1
                
            w["start"], w["end"] = enforce_curtains(w["start"], w["end"], self.all_curtains)
            last_e = w["end"]

    # ─── MAIN ORCHESTRATOR ──────────────────────────────────────────────────────

    def process_audio(self, vocals_path: str, raw_lyrics: str, output_json_path: str):
        self._track_stem = os.path.basename(output_json_path).replace("_(Karaoke Lyrics).json", "")

        log.info("=" * 50)
        log.info(f"Aligner СТАРТ (Symphony V11 Semantic Pivot): {self._track_stem}")
        
        canon_words_original = prepare_text(raw_lyrics)
        if not canon_words_original:
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = detect_language(raw_lyrics)
        model = None
        canon_words = []
        
        try:
            # Сохраняем сырое аудио для Семантического Аудитора и Гарпуна
            audio_data_raw, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data_raw) / sr
            
            gated_audio_data = vocal_sniper(audio_data_raw, sr)
            iron_curtains = build_iron_curtain(gated_audio_data, sr)
            vad_mask, onsets, is_harmonic_fn = get_acoustic_maps(gated_audio_data, sr)
            
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            
            self.all_curtains = sorted(iron_curtains, key=lambda x: x[0])
            
            # V11: Авангард устанавливает Занавес на раннюю болтовню
            self._vanguard_protocol(model, audio_data_raw, canon_words_original, lang)
            self.all_curtains = sorted(self.all_curtains, key=lambda x: x[0])

            # V11: Функция для Семантического Аудитора
            def spot_check_fn(t_start, t_end, target_phrase):
                log.info(f"   🔍 [Semantic Spot-Check] Проверка фрагмента {t_start:.1f}s - {t_end:.1f}s...")
                crop = audio_data_raw[int(max(0, t_start)*sr) : int(min(audio_duration, t_end)*sr)]
                if len(crop) < sr * 0.5: return True 
                try:
                    res = model.transcribe(crop, language=lang)
                    blind_text = re.sub(r'[^\w\s]', '', res.text.lower())
                    score = rapidfuzz.fuzz.partial_ratio(target_phrase, blind_text)
                    if score < 50:
                        log.warning(f"      ❌ Провал проверки! Искали '{target_phrase}', услышали '{blind_text}'")
                        return False
                    log.info("      ✅ Проверка пройдена.")
                    return True
                except:
                    return True # При сбое движка не штрафуем

            best_words = []
            best_score = -1.0

            for pass_idx in range(2):
                aggressive_mode = (pass_idx == 1)
                canon_words = copy.deepcopy(canon_words_original)
                
                if aggressive_mode:
                    log.warning("⏱️ МАШИНА ВРЕМЕНИ: Суровая оценка забраковала результат. Запуск Aggressive Mode (Pass 2)!")
                    log.warning("Включено: Хирургическая глухота (VAD Masking), Приоритет Ткацкого Станка.")

                self._platinum_skeleton(model, gated_audio_data, canon_words, lang)

                for iteration in range(3):
                    bugs = self._audit_json(canon_words)
                    gaps = self._find_gaps(canon_words)
                    
                    if not bugs and not gaps:
                        log.info(f"[Critic] Итерация {iteration+1}: Аудит пройден.")
                        break
                        
                    if bugs:
                        self._fix_bugs(canon_words, bugs)
                    
                    if gaps:
                        for gap in gaps:
                            self._micro_dtw_surgery(canon_words, gap, gated_audio_data, model, lang, aggressive_mode, vad_mask)
                
                for iteration in range(2):
                    anomalies = self._run_tribunal(canon_words, is_harmonic_fn)
                    if not anomalies:
                        break
                        
                    for s_idx, e_idx, reason in anomalies:
                        log.info(f"   -> Карантин [{s_idx}-{e_idx}]: {reason}. Сброс таймингов.")
                        for k in range(s_idx, e_idx + 1):
                            canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                        
                        t_start, t_end = get_safe_bounds(canon_words, s_idx, e_idx, audio_duration)
                        
                        if reason in ["PHYSICAL_IMPOSSIBILITY", "UNRESOLVED_GAP"] and (e_idx - s_idx) >= 2:
                            if macro_compass(canon_words, s_idx, e_idx, gated_audio_data, t_start, t_end, model, lang):
                                continue 
                        
                        if heal_by_motif_matrix(canon_words, s_idx, e_idx, audio_duration): continue
                        if ctc_inquisitor(canon_words, s_idx, e_idx, gated_audio_data, model, lang, t_start, t_end): continue
                        
                        if aggressive_mode:
                            heal_phonetic_loom(canon_words, s_idx, e_idx, t_start, t_end, vad_mask)
                
                self._apply_gravity(canon_words, audio_duration, vad_mask)
                self._apply_vad_guillotine(canon_words, vad_mask)
                self._smoothing(canon_words)

                # V11: Оценка с учетом Семантического Аудитора
                score = evaluate_alignment_quality(canon_words, vad_mask, self.all_curtains, spot_check_fn=spot_check_fn)
                log.info(f"📊 Оценка качества после Pass {pass_idx + 1}: {score:.1f}/100")
                
                if score > best_score:
                    best_score = score
                    best_words = copy.deepcopy(canon_words)
                    
                if score >= 85.0:
                    break
            
            # Принимаем лучший из 2-х проходов
            canon_words = best_words
            score = best_score

            # ─── V11: ТОЧЕЧНАЯ РЕСТАВРАЦИЯ (СЕМАНТИЧЕСКИЙ ГАРПУН) ────────────
            if score < 85.0:
                log.warning(f"🚨 [Targeted Fallback] Оценка {score:.1f}/100. Запуск Семантического Гарпуна на сыром звуке!")
                
                # Принудительно рвем плохие связи
                bugs = self._audit_json(canon_words)
                self._fix_bugs(canon_words, bugs)
                anomalies = self._run_tribunal(canon_words, is_harmonic_fn)
                for s_idx, e_idx, _ in anomalies:
                    for k in range(s_idx, e_idx + 1):
                        canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                
                gaps = self._find_gaps(canon_words)
                harpoon_used = False
                
                for (s_idx, e_idx) in gaps:
                    t_start, t_end = get_safe_bounds(canon_words, s_idx, e_idx, audio_duration)
                    t_start = max(0.0, t_start - 0.5)
                    t_end = min(audio_duration, t_end + 0.5)
                    
                    # Гарпун работает с RAW AUDIO
                    if semantic_harpoon(canon_words, s_idx, e_idx, audio_data_raw, t_start, t_end, model, lang):
                        harpoon_used = True
                
                if harpoon_used:
                    # Финальная склейка мелких щелей после Гарпуна
                    self._apply_gravity(canon_words, audio_duration, vad_mask)
                    self._apply_vad_guillotine(canon_words, vad_mask)
                    self._smoothing(canon_words)
                    score = evaluate_alignment_quality(canon_words, vad_mask, self.all_curtains) 
                    log.info(f"📊 Оценка качества после Реставрации: {score:.1f}/100")

        except Exception as e:
            log.error(f"Ошибка Aligner: {e}")
            raise e
        finally:
            if model: del model
            if 'audio_data_raw' in locals(): del audio_data_raw
            if 'gated_audio_data' in locals(): del gated_audio_data
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

        dump_debug("11_Final_Symphony", final_json, self._track_stem)
        log.info(f"Aligner ГОТОВО → {output_json_path}")
        log.info("=" * 50)
        
        return output_json_path