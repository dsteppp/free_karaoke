import rapidfuzz
import copy
from aligner_utils import get_phonetic_bounds, calculate_overlap, get_vowel_weight
from app_logger import get_logger

log = get_logger("aligner_orchestra")

def execute_sequence_matching(canon_words: list, heard_words: list, vad_intervals: list) -> list:
    """
    Главный движок выравнивания. Сопоставляет идеальный текст (canon_words) 
    с тем, что реально услышала нейросеть (heard_words).
    
    Возвращает обновленный список canon_words с таймингами.
    """
    log.info("=" * 50)
    log.info("🧠 [Orchestra] Старт Neural Sequence Matching...")
    
    n_canon = len(canon_words)
    n_heard = len(heard_words)
    
    if n_heard == 0:
        log.warning("   ⚠️ Нейросеть ничего не услышала! Sequence Matching невозможен.")
        return canon_words
        
    # 1. Построение матрицы Левенштейна (Needleman-Wunsch)
    dp = [[0] * (n_heard + 1) for _ in range(n_canon + 1)]
    backtrack = [[(0, 0)] * (n_heard + 1) for _ in range(n_canon + 1)]
    
    # Штрафы
    MATCH_SCORE = 3
    PARTIAL_MATCH_SCORE = 1
    GAP_PENALTY = -1
    MISMATCH_PENALTY = -1
    
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
            
            similarity = rapidfuzz.fuzz.ratio(c_text, h_text)
            
            if similarity >= 80:
                cost = MATCH_SCORE
            elif similarity >= 50:
                cost = PARTIAL_MATCH_SCORE
            else:
                cost = MISMATCH_PENALTY
                
            # Варианты: Совпадение/Замена, Пропуск в Canon (Удаление), Пропуск в Heard (Вставка)
            match_val = dp[i-1][j-1] + cost
            delete_val = dp[i-1][j] + GAP_PENALTY
            insert_val = dp[i][j-1] + GAP_PENALTY
            
            best_val = max(match_val, delete_val, insert_val)
            dp[i][j] = best_val
            
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
        
        if prev_i == i - 1 and prev_j == j - 1:
            c_text = canon_words[i-1]["clean_text"]
            h_text = heard_words[j-1]["clean"]
            similarity = rapidfuzz.fuzz.ratio(c_text, h_text)
            
            if similarity >= 50:
                matches.append((i-1, j-1, similarity))
        
        i, j = prev_i, prev_j

    matches.reverse()
    
    # 3. Перенос таймингов для совпавших слов
    log.info(f"   🔗 Найдено {len(matches)} прямых совпадений из {n_canon} эталонных слов.")
    
    for c_idx, h_idx, sim in matches:
        hw = heard_words[h_idx]
        cw = canon_words[c_idx]
        
        cw["start"] = hw["start"]
        cw["end"] = hw["end"]
        log.debug(f"      [Match] '{cw['word']}' (Genius) <-> '{hw['word']}' (Whisper) | Sim: {sim}% | {cw['start']:.2f}s - {cw['end']:.2f}s")
        
    # 4. Smart VAD-Snapping (Спасение нераспределенных слов)
    canon_updated = _smart_vad_snapping(canon_words, vad_intervals)
    
    log.info("🧠 [Orchestra] Sequence Matching завершен.")
    log.info("=" * 50)
    return canon_updated

def _smart_vad_snapping(words: list, vad_intervals: list) -> list:
    """
    Интеллектуальное заполнение дыр.
    Если слово не было услышано Whisper'ом, алгоритм ищет для него
    ближайший свободный VAD-интервал между соседними подтвержденными словами.
    """
    log.info("   🧩 [VAD-Snapping] Запуск спасения нераспределенных слов...")
    
    n = len(words)
    i = 0
    healed_count = 0
    
    while i < n:
        if words[i]["start"] == -1.0:
            # Находим границы "дыры" (gap)
            j = i
            while j < n and words[j]["start"] == -1.0:
                j += 1
                
            gap_size = j - i
            
            # Определяем временные рамки, куда можно вставить эти слова
            t_start = words[i-1]["end"] + 0.05 if i > 0 and words[i-1]["start"] != -1.0 else 0.0
            # Если дыра в самом конце, ограничиваемся последним VAD
            t_end = words[j]["start"] - 0.05 if j < n and words[j]["start"] != -1.0 else (vad_intervals[-1][1] if vad_intervals else 1000.0)
            
            log.debug(f"      -> Дыра [{i}:{j-1}] ({gap_size} слов). Окно: {t_start:.2f}s - {t_end:.2f}s")
            
            # Собираем доступные VAD-интервалы в этом окне
            available_vads = []
            for vs, ve in vad_intervals:
                if ve > t_start and vs < t_end:
                    overlap_s = max(t_start, vs)
                    overlap_e = min(t_end, ve)
                    if overlap_e - overlap_s > 0.1: # Игнорируем микро-шумы
                        available_vads.append((overlap_s, overlap_e))
            
            if not available_vads:
                log.warning(f"         ⚠️ Нет доступного VAD для слов [{i}:{j-1}]. Окно пустое!")
                i = j
                continue
                
            total_vad_dur = sum(e - s for s, e in available_vads)
            
            # Считаем суммарный фонетический вес слов в дыре
            weights = [get_vowel_weight(words[k]["clean_text"], words[k]["line_break"]) for k in range(i, j)]
            total_weight = sum(weights)
            
            # Распределяем слова пропорционально их фонетическому весу по доступным VAD
            current_time_in_vad = 0.0
            
            for k in range(i, j):
                w = words[k]
                
                # Доля времени, которая полагается этому слову
                word_vad_share = (weights[k-i] / total_weight) * total_vad_dur
                
                # Защита от бесконечного растягивания (как в "Осень пьяная")
                min_p_dur, max_p_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
                actual_dur = min(word_vad_share, max_p_dur)
                
                # Ищем, в какой VAD-интервал ложится это время
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
                    log.debug(f"         [Healed] '{w['word']}' -> {placed_start:.2f}s - {placed_end:.2f}s")
                
                current_time_in_vad += word_vad_share
                
            i = j
        else:
            i += 1
            
    log.info(f"   ✨ VAD-Snapping спас {healed_count} слов!")
    return words