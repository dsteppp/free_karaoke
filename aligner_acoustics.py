import librosa
import numpy as np
from app_logger import get_logger

log = get_logger("aligner_acoustics")

# ─── V8/V9: SMART THRESHOLDS (SNIPER И CURTAIN) ────────────────────────────

def vocal_sniper(audio_data: np.ndarray, sr: int) -> np.ndarray:
    """
    V8: Smart Vocal Sniper. 
    Очищает хвосты и вдохи относительно базового шума конкретной песни (noise_floor).
    """
    log.info("🎯 [Vocal Sniper] Зачистка вокального стема (Smart Pre-gating)...")
    hop_length = 512
    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    
    # Динамический порог на базе 15-го перцентиля (шум паузы)
    noise_floor = np.percentile(rms, 15)
    thresh = max(10 ** (-42 / 20), noise_floor * 2.0)
    
    mask = rms > thresh
    # Сглаживаем маску
    mask = np.convolve(mask, np.ones(5)/5, mode='same') > 0.2
    mask_audio = np.repeat(mask, hop_length)
    
    if len(mask_audio) < len(audio_data):
        mask_audio = np.pad(mask_audio, (0, len(audio_data) - len(mask_audio)))
    else:
        mask_audio = mask_audio[:len(audio_data)]
        
    gated = np.where(mask_audio, audio_data, 0.0)
    return gated.astype(np.float32)

def build_iron_curtain(audio_data: np.ndarray, sr: int) -> list:
    """
    V8: Smart Iron Curtain. 
    Создает зоны абсолютной пустоты с динамическим порогом.
    """
    log.info("🛡️ [Iron Curtain] Сканирование проигрышей (Smart Threshold)...")
    hop_length = 512
    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    
    # Динамический порог для абсолютной тишины
    noise_floor = np.percentile(rms, 10)
    thresh = max(10 ** (-50 / 20), noise_floor * 1.2)
    
    silence_mask = rms < thresh
    
    curtains = []
    in_silence = False
    start_t = 0.0
    times = librosa.frames_to_time(np.arange(len(silence_mask)), sr=sr, hop_length=hop_length)
    
    for i, is_silent in enumerate(silence_mask):
        if is_silent and not in_silence:
            in_silence = True
            start_t = times[i]
        elif not is_silent and in_silence:
            in_silence = False
            end_t = times[i]
            if end_t - start_t > 2.5:
                curtains.append((start_t, end_t))
                log.info(f"   🧱 Железный занавес установлен: {start_t:.2f}s - {end_t:.2f}s")
                
    if in_silence:
        end_t = times[-1]
        if end_t - start_t > 2.5:
            curtains.append((start_t, end_t))
            log.info(f"   🧱 Железный занавес установлен (конец): {start_t:.2f}s - {end_t:.2f}s")
            
    return curtains

def enforce_curtains(start: float, end: float, curtains: list) -> tuple:
    """Сдвигает тайминги, чтобы слово не пересекало Железный Занавес."""
    for c_s, c_e in curtains:
        if start < c_s and end > c_s: 
            end = c_s - 0.01
        elif start < c_e and end > c_e: 
            start = c_e + 0.01
        elif start >= c_s and end <= c_e:
            start = c_e + 0.01
            end = start + 0.1
    return start, max(start + 0.05, end)

# ─── V9: СЕМАНТИЧЕСКИЙ VAD И АКУСТИЧЕСКАЯ ТОПОГРАФИЯ ─────────────────────────

def get_acoustic_maps(audio_data: np.ndarray, sr: int) -> tuple:
    """Генерирует карту голоса (VAD), атаки (Onsets) и функцию проверки гармоник."""
    log.info("[Orchestra] Генерация акустической топографии (Semantic VAD, Onsets, Harmonics)...")
    hop_length = 512
    times = librosa.frames_to_time(np.arange(len(audio_data)//hop_length + 1), sr=sr, hop_length=hop_length)

    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    rms_norm = rms / (np.max(rms) + 1e-8)
    
    # 1. Первичный поиск энергии
    raw_vad_frames = rms_norm > 0.015 
    
    raw_intervals, in_speech, start_t = [], False, 0.0
    for t, is_active in zip(times[:len(raw_vad_frames)], raw_vad_frames):
        if is_active and not in_speech:
            start_t, in_speech = t, True
        elif not is_active and in_speech:
            raw_intervals.append((start_t, t))
            in_speech = False
    if in_speech: raw_intervals.append((start_t, times[-1]))

    # 2. V9: Семантический фильтр (Spectral Flatness)
    # Плоскость спектра: 0.0 = чистый тон (гласная), 1.0 = белый шум (барабан, вдох)
    flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length)[0]
    
    vad_mask = []
    pad = 0.2  # Soft Padding, чтобы не обрезать глухие согласные (с, ш, х)
    
    for s, e in raw_intervals:
        s_frame = librosa.time_to_frames(s, sr=sr, hop_length=hop_length)
        e_frame = librosa.time_to_frames(e, sr=sr, hop_length=hop_length)
        
        # Если блок достаточно длинный, чтобы его анализировать
        if s_frame < e_frame and s_frame < len(flatness):
            chunk_flatness = flatness[s_frame:e_frame]
            # Если минимальный flatness в куске меньше 0.1, значит там есть хотя бы одна тональная нота
            if np.min(chunk_flatness) < 0.1:
                s_pad, e_pad = max(0.0, s - pad), e + pad
                if not vad_mask: 
                    vad_mask.append((s_pad, e_pad))
                else:
                    last_s, last_e = vad_mask[-1]
                    if s_pad - last_e < 0.5: 
                        vad_mask[-1] = (last_s, max(last_e, e_pad))
                    elif e_pad - s_pad > 0.1: 
                        vad_mask.append((s_pad, e_pad))
            else:
                # В этом куске нет гармоник (это удар рабочего барабана или резкий вдох). Игнорируем.
                pass
        
    o_env = librosa.onset.onset_strength(y=audio_data, sr=sr)
    raw_onsets = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, units='time')
    # Атаки звука (onsets) берем только из подтвержденных голосовых зон
    onsets = [o_t for o_t in raw_onsets if any(vs <= o_t <= ve for (vs, ve) in vad_mask)]

    def is_harmonic(t_start, t_end):
        s_frame = librosa.time_to_frames(t_start, sr=sr, hop_length=hop_length)
        e_frame = librosa.time_to_frames(t_end, sr=sr, hop_length=hop_length)
        if s_frame >= e_frame or s_frame >= len(flatness): return False
        chunk = flatness[s_frame:e_frame]
        return np.median(chunk) < 0.05

    return vad_mask, onsets, is_harmonic

def apply_vad_deafness(crop_audio: np.ndarray, sr: int, t_start: float, vad_mask: list) -> np.ndarray:
    """Хирургическая глухота (Attention Masking). Заглушает участки вне VAD-маски."""
    mask = np.zeros_like(crop_audio, dtype=bool)
    times = t_start + np.arange(len(crop_audio)) / sr
    
    for vs, ve in vad_mask:
        mask |= (times >= vs) & (times <= ve)
        
    # Заглушаем на 90% всё, что не попадает в VAD
    return np.where(mask, crop_audio, crop_audio * 0.1)