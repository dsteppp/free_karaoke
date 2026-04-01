import librosa
import numpy as np
from app_logger import get_logger

# 🛠️ Единый логгер для всей симфонии
log = get_logger("aligner")

# ─── V6.2: TRUE VOCAL CANVAS & VOID INTEGRITY ───────────────────────────────────

def enforce_curtains(start: float, end: float, curtains: list) -> tuple:
    """
    V6.2: Строгая изоляция Мертвых Зон.
    Выталкивает тайминги из Железного Занавеса (Instrumental Void).
    """
    for c_s, c_e in curtains:
        # Если слово полностью внутри занавеса - выталкиваем вправо (Бульдозер)
        if start >= c_s and end <= c_e:
            dur = end - start
            start = c_e + 0.01
            end = start + dur
        # Если слово налезает на занавес слева
        elif start < c_s and end > c_s: 
            end = c_s - 0.01
        # Если слово налезает на занавес справа
        elif start < c_e and end > c_e: 
            start = c_e + 0.01
            
    return start, max(start + 0.05, end)

def get_acoustic_maps(audio_data: np.ndarray, sr: int) -> tuple:
    """
    V6.2: Генерация Истинной Вокальной Карты и Железных Занавесов.
    Использует спектральный фильтр (Flatness) для отсечения барабанов,
    а также гибридный метод поиска Мертвых Зон (Тишина + Отсутствие гармоник).
    """
    log.info("🗺️ [Acoustics] Генерация Истинной Вокальной Карты (VAD & Curtains)...")
    hop_length = 512
    times = librosa.frames_to_time(np.arange(len(audio_data)//hop_length + 1), sr=sr, hop_length=hop_length)
    audio_duration = len(audio_data) / sr

    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    rms_norm = rms / (np.max(rms) + 1e-8)
    flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length)[0]
    
    # 1. Разделяем энергию
    strong_vad_frames = rms_norm > 0.02
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

    def extract_harmonic_intervals(frames_mask, pad):
        raw_intervals = frames_to_intervals(frames_mask, pad=pad)
        harmonic_intervals = []
        for s, e in raw_intervals:
            s_frame = librosa.time_to_frames(s, sr=sr, hop_length=hop_length)
            e_frame = librosa.time_to_frames(e, sr=sr, hop_length=hop_length)
            if s_frame < e_frame and s_frame < len(flatness):
                # V6.2: ФИЛЬТР БАРАБАНОВ. Звук должен иметь тональность (голос/мелодия)
                if np.min(flatness[s_frame:e_frame]) < 0.1:
                    if not harmonic_intervals:
                        harmonic_intervals.append((s, e))
                    else:
                        last_s, last_e = harmonic_intervals[-1]
                        if s - last_e < 0.5:
                            harmonic_intervals[-1] = (last_s, max(last_e, e))
                        elif e - s > 0.1:
                            harmonic_intervals.append((s, e))
        return harmonic_intervals

    # 2. Извлекаем только ГАРМОНИЧЕСКИЙ VAD (игнорируя чистые ударные)
    strong_vad_mask = extract_harmonic_intervals(strong_vad_frames, pad=0.2)
    weak_vad_mask = extract_harmonic_intervals(weak_vad_frames, pad=0.1)

    # 3. ПОСТРОЕНИЕ ЖЕЛЕЗНЫХ ЗАНАВЕСОВ (МЕТОД 1: ОТСУТСТВИЕ ГОЛОСА)
    combined_vad = sorted(strong_vad_mask + weak_vad_mask, key=lambda x: x[0])
    merged_vad = []
    for s, e in combined_vad:
        if not merged_vad: merged_vad.append((s, e))
        else:
            last_s, last_e = merged_vad[-1]
            if s - last_e < 1.5: # Прощаем паузы до 1.5с внутри вокала
                merged_vad[-1] = (last_s, max(last_e, e))
            else:
                merged_vad.append((s, e))
                
    iron_curtains = []
    last_e = 0.0
    for s, e in merged_vad:
        if s - last_e > 3.5: # Дыра без тонального звука > 3.5s = Занавес
            iron_curtains.append((last_e, s))
        last_e = e
        
    if audio_duration - last_e > 3.5:
        iron_curtains.append((last_e, audio_duration))

    # 4. ПОСТРОЕНИЕ ЖЕЛЕЗНЫХ ЗАНАВЕСОВ (МЕТОД 2: АБСОЛЮТНАЯ ТИШИНА ИЗ V5.3)
    noise_floor = np.percentile(rms, 5)
    thresh = max(10 ** (-60 / 20), noise_floor * 1.1)
    silence_mask = rms < thresh
    
    in_silence = False
    start_t = 0.0
    for i, is_silent in enumerate(silence_mask):
        if is_silent and not in_silence:
            in_silence = True
            start_t = times[i]
        elif not is_silent and in_silence:
            in_silence = False
            end_t = times[i]
            if end_t - start_t > 3.0:
                iron_curtains.append((start_t, end_t))
                
    if in_silence and (times[-1] - start_t > 3.0):
        iron_curtains.append((start_t, times[-1]))

    # 5. СЛИЯНИЕ ВСЕХ ЗАНАВЕСОВ В МОНОЛИТ
    iron_curtains.sort(key=lambda x: x[0])
    merged_curtains = []
    for s, e in iron_curtains:
        if not merged_curtains: merged_curtains.append((s, e))
        else:
            last_s, last_e = merged_curtains[-1]
            if s <= last_e: merged_curtains[-1] = (last_s, max(last_e, e))
            else: merged_curtains.append((s, e))
            
    iron_curtains = merged_curtains

    # 📡 ТЕЛЕМЕТРИЯ V6.2
    total_vocal = sum(e - s for s, e in merged_vad)
    total_instrumental = audio_duration - total_vocal
    
    log.info(f"🎤 [Acoustics] Вокал: {total_vocal:.1f}s. Инструментал/Пустоты: {total_instrumental:.1f}s.")
    log.info(f"🧱 [Acoustics] Установлено Железных Занавесов: {len(iron_curtains)}")
    for i, (cs, ce) in enumerate(iron_curtains):
        log.debug(f"   -> Занавес {i+1}: {cs:.1f}s - {ce:.1f}s")

    # 6. Onsets и Гармоники
    o_env = librosa.onset.onset_strength(y=audio_data, sr=sr)
    raw_onsets = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, units='time')
    
    onsets = [o_t for o_t in raw_onsets if any(vs <= o_t <= ve for (vs, ve) in strong_vad_mask) or 
                                           any(ws <= o_t <= we for (ws, we) in weak_vad_mask)]

    def is_harmonic(t_start, t_end):
        s_frame = librosa.time_to_frames(t_start, sr=sr, hop_length=hop_length)
        e_frame = librosa.time_to_frames(t_end, sr=sr, hop_length=hop_length)
        if s_frame >= e_frame or s_frame >= len(flatness): return False
        return np.median(flatness[s_frame:e_frame]) < 0.05

    return strong_vad_mask, weak_vad_mask, iron_curtains, onsets, is_harmonic