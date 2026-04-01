import re
import string
from app_logger import get_logger

log = get_logger("aligner_utils")

def detect_language(text: str) -> str:
    """Определяет доминирующий язык текста для Whisper."""
    ru_chars = sum(1 for c in text if c.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    en_chars = sum(1 for c in text if c.lower() in string.ascii_lowercase)
    lang = "ru" if ru_chars > en_chars else "en"
    log.info(f"🔤 [Utils] Доминирующий язык: {lang.upper()}")
    return lang

def clean_word(word: str) -> str:
    """Очистка для идеального совпадения в матрице (только алфавит)."""
    return re.sub(r'[^\w]', '', word.lower())

# ==============================================================================
# V10.0 Syllable Estimator (Жесткая физика)
# ==============================================================================
class SyllableEstimator:
    """Модуль мгновенной оценки физической длительности слова на основе слогов."""
    
    @staticmethod
    def count_en(word: str) -> int:
        word = word.lower()
        if len(word) <= 3: return 1
        word = re.sub(r'(?:[^laeiouy]es|ed|[^laeiouy]e)$', '', word)
        word = re.sub(r'^y', '', word)
        syllables = len(re.findall(r'[aeiouy]{1,2}', word))
        return max(1, syllables)

    @staticmethod
    def count_ru(word: str) -> int:
        vowels = "аеёиоуыэюя"
        return sum(1 for char in word.lower() if char in vowels)

    @classmethod
    def estimate(cls, word: str) -> int:
        ru_chars = sum(1 for c in word.lower() if c in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
        return cls.count_ru(word) if ru_chars > 0 else cls.count_en(word)

def get_phonetic_bounds(syllables: int, is_line_end: bool = False) -> tuple:
    """
    Возвращает железные рамки длительности (мин, макс).
    Слово не может звучать быстрее или медленнее этих лимитов.
    """
    # Человек не может произнести слог быстрее 80мс
    min_dur = max(0.08, syllables * 0.12)
    # Медленнее 800мс на слог - это уже вой, а не пение (кроме концов строк)
    max_dur = (syllables * 0.8) + (0.8 if is_line_end else 0.3)
    return min_dur, max_dur

def check_sdr_sanity(total_syllables: int, duration_sec: float, is_same_line: bool = False) -> bool:
    """
    V10: O(1) SDR-Guard. Защита от пулеметных очередей в DP-матрице.
    """
    if duration_sec <= 0: return False
    if is_same_line and duration_sec > 2.5: return False
    sdr = total_syllables / duration_sec
    return (0.2 <= sdr <= 10.0)

# ==============================================================================
# V10.0 Text Preparation (Атомарность строк)
# ==============================================================================
def prepare_text(raw_lyrics: str) -> list:
    """
    Парсит текст и внедряет line_idx. 
    В V10 строка (line) — это неделимый монолит. Алгоритм не имеет права её рвать.
    """
    log.info("📝 [Utils] Подготовка эталонного текста (V10 Atomic Lines)...")
    if not raw_lyrics: 
        return []
    
    words = []
    lines = raw_lyrics.split('\n')
    line_idx = 0
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('[') and line.endswith(']'):
            continue
            
        line_words = line.split()
        for j, w in enumerate(line_words):
            clean_w = clean_word(w)
            if not clean_w: 
                continue
            
            is_last_in_line = (j == len(line_words) - 1)
            sylls = SyllableEstimator.estimate(clean_w)
            min_dur, max_dur = get_phonetic_bounds(sylls, is_last_in_line)
            
            words.append({
                "word": w,
                "clean_text": clean_w,
                "start": -1.0,
                "end": -1.0,
                "line_idx": line_idx,          # V10: Идентификатор строки
                "line_break": is_last_in_line,
                "syllables": sylls,
                "min_dur": min_dur,
                "max_dur": max_dur,
                "is_anchor": False             # V10: Флаг подтвержденного якоря
            })
            
        line_idx += 1
            
    log.info(f"   ✅ Загружено слов: {len(words)}, Неделимых строк: {line_idx}")
    return words

# ==============================================================================
# V10.0 QA Logic
# ==============================================================================
def calculate_overlap(s1: float, e1: float, intervals: list) -> float:
    """Быстрый расчет перекрытия отрезка с VAD-островами."""
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
    """Строгая и тихая оценка итогового результата без лишнего спама."""
    if not words: return 0.0
    
    score = 100.0
    total = len(words)
    placed = sum(1 for w in words if w["start"] != -1.0)
    
    if placed < total:
        score -= ((total - placed) / total) * 50.0
        log.warning(f"   📉 QA: {total - placed} слов не получили таймингов.")
        
    physics_err = 0
    vad_err = 0
    time_travel = 0
    
    prev_end = -1.0
    for w in words:
        s, e = w["start"], w["end"]
        if s == -1.0: continue
            
        dur = e - s
        
        # 1. Монотонность (Машина времени)
        if s < prev_end - 0.05: # Допуск 50мс на микро-нахлесты
            time_travel += 1
            score -= 2.0
            
        # 2. Физика слова
        if dur < w["min_dur"] * 0.8 or dur > w["max_dur"] * 1.5:
            physics_err += 1
            score -= 0.5
            
        # 3. Висение в тишине
        overlap = calculate_overlap(s, e, vad_intervals)
        if dur > 0 and (overlap / dur) < 0.15:
            vad_err += 1
            score -= 1.0
            
        prev_end = e
            
    if physics_err > 0: log.debug(f"   ⚠️ QA: Нарушена физика слова (сжато/растянуто) - {physics_err} шт.")
    if vad_err > 0: log.debug(f"   ⚠️ QA: Слово вне VAD (в тишине) - {vad_err} шт.")
    if time_travel > 0: log.warning(f"   🚨 QA: НАРУШЕНА ЛИНЕЙНОСТЬ ВРЕМЕНИ (Time Travel) - {time_travel} шт.")
        
    final_score = max(0.0, min(100.0, score))
    log.info(f"   🏆 V10 QA Score: {final_score:.1f}/100")
    return final_score