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

# ─── ИМПОРТЫ ИЗ НАШЕЙ НОВОЙ МОДУЛЬНОЙ СИСТЕМЫ (SYMPHONY V6.3 HYBRID) ─────────
from aligner_utils import (
    detect_language, prepare_text, get_vowel_weight, get_empirical_data,
    get_phonetic_bounds, get_safe_bounds, evaluate_alignment_quality,
    is_repetition_island, calculate_overlap
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

    # ─── ЭТАП 1: АВАНГАРД И ПЛАТИНОВЫЙ СКЕЛЕТ ─────────────────────────────────

    def _vanguard_protocol(self, model, audio_data: np.ndarray, words: list, lang: str):
        """Ленивый Авангард. Ищет старт трека, чтобы отсечь инструментал в интро."""
        if not words: return
        log.info("🛡️ [Vanguard] Поиск истинного начала песни (Лентяй-сканер)...")
        sr = 16000
        audio_dur = len(audio_data) / sr
        
        first_lines = []
        lines_found = 0
        for w in words:
            first_lines.append(w["clean_text"])
            if w["line_break"]: lines_found += 1
            if lines_found >= 2 or len(first_lines) >= 12: break
            
        target_text = " ".join(first_lines)
        search_len = len(first_lines)
        if search_len < 2: return
        
        window_size = 30.0
        step_size = 15.0
        search_start = 0.0
        
        while search_start < min(audio_dur, 90.0): # Ищем старт только в первых 90 сек
            crop_end = min(search_start + window_size, audio_dur)
            crop = audio_data[int(search_start * sr) : int(crop_end * sr)]
            try:
                res = model.transcribe(crop, language=lang)
                blind_words = res.all_words()
                
                if blind_words:
                    b_texts = [re.sub(r'[^\w]', '', w.word.lower()) for w in blind_words]
                    for i in range(len(b_texts) - search_len + 1):
                        chunk = " ".join([t for t in b_texts[i:i+search_len] if t])
                        score = rapidfuzz.fuzz.partial_ratio(target_text, chunk)
                        
                        if score > 70:
                            best_t = search_start + blind_words[i].start
                            if best_t > 3.0:
                                log.info(f"   🚩 Истинное начало найдено на {best_t:.2f}s. Установка Занавеса.")
                                self.all_curtains.append((0.0, best_t - 0.2))
                            else:
                                log.info("   ✅ Текст начинается сразу, занавес не требуется.")
                            return 
            except Exception as e:
                log.warning(f"   ❌ Ошибка Авангарда на отрезке {search_start}s: {e}")
            search_start += step_size
            
        log.info("   ⚠️ Авангард просканировал интро, но не нашел уверенного старта.")

    def _platinum_skeleton(self, model, audio_data: np.ndarray, words: list, lang: str):
        """Жесткая сборка базового черновика."""
        log.info("📝 [Draft] Сборка жесткого скелета (Platinum)...")
        text_for_whisper = " ".join([w["word"] for w in words])
        
        try:
            result = model.align(audio_data, text_for_whisper, language=lang)
            sw_words = result.all_words()
            bad_count = sum(1 for w in sw_words if (w.end - w.start) < 0.05)
            if bad_count / len(sw_words) > 0.15: raise ValueError("DTW Failed")
        except Exception:
            log.warning("   ⚠️ DTW забракован. Переход на слепую транскрибацию...")
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
                    
            is_platinum = False
            if best_match_len >= 4: is_platinum = True
            elif best_match_len == 3:
                if sum(len(words[best_c_idx + k]["clean_text"]) for k in range(3)) >= 12: is_platinum = True
            elif best_match_len == 2:
                if sum(len(words[best_c_idx + k]["clean_text"]) for k in range(2)) >= 10: is_platinum = True

            if is_platinum:
                for k in range(best_match_len):
                    words[best_c_idx + k]["start"] = valid_sw[sw_idx + k]["start"]
                    words[best_c_idx + k]["end"] = valid_sw[sw_idx + k]["end"]
                canon_idx = best_c_idx + best_match_len
                sw_idx += best_match_len
                anchors_count += best_match_len
            else:
                sw_idx += 1

        log.info(f"   📋 Платиновый скелет собран: {anchors_count}/{len(words)} слов.")

    # ─── ЭТАП 2: ОРАКУЛ, СВЕРКА И РАДАР ───────────────────────────────────────

    def _blind_oracle(self, model, audio_data: np.ndarray, lang: str) -> list:
        log.info("👁️ [Oracle] Слепой Оракул слушает трек...")
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

    def _crosscheck_oracle(self, words: list, blind_words: list):
        """Сносит слова только при явном расхождении (защита от чрезмерной агрессии)."""
        log.info("⚖️ [Crosscheck] Сверка Черновика со Слепым Оракулом...")
        rejected = 0
        for w in words:
            if w["start"] == -1.0: continue
            
            min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
            dur = w["end"] - w["start"]
            
            local_blinds = [bw for bw in blind_words if not (bw["end"] < w["start"] - 0.5 or bw["start"] > w["end"] + 0.5)]
            
            # 1. Слово растянуто, и оракул не слышит его
            if dur > max_dur * 2.0:
                match = any(rapidfuzz.fuzz.ratio(w["clean_text"], bw["clean"]) > 60 for bw in local_blinds)
                if not match:
                    w["start"], w["end"] = -1.0, -1.0
                    rejected += 1
                    continue
                    
            # 2. Оракул слышит тут совершенно другой текст (галлюцинация DTW)
            if local_blinds:
                best_match = max((rapidfuzz.fuzz.ratio(w["clean_text"], bw["clean"]) for bw in local_blinds), default=0)
                if best_match < 30 and len(local_blinds) >= 2:
                    w["start"], w["end"] = -1.0, -1.0
                    rejected += 1
                    
        total = len([w for w in words if w["start"] != -1.0]) + rejected
        log.info(f"   📉 Оракул забраковал {rejected} сомнительных слов.")


    def _bi_directional_radar(self, words: list):
        log.info("📡 [Radar] Двунаправленное сканирование аномалий...")
        
        # L->R: Нарушители Занавесов
        for w in words:
            if w["start"] != -1.0:
                if w["end"] - w["start"] < 0.05:
                    w["start"], w["end"] = -1.0, -1.0
                elif calculate_overlap(w["start"], w["end"], self.all_curtains) > 0.05:
                    w["start"], w["end"] = -1.0, -1.0

        # R->L: Убийца Фейковых Интро (Откалиброванный)
        n = len(words)
        for i in range(n - 2, -1, -1):
            w1, w2 = words[i], words[i+1]
            if w1["start"] != -1.0 and w2["start"] != -1.0:
                if w1.get("stanza_idx", 0) == w2.get("stanza_idx", 0):
                    gap = w2["start"] - w1["end"]
                    # Разрыв > 10 секунд И слово прилипло к началу (< 5.0с)
                    if gap > 10.0 and w1["start"] < 5.0:
                        has_curtain = any(cs >= w1["end"] and ce <= w2["start"] for cs, ce in self.all_curtains)
                        if not has_curtain:
                            log.warning(f"   🎯 [R->L Radar] Обнаружено Фейковое Интро! Разрыв {gap:.1f}s. Снос левой части.")
                            for k in range(i + 1):
                                words[k]["start"], words[k]["end"] = -1.0, -1.0
                            break

    def _outro_protection(self, words: list, strong_vad: list) -> bool:
        """Сносит концовку, только если после неё идет уверенный вокал > 4 секунд."""
        last_idx = -1
        last_end = 0.0
        for i, w in enumerate(words):
            if w["start"] != -1.0 and w["end"] > last_end:
                last_end = w["end"]
                last_idx = i
                
        if last_idx == -1 or not strong_vad: return False
        
        last_vocal_end = strong_vad[-1][1]
        if last_vocal_end - last_end > 10.0:
            tail_vad = [v for v in strong_vad if v[0] > last_end + 2.0]
            tail_vad_dur = sum(e - s for s, e in tail_vad)
            if tail_vad_dur > 4.0:
                log.warning(f"   🛡️ [Outro Protection] Плотный вокал после текста ({tail_vad_dur:.1f}s). Откат последнего куплета!")
                last_stanza = words[-1].get("stanza_idx", 0)
                for w in words:
                    if w.get("stanza_idx", 0) == last_stanza:
                        w["start"], w["end"] = -1.0, -1.0
                return True
        return False

    # ─── ЭТАП 3: АУДИТОР И ХИРУРГ (ОТ V13.1) ──────────────────────────────────

    def _audit_json(self, words: list) -> list:
        bugs = []
        n = len(words)
        
        clusters = []
        curr_cluster = []
        for i in range(n):
            if words[i]["start"] != -1: curr_cluster.append(i)
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
                if gap > 3.0 and not words[i]["line_break"]:
                    if not any(c_s >= words[i]["end"] and c_e <= words[i+1]["start"] for c_s, c_e in self.all_curtains):
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
                vowel_w = get_vowel_weight(w["clean_text"], w["line_break"])
                w["end"] = w["start"] + vowel_w * 0.8 + 0.5
                log.warning(f"[Surgeon] Хвост OVERSTRETCH обрублен: '{w['clean_text']}'")
            elif bug["type"] == "TORN_LINE":
                idx = bug["idx"]
                log.warning(f"[Surgeon] Взлом TORN_LINE: сброс слов {idx-1} и {idx}")
                words[idx-1]["start"], words[idx-1]["end"] = -1.0, -1.0
                words[idx]["start"], words[idx]["end"] = -1.0, -1.0

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

    # ─── ЭТАП 4: АРЕНА И ОПЕРАЦИОННАЯ ──────────────────────────────────────────

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

    def _the_arena_surgery(self, words: list, gap: tuple, audio_data: np.ndarray, model, lang: str, strong_vad: list, weak_vad: list, first_vocal_t: float, audio_duration: float):
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
            
        prop_loom = propose_loom(words, s_idx, e_idx, t_start, t_end, strong_vad, weak_vad, first_vocal_t)
        if prop_loom: proposals.append(prop_loom)
            
        winner = the_supreme_judge(proposals, words, s_idx, e_idx, strong_vad, weak_vad, self.all_curtains, first_vocal_t)
        
        if winner:
            for k, t in enumerate(winner.timings):
                mapped_s, mapped_e = enforce_curtains(t["start"], t["end"], self.all_curtains)
                words[s_idx + k]["start"] = mapped_s
                words[s_idx + k]["end"] = mapped_e
        else:
            log.warning(f"   ⚠️ Арена не выявила победителя для [{s_idx}-{e_idx}].")

    # ─── ЭТАП 5: ФИНАЛЬНАЯ ПОЛИРОВКА ────────────────────────────────────────────

    def _local_snapping(self, words: list, audio_duration: float):
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

    def _apply_absolute_gravity(self, words: list, audio_duration: float, vad_mask: list):
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
        log.info(f"Aligner СТАРТ (Symphony V6.3 Hybrid): {self._track_stem}")
        
        canon_words = prepare_text(raw_lyrics)
        if not canon_words:
            with open(output_json_path, "w", encoding="utf-8") as f: json.dump([], f)
            return output_json_path

        lang = detect_language(raw_lyrics)
        model = None
        
        try:
            audio_data_raw, sr = librosa.load(vocals_path, sr=16000, mono=True)
            audio_duration = len(audio_data_raw) / sr
            
            # 1. Сборка Занавесов
            self.all_curtains = build_iron_curtain(audio_data_raw, sr)
            
            # 2. Авангард (может добавить Занавес в самое начало)
            model = stable_whisper.load_model(self.model_name, download_root=self.whisper_model_dir, device=self.device)
            self._vanguard_protocol(model, audio_data_raw, canon_words, lang)
            self.all_curtains = sorted(self.all_curtains, key=lambda x: x[0])
            
            # 3. Генерация Карт (THE PURGE вырежет VAD из всех занавесов)
            strong_vad, weak_vad, onsets, is_harmonic_fn = get_acoustic_maps(audio_data_raw, sr, self.all_curtains)
            combined_vad = sorted(strong_vad + weak_vad, key=lambda x: x[0])
            first_vocal_t = strong_vad[0][0] if strong_vad else 0.0

            # 4. Двойной Движок
            self._platinum_skeleton(model, audio_data_raw, canon_words, lang)
            blind_words = self._blind_oracle(model, audio_data_raw, lang)
            self._crosscheck_oracle(canon_words, blind_words)
            
            # 5. Биометрия
            passport = get_empirical_data(canon_words)
            log.info(f"   🧬 Паспорт Песни: SDR = {passport['sdr']:.2f} слог/с, Вдох = {passport['avg_breath']:.2f}с")

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

            # 6. Цикл Ковки
            max_loops = 3
            prev_gaps = []
            for loop_idx in range(max_loops):
                bugs = self._audit_json(canon_words)
                self._fix_bugs(canon_words, bugs)
                
                anomalies = self._run_tribunal(canon_words, is_harmonic_fn)
                for s_idx, e_idx, reason in anomalies:
                    log.info(f"   -> Карантин [{s_idx}-{e_idx}]: {reason}. Сброс таймингов.")
                    for k in range(s_idx, e_idx + 1): canon_words[k]["start"] = canon_words[k]["end"] = -1.0
                
                self._bi_directional_radar(canon_words)
                
                if loop_idx == 0:
                    self._outro_protection(canon_words, strong_vad)
                
                gaps = self._find_gaps(canon_words)
                
                if not gaps and not bugs and not anomalies:
                    log.info(f"   ✨ [The Forge] Аудит пройден. Аномалий нет (Итерация {loop_idx+1}).")
                    break
                    
                if gaps == prev_gaps:
                    log.warning("   🛑 [Stalemate] Арена зациклилась. Остановка Ковки.")
                    break
                prev_gaps = copy.deepcopy(gaps)
                
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
                    
                    self._the_arena_surgery(canon_words, gap, audio_data_raw, model, lang, strong_vad, weak_vad, first_vocal_t, audio_duration)

            self._local_snapping(canon_words, audio_duration)
            
            if any(w["start"] == -1.0 for w in canon_words):
                self._apply_absolute_gravity(canon_words, audio_duration, combined_vad)
                
            self._apply_vad_guillotine(canon_words, combined_vad)
            self._smoothing(canon_words)

            score = evaluate_alignment_quality(canon_words, strong_vad, weak_vad, self.all_curtains, spot_check_fn)
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