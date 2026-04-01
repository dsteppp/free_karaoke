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
    """
    Разбирает сырой текст с Genius. Сохраняет флаг конца строки.
    """
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
                "stanza_idx": stanza_idx,
                "locked": False  # V9.0: Флаг жесткого якоря
            })
            
    log.info(f"   ✅ Обработано слов: {len(words)}, Строф: {stanza_idx + 1}")
    return words


# ==============================================================================
# V9.0 G2P & Syllable Estimator (Фонетический анализ)
# ==============================================================================

class SyllableEstimator:
    """Продвинутый анализатор слогов для точного расчета физики слова."""
    
    @staticmethod
    def count_en(word: str) -> int:
        word = word.lower()
        if len(word) <= 3:
            return 1
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

def count_vowels(word: str) -> int:
    """Обертка для обратной совместимости."""
    return SyllableEstimator.estimate(word)

def get_vowel_weight(word: str, is_line_end: bool = False) -> float:
    """Рассчитывает 'фонетический вес' слова на базе реальных слогов."""
    syllables = SyllableEstimator.estimate(word)
    # 1 слог ~ 0.3 сек базового веса
    base_weight = max(0.4, syllables * 0.3)
    if is_line_end:
        base_weight *= 1.5
    return base_weight

def get_phonetic_bounds(word: str, is_line_end: bool = False) -> tuple:
    """Возвращает физиологический предел длительности слова (min_dur, max_dur)."""
    syllables = SyllableEstimator.estimate(word)
    min_dur = max(0.08, syllables * 0.12)  # Не быстрее 120мс на слог
    max_dur = (syllables * 0.7) + (0.5 if is_line_end else 0.2)
    return min_dur, max_dur

def check_sdr_sanity(words: list, start_idx: int, end_idx: int, duration_sec: float, is_same_line: bool = False) -> tuple:
    """SDR-Guard (Syllable Delivery Rate)."""
    if duration_sec <= 0:
        return False, 999.0
        
    if is_same_line and duration_sec > 2.5:
        return False, 0.0

    total_syllables = sum(SyllableEstimator.estimate(words[k]["clean_text"]) for k in range(start_idx, end_idx + 1))
    sdr = total_syllables / duration_sec
    
    # Расширенные пределы для рэпа и мелизмов (0.3 - 9.0 -> 0.2 - 10.0)
    is_sane = (0.2 <= sdr <= 10.0)
    return is_sane, sdr

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


# ==============================================================================
# V9.0 Anomaly Inspector (Детектор болячек для Self-Healing)
# ==============================================================================

class AnomalyInspector:
    """Модуль аудита. Ищет физически невозможные зоны в таймингах."""
    
    @staticmethod
    def scan(words: list, vad_intervals: list) -> list:
        anomalies = []
        n = len(words)
        
        i = 0
        while i < n:
            w = words[i]
            if w["start"] == -1.0 or w["end"] == -1.0:
                i += 1
                continue
                
            dur = w["end"] - w["start"]
            min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
            overlap = calculate_overlap(w["start"], w["end"], vad_intervals)
            vad_ratio = overlap / dur if dur > 0 else 0
            
            # Ищем кластеры ошибок (собираем проблемные слова вместе)
            reason = None
            if vad_ratio < 0.15:
                reason = "VAD_VIOLATION"
            elif dur < min_dur * 0.7:
                reason = "MACHINEGUN"
            elif dur > max_dur * 1.5:
                reason = "RUBBER_WORD"
                
            if reason:
                # Расширяем зону аномалии на соседние слова в той же строке
                start_idx = i
                end_idx = i
                
                # Захват контекста влево
                while start_idx > 0 and not words[start_idx-1]["line_break"] and (words[i]["start"] - words[start_idx-1]["end"]) < 1.0:
                    start_idx -= 1
                    
                # Захват контекста вправо
                while end_idx < n - 1 and not words[end_idx]["line_break"] and (words[end_idx+1]["start"] - words[i]["end"]) < 1.0:
                    end_idx += 1
                    
                anomalies.append({
                    "type": reason,
                    "start_idx": start_idx,
                    "end_idx": end_idx,
                    "t_start": words[start_idx]["start"],
                    "t_end": words[end_idx]["end"]
                })
                i = end_idx + 1 # Прыгаем за пределы найденного кластера
            else:
                i += 1
                
        # Дедупликация пересекающихся зон
        merged = []
        for a in anomalies:
            if not merged:
                merged.append(a)
            else:
                last = merged[-1]
                if a["start_idx"] <= last["end_idx"]:
                    last["end_idx"] = max(last["end_idx"], a["end_idx"])
                    last["t_end"] = max(last["t_end"], a["t_end"])
                    last["type"] = "COMPLEX_ANOMALY"
                else:
                    merged.append(a)
                    
        if merged:
            log.warning(f"   🚨 [Inspector] Найдено аномальных зон: {len(merged)}")
            
        return merged

def evaluate_alignment_quality(words: list, vad_intervals: list) -> float:
    """Оценивает качество таймингов."""
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
        
        if dur < min_dur * 0.7 or dur > max_dur * 1.5:
            score -= 1.0
            physics_violators += 1
            
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