import wave
import numpy as np
from pathlib import Path

SAMPLE_RATE = 16000
MIN_CLIP_DURATION = 7
MAX_CLIP_DURATION = 90
SWEET_SPOT_MIN = 15
SWEET_SPOT_MAX = 45
ENERGY_THRESHOLD = 0.03
MIN_CLIP_ENERGY = 0.04

def _load_audio(audio_path: str) -> np.ndarray:
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    if path.stat().st_size == 0:
        raise ValueError("Audio file is empty")

    with wave.open(str(path), "rb") as wf:
        nchannels = wf.getnchannels()
        frames = wf.readframes(wf.getnframes())
        samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        if nchannels > 1:
            samples = samples.reshape(-1, nchannels).mean(axis=1)

    return samples

def _rms(samples: np.ndarray) -> float:
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))

def _detect_mood_from_energy(avg_energy: float, peak_energy: float, zcr: float = 0.0) -> str:
    dynamic_range = peak_energy - avg_energy
    if avg_energy > 0.15 and peak_energy > 0.25:
        if zcr > 0.15:
            return "funny"
        return "hype"
    elif dynamic_range > 0.18 and avg_energy < 0.12:
        return "emotional"
    elif avg_energy < 0.04 and zcr < 0.08:
        return "chill"
    elif 0.04 <= avg_energy < 0.10 and dynamic_range < 0.10:
        return "serious"
    elif zcr > 0.20 and avg_energy > 0.10:
        return "funny"
    else:
        return "chill"

def _mood_vec(avg: np.ndarray, peak: np.ndarray, zcr: np.ndarray) -> np.ndarray:
    """Vectorized mood detection over arrays of segment stats."""
    dynamic_range = peak - avg
    moods = np.full(avg.shape, "chill", dtype=object)

    m1 = (avg > 0.15) & (peak > 0.25) & (zcr > 0.15)
    moods[m1] = "funny"
    m2 = (avg > 0.15) & (peak > 0.25)
    moods[m2] = "hype"
    m3 = (dynamic_range > 0.18) & (avg < 0.12)
    moods[m3 & ~m1 & ~m2] = "emotional"
    m4 = (avg < 0.04) & (zcr < 0.08)
    moods[m4 & ~m1 & ~m2 & ~m3] = "chill"
    m5 = (avg >= 0.04) & (avg < 0.10) & (dynamic_range < 0.10)
    moods[m5 & ~m1 & ~m2 & ~m3 & ~m4] = "serious"
    m6 = (zcr > 0.20) & (avg > 0.10)
    moods[m6 & ~m1 & ~m2 & ~m3 & ~m4 & ~m5] = "funny"

    return moods


def score_clip_energy(audio_path: str, start: float, end: float) -> float:
    samples = _load_audio(audio_path)

    start_sample = max(0, int(start * SAMPLE_RATE))
    end_sample = min(len(samples), int(end * SAMPLE_RATE))

    if end_sample - start_sample < SAMPLE_RATE * 0.5:
        return 0.0

    clip_samples = samples[start_sample:end_sample]

    window_size = int(0.1 * SAMPLE_RATE)
    n_windows = len(clip_samples) // window_size
    if n_windows == 0:
        return 0.0
    trimmed = clip_samples[:n_windows * window_size].reshape(n_windows, window_size)
    rms_per_window = np.sqrt(np.mean(trimmed ** 2, axis=1))
    mean_energy = float(np.mean(rms_per_window))
    return min(1.0, mean_energy / ENERGY_THRESHOLD)


def detect_energy_clips(audio_path: str, duration: float) -> list:
    samples = _load_audio(audio_path)
    num_samples = len(samples)

    step_size = int(0.25 * SAMPLE_RATE)
    window_size = int(0.5 * SAMPLE_RATE)

    n_steps = num_samples // step_size
    if n_steps < 2:
        return []

    trimmed = samples[:n_steps * step_size + window_size - step_size]
    windows = np.lib.stride_tricks.sliding_window_view(trimmed, window_size)[::step_size][:n_steps]
    energy_curve = np.sqrt(np.mean(windows ** 2, axis=1))

    if window_size > 1:
        signs = np.sign(windows)
        signs[signs == 0] = 1
        zcr_curve = np.sum(np.abs(np.diff(signs, axis=1)) > 0, axis=1) / window_size
    else:
        zcr_curve = np.zeros(n_steps)

    time_per_step = step_size / SAMPLE_RATE
    min_window_steps = int(SWEET_SPOT_MIN / time_per_step)
    max_window_steps = int(SWEET_SPOT_MAX / time_per_step)

    candidates = []
    for window_len in range(min_window_steps, max_window_steps + 1):
        if window_len > n_steps:
            break
        n_segments = n_steps - window_len + 1
        step = max(1, int(window_len * 0.3))

        if n_segments >= window_len:
            ec_view = np.lib.stride_tricks.sliding_window_view(energy_curve, window_len)
            peak_full = ec_view.max(axis=1)
        else:
            peak_full = np.array([energy_curve[i:i + window_len].max() for i in range(n_segments)])

        peak_all = peak_full[::step]
        n_kept = len(peak_all)

        avg_all = np.convolve(energy_curve, np.ones(window_len) / window_len, mode="valid")[::step][:n_kept]
        zcr_all = np.convolve(zcr_curve, np.ones(window_len) / window_len, mode="valid")[::step][:n_kept]

        n = min(len(avg_all), len(peak_all), len(zcr_all))
        avg_all = avg_all[:n]
        peak_all = peak_all[:n]
        zcr_all = zcr_all[:n]

        total_score = avg_all * 0.6 + peak_all * 0.4
        moods = _mood_vec(avg_all, peak_all, zcr_all)

        starts = (np.arange(n) * step) * time_per_step
        ends = np.minimum(starts + window_len * time_per_step, duration)

        mask = (ends - starts >= MIN_CLIP_DURATION) & (ends - starts <= MAX_CLIP_DURATION)
        starts = starts[mask]
        ends = ends[mask]
        avg_all = avg_all[mask]
        peak_all = peak_all[mask]
        zcr_all = zcr_all[mask]
        total_score = total_score[mask]
        moods = moods[mask]

        for i in range(len(starts)):
            cd = float(ends[i] - starts[i])
            candidates.append({
                "start": round(float(starts[i]), 1),
                "end": round(float(ends[i]), 1),
                "duration": round(cd, 1),
                "energy_score": round(float(total_score[i]), 4),
                "avg_energy": round(float(avg_all[i]), 4),
                "peak_energy": round(float(peak_all[i]), 4),
                "zcr": round(float(zcr_all[i]), 4),
                "mood": str(moods[i]),
            })

    if not candidates:
        return []

    candidates.sort(key=lambda x: x["energy_score"], reverse=True)

    target_moods = ["hype", "funny", "emotional", "serious", "chill"]
    selected = []
    used_moods = []

    for target in target_moods:
        for c in candidates:
            if c["mood"] != target:
                continue
            overlap = False
            for d in selected:
                if c["start"] < d["end"] and c["end"] > d["start"]:
                    overlap_duration = min(c["end"], d["end"]) - max(c["start"], d["start"])
                    if overlap_duration / min(c["duration"], d["duration"]) > 0.4:
                        overlap = True
                        break
            if not overlap:
                selected.append(c)
                used_moods.append(target)
                break

    for c in candidates:
        if len(selected) >= 5:
            break
        if c["mood"] in used_moods:
            continue
        overlap = False
        for d in selected:
            if c["start"] < d["end"] and c["end"] > d["start"]:
                overlap_duration = min(c["end"], d["end"]) - max(c["start"], d["start"])
                if overlap_duration / min(c["duration"], d["duration"]) > 0.4:
                    overlap = True
                    break
        if not overlap:
            selected.append(c)
            used_moods.append(c["mood"])

    selected.sort(key=lambda x: x["start"])

    return selected[:5]
