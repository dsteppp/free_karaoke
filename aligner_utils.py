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
    Позже Фильтр №4 (Целостность строк) не позволит разорвать фразу, если line_break = False.
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
    Защищает от растягивания слова "да" на 5 секунд.
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

def extract_motif_rhythm(words: list, start_idx: int, end_idx: int) -> dict:
    """
    ФИЛЬТР №3: Извлечение ритмического слепка (для повторяющихся строк).
    Считает относительные длительности каждого слова во фразе.
    """
    log.debug(f"   🧬 [Motif] Извлечение ритма из фразы [{start_idx}:{end_idx}]")
    
    total_dur = words[end_idx]["end"] - words[start_idx]["start"]
    if total_dur <= 0:
        return None
        
    ratios = []
    for k in range(start_idx, end_idx + 1):
        w_dur = words[k]["end"] - words[k]["start"]
        ratios.append({
            "word_ratio": w_dur / total_dur,
            # Смещение от начала фразы
            "start_offset_ratio": (words[k]["start"] - words[start_idx]["start"]) / total_dur 
        })
        
    return {"total_dur": total_dur, "ratios": ratios}

def apply_motif_rhythm(words: list, start_idx: int, end_idx: int, motif: dict, target_start: float, target_end: float):
    """
    ФИЛЬТР №3: Применение ритмического слепка к "слепой" зоне.
    Наклонирует тайминги из уже спетой строчки на нераспознанную.
    """
    window_dur = target_end - target_start
    # Масштабируем: если окно больше оригинального мотива, растягиваем, если меньше - сжимаем
    scale = window_dur / motif["total_dur"] 
    # Ограничиваем сильное растяжение/сжатие
    scale = max(0.8, min(scale, 1.2)) 
    
    actual_dur = motif["total_dur"] * scale
    
    # Центрируем мотив в доступном окне
    offset = target_start + (window_dur - actual_dur) / 2
    
    log.debug(f"   🧬 [Motif] Клонирование ритма в окно {target_start:.2f}s - {target_end:.2f}s (Масштаб: x{scale:.2f})")
    
    ratios = motif["ratios"]
    for i, k in enumerate(range(start_idx, end_idx + 1)):
        w = words[k]
        w["start"] = offset + (ratios[i]["start_offset_ratio"] * actual_dur)
        w["end"] = w["start"] + (ratios[i]["word_ratio"] * actual_dur)

def evaluate_alignment_quality(words: list, vad_intervals: list) -> float:
    """
    Жесткая проверка итогового качества таймингов.
    Выявляет слова, которые повисли в пустоте или имеют невозможную длину.
    """
    if not words: 
        return 0.0
        
    score = 100.0
    total_words = len(words)
    placed_words = sum(1 for w in words if w["start"] != -1.0)
    
    if placed_words < total_words:
        penalty = ((total_words - placed_words) / total_words) * 50.0
        score -= penalty
        log.warning(f"   📉 [QA] Штраф за нераспределенные слова: -{penalty:.1f} (Не найдено: {total_words - placed_words})")
        
    physics_penalties = 0
    vad_penalties = 0
        
    for w in words:
        if w["start"] == -1.0: 
            continue
            
        dur = w["end"] - w["start"]
        min_dur, max_dur = get_phonetic_bounds(w["clean_text"], w["line_break"])
        
        # 1. Проверка физики слова (очень короткое или тянется как резина)
        if dur < 0.05 or dur > max_dur * 2.0:
            score -= 1.0
            physics_penalties += 1
            
        # 2. Проверка попадания в VAD (Не поет ли певец в абсолютной тишине?)
        overlap = calculate_overlap(w["start"], w["end"], vad_intervals)
        vad_ratio = overlap / dur if dur > 0 else 0
        
        # Если слово больше чем на 80% висит в тишине - штрафуем
        if vad_ratio < 0.2:
            score -= 2.0
            vad_penalties += 1
            
    if physics_penalties > 0:
        log.warning(f"   📉 [QA] Нарушение физики длительностей: {physics_penalties} слов (-{physics_penalties:.1f} баллов).")
    if vad_penalties > 0:
        log.warning(f"   📉 [QA] Слова висят в тишине (Вне VAD): {vad_penalties} слов (-{vad_penalties * 2.0:.1f} баллов).")
            
    return max(0.0, min(100.0, score))