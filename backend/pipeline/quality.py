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

def _detect_mood_from_energy(avg_energy: float, peak_energy: float) -> str:
    if avg_energy > 0.15 and peak_energy > 0.25:
        return "hype"
    elif peak_energy > 0.20 and avg_energy < 0.10:
        return "emotional"
    elif avg_energy < 0.05:
        return "chill"
    elif avg_energy > 0.08:
        return "serious"
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
                "mood": _detect_mood_from_energy(avg_energy, peak_energy)
            })

    candidates.sort(key=lambda x: x["energy_score"], reverse=True)

    deduped = []
    for c in candidates:
        overlap = False
        for d in deduped:
            if c["start"] < d["end"] and c["end"] > d["start"]:
                overlap_duration = min(c["end"], d["end"]) - max(c["start"], d["start"])
                if overlap_duration / min(c["duration"], d["duration"]) > 0.5:
                    overlap = True
                    break
        if not overlap:
            deduped.append(c)
            if len(deduped) >= 5:
                break

    return deduped[:5]
