import re
import string
from app_logger import get_logger

log = get_logger("aligner_utils")

def detect_language(text: str) -> str:
    """Определяет доминирующий язык текста для передачи в Whisper."""
    ru_chars = sum(1 for c in text if c.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    en_chars = sum(1 for c in text if c.lower() in string.ascii_lowercase)
    lang = "ru" if ru_chars > en_chars else "en"
    log.debug(f"🔤 [Utils] Язык текста определен как: {lang.upper()}")
    return lang

def clean_word(word: str) -> str:
    """
    Агрессивная очистка слова от пунктуации. 
    Оставляет только буквы и цифры для идеального совпадения в Левенштейне.
    """
    return re.sub(r'[^\w]', '', word.lower())

def prepare_text(raw_lyrics: str) -> list:
    """
    Разбирает сырой текст с Genius.
    Важнейший момент: мы сохраняем флаг line_break (конец строки).
    Позже Фильтр Целостности Строк не позволит разорвать фразу, если line_break = False.
    """
    log.info("📝 [Utils] Подготовка эталонного текста...")
    if not raw_lyrics: 
        return []
    
    words = []
    lines = raw_lyrics.split('\n')
    stanza_idx = 0
    
    for line in lines:
        line = line.strip()
        
        # Разделитель строф (пустая строка)
        if not line:
            stanza_idx += 1
            continue
            
        # Пропускаем мета-теги Genius (например: [Припев], [Куплет 1: Баста])
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
    """Считает количество слогов (гласных) в слове для оценки SDR."""
    vowels = "аеёиоуыэюяaeiouy"
    return sum(1 for char in word.lower() if char in vowels)

def check_sdr_sanity(words: list, start_idx: int, end_idx: int, duration_sec: float) -> tuple:
    """
    SDR-Guard (Syllable Delivery Rate).
    Проверяет, реально ли человеку спеть указанные слова за указанное время.
    Возвращает (is_sane: bool, sdr_value: float).
    """
    if duration_sec <= 0:
        return False, 999.0
        
    total_syllables = 0
    for k in range(start_idx, end_idx + 1):
        # Если слово состоит только из согласных (например, "б", "в"), считаем как 1 слог
        syllables = max(1, count_vowels(words[k]["clean_text"]))
        total_syllables += syllables
        
    sdr = total_syllables / duration_sec
    
    # Физические пределы человека:
    # Меньше 0.3 слога в секунду - это неестественное растягивание (1 слово на 10 секунд).
    # Больше 8.0 слогов в секунду - это пулеметный рэп Эминема. Больше 9 - физически невозможно.
    is_sane = (0.3 <= sdr <= 9.0)
    
    return is_sane, sdr

def get_vowel_weight(word: str, is_line_end: bool = False) -> float:
    """
    Рассчитывает "фонетический вес" слова для Фонетической Заливки.
    Гласные буквы тянутся дольше, чем согласные. Слово в конце строки тянется дольше.
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
    Возвращает физиологический предел длительности слова (min_dur, max_dur).
    Защищает от растягивания коротких слов на 5 секунд.
    """
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

def evaluate_alignment_quality(words: list, vad_intervals: list) -> float:
    """
    Жесткая проверка итогового качества таймингов.
    Выявляет слова, которые повисли в пустоте или имеют невозможную длину.
    В лог выводится поимённый список нарушителей.
    """
    log.info("📊 [QA Evaluator] Анализ итогового качества таймингов...")
    if not words: 
        return 0.0
        
    score = 100.0
    total_words = len(words)
    placed_words = sum(1 for w in words if w["start"] != -1.0)
    
    if placed_words < total_words:
        penalty = ((total_words - placed_words) / total_words) * 50.0
        score -= penalty
        log.warning(f"   📉 Штраф за нераспределенные слова: -{penalty:.1f} (Не найдено: {total_words - placed_words})")
        
    physics_violators = []
    vad_violators = []
        
    for w in words:
        if w["start"] == -1.0: 
            continue
            
        dur = w["end"] - w["start"]
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        
        # 1. Проверка физики слова (очень короткое или тянется как резина)
        if dur < 0.05 or dur > max_dur * 2.0:
            score -= 1.0
            physics_violators.append(f"'{w['word']}' ({dur:.2f}s, max: {max_dur*2:.2f}s)")
            
        # 2. Проверка попадания в VAD (Не поет ли певец в абсолютной тишине?)
        overlap = calculate_overlap(w["start"], w["end"], vad_intervals)
        vad_ratio = overlap / dur if dur > 0 else 0
        
        # Если слово больше чем на 80% висит в тишине - штрафуем
        if vad_ratio < 0.2:
            score -= 2.0
            vad_violators.append(f"'{w['word']}' (VAD: {vad_ratio*100:.0f}%, {w['start']:.2f}s-{w['end']:.2f}s)")
            
    if physics_violators:
        log.warning(f"   📉 Нарушение физики длительностей ({len(physics_violators)} слов): {', '.join(physics_violators[:5])}...")
    if vad_violators:
        log.warning(f"   📉 Слова висят вне VAD ({len(vad_violators)} слов): {', '.join(vad_violators[:5])}...")
            
    final_score = max(0.0, min(100.0, score))
    log.info(f"   🏆 Оценка: {final_score:.1f}/100")
    return final_score