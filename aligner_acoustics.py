import librosa
import numpy as np
from app_logger import get_logger

log = get_logger("aligner_acoustics")

# ─── V5.0: NON-DESTRUCTIVE ACOUSTICS (VOCAL HEATMAP) ────────────────────────────

def vocal_sniper(audio_data: np.ndarray, sr: int) -> np.ndarray:
    """
    V5.0: Оружие разряжено (Safe Source).
    Мы не вырезаем тихие звуки физически, чтобы не повредить шепот (например, Кристина Си).
    Возвращаем оригинальное аудио без изменений. Whisper и Арена будут слушать чистый оригинал.
    """
    log.info("🎯 [Vocal Sniper] Режим Read-Only. Аудио сохранено в оригинале.")
    return audio_data

def build_iron_curtain(audio_data: np.ndarray, sr: int) -> list:
    """
    V5.0: Soft Iron Curtain (Поиск Великой Пустоты).
    Определяет только зоны АБСОЛЮТНОЙ тишины или чистого минуса (> 3 сек).
    В V5.0 (Line-First) эти зоны используются для запрета разрыва строк (Void Integrity).
    """
    log.info("🛡️ [Iron Curtain] Сканирование зон абсолютной пустоты (Soft Threshold)...")
    hop_length = 512
    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    
    # Смягчаем порог: берем 5-й перцентиль (самые тихие участки)
    noise_floor = np.percentile(rms, 5)
    # Жесткий лимит -60 dB 
    thresh = max(10 ** (-60 / 20), noise_floor * 1.1)
    
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
            if end_t - start_t > 3.0:
                curtains.append((start_t, end_t))
                log.info(f"   🧱 Soft Curtain установлен: {start_t:.2f}s - {end_t:.2f}s")
                
    if in_silence:
        end_t = times[-1]
        if end_t - start_t > 3.0:
            curtains.append((start_t, end_t))
            log.info(f"   🧱 Soft Curtain установлен (конец): {start_t:.2f}s - {end_t:.2f}s")
            
    return curtains

def enforce_curtains(start: float, end: float, curtains: list) -> tuple:
    """Сдвигает тайминги, чтобы слово физически не заходило за занавес (Instrumental Void)."""
    for c_s, c_e in curtains:
        if start < c_s and end > c_s: 
            end = c_s - 0.01
        elif start < c_e and end > c_e: 
            start = c_e + 0.01
        elif start >= c_s and end <= c_e:
            start = c_e + 0.01
            end = start + 0.1
    return start, max(start + 0.05, end)

# ─── СЕМАНТИЧЕСКИЙ VAD И АКУСТИЧЕСКАЯ ТОПОГРАФИЯ ─────────────────────────

def get_acoustic_maps(audio_data: np.ndarray, sr: int) -> tuple:
    """
    V5.0: Генерация Vocal Heatmap (Информационная карта).
    Выдает базис для расчета Емкости VAD (VAD Capacity) в главном скрипте.
    """
    log.info("🗺️ [Orchestra] Генерация акустической топографии (Vocal Heatmap, Onsets)...")
    hop_length = 512
    times = librosa.frames_to_time(np.arange(len(audio_data)//hop_length + 1), sr=sr, hop_length=hop_length)

    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    rms_norm = rms / (np.max(rms) + 1e-8)
    
    # Разделяем на уверенный голос (Red Zone) и слабый голос/шепот (Yellow Zone)
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

    flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length)[0]

    # Строим карту сильного голоса (с учетом тональности)
    raw_strong = frames_to_intervals(strong_vad_frames, pad=0.2)
    strong_vad_mask = []
    for s, e in raw_strong:
        s_frame = librosa.time_to_frames(s, sr=sr, hop_length=hop_length)
        e_frame = librosa.time_to_frames(e, sr=sr, hop_length=hop_length)
        if s_frame < e_frame and s_frame < len(flatness):
            if np.min(flatness[s_frame:e_frame]) < 0.1: # Есть тональность
                if not strong_vad_mask:
                    strong_vad_mask.append((s, e))
                else:
                    last_s, last_e = strong_vad_mask[-1]
                    if s - last_e < 0.5:
                        strong_vad_mask[-1] = (last_s, max(last_e, e))
                    elif e - s > 0.1:
                        strong_vad_mask.append((s, e))
                        
    # Слабая зона (шепот Кристины Си)
    weak_vad_mask = frames_to_intervals(weak_vad_frames, pad=0.1)

    o_env = librosa.onset.onset_strength(y=audio_data, sr=sr)
    raw_onsets = librosa.onset.onset_detect(onset_envelope=o_env, sr=sr, units='time')
    
    # Onsets берем и из сильной, и из слабой зоны
    onsets = [o_t for o_t in raw_onsets if any(vs <= o_t <= ve for (vs, ve) in strong_vad_mask) or 
                                           any(ws <= o_t <= we for (ws, we) in weak_vad_mask)]

    def is_harmonic(t_start, t_end):
        s_frame = librosa.time_to_frames(t_start, sr=sr, hop_length=hop_length)
        e_frame = librosa.time_to_frames(t_end, sr=sr, hop_length=hop_length)
        if s_frame >= e_frame or s_frame >= len(flatness): return False
        return np.median(flatness[s_frame:e_frame]) < 0.05

    return strong_vad_mask, weak_vad_mask, onsets, is_harmonic

def apply_vad_deafness(crop_audio: np.ndarray, sr: int, t_start: float, vad_mask: list) -> np.ndarray:
    """
    V5.0: Функция отключена (Safe Source).
    Хирургическая глухота больше не модифицирует аудио, 
    чтобы не лишать Whisper контекста на этапе Арены (Semantic Harpoon).
    """
    return crop_audio