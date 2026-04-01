import rapidfuzz
from aligner_utils import (
    get_phonetic_bounds, calculate_overlap, get_vowel_weight,
    extract_motif_rhythm, apply_motif_rhythm
)
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list) -> list:
    """
    Главный алгоритм привязки (Neural Sequence Alignment).
    Сопоставляет идеальный текст (canon_words) с отфильтрованным транскриптом (heard_words).
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Neural Sequence Matching...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Транскрипт пуст (или удален фильтром). Sequence Matching невозможен.")
        return canon_words
        
    # 1. Матрица Нидлмана-Вунша (Levenshtein Distance)
    dp = [[0] * (n_heard + 1) for _ in range(n_canon + 1)]
    backtrack = [[(0, 0)] * (n_heard + 1) for _ in range(n_canon + 1)]
    
    # Весовые коэффициенты для выравнивания
    MATCH_SCORE = 3          # Точное совпадение
    PARTIAL_MATCH_SCORE = 1  # Частичное (например, "пьяная" и "пья")
    GAP_PENALTY = -1         # Слово пропущено нейросетью или лишний шум
    MISMATCH_PENALTY = -1    # Слова вообще не похожи
    
    for i in range(1, n_canon + 1):
        dp[i][0] = i * GAP_PENALTY
        backtrack[i][0] = (i - 1, 0)
        
    for j in range(1, n_heard + 1):
        dp[0][j] = j * GAP_PENALTY
        backtrack[0][j] = (0, j - 1)
        
    for i in range(1, n_canon + 1):
        for j in range(1, n_heard + 1):
            c_text = canon_words[i-1]["clean_text"]
            h_text = heard_words[j-1]["clean"]
            
            # Вычисляем процент сходства строк (0-100)
            similarity = rapidfuzz.fuzz.ratio(c_text, h_text)
            
            if similarity >= 80:
                cost = MATCH_SCORE
            elif similarity >= 50:
                cost = PARTIAL_MATCH_SCORE
            else:
                cost = MISMATCH_PENALTY
                
            # Оцениваем 3 пути: Совпадение, Пропуск в Canon, Пропуск в Heard
            match_val = dp[i-1][j-1] + cost
            delete_val = dp[i-1][j] + GAP_PENALTY
            insert_val = dp[i][j-1] + GAP_PENALTY
            
            best_val = max(match_val, delete_val, insert_val)
            dp[i][j] = best_val
            
            # Запоминаем шаг для обратного прохода
            if best_val == match_val:
                backtrack[i][j] = (i-1, j-1)
            elif best_val == delete_val:
                backtrack[i][j] = (i-1, j)
            else:
                backtrack[i][j] = (i, j-1)

    # 2. Обратный проход (Backtracking)
    i, j = n_canon, n_heard
    matches = []
    
    while i > 0 and j > 0:
        prev_i, prev_j = backtrack[i][j]
        
        # Если мы шагнули по диагонали (Совпадение/Замена)
        if prev_i == i - 1 and prev_j == j - 1:
            c_text = canon_words[i-1]["clean_text"]
            h_text = heard_words[j-1]["clean"]
            similarity = rapidfuzz.fuzz.ratio(c_text, h_text)
            
            # Берем только слова, похожие больше чем на 50%
            if similarity >= 50:
                matches.append((i-1, j-1, similarity))
        
        i, j = prev_i, prev_j

    matches.reverse()
    log.info(f"   🔗 Найдено {len(matches)} прямых совпадений из {n_canon} эталонных слов.")
    
    # 3. Применяем тайминги из Whisper к эталонному тексту
    for c_idx, h_idx, sim in matches:
        hw = heard_words[h_idx]
        cw = canon_words[c_idx]
        
        cw["start"] = hw["start"]
        cw["end"] = hw["end"]
        log.debug(f"      [Match] '{cw['word']}' (Genius) <-> '{hw['word']}' (Whisper) | Sim: {sim}% | {cw['start']:.2f}s - {cw['end']:.2f}s")
        
    # 4. ФИЛЬТР №3: Клонирование мотивов (Repetition Interpolator)
    # Ищем большие дыры, где текст повторяется, но Whisper его пропустил (ZOLOTO)
    _clone_repetitive_motifs(canon_words, vad_intervals)

    # 5. Smart VAD-Snapping (Заполнение мелких дыр)
    _smart_vad_snapping(canon_words, vad_intervals)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_words

def _clone_repetitive_motifs(words: list, vad_intervals: list):
    """
    ФИЛЬТР №3: Защита от "заикания" Whisper'а.
    Если нейросеть пропустила кусок текста, мы проверяем: не пел ли артист эти же слова раньше?
    Если пел - копируем ритм из спетого куска и вставляем в тишину.
    """
    n = len(words)
    i = 0
    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            gap_size = j - i
            
            # Работаем только с большими дырами (больше 3 слов)
            if gap_size >= 4:
                # Берем текст дыры
                gap_text = " ".join([words[k]["clean_text"] for k in range(i, j)])
                
                # Ищем этот же текст РАНЬШЕ в уже распределенных словах
                best_match_idx = -1
                
                for search_idx in range(0, i - gap_size):
                    # Проверяем, распределен ли этот кусок
                    if words[search_idx]["start"] != -1.0 and words[search_idx + gap_size - 1]["start"] != -1.0:
                        search_text = " ".join([words[k]["clean_text"] for k in range(search_idx, search_idx + gap_size)])
                        
                        if rapidfuzz.fuzz.ratio(gap_text, search_text) > 90:
                            best_match_idx = search_idx
                            break
                            
                if best_match_idx != -1:
                    log.info(f"   🔁 [Motif Clone] Обнаружен пропуск повторяющегося текста: '{gap_text}'")
                    # Извлекаем ритм из оригинального спетого куска
                    motif = extract_motif_rhythm(words, best_match_idx, best_match_idx + gap_size - 1)
                    
                    if motif:
                        # Ищем окно для вставки
                        t_start = words[i-1]["end"] + 0.1 if i > 0 and words[i-1]["start"] != -1.0 else 0.0
                        t_end = words[j]["start"] - 0.1 if j < n and words[j]["start"] != -1.0 else vad_intervals[-1][1]
                        
                        # Клонируем тайминги
                        apply_motif_rhythm(words, i, j - 1, motif, t_start, t_end)
            i = j
        else:
            i += 1

def _smart_vad_snapping(words: list, vad_intervals: list):
    """
    Интеллектуальное распределение нераспознанных слов (ФИЛЬТР №4: Line Integrity).
    Строго соблюдает line_break: если фраза неразрывна, она переносится целиком в один VAD.
    """
    log.info("   🧩 [VAD-Snapping] Интерполяция оставшихся слов в пустоты...")
    
    n = len(words)
    i = 0
    healed_count = 0
    
    while i < n:
        if words[i]["start"] == -1.0:
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            gap_size = j - i
            
            # Окно поиска
            t_start = words[i-1]["end"] + 0.05 if i > 0 and words[i-1]["start"] != -1.0 else 0.0
            t_end = words[j]["start"] - 0.05 if j < n and words[j]["start"] != -1.0 else (vad_intervals[-1][1] if vad_intervals else 1000.0)
            
            # Собираем VAD-интервалы в этом окне
            available_vads = []
            for vs, ve in vad_intervals:
                if ve > t_start and vs < t_end:
                    o_s = max(t_start, vs)
                    o_e = min(t_end, ve)
                    if o_e - o_s > 0.1: # Игнорируем микро-шумы
                        available_vads.append((o_s, o_e))
            
            if not available_vads:
                # Если VAD пуст (гитарное соло), мы НЕ пытаемся размазать слова здесь. 
                # Мы оставляем их пустыми, чтобы финальный интерполятор сжал их в безопасной зоне.
                log.debug(f"         ⚠️ [VAD-Snapping] Окно [{i}:{j-1}] попадает в тишину. Пропуск.")
                i = j
                continue
                
            # ФИЛЬТР №4: Line Integrity (Неразрывность строк).
            # Проверяем, есть ли внутри дыры разрывы строк. Если нет - это единая фраза.
            has_line_break = any(words[k]["line_break"] for k in range(i, j - 1))
            
            if not has_line_break and len(available_vads) > 1:
                # Вся фраза должна лечь в ОДИН самый большой VAD-интервал, чтобы не разорваться гитарным соло
                largest_vad = max(available_vads, key=lambda x: x[1] - x[0])
                available_vads = [largest_vad]
                log.debug(f"         🔒 [Line Integrity] Фраза [{i}:{j-1}] неразрывна. Выбран единый VAD: {largest_vad[0]:.2f}s - {largest_vad[1]:.2f}s")
                
            total_vad_dur = sum(e - s for s, e in available_vads)
            weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
            total_weight = sum(weights)
            
            current_time_in_vad = 0.0
            
            for k in range(i, j):
                w = words[k]
                word_vad_share = (weights[k-i] / total_weight) * total_vad_dur
                
                min_p_dur, max_p_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
                actual_dur = min(word_vad_share, max_p_dur)
                
                accumulated = 0.0
                placed_start, placed_end = -1.0, -1.0
                
                for vs, ve in available_vads:
                    vad_len = ve - vs
                    if current_time_in_vad < accumulated + vad_len:
                        offset = current_time_in_vad - accumulated
                        placed_start = vs + offset
                        placed_end = min(ve, placed_start + actual_dur)
                        break
                    accumulated += vad_len
                    
                if placed_start != -1.0:
                    w["start"] = placed_start
                    w["end"] = placed_end
                    healed_count += 1
                
                current_time_in_vad += word_vad_share
                
            i = j
        else:
            i += 1
            
    if healed_count > 0:
        log.info(f"   ✨ VAD-Snapping спас {healed_count} слов!")