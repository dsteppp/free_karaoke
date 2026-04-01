import re
import string
from app_logger import get_logger

log = get_logger("aligner_utils")

def detect_language(text: str) -> str:
    """Определяет доминирующий язык текста."""
    ru_chars = sum(1 for c in text if c.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    en_chars = sum(1 for c in text if c.lower() in string.ascii_lowercase)
    lang = "ru" if ru_chars > en_chars else "en"
    log.info(f"🔤 [Utils] Язык текста: {lang.upper()}")
    return lang

def clean_word(word: str) -> str:
    """Оставляет только буквы и цифры для идеального совпадения в Левенштейне."""
    return re.sub(r'[^\w]', '', word.lower())

def prepare_text(raw_lyrics: str) -> list:
    """Разбирает сырой текст с Genius. Сохраняет флаг конца строки."""
    log.info("📝 [Utils] Подготовка эталонного текста...")
    if not raw_lyrics: 
        return []
    
    words = []
    lines = raw_lyrics.split('\n')
    stanza_idx = 0
    
    for line in lines:
        line = line.strip()
        
        if not line:
            stanza_idx += 1
            continue
            
        if line.startswith('[') and line.endswith(']'):
            continue
            
        line_words = line.split()
        for j, w in enumerate(line_words):
            clean_w = clean_word(w)
            if not clean_w: 
                continue
            
            is_last_in_line = (j == len(line_words) - 1)
            
            words.append({
                "word": w,
                "clean_text": clean_w,
                "start": -1.0,
                "end": -1.0,
                "line_break": is_last_in_line,
                "stanza_idx": stanza_idx
            })
            
    log.info(f"   ✅ Обработано слов: {len(words)}, Строф: {stanza_idx + 1}")
    return words

def count_vowels(word: str) -> int:
    """Считает количество слогов (гласных) в слове."""
    vowels = "аеёиоуыэюяaeiouy"
    return sum(1 for char in word.lower() if char in vowels)

def check_sdr_sanity(words: list, start_idx: int, end_idx: int, duration_sec: float, is_same_line: bool = False) -> tuple:
    """
    SDR-Guard (Syllable Delivery Rate) v8.5.
    Проверяет, реально ли человеку спеть указанные слова за указанное время.
    """
    if duration_sec <= 0:
        return False, 999.0
        
    # Защита от разрыва одной строки огромной паузой
    if is_same_line and duration_sec > 2.5:
        return False, 0.0

    total_syllables = sum(max(1, count_vowels(words[k]["clean_text"])) for k in range(start_idx, end_idx + 1))
    sdr = total_syllables / duration_sec
    
    # 0.3 слога/сек - слишком медленно, 9.0 слогов/сек - физический предел человека
    is_sane = (0.3 <= sdr <= 9.0)
    
    return is_sane, sdr

def get_vowel_weight(word: str, is_line_end: bool = False) -> float:
    """Рассчитывает 'фонетический вес' слова."""
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
    """Возвращает физиологический предел длительности слова (min_dur, max_dur)."""
    weight = get_vowel_weight(word, is_line_end)
    min_dur = max(0.05, weight * 0.15)
    max_dur = weight * 0.8 + 0.5
    return min_dur, max_dur

def calculate_overlap(s1: float, e1: float, intervals: list) -> float:
    """Считает суммарное время пересечения отрезка [s1, e1] с физическими VAD-интервалами."""
    if e1 <= s1 or not intervals: 
        return 0.0
        
    overlap = 0.0
    for i_s, i_e in intervals:
        o_s = max(s1, i_s)
        o_e = min(e1, i_e)
        if o_e > o_s:
            overlap += (o_e - o_s)
    return overlap

def calculate_line_breaks_pause(words: list, start_idx: int, end_idx: int) -> float:
    """
    V8.5: Вычисляет, сколько времени нужно заложить на паузы между строками.
    (Для решения проблемы трека 'Непроизошло' на 2:22).
    Возвращает суммарную длительность пауз в секундах.
    """
    line_breaks_count = 0
    for k in range(start_idx, end_idx):
        if words[k]["line_break"]:
            line_breaks_count += 1
            
    # За каждую смену строки закладываем 0.4 секунды паузы на вдох
    return line_breaks_count * 0.4

def evaluate_alignment_quality(words: list, vad_intervals: list) -> float:
    """Оценивает качество таймингов. Выдает сухую статистику."""
    log.info("📊 [QA Evaluator] Анализ итогового качества таймингов...")
    if not words: 
        return 0.0
        
    score = 100.0
    total_words = len(words)
    placed_words = sum(1 for w in words if w["start"] != -1.0)
    
    if placed_words < total_words:
        penalty = ((total_words - placed_words) / total_words) * 50.0
        score -= penalty
        log.warning(f"   📉 Штраф: Нераспределено слов: {total_words - placed_words}")
        
    physics_violators = 0
    vad_violators = 0
        
    for w in words:
        if w["start"] == -1.0: 
            continue
            
        dur = w["end"] - w["start"]
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        
        # 1. Проверка физики (слишком быстро/медленно)
        if dur < 0.05 or dur > max_dur * 2.0:
            score -= 1.0
            physics_violators += 1
            
        # 2. Проверка тишины
        overlap = calculate_overlap(w["start"], w["end"], vad_intervals)
        vad_ratio = overlap / dur if dur > 0 else 0
        if vad_ratio < 0.2:
            score -= 2.0
            vad_violators += 1
            
    if physics_violators > 0:
        log.warning(f"   📉 Нарушение физики (Резина/Пулемет): {physics_violators} слов.")
    if vad_violators > 0:
        log.warning(f"   📉 Слова висят вне VAD (В тишине): {vad_violators} слов.")
            
    final_score = max(0.0, min(100.0, score))
    log.info(f"   🏆 Итоговая Оценка: {final_score:.1f}/100")
    return final_score