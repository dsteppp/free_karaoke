import librosa
import numpy as np
from app_logger import get_logger

log = get_logger("aligner_acoustics")

# ─── V6.3: ACOUSTIC PHYSICS & THE IRON CURTAIN ───────────────────────────────

def vocal_sniper(audio_data: np.ndarray, sr: int) -> np.ndarray:
    """
    Safe Source (Read-Only). Мы не вырезаем звук физически из массива, 
    чтобы Whisper имел полный акустический контекст на этапе Слепого Оракула.
    """
    log.info("🎯 [Vocal Sniper] Режим Safe Source. Оригинал сохранен.")
    return audio_data


def build_iron_curtain(audio_data: np.ndarray, sr: int) -> list:
    """
    V6.3: The Great Void + Musical Voids.
    Возводит Железные Занавесы на участках абсолютной тишины 
    и длинных негармонических проигрышах (барабанные соло/шум).
    """
    log.info("🛡️ [Iron Curtain] Возведение Железных Занавесов (Тишина + Шум)...")
    hop_length = 512
    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length)[0]
    
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
    
    # Динамический уровень шума трека (5-й перцентиль)
    noise_floor = np.percentile(rms, 5)
    thresh_silence = max(10 ** (-60 / 20), noise_floor * 1.2)
    
    # 1. Абсолютная пустота
    is_silent = rms < thresh_silence
    
    # 2. Музыкальные ямы (Громко, но flatness > 0.1 -> Шум/Ударные/Отсутствие тональности)
    is_noisy = (rms >= thresh_silence) & (flatness > 0.1)

    curtains = []
    
    def extract_intervals(mask, min_dur):
        intervals = []
        in_zone = False
        start_t = 0.0
        for i, active in enumerate(mask):
            if active and not in_zone:
                in_zone = True
                start_t = times[i]
            elif not active and in_zone:
                in_zone = False
                end_t = times[i]
                if end_t - start_t >= min_dur:
                    intervals.append((start_t, end_t))
        if in_zone:
            end_t = times[-1]
            if end_t - start_t >= min_dur:
                intervals.append((start_t, end_t))
        return intervals

    # Тишина дольше 3.0 секунд (The Great Void)
    silence_intervals = extract_intervals(is_silent, min_dur=3.0)
    for s, e in silence_intervals:
        curtains.append((s, e))
        log.info(f"   🧱 Железный Занавес (Мертвая Зона): {s:.2f}s - {e:.2f}s")
        
    # Шум/Барабаны дольше 3.5 секунд (Защита Интро и Аутро)
    noise_intervals = extract_intervals(is_noisy, min_dur=3.5)
    for s, e in noise_intervals:
        curtains.append((s, e))
        log.info(f"   🧱 Железный Занавес (Слепой Шум): {s:.2f}s - {e:.2f}s")

    # Слияние пересекающихся занавесов
    if not curtains:
        return []
        
    curtains.sort(key=lambda x: x[0])
    merged = [curtains[0]]
    for curr in curtains[1:]:
        last = merged[-1]
        if curr[0] <= last[1] + 0.1: 
            merged[-1] = (last[0], max(last[1], curr[1]))
        else:
            merged.append(curr)
            
    return merged


def purge_vad(vad_mask: list, curtains: list) -> list:
    """
    V6.3: THE PURGE (Великая Зачистка).
    Хирургическое удаление любых кусков VAD, попавших внутрь Железного Занавеса.
    """
    if not curtains or not vad_mask:
        return vad_mask
        
    purged_vad = []
    for vs, ve in vad_mask:
        curr_s = vs
        for cs, ce in curtains:
            if ce <= curr_s: continue
            if cs >= ve: break
            
            if curr_s < cs:
                purged_vad.append((curr_s, cs))
            curr_s = max(curr_s, ce)
            
        if curr_s < ve:
            purged_vad.append((curr_s, ve))
            
    return purged_vad


def enforce_curtains(start: float, end: float, curtains: list) -> tuple:
    """
    V6.3: Bulldozer. Физически выталкивает тайминги слов из Мертвых Зон.
    """
    dur = end - start
    for c_s, c_e in curtains:
        # Слово полностью поглощено занавесом -> Выкидываем вправо
        if start >= c_s and end <= c_e:
            start = c_e + 0.01
            end = start + dur
        # Наезд слева -> обрубаем хвост
        elif start < c_s and end > c_s:
            end = c_s - 0.01
            if end <= start: end = start + 0.05
        # Наезд справа -> двигаем старт
        elif start < c_e and end > c_e:
            start = c_e + 0.01
            if end <= start: end = start + 0.05
            
    return start, end


def get_acoustic_maps(audio_data: np.ndarray, sr: int, curtains: list = None) -> tuple:
    """
    V6.3: Генерация Гармонической Вокальной Карты + Спектральная Фильтрация.
    Возвращает: strong_vad, weak_vad, onsets, is_harmonic_fn
    """
    log.info("🗺️ [Orchestra] Генерация акустической топографии (Гармонический VAD)...")
    hop_length = 512
    times = librosa.frames_to_time(np.arange(len(audio_data)//hop_length + 1), sr=sr, hop_length=hop_length)

    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    rms_norm = rms / (np.max(rms) + 1e-8)
    flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length)[0]
    
    # Строгий VAD: Высокая громкость + Наличие четкой тональности (flatness < 0.1)
    strong_vad_frames = (rms_norm > 0.02) & (flatness < 0.1)
    
    # Слабый VAD: Дыхание, шипящие (могут быть шумными, поэтому flatness не проверяем)
    weak_vad_frames = (rms_norm > 0.005) & (rms_norm <= 0.02)
    
    def frames_to_intervals(frames_mask, pad=0.0):
        intervals = []
        in_zone = False
        s_t = 0.0
        for t, is_active in zip(times[:len(frames_mask)], frames_mask):
            if is_active and not in_zone:
                s_t, in_zone = t, True
            elif not is_active and in_zone:
                intervals.append((max(0, s_t - pad), t + pad))
                in_zone = False
        if in_zone: 
            intervals.append((max(0, s_t - pad), times[-1] + pad))
        return intervals

    raw_strong = frames_to_intervals(strong_vad_frames, pad=0.15)
    raw_weak = frames_to_intervals(weak_vad_frames, pad=0.1)

    def merge_intervals(intervals, gap):
        merged = []
        for s, e in intervals:
            if not merged: merged.append((s, e))
            else:
                last_s, last_e = merged[-1]
                if s - last_e < gap: merged[-1] = (last_s, max(last_e, e))
                else: merged.append((s, e))
        return merged

    strong_vad_mask = merge_intervals(raw_strong, 0.4)
    weak_vad_mask = merge_intervals(raw_weak, 0.2)

    # Применяем THE PURGE: Вокал внутри Занавесов — это ложь (барабаны). Вырезаем!
    if curtains:
        strong_vad_mask = purge_vad(strong_vad_mask, curtains)
        weak_vad_mask = purge_vad(weak_vad_mask, curtains)
        log.info("   🔪 [The Purge] VAD-карты очищены от Мертвых Зон.")

    o_env = librosa.onset.onset_strength(y=audio_data, sr=sr)
    raw_onsets = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, units='time')
    
    # Onsets берем только там, где есть подтвержденный голос
    onsets = [o_t for o_t in raw_onsets if any(vs <= o_t <= ve for (vs, ve) in strong_vad_mask) or 
                                           any(ws <= o_t <= we for (ws, we) in weak_vad_mask)]

    def is_harmonic(t_start, t_end):
        s_frame = librosa.time_to_frames(t_start, sr=sr, hop_length=hop_length)
        e_frame = librosa.time_to_frames(t_end, sr=sr, hop_length=hop_length)
        if s_frame >= e_frame or s_frame >= len(flatness): return False
        return np.median(flatness[s_frame:e_frame]) < 0.08

    return strong_vad_mask, weak_vad_mask, onsets, is_harmonic

def apply_vad_deafness(crop_audio: np.ndarray, sr: int, t_start: float, vad_mask: list) -> np.ndarray:
    """Функция отключена. Заглушка для совместимости."""
    return crop_audio