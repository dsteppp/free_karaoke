import rapidfuzz
from bisect import bisect_right
from aligner_utils import (
    get_phonetic_bounds, get_vowel_weight, check_sdr_sanity
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

# ==============================================================================
# БЛОК ИНИЦИАЛИЗАЦИИ NUMBA (С защитой от Android/Mock)
# ==============================================================================
NUMBA_AVAILABLE = False
try:
    import numpy as np
    from numba import njit
    
    # Жесткая защита от Chaquopy (Android) и виртуальных заглушек
    if type(np).__name__ == "MagicMock" or type(njit).__name__ == "MagicMock":
        raise ImportError("Обнаружены Mock-библиотеки (Android среда). Numba отключена.")

    @njit(fastmath=True)
    def _numba_dp_solver(c_starts, c_ends, c_sims, c_cidx, canon_vowels, canon_lbreaks):
        num_cand = len(c_starts)
        dp = np.full(num_cand, -np.inf)
        parent = np.full(num_cand, -1, dtype=np.int32)
        
        for i in range(num_cand):
            dp[i] = c_sims[i]

        for i in range(1, num_cand):
            best_val = dp[i]
            best_p = -1
            for p in range(i):
                if c_cidx[i] <= c_cidx[p]:
                    continue
                if c_starts[i] < c_ends[p]:
                    continue
                
                gap = c_starts[i] - c_ends[p]
                if gap < -0.1 or gap > 30.0:
                    continue
                
                is_sane = True
                if c_cidx[i] == c_cidx[p] + 1:
                    is_same_line = not canon_lbreaks[c_cidx[p]]
                    if is_same_line and gap > 2.5:
                        is_sane = False
                else:
                    gap_vowels = 0
                    for v_idx in range(c_cidx[p] + 1, c_cidx[i]):
                        gap_vowels += canon_vowels[v_idx]
                    
                    if gap > 0:
                        vps = gap_vowels / gap
                        if vps < 0.5:
                            is_sane = False
                    else:
                        is_sane = False
                
                if is_sane:
                    val = dp[p] + c_sims[i]
                    if val > best_val:
                        best_val = val
                        best_p = p
                        
            dp[i] = best_val
            parent[i] = best_p
            
        max_idx = -1
        max_val = -np.inf
        for i in range(num_cand):
            if dp[i] > max_val:
                max_val = dp[i]
                max_idx = i
                
        return parent, max_idx, max_val

    NUMBA_AVAILABLE = True
except ImportError as ie:
    # Тихий пропуск, это нормально для Android
    pass
except Exception as e:
    log.warning(f"⚠️ Ошибка инициализации Numba: {e}. Оркестратор будет работать в режиме Python.")
# ==============================================================================


def _solve_dp_path(candidates: list, active_canon: list) -> list:
    """
    Единая функция динамического программирования для поиска оптимального пути.
    Автоматически переключается между C++ (Numba) и чистым Python (Fallback).
    """
    num_cand = len(candidates)
    if num_cand == 0:
        return []

    # --- ВЕТКА 1: БЫСТРЫЙ ПУТЬ (Numba / C++) ---
    if NUMBA_AVAILABLE:
        try:
            c_starts = np.array([c.get("start", 0.0) for c in candidates], dtype=np.float64)
            c_ends = np.array([c.get("end", 0.0) for c in candidates], dtype=np.float64)
            c_sims = np.array([c.get("sim", 0.0) for c in candidates], dtype=np.float64)
            c_cidx = np.array([c.get("c_idx", 0) for c in candidates], dtype=np.int32)
            
            def _count_vowels(text):
                return sum(1 for char in str(text).lower() if char in "aeiouyаеёиоуыэюя")
                
            canon_vowels = np.array([_count_vowels(w.get("clean_text", w.get("word", ""))) for w in active_canon], dtype=np.int32)
            canon_lbreaks = np.array([bool(w.get("line_break", False)) for w in active_canon], dtype=np.bool_)
            
            parent, max_idx, max_val = _numba_dp_solver(c_starts, c_ends, c_sims, c_cidx, canon_vowels, canon_lbreaks)
            
            raw_sequence = []
            curr_idx = max_idx
            while curr_idx != -1:
                raw_sequence.append(candidates[curr_idx])
                curr_idx = parent[curr_idx]
            
            raw_sequence.reverse()
            return raw_sequence
        except Exception as e:
            log.error(f"⚠️ Сбой Numba-акселерации ({e}). Экстренный переход на безопасный Python-цикл.")
            # Если упало (например, из-за битых данных), проваливаемся в Ветку 2

    # --- ВЕТКА 2: МЕДЛЕННЫЙ ПУТЬ (Чистый Python / Fallback) ---
    dp = [c["sim"] for c in candidates]
    parent = [-1] * num_cand

    MAX_GAP = 30.0
    start_times = [c["start"] for c in candidates]

    for i in range(1, num_cand):
        best_score = dp[i]
        best_p = -1
        curr = candidates[i]

        min_start = curr["start"] - MAX_GAP
        j_min = bisect_right(start_times, min_start)

        for j in range(i - 1, j_min - 1, -1):
            prev = candidates[j]

            if curr["c_idx"] <= prev["c_idx"]:
                continue

            dur = curr["start"] - prev["end"]
            if dur < -0.1:
                continue

            if dur > MAX_GAP:
                continue

            is_sane = False

            if curr["c_idx"] == prev["c_idx"] + 1:
                is_same_line = not active_canon[prev["c_idx"]]["line_break"]
                if is_same_line and dur > 2.5:
                    is_sane = False
                else:
                    is_sane = True
            else:
                is_sane, _ = check_sdr_sanity(active_canon, prev["c_idx"] + 1, curr["c_idx"] - 1, dur, False)

            if is_sane:
                score = dp[j] + curr["sim"]
                if score > best_score:
                    best_score = score
                    best_p = j

        dp[i] = best_score
        parent[i] = best_p

    max_idx = dp.index(max(dp))
    curr_idx = max_idx
    raw_sequence = []

    while curr_idx != -1:
        raw_sequence.append(candidates[curr_idx])
        curr_idx = parent[curr_idx]

    raw_sequence.reverse()
    return raw_sequence


def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float, start_word_index: int = 0, anchor_time: float = None) -> list:
    """
    V8.4 Elastic Cluster Alignment.
    Математика кластеров + Эластичная заливка VAD.
    Оптимизировано: бинарный поиск по времени для DP-цикла.

    Параметры:
        start_word_index: индекс слова, с которого начинать matching.
                          Слова до этого индекса НЕ обрабатываются — их тайминги сохраняются.
        anchor_time: точное время (секунды) ручного якоря.
                     Используется для фильтрации heard_words и фиксации стартовой точки.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Elastic Sequence Matching...")
    if start_word_index > 0:
        log.info("   📍 Partial rescan: обрабатываем слова с индекса %d из %d", start_word_index, len(canon_words))
        log.info("   🔒 Слова [0:%d] заблокированы — тайминги не изменятся", start_word_index)
        if anchor_time is not None:
            log.info("   ⚓ Ручной якорь: слово %d начинается в %.2fс", start_word_index, anchor_time)

    n_canon = len(canon_words)
    n_heard = len(heard_words)

    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст. Sequence Matching отменен.")
        return canon_words

    # Если start_word_index > 0 — это partial rescan
    if start_word_index > 0 and start_word_index < n_canon:
        return _partial_sequence_matching(canon_words, heard_words, vad_intervals, audio_duration, start_word_index, anchor_time)

    # Стандартный полный matching (start_word_index == 0)
    return _full_sequence_matching(canon_words, heard_words, vad_intervals, audio_duration)


def _full_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float) -> list:
    """Полное сопоставление всех слов (стандартный режим)."""
    n_canon = len(canon_words)
    n_heard = len(heard_words)

    # 1. Формируем пул кандидатов (совпадения > 60%)
    candidates = []
    for c_idx in range(n_canon):
        for h_idx in range(n_heard):
            c_text = canon_words[c_idx]["clean_text"]
            h_text = heard_words[h_idx]["clean"]
            sim = rapidfuzz.fuzz.ratio(c_text, h_text)
            if sim >= 60:
                candidates.append({
                    "c_idx": c_idx,
                    "h_idx": h_idx,
                    "sim": sim,
                    "start": heard_words[h_idx]["start"],
                    "end": heard_words[h_idx]["end"]
                })

    candidates.sort(key=lambda x: x["start"])

    # 2. SDR-Guard v2: Динамическое программирование пути
    raw_sequence = _solve_dp_path(candidates, canon_words)
    if not raw_sequence:
        log.warning("   ⚠️ Нет ни одного валидного совпадения текста.")
        return canon_words

    # 3. V8.4 Cluster Filter
    clusters = []
    current_cluster = []

    for i, match in enumerate(raw_sequence):
        if not current_cluster:
            current_cluster.append(match)
        else:
            prev_match = current_cluster[-1]
            time_diff = match["start"] - prev_match["end"]
            if time_diff <= 5.0:
                current_cluster.append(match)
            else:
                clusters.append(current_cluster)
                current_cluster = [match]

    if current_cluster:
        clusters.append(current_cluster)

    valid_sequence = []
    orphans_removed = 0
    for cluster in clusters:
        if len(cluster) >= 3:
            valid_sequence.extend(cluster)
        else:
            orphans_removed += len(cluster)

    if orphans_removed > 0:
        log.info(f"   🗑️ [Cluster Filter] Убито сиротских якорей (галлюцинаций): {orphans_removed}")

    log.info(f"   🔗 Утверждено жестких якорей: {len(valid_sequence)}")

    for match in valid_sequence:
        cw = canon_words[match["c_idx"]]
        cw["start"] = match["start"]
        cw["end"] = match["end"]

    # 4. Elastic VAD Assembly
    _elastic_vad_assembly(canon_words, vad_intervals, audio_duration)

    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words


def _partial_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list, audio_duration: float, start_word_index: int, anchor_time: float = None) -> list:
    """
    Частичное сопоставление только для слов [start_word_index:].

    anchor_time — точная точка начала вокала, установленная пользователем.
    Все heard_words ДО anchor_time отбрасываются.
    Первое слово partial_canon фиксируется на anchor_time как жёсткий якорь.
    """
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    partial_canon = canon_words[start_word_index:]
    n_canon_partial = len(partial_canon)

    log.info("   📝 Partial matching: %d слов из %d (якорь=%.2fс)", n_canon_partial, n_canon, anchor_time or 0)
    if anchor_time is not None:
        log.info("   ⚓ Anchor word: #%d «%s» на %.2fс", start_word_index, partial_canon[0]["word"] if partial_canon else "?", anchor_time)

    # ── КЛЮЧЕВОЕ: фильтруем heard_words — только те, что >= anchor_time ──────
    if anchor_time is not None:
        heard_before_filter = len(heard_words)
        # Буфер 0.3с — чтобы захватить слова, которые чуть раньше якоря
        heard_words = [w for w in heard_words if w["start"] >= anchor_time - 0.3]
        filtered_count = heard_before_filter - len(heard_words)
        log.info("   ✂️ heard_words обрезан по anchor_time (%.2fс):", anchor_time)
        log.info("      📥 Было: %d слов", heard_before_filter)
        log.info("      🗑️ Отброшено (до якоря - 0.3с): %d", filtered_count)
        log.info("      ✅ Осталось для matching: %d", len(heard_words))

        # Лог первых отфильтрованных слов
        for i, hw in enumerate(heard_words[:8]):
            log.info("      heard_clip[%d]: «%s» %.2fс-%.2fс", i, hw["clean"], hw["start"], hw["end"])
        if len(heard_words) > 8:
            log.info("      ... и ещё %d слов", len(heard_words) - 8)

    # 1. Формируем пул кандидатов (совпадения > 60%)
    log.info("   🔍 Поиск кандидатов (fuzz.ratio >= 60%%)...")
    candidates = []
    for c_idx in range(n_canon_partial):
        for h_idx in range(len(heard_words)):
            c_text = partial_canon[c_idx]["clean_text"]
            h_text = heard_words[h_idx]["clean"]
            sim = rapidfuzz.fuzz.ratio(c_text, h_text)
            if sim >= 60:
                candidates.append({
                    "c_idx": c_idx,  # индекс в partial_canon
                    "h_idx": h_idx,
                    "sim": sim,
                    "start": heard_words[h_idx]["start"],
                    "end": heard_words[h_idx]["end"]
                })

    candidates.sort(key=lambda x: x["start"])
    log.info("   🔍 Найдено кандидатов: %d", len(candidates))

    # Покажем топ кандидатов по similarity
    if candidates:
        top_cands = sorted(candidates, key=lambda x: x["sim"], reverse=True)[:5]
        for tc in top_cands:
            log.info("      кандидат: canon[%d]«%s» ↔ heard[%d]«%s» sim=%d%% t=%.2fс",
                     tc["c_idx"], partial_canon[tc["c_idx"]]["clean_text"],
                     tc["h_idx"], heard_words[tc["h_idx"]]["clean"],
                     tc["sim"], tc["start"])

    # 2. SDR-Guard v2: Динамическое программирование пути
    raw_sequence = _solve_dp_path(candidates, partial_canon)
    if not raw_sequence:
        log.warning("   ⚠️ Нет ни одного валидного совпадения текста.")
        return canon_words

    path_score = sum(match["sim"] for match in raw_sequence)
    log.info("   🛤️ DP нашёл путь: %d якорей, score ≈ %d", len(raw_sequence), path_score)
    
    # Покажем путь
    for i, match in enumerate(raw_sequence[:8]):
        log.info("      path[%d]: canon[%d]«%s» ← heard «%s» t=%.2fс sim=%d",
                 i, match["c_idx"], partial_canon[match["c_idx"]]["clean_text"],
                 heard_words[match["h_idx"]]["clean"], match["start"], match["sim"])
    if len(raw_sequence) > 8:
        log.info("      ... и ещё %d якорей", len(raw_sequence) - 8)

    # 3. V8.4 Cluster Filter
    clusters = []
    current_cluster = []

    for i, match in enumerate(raw_sequence):
        if not current_cluster:
            current_cluster.append(match)
        else:
            prev_match = current_cluster[-1]
            time_diff = match["start"] - prev_match["end"]
            if time_diff <= 5.0:
                current_cluster.append(match)
            else:
                clusters.append(current_cluster)
                current_cluster = [match]

    if current_cluster:
        clusters.append(current_cluster)

    log.info("   📊 Кластеров найдено: %d", len(clusters))
    for i, cl in enumerate(clusters):
        log.info("      cluster[%d]: %d якорей, t=%.2fс-%.2fс", i, len(cl), cl[0]["start"], cl[-1]["end"])

    valid_sequence = []
    orphans_removed = 0
    for cluster in clusters:
        if len(cluster) >= 3:
            valid_sequence.extend(cluster)
        else:
            orphans_removed += len(cluster)

    if orphans_removed > 0:
        log.info(f"   🗑️ [Cluster Filter] Убито сиротских якорей (галлюцинаций): {orphans_removed}")

    log.info(f"   🔗 Утверждено жестких якорей: {len(valid_sequence)}")

    # ── КЛЮЧЕВОЕ: фиксируем первый якорь на anchor_time ──────────────────────
    if anchor_time is not None and valid_sequence:
        # Первый элемент valid_sequence — это первое найденное совпадение.
        # Если оно начинается раньше anchor_time - 0.5с — сдвигаем/отбрасываем.
        first_match = valid_sequence[0]
        if first_match["start"] < anchor_time - 0.5:
            log.info("   ⚓ Первый якорь (%.2fс) раньше ручного якоря (%.2fс) — отбрасываем",
                     first_match["start"], anchor_time)
            valid_sequence = valid_sequence[1:]
            if valid_sequence:
                log.info("   ⚓ Новый первый якорь: «%s» на %.2fс",
                         partial_canon[valid_sequence[0]["c_idx"]]["clean_text"],
                         valid_sequence[0]["start"])
            else:
                log.warning("   ⚠️ Все якоря отброшены — были раньше anchor_time!")

        # Если первый якорь всё ещё не совпадает с anchor_time — логируем расхождение
        if valid_sequence:
            first_match = valid_sequence[0]
            # Если ручной якорь уже установлен в canon_words — используем его
            manual_start = canon_words[start_word_index].get("start", -1)
            if manual_start > 0 and abs(manual_start - first_match["start"]) > 1.0:
                log.info("   ⚓ Ручной якорь %.2fс отличается от найденного %.2fс (расхождение %.2fс)",
                         manual_start, first_match["start"], abs(manual_start - first_match["start"]))
            elif manual_start > 0:
                log.info("   ⚓ Ручной якорь %.2fс ≈ найденный %.2fс — совпадают!",
                         manual_start, first_match["start"])

    # Применяем тайминги к partial_canon (с учётом сдвига индексов)
    for match in valid_sequence:
        cw = partial_canon[match["c_idx"]]
        cw["start"] = match["start"]
        cw["end"] = match["end"]

    log.info("   📊 Тайминги применены к %d словам из %d", len(valid_sequence), n_canon_partial)

    # 4. Elastic VAD Assembly — только для partial_canon
    # ВАЖНО: передаём обрезанные vad_intervals (только от anchor_time)
    log.info("   🧲 Запуск Elastic VAD Assembly (anchor_time=%.2fс)...", anchor_time or 0)
    _elastic_vad_assembly(partial_canon, vad_intervals, audio_duration, anchor_time)

    # Подсчитаем сколько слов заполнено через Elastic VAD
    filled_by_vad = sum(1 for w in partial_canon if w["start"] >= 0 and w.get("start", -1) > 0)
    still_broken = sum(1 for w in partial_canon if w["start"] == -1.0)
    log.info("   📊 После Elastic VAD: %d слов с таймингами, %d всё ещё без", filled_by_vad, still_broken)

    log.info("🧠 [Orchestra] Partial Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words  # Возвращаем полный массив (старые + новые тайминги)

def _elastic_vad_assembly(words: list, vad_intervals: list, audio_duration: float, anchor_time: float = None):
    """
    ФИЛЬТР №3: Elastic VAD Assembly (V8.4).
    Ищет голос внутри слепых зон и растягивает слова ровно по контуру этого голоса.

    anchor_time — если задан, это partial rescan. Первый якорь — это anchor_time,
    и все VAD-интервалы ДО anchor_time игнорируются.
    """
    log.info("   🧲 [Elastic Assembly] Старт эластичной заливки слепых зон...")
    if anchor_time is not None:
        log.info("   ⚓ Partial rescan: anchor_time=%.2fс — заливка от этой точки", anchor_time)

    # Подсчитаем слепые зоны
    blind_spots = []
    i = 0
    while i < len(words):
        if words[i]["start"] == -1.0:
            j = i
            while j < len(words) and words[j]["start"] == -1.0:
                j += 1
            blind_spots.append((i, j))
            i = j
        else:
            i += 1

    log.info("   📊 Найдено слепых зон: %d", len(blind_spots))
    for bs_idx, (start_i, end_i) in enumerate(blind_spots):
        word_text = " ".join(words[k]["clean_text"] for k in range(start_i, min(end_i, start_i + 5)))
        if end_i - start_i > 5:
            word_text += " ..."
        log.info("      blind_spot[%d]: слова [%d:%d] «%s»", bs_idx, start_i, end_i, word_text)

    n = len(words)
    i = 0
    healed_count = 0
    zones_processed = 0

    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1

            gap_size = j - i

            # ── КЛЮЧЕВОЕ для partial rescan: правильный anchor_prev_end ──────
            if anchor_time is not None and i == 0:
                # Это partial rescan — первый якорь это anchor_time
                anchor_prev_end = anchor_time
                log.info("   📍 Partial rescan: anchor_prev_end = %.2fс (ручной якорь)", anchor_prev_end)
            elif i > 0 and words[i-1]["start"] != -1.0:
                anchor_prev_end = words[i-1]["end"]
            else:
                anchor_prev_end = 0.0

            anchor_next_start = words[j]["start"] if j < n and words[j]["start"] != -1.0 else audio_duration

            log.info("   🔍 Слепая зона [%d:%d] (%d слов): prev_end=%.2fс → next_start=%.2fс",
                     i, j, gap_size, anchor_prev_end, anchor_next_start)

            # Собираем VAD-острова, которые находятся ВНУТРИ этой дыры
            available_vads = []
            for vs, ve in vad_intervals:
                # Остров должен быть строго между якорями (с микро-отступом 0.05с)
                if ve > anchor_prev_end + 0.05 and vs < anchor_next_start - 0.05:
                    o_s = max(anchor_prev_end + 0.05, vs)
                    o_e = min(anchor_next_start - 0.05, ve)
                    if o_e - o_s > 0.1: # Игнорируем микро-шумы
                        available_vads.append((o_s, o_e))

            log.info("      📊 VAD-островов в диапазоне [%.2f, %.2f]: %d",
                     anchor_prev_end, anchor_next_start, len(available_vads))
            for v_idx, (vs, ve) in enumerate(available_vads[:5]):
                log.info("         vad[%d]: %.2fс — %.2fс (%.2fс)", v_idx, vs, ve, ve - vs)
            if len(available_vads) > 5:
                log.info("         ... и ещё %d", len(available_vads) - 5)

            # СЦЕНАРИЙ 1: ИНТРО (До первого якоря)
            if i == 0 and available_vads:
                # В интро текст прижимается к первому якорю (вправо)
                # Берем только последний VAD-остров перед якорем, чтобы избежать шума зала на 0-й секунде
                target_vad = available_vads[-1]
                t_start, t_end = target_vad[0], target_vad[1]
                log.info("      📍 Сценарий ИНТРО: используем последний VAD-остров %.2fс-%.2fс", t_start, t_end)

            # СЦЕНАРИЙ 2: АУТРО (После последнего якоря)
            elif j == n and available_vads:
                # В аутро используем ВСЕ доступные VAD-острова от anchor_prev_end до конца
                # Раньше брался только первый остров — слова сжимались в одну точку
                t_start = available_vads[0][0]
                t_end = available_vads[-1][1]
                log.info("      📍 Сценарий АУТРО: используем все %d VAD-островов от %.2fс до %.2fс",
                         len(available_vads), t_start, t_end)

            # СЦЕНАРИЙ 3: ДЫРА В СЕРЕДИНЕ (Между якорями)
            else:
                if available_vads:
                    # Растягиваем слова от начала первого острова до конца последнего острова в этой дыре
                    t_start = available_vads[0][0]
                    t_end = available_vads[-1][1]
                    log.info("      📍 Сценарий ДЫРА: %d VAD-островов, растягиваем %.2fс-%.2fс",
                             len(available_vads), t_start, t_end)
                else:
                    # Аварийный сценарий: VAD вообще не услышал голос в этой дыре.
                    # Равномерно заполняем пространство между якорями.
                    t_start = anchor_prev_end + 0.05
                    t_end = anchor_next_start - 0.05
                    log.info("      ⚠️ Сценарий АВАРИЯ: нет VAD, заполняем %.2fс-%.2fс равномерно", t_start, t_end)

            if t_start >= t_end:
                t_start = max(anchor_prev_end + 0.01, t_end - 0.1)
                log.info("      ⚠️ Коррекция: t_start >= t_end,调整后 %.2fс-%.2fс", t_start, t_end)

            # ELASTIC PACKING (Резиновое распределение по весу гласных)
            # Это решает проблему "недокрашивания" Доры
            weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
            total_weight = sum(weights)
            total_time = t_end - t_start

            log.info("      📊 Elastic packing: total_weight=%d, total_time=%.2fс", total_weight, total_time)

            current_time = t_start
            micro_gap = 0.05 # 50мс пауза между словами для дыхания плеера

            for k in range(i, j):
                w = words[k]
                # Доля времени для этого слова (пропорционально количеству гласных)
                word_share = (weights[k-i] / total_weight) * total_time

                # Защита от бесконечного растягивания одного слова
                min_p, max_p = get_phonetic_bounds(w["clean_text"], w["line_break"])
                actual_dur = min(max(word_share, min_p), max_p * 1.5) # Позволяем растянуть до 1.5 от максимума

                w["start"] = current_time
                w["end"] = min(current_time + actual_dur, t_end)

                log.info("         [%d] «%s» weight=%d share=%.2fс → %.2fс-%.2fс (dur=%.2fс)",
                         k, w["clean_text"], weights[k-i], word_share, w["start"], w["end"], actual_dur)

                # Сдвигаем курсор времени
                current_time = w["end"] + micro_gap
                healed_count += 1

            zones_processed += 1
            i = j
        else:
            i += 1

    if healed_count > 0:
        log.info("   🧲 [Elastic Assembly] Заполнено %d слепых зон (%d слов).", zones_processed, healed_count)
    else:
        log.info("   🧲 [Elastic Assembly] Нет слепых зон для заполнения.")
