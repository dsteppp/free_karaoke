import librosa
import numpy as np
from app_logger import get_logger

log = get_logger("aligner")

def enforce_curtains(start: float, end: float, curtains: list) -> tuple:
    for c_s, c_e in curtains:
        if start >= c_s and end <= c_e:
            dur = end - start
            start = c_e + 0.01
            end = start + dur
        elif start < c_s and end > c_s: end = c_s - 0.01
        elif start < c_e and end > c_e: start = c_e + 0.01
    return start, max(start + 0.05, end)

def get_acoustic_maps(audio_data: np.ndarray, sr: int) -> tuple:
    log.info("🗺️ [Acoustics] Генерация Истинной Вокальной Карты (V6.4 Ultimate)...")
    hop_length = 512
    times = librosa.frames_to_time(np.arange(len(audio_data)//hop_length + 1), sr=sr, hop_length=hop_length)
    audio_duration = len(audio_data) / sr

    rms = librosa.feature.rms(y=audio_data, frame_length=2048, hop_length=hop_length)[0]
    rms_norm = rms / (np.max(rms) + 1e-8)
    flatness = librosa.feature.spectral_flatness(y=audio_data, hop_length=hop_length)[0]

    iron_curtains = []

    # 1. ВЕЛИКАЯ ПУСТОТА
    noise_floor = np.percentile(rms, 5)
    thresh = max(10 ** (-60 / 20), noise_floor * 1.5) 
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

    # 2. ГЕНЕРАЦИЯ СЫРОГО VAD (УСИЛЕННЫЙ ПОРОГ ПРОТИВ БАРАБАНОВ)
    strong_vad_frames = rms_norm > 0.04 # Было 0.02
    weak_vad_frames = (rms_norm > 0.01) & (rms_norm <= 0.04)
    
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
        if in_zone: intervals.append((max(0, s_t - pad), times[-1] + pad))
        return intervals

    def extract_harmonic_intervals(frames_mask, pad):
        raw_intervals = frames_to_intervals(frames_mask, pad=pad)
        harmonic_intervals = []
        for s, e in raw_intervals:
            s_frame = librosa.time_to_frames(s, sr=sr, hop_length=hop_length)
            e_frame = librosa.time_to_frames(e, sr=sr, hop_length=hop_length)
            if s_frame < e_frame and s_frame < len(flatness):
                if np.min(flatness[s_frame:e_frame]) < 0.1:
                    if not harmonic_intervals: harmonic_intervals.append((s, e))
                    else:
                        last_s, last_e = harmonic_intervals[-1]
                        if s - last_e < 0.5: harmonic_intervals[-1] = (last_s, max(last_e, e))
                        elif e - s > 0.1: harmonic_intervals.append((s, e))
        return harmonic_intervals

    raw_strong = extract_harmonic_intervals(strong_vad_frames, pad=0.2)
    raw_weak = extract_harmonic_intervals(weak_vad_frames, pad=0.1)

    # 3. МУЗЫКАЛЬНЫЕ ЯМЫ
    combined_raw_vad = sorted(raw_strong + raw_weak, key=lambda x: x[0])
    merged_vad = []
    for s, e in combined_raw_vad:
        if not merged_vad: merged_vad.append((s, e))
        else:
            last_s, last_e = merged_vad[-1]
            if s - last_e < 1.5: merged_vad[-1] = (last_s, max(last_e, e))
            else: merged_vad.append((s, e))
                
    last_e = 0.0
    for s, e in merged_vad:
        if s - last_e > 3.5: iron_curtains.append((last_e, s))
        last_e = e
    if audio_duration - last_e > 3.5: iron_curtains.append((last_e, audio_duration))

    # 4. СЛИЯНИЕ ВСЕХ ЗАНАВЕСОВ В БЕТОННЫЙ МОНОЛИТ
    iron_curtains.sort(key=lambda x: x[0])
    merged_curtains = []
    for s, e in iron_curtains:
        if not merged_curtains: merged_curtains.append((s, e))
        else:
            last_s, last_e = merged_curtains[-1]
            if s <= last_e: merged_curtains[-1] = (last_s, max(last_e, e))
            else: merged_curtains.append((s, e))
    iron_curtains = merged_curtains

    # 5. THE PURGE (ЗАЧИСТКА VAD)
    def purge_vad(vad_list, curtains):
        purged = []
        for v_s, v_e in vad_list:
            current_segments = [(v_s, v_e)]
            for c_s, c_e in curtains:
                new_segments = []
                for seg_s, seg_e in current_segments:
                    if seg_s >= c_s and seg_e <= c_e: continue 
                    elif c_s <= seg_s < c_e and seg_e > c_e: new_segments.append((c_e, seg_e))
                    elif seg_s < c_s and c_s < seg_e <= c_e: new_segments.append((seg_s, c_s))
                    elif seg_s < c_s and seg_e > c_e: 
                        new_segments.append((seg_s, c_s))
                        new_segments.append((c_e, seg_e))
                    else: new_segments.append((seg_s, seg_e))
                current_segments = new_segments
            
            for s, e in current_segments:
                if e - s >= 0.05: purged.append((s, e))
        return sorted(purged, key=lambda x: x[0])

    strong_vad_mask = purge_vad(raw_strong, iron_curtains)
    weak_vad_mask = purge_vad(raw_weak, iron_curtains)

    # 6. ТЕЛЕМЕТРИЯ
    final_combined_vad = sorted(strong_vad_mask + weak_vad_mask, key=lambda x: x[0])
    final_merged = []
    for s, e in final_combined_vad:
        if not final_merged: final_merged.append((s, e))
        else:
            last_s, last_e = final_merged[-1]
            if s <= last_e: final_merged[-1] = (last_s, max(last_e, e))
            else: final_merged.append((s, e))

    total_vocal = sum(e - s for s, e in final_merged)
    total_instrumental = audio_duration - total_vocal
    
    log.info(f"🎤 [Acoustics] Вокал: {total_vocal:.1f}s. Инструментал/Пустоты: {total_instrumental:.1f}s.")
    log.info(f"🧱 [Acoustics] Установлено Железных Занавесов: {len(iron_curtains)}")

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