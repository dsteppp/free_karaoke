import re
import math
import string
import rapidfuzz
from collections import defaultdict
from app_logger import get_logger

log = get_logger("aligner_utils")

def detect_language(text: str) -> str:
    ru_chars = sum(1 for c in text if c.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    en_chars = sum(1 for c in text if c.lower() in string.ascii_lowercase)
    return "ru" if ru_chars > en_chars else "en"

def clean_word(word: str) -> str:
    """Удаляет всю пунктуацию и приводит к нижнему регистру для идеального сравнения."""
    return re.sub(r'[^\w]', '', word.lower())

def prepare_text(raw_lyrics: str) -> list:
    """
    Разбивает текст на слова, сохраняя структуру строк (line_break) и строф (stanza_idx).
    Возвращает список словарей-пустышек для заполнения таймингами.
    """
    if not raw_lyrics: return []
    
    words = []
    lines = raw_lyrics.split('\n')
    stanza_idx = 0
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            stanza_idx += 1
            continue
            
        # Удаляем теги типа [Припев]
        if line.startswith('[') and line.endswith(']'):
            continue
            
        line_words = line.split()
        for j, w in enumerate(line_words):
            clean_w = clean_word(w)
            if not clean_w: continue
            
            is_last_in_line = (j == len(line_words) - 1)
            
            words.append({
                "word": w,
                "clean_text": clean_w,
                "start": -1.0,
                "end": -1.0,
                "line_break": is_last_in_line,
                "stanza_idx": stanza_idx
            })
            
    return words

def get_vowel_weight(word: str, is_line_end: bool = False) -> float:
    """
    Вычисляет 'вокальный вес' слова.
    Гласные весят больше согласных. Слова в конце строки тянутся дольше.
    """
    vowels = "аеёиоуыэюяaeiouy"
    base_weight = 0.5
    for char in word.lower():
        if char in vowels:
            base_weight += 0.8
        else:
            base_weight += 0.2
            
    if is_line_end:
        base_weight *= 1.5
        
    return base_weight

def get_phonetic_bounds(word: str, is_line_end: bool = False) -> tuple:
    """
    Возвращает (min_duration, max_duration) для слова на основе фонетики.
    """
    weight = get_vowel_weight(word, is_line_end)
    min_dur = max(0.08, weight * 0.15)
    max_dur = weight * 0.8 + 0.5
    return min_dur, max_dur

def calculate_overlap(s1: float, e1: float, intervals: list) -> float:
    """Считает сумму пересечений отрезка [s1, e1] со списком интервалов."""
    if e1 <= s1: return 0.0
    overlap = 0.0
    for i_s, i_e in intervals:
        o_s = max(s1, i_s)
        o_e = min(e1, i_e)
        if o_e > o_s:
            overlap += (o_e - o_s)
    return overlap

def match_sequences(canon_words: list, heard_words: list) -> list:
    """
    Фундамент Идеального Гибрида: Sequence Alignment.
    Берет идеальный текст (Genius) и грязный транскрипт (Whisper),
    и сопоставляет их с помощью расстояния Левенштейна.
    Возвращает список соответствий: [(idx_canon, idx_heard), ...]
    """
    log.info("🧬 [Sequence Matcher] Сопоставление распознанного текста с эталонным...")
    
    canon_text = [w["clean_text"] for w in canon_words]
    heard_text = [w["clean_text"] for w in heard_words]
    
    # Создаем матрицу расстояний (Needleman-Wunsch / Levenshtein)
    # Штрафы: Совпадение = +3, Замена = -1, Вставка/Удаление = -1
    n, m = len(canon_text), len(heard_text)
    
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    
    for i in range(1, n + 1):
        dp[i][0] = -i
    for j in range(1, m + 1):
        dp[0][j] = -j
        
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match_score = rapidfuzz.fuzz.ratio(canon_text[i-1], heard_text[j-1])
            
            # Если слова похожи больше чем на 75% - считаем совпадением
            if match_score >= 75:
                cost = 3
            # Если похожи частично (например "пьяная" и "пья")
            elif match_score >= 50:
                cost = 1
            else:
                cost = -1
                
            dp[i][j] = max(
                dp[i-1][j-1] + cost,      # Замена / Совпадение
                dp[i-1][j] - 1,           # Удаление (слово есть в Genius, но не услышано)
                dp[i][j-1] - 1            # Вставка (Whisper услышал лишнее эхо/бэк)
            )
            
    # Обратный проход (Backtracking) для поиска оптимального пути
    i, j = n, m
    matches = []
    
    while i > 0 and j > 0:
        current_score = dp[i][j]
        
        match_score = rapidfuzz.fuzz.ratio(canon_text[i-1], heard_text[j-1])
        if match_score >= 75:
            cost = 3
        elif match_score >= 50:
            cost = 1
        else:
            cost = -1
            
        if current_score == dp[i-1][j-1] + cost:
            # Нашли пару (даже если частичную)
            if cost >= 1:
                matches.append((i-1, j-1))
            i -= 1
            j -= 1
        elif current_score == dp[i-1][j] - 1:
            i -= 1
        else:
            j -= 1
            
    matches.reverse()
    log.info(f"   🔗 Найдено прямых совпадений: {len(matches)} из {n} эталонных слов.")
    return matches

def get_empirical_data(words: list) -> dict:
    """Анализирует темп песни (Syllable Delivery Rate)."""
    total_dur = 0.0
    total_syllables = 0
    breaths = []
    
    for i, w in enumerate(words):
        if w["start"] != -1.0:
            total_dur += (w["end"] - w["start"])
            total_syllables += len(re.sub(r'[^аеёиоуыэюяaeiouy]', '', w["clean_text"]))
            
        if i > 0 and w["start"] != -1.0 and words[i-1]["end"] != -1.0:
            gap = w["start"] - words[i-1]["end"]
            if w["stanza_idx"] == words[i-1]["stanza_idx"] and 0.1 < gap < 2.0:
                breaths.append(gap)
                
    sdr = total_syllables / total_dur if total_dur > 0 else 0.0
    avg_breath = sum(breaths) / len(breaths) if breaths else 0.5
    
    return {
        "sdr": sdr,
        "avg_breath": avg_breath
    }

def evaluate_alignment_quality(words: list, vad_intervals: list) -> float:
    """Оценивает итоговое качество (0-100) на основе физики (попадание в VAD)."""
    if not words: return 0.0
    
    score = 100.0
    total_words = len(words)
    placed_words = sum(1 for w in words if w["start"] != -1.0)
    
    # Штраф за нераспределенные слова
    if placed_words < total_words:
        score -= ((total_words - placed_words) / total_words) * 50.0
        
    for w in words:
        if w["start"] == -1.0: continue
        
        dur = w["end"] - w["start"]
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        
        # Штраф за физически невозможную длительность
        if dur < 0.05 or dur > max_dur * 2.0:
            score -= 1.0
            
        # Награда/Штраф за попадание в VAD
        overlap = calculate_overlap(w["start"], w["end"], vad_intervals)
        vad_ratio = overlap / dur if dur > 0 else 0
        if vad_ratio < 0.2:
            score -= 2.0
            
    return max(0.0, min(100.0, score))