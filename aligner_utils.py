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
    Позже Фильтр Целостности Строк не позволит разорвать фразу паузой в 5 секунд.
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

def check_sdr_sanity(words: list, start_idx: int, end_idx: int, duration_sec: float, is_same_line: bool = False) -> tuple:
    """
    SDR-Guard (Syllable Delivery Rate) v8.3.
    Проверяет, реально ли человеку спеть указанные слова за указанное время.
    """
    if duration_sec <= 0:
        return False, 999.0
        
    # V8.3 INTRO-GUARD: Жесткая проверка пауз внутри одной строки.
    # Если это соседние слова в одной фразе, между ними не может быть паузы 4 секунды (Галлюцинация)
    if is_same_line and duration_sec > 2.5:
        log.debug(f"         🚫 [SDR-Guard] Убит ложный якорь: Пауза {duration_sec:.2f}s внутри одной строки недопустима!")
        return False, 0.0

    total_syllables = 0
    for k in range(start_idx, end_idx + 1):
        syllables = max(1, count_vowels(words[k]["clean_text"]))
        total_syllables += syllables
        
    sdr = total_syllables / duration_sec
    
    # Физические пределы человека:
    # Меньше 0.3 слога в секунду - это неестественное растягивание.
    # Больше 8.0 слогов в секунду - это пулеметный рэп Эминема.
    is_sane = (0.3 <= sdr <= 9.0)
    
    if not is_sane:
        log.debug(f"         🚫 [SDR-Guard] Убит ложный якорь: Аномальная скорость {sdr:.1f} слогов/сек (Время: {duration_sec:.2f}s)")
    
    return is_sane, sdr

def get_vowel_weight(word: str, is_line_end: bool = False) -> float:
    """
    Рассчитывает "фонетический вес" слова.
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

def calculate_phonetic_duration(words: list, start_idx: int, end_idx: int) -> float:
    """
    V8.3 Фонетический калькулятор.
    Вычисляет среднее физическое время, необходимое певцу для произнесения группы слов.
    Используется для правосторонней сборки (Right-Aligned Packing).
    """
    needed_dur = 0.0
    for k in range(start_idx, end_idx):
        min_p, max_p = get_phonetic_bounds(words[k]["clean_text"], words[k]["line_break"])
        # Берем среднее между минимально возможной и максимально возможной длиной слова
        needed_dur += (min_p + max_p) / 2
    return needed_dur

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
    В лог выводится поимённый список нарушителей с точными цифрами.
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
            physics_violators.append(f"'{w['word']}' [{w['start']:.2f}s-{w['end']:.2f}s] (Длина: {dur:.2f}s, Лимит: {max_dur*2:.2f}s)")
            
        # 2. Проверка попадания в VAD (Не поет ли певец в абсолютной тишине?)
        overlap = calculate_overlap(w["start"], w["end"], vad_intervals)
        vad_ratio = overlap / dur if dur > 0 else 0
        
        # Если слово больше чем на 80% висит в тишине - штрафуем
        if vad_ratio < 0.2:
            score -= 2.0
            vad_violators.append(f"'{w['word']}' [{w['start']:.2f}s-{w['end']:.2f}s] (В голосе: {vad_ratio*100:.0f}%)")
            
    if physics_violators:
        log.warning(f"   📉 Нарушение физики (Резина/Пулемет) ({len(physics_violators)} слов): {', '.join(physics_violators[:5])}...")
    if vad_violators:
        log.warning(f"   📉 Слова висят вне VAD (В тишине) ({len(vad_violators)} слов): {', '.join(vad_violators[:5])}...")
            
    final_score = max(0.0, min(100.0, score))
    log.info(f"   🏆 Итоговая Оценка Физического Совпадения: {final_score:.1f}/100")
    return final_score