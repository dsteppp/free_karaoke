import re
import string
from app_logger import get_logger

log = get_logger("aligner_utils")

def detect_language(text: str) -> str:
    ru_chars = sum(1 for c in text if c.lower() in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя")
    en_chars = sum(1 for c in text if c.lower() in string.ascii_lowercase)
    lang = "ru" if ru_chars > en_chars else "en"
    log.info(f"🔤 [Utils] Язык текста: {lang.upper()}")
    return lang

def clean_word(word: str) -> str:
    return re.sub(r'[^\w]', '', word.lower())

def prepare_text(raw_lyrics: str) -> list:
    log.info("📝 [Utils] Подготовка эталонного текста...")
    if not raw_lyrics: return []
    
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
            
    log.info(f"   ✅ Обработано слов: {len(words)}, Строф: {stanza_idx + 1}")
    return words

def count_vowels(word: str) -> int:
    vowels = "аеёиоуыэюяaeiouy"
    return sum(1 for char in word.lower() if char in vowels)

def extract_rhythm_dna(words: list) -> dict:
    """
    V8.6: Анализирует подтвержденные якоря и извлекает физический ритм певца.
    Возвращает словарь с базовыми константами.
    """
    dna = {"velocity": 0.25, "micro_gap": 0.1, "macro_gap": 1.2}
    
    valid_words = [w for w in words if w["start"] != -1.0]
    if len(valid_words) < 5:
        log.warning("   ⚠️ Недостаточно якорей для анализа ритма. Используем стандартную ДНК.")
        return dna

    # 1. Скорость гласной (Velocity)
    total_vowels = sum(max(1, count_vowels(w["clean_text"])) for w in valid_words)
    total_dur = sum(w["end"] - w["start"] for w in valid_words)
    if total_vowels > 0:
        dna["velocity"] = min(max(0.1, total_dur / total_vowels), 0.5)

    # 2. Анализ пауз (Gaps)
    micro_gaps = []
    macro_gaps = []
    
    for i in range(len(words) - 1):
        w1 = words[i]
        w2 = words[i+1]
        
        if w1["start"] != -1.0 and w2["start"] != -1.0:
            gap = w2["start"] - w1["end"]
            if gap >= 0:
                if w1["line_break"]:
                    if gap < 4.0:  # Игнорируем длинные проигрыши (соло)
                        macro_gaps.append(gap)
                else:
                    if gap < 1.0:  # Игнорируем разорванные галлюцинациями строки
                        micro_gaps.append(gap)

    if micro_gaps:
        dna["micro_gap"] = min(max(0.05, sum(micro_gaps) / len(micro_gaps)), 0.3)
    if macro_gaps:
        dna["macro_gap"] = min(max(0.4, sum(macro_gaps) / len(macro_gaps)), 2.5)

    log.info(f"🧬 [Rhythm DNA] Извлечен ритм трека:")
    log.info(f"   ┣ Скорость слога: {dna['velocity']:.2f}s")
    log.info(f"   ┣ Внутристрочная пауза (Micro): {dna['micro_gap']:.2f}s")
    log.info(f"   ┗ Межстрочная пауза (Macro): {dna['macro_gap']:.2f}s")
    
    return dna

def get_vowel_weight(word: str, is_line_end: bool = False) -> float:
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
    weight = get_vowel_weight(word, is_line_end)
    min_dur = max(0.05, weight * 0.15)
    max_dur = weight * 0.8 + 0.5
    return min_dur, max_dur

def calculate_word_duration(word: str, dna: dict, is_line_end: bool = False) -> float:
    """V8.6: Вычисляет идеальную длину слова на основе ДНК трека."""
    vowel_count = max(1, count_vowels(word))
    dur = vowel_count * dna["velocity"]
    if is_line_end:
        dur *= 1.2  # В конце строки слова часто слегка тянутся
    return dur

def check_sdr_sanity(words: list, start_idx: int, end_idx: int, duration_sec: float, is_same_line: bool = False) -> tuple:
    if duration_sec <= 0: return False, 999.0
    if is_same_line and duration_sec > 2.5: return False, 0.0
    total_syllables = sum(max(1, count_vowels(words[k]["clean_text"])) for k in range(start_idx, end_idx + 1))
    sdr = total_syllables / duration_sec
    is_sane = (0.3 <= sdr <= 9.0)
    return is_sane, sdr

def calculate_overlap(s1: float, e1: float, intervals: list) -> float:
    if e1 <= s1 or not intervals: return 0.0
    overlap = 0.0
    for i_s, i_e in intervals:
        o_s = max(s1, i_s)
        o_e = min(e1, i_e)
        if o_e > o_s: overlap += (o_e - o_s)
    return overlap

def evaluate_alignment_quality(words: list, vad_intervals: list) -> float:
    log.info("📊 [QA Evaluator] Анализ итогового качества таймингов...")
    if not words: return 0.0
        
    score = 100.0
    total_words = len(words)
    placed_words = sum(1 for w in words if w["start"] != -1.0)
    
    if placed_words < total_words:
        penalty = ((total_words - placed_words) / total_words) * 50.0
        score -= penalty
        log.warning(f"   📉 Штраф: Нераспределено слов: {total_words - placed_words}")
        
    physics_violators = 0
        
    for w in words:
        if w["start"] == -1.0: continue
        dur = w["end"] - w["start"]
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        if dur < 0.05 or dur > max_dur * 2.0:
            score -= 1.0
            physics_violators += 1
            
    if physics_violators > 0:
        log.warning(f"   📉 Нарушение физики (Резина/Пулемет): {physics_violators} слов.")
            
    final_score = max(0.0, min(100.0, score))
    log.info(f"   🏆 Итоговая Оценка: {final_score:.1f}/100")
    return final_score