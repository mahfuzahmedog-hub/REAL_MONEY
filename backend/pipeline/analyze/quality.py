import wave
import numpy as np
from pathlib import Path

SAMPLE_RATE = 16000
MIN_CLIP_DURATION = 7
MAX_CLIP_DURATION = 90
SWEET_SPOT_MIN = 15
SWEET_SPOT_MAX = 45
ENERGY_THRESHOLD = 0.05

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

def _zcr(samples: np.ndarray) -> float:
    if len(samples) < 2:
        return 0.0
    signs = np.sign(samples)
    signs[signs == 0] = 1
    crossings = np.sum(np.abs(np.diff(signs)) > 0)
    return float(crossings) / len(samples)

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

def score_clip_energy(audio_path: str, start: float, end: float) -> float:
    samples = _load_audio(audio_path)
    total_duration = len(samples) / SAMPLE_RATE

    start_sample = max(0, int(start * SAMPLE_RATE))
    end_sample = min(len(samples), int(end * SAMPLE_RATE))

    if end_sample - start_sample < SAMPLE_RATE * 0.5:
        return 0.0

    clip_samples = samples[start_sample:end_sample]

    window_size = int(0.1 * SAMPLE_RATE)
    energy_windows = []
    for i in range(0, len(clip_samples), window_size):
        window = clip_samples[i:i + window_size]
        if len(window) < window_size // 2:
            break
        energy_windows.append(_rms(window))

    if not energy_windows:
        return 0.0

    mean_energy = float(np.mean(energy_windows))
    return min(1.0, mean_energy / ENERGY_THRESHOLD)

def detect_energy_clips(audio_path: str, duration: float) -> list:
    samples = _load_audio(audio_path)
    num_samples = len(samples)

    window_size = int(0.5 * SAMPLE_RATE)
    step_size = int(0.25 * SAMPLE_RATE)

    energy_curve = []
    for i in range(0, num_samples, step_size):
        window = samples[i:i + window_size]
        if len(window) < window_size // 2:
            break
        energy_curve.append(_rms(window))

    energy_curve = np.array(energy_curve)
    time_per_step = step_size / SAMPLE_RATE

    min_window_steps = int(SWEET_SPOT_MIN / time_per_step)
    max_window_steps = int(SWEET_SPOT_MAX / time_per_step)

    candidates = []
    for window_len in range(min_window_steps, max_window_steps + 1):
        for i in range(0, len(energy_curve) - window_len, int(window_len * 0.3)):
            segment = energy_curve[i:i + window_len]
            avg_energy = float(np.mean(segment))
            peak_energy = float(np.max(segment))

            seg_start_sample = i * step_size
            seg_end_sample = (i + window_len) * step_size
            seg_samples = samples[seg_start_sample:seg_end_sample]
            zcr = _zcr(seg_samples)

            total_score = avg_energy * 0.6 + peak_energy * 0.4

            start_time = i * time_per_step
            end_time = (i + window_len) * time_per_step
            clip_duration = end_time - start_time

            if clip_duration < MIN_CLIP_DURATION or clip_duration > MAX_CLIP_DURATION:
                continue

            candidates.append({
                "start": round(start_time, 1),
                "end": round(min(end_time, duration), 1),
                "duration": round(clip_duration, 1),
                "energy_score": round(total_score, 4),
                "avg_energy": round(avg_energy, 4),
                "peak_energy": round(peak_energy, 4),
                "zcr": round(zcr, 4),
                "mood": _detect_mood_from_energy(avg_energy, peak_energy, zcr)
            })

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
