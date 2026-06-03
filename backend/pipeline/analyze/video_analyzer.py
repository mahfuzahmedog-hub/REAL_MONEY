import numpy as np
from pathlib import Path

SAMPLE_RATE = 16000

LOW_ENERGY_THRESHOLD = 0.02
HIGH_ENERGY_THRESHOLD = 0.15
LAUGHTER_FREQ_LOW = 2000
LAUGHTER_FREQ_HIGH = 4000
APPLAUSE_FREQ_LOW = 500
APPLAUSE_FREQ_HIGH = 3000
SWEET_SPOT_MIN = 15
SWEET_SPOT_MAX = 45

HUMOR_TRIGGER_WORDS = {
    "like", "just", "actually", "basically", "literally", "seriously",
    "right?", "you know", "i mean", "wait", "okay", "so",
    "but", "because", "when", "if", "then", "now",
    "ever", "never", "always", "every time", "classic",
}


def _load_audio(audio_path: str) -> np.ndarray:
    import wave
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


def _psd(samples: np.ndarray, fs: int) -> tuple:
    n = len(samples)
    if n < 64:
        n = 64
    window = np.hanning(min(n, 4096))
    seg = samples[:len(window)]
    if len(seg) < len(window):
        window = window[:len(seg)]
    fft = np.fft.rfft(seg * window)
    psd = np.abs(fft) ** 2 / len(window)
    freqs = np.fft.rfftfreq(len(window), 1 / fs)
    return freqs, psd


def _spectral_profile(samples: np.ndarray, fs: int) -> dict:
    freqs, psd_val = _psd(samples, fs)
    laugh_band = psd_val[(freqs >= LAUGHTER_FREQ_LOW) & (freqs <= LAUGHTER_FREQ_HIGH)]
    applause_band = psd_val[(freqs >= APPLAUSE_FREQ_LOW) & (freqs <= APPLAUSE_FREQ_HIGH)]
    total_energy = psd_val.sum()
    laugh_energy = laugh_band.sum() if len(laugh_band) > 0 else 0
    applause_energy = applause_band.sum() if len(applause_band) > 0 else 0
    laugh_ratio = laugh_energy / total_energy if total_energy > 0 else 0
    return {
        "laugh_ratio": float(laugh_ratio),
        "applause_ratio": float(applause_energy / total_energy) if total_energy > 0 else 0,
    }


def _detect_laughter_bursts(samples: np.ndarray, fs: int, window_sec: float = 0.5) -> np.ndarray:
    window_size = int(window_sec * fs)
    n_windows = len(samples) // window_size
    if n_windows < 2:
        return np.array([])
    trimmed = samples[:n_windows * window_size].reshape(n_windows, window_size)
    laugh_ratios = []
    for i in range(n_windows):
        seg = trimmed[i]
        freqs, psd_val = _psd(seg, fs)
        laugh_energy = np.sum(psd_val[(freqs >= LAUGHTER_FREQ_LOW) & (freqs <= LAUGHTER_FREQ_HIGH)])
        talk_energy = np.sum(psd_val[(freqs >= 200) & (freqs <= 800)]) + 1e-10
        laugh_ratios.append(laugh_energy / talk_energy)
    return np.array(laugh_ratios)


def _analyze_audio_segment(samples: np.ndarray, start: float, end: float, fs: int) -> dict:
    s = max(0, int(start * fs))
    e = min(len(samples), int(end * fs))
    if e - s < fs * 0.5:
        return {"energy": 0, "laugh_score": 0, "applause_score": 0, "spectral": {}}
    seg = samples[s:e]
    rms = float(np.sqrt(np.mean(seg ** 2)))
    spectral = _spectral_profile(seg, fs)
    laugh_bursts = _detect_laughter_bursts(seg, fs)
    laugh_burst_score = float(np.mean(laugh_bursts)) if len(laugh_bursts) > 0 else 0
    laugh_burst_peak = float(np.max(laugh_bursts)) if len(laugh_bursts) > 0 else 0

    zcr = float(np.sum(np.abs(np.diff(np.sign(seg)))) / len(seg)) if len(seg) > 0 else 0

    return {
        "energy": round(rms, 4),
        "zcr": round(zcr, 4),
        "laugh_score": round(min(1.0, laugh_burst_score * 2), 4),
        "laugh_peak": round(min(1.0, laugh_burst_peak * 2), 4),
        "applause_score": round(min(1.0, spectral.get("applause_ratio", 0) * 5), 4),
        "laugh_ratio": round(spectral.get("laugh_ratio", 0), 4),
        "spectral": spectral,
    }


def _text_humor_score(text: str) -> float:
    if not text:
        return 0.0
    lower = text.lower()
    words = lower.split()
    trigger_count = sum(1 for w in words if w.strip(".,!?;:'\"()[]{}") in HUMOR_TRIGGER_WORDS)
    contains_question = "?" in text
    contains_exclamation = "!" in text
    word_count = len(words)
    if word_count == 0:
        return 0.0

    if contains_question and word_count < 8:
        return min(1.0, 0.5 + trigger_count * 0.1)
    if contains_exclamation and trigger_count > 0:
        return min(1.0, 0.6 + trigger_count * 0.08)
    if word_count >= 15:
        return min(1.0, 0.3 + trigger_count * 0.05)
    if word_count <= 5 and contains_question:
        return 0.7
    return min(1.0, trigger_count * 0.12)


def analyze_segment(audio_path: str, start: float, end: float, transcript_text: str = "") -> dict:
    samples = _load_audio(audio_path)
    audio_result = _analyze_audio_segment(samples, start, end, SAMPLE_RATE)
    text_score = _text_humor_score(transcript_text)
    combined = _compute_combined_score(audio_result, text_score)
    mood = _classify_mood(audio_result, text_score)
    return {
        "start": round(start, 1),
        "end": round(end, 1),
        "duration": round(end - start, 1),
        "worth_score": round(combined["worth"], 2),
        "humor_score": round(combined["humor"], 2),
        "sentiment_score": round(text_score, 2),
        "laugh_score": audio_result["laugh_score"],
        "laugh_peak": audio_result["laugh_peak"],
        "applause_score": audio_result["applause_score"],
        "energy": audio_result["energy"],
        "zcr": audio_result["zcr"],
        "mood": mood,
        "is_worth_clipping": combined["worth"] >= 0.4,
    }


def _compute_combined_score(audio: dict, text_score: float) -> dict:
    laugh = max(audio["laugh_score"], audio["laugh_peak"] * 0.7)
    energy = audio["energy"]
    applause = audio["applause_score"]

    humor_from_audio = laugh * 0.6 + min(1.0, energy / 0.15) * 0.2 + applause * 0.2
    humor_from_text = text_score

    combined_humor = humor_from_audio * 0.55 + humor_from_text * 0.45
    energy_bonus = min(1.0, max(0, energy - LOW_ENERGY_THRESHOLD) / (HIGH_ENERGY_THRESHOLD - LOW_ENERGY_THRESHOLD))

    worth = combined_humor * 0.7 + energy_bonus * 0.3
    return {"humor": combined_humor, "energy_bonus": energy_bonus, "worth": worth}


def _classify_mood(audio: dict, text_score: float) -> str:
    laugh = max(audio["laugh_score"], audio["laugh_peak"] * 0.7)
    energy = audio["energy"]
    applause = audio["applause_score"]

    if laugh > 0.3 and energy > 0.08:
        return "funny"
    if laugh > 0.2:
        return "funny"
    if applause > 0.3:
        return "hype"
    if energy > 0.12 and audio["zcr"] > 0.12:
        return "hype"
    if energy > 0.10:
        return "emotional"
    if text_score > 0.5 and energy > 0.05:
        return "funny"
    if text_score > 0.3:
        return "serious"
    return "chill"


def scan_video_for_clips(audio_path: str, duration: float, transcript: list = None) -> list:
    samples = _load_audio(audio_path)
    step_sec = 0.5
    window_sec = 2.0
    window_size = int(window_sec * SAMPLE_RATE)
    step_size = int(step_sec * SAMPLE_RATE)
    n_steps = (len(samples) - window_size) // step_size
    if n_steps < 2:
        return []

    laugh_bursts = _detect_laughter_bursts(samples, SAMPLE_RATE, 0.5)

    scan_results = []
    for i in range(n_steps):
        t = i * step_sec
        seg = samples[i * step_size:i * step_size + window_size]
        rms = float(np.sqrt(np.mean(seg ** 2)))
        lb_idx = int(t / 0.5)
        laugh_burst = float(laugh_bursts[lb_idx]) if lb_idx < len(laugh_bursts) else 0
        spectral = _spectral_profile(seg, SAMPLE_RATE)
        text_score = 0.0

        if transcript:
            for seg_t in transcript:
                if seg_t["start"] <= t + window_sec and seg_t["end"] >= t:
                    text_score = max(text_score, _text_humor_score(seg_t.get("text", "")))

        worth_score = _compute_combined_score({
            "laugh_score": laugh_burst,
            "laugh_peak": 0,
            "energy": rms,
            "applause_score": spectral.get("applause_ratio", 0),
        }, text_score)["worth"]

        scan_results.append({
            "t": round(t, 1),
            "worth": round(worth_score, 2),
            "energy": round(rms, 4),
            "laugh": round(laugh_burst, 4),
            "text_score": round(text_score, 2),
        })

    if not scan_results:
        return []

    laugh_threshold = np.percentile([s["laugh"] for s in scan_results], 80) if scan_results else 0.1
    energy_threshold = np.percentile([s["energy"] for s in scan_results], 70) if scan_results else 0.05
    worth_threshold = np.percentile([s["worth"] for s in scan_results], 65) if scan_results else 0.3

    hot_flags = np.array([
        1 if (s["laugh"] > laugh_threshold or (s["energy"] > energy_threshold and s["worth"] > worth_threshold))
        else 0 for s in scan_results
    ], dtype=float)

    if len(hot_flags) < 5:
        return []

    kernel_size = max(3, int(5.0 / step_sec) // 2 * 2 + 1)
    kernel = np.ones(kernel_size) / kernel_size
    density = np.convolve(hot_flags, kernel, mode="same")

    density_threshold = 0.4
    hot_zones = []
    in_zone = False
    zone_start = 0.0
    prev_t = 0.0

    for i, s in enumerate(scan_results):
        is_hot_zone = density[i] >= density_threshold
        if is_hot_zone and not in_zone:
            zone_start = s["t"]
            in_zone = True
        elif not is_hot_zone and in_zone:
            zone_end = prev_t
            zone_dur = zone_end - zone_start
            if zone_dur >= 5.0:
                hot_zones.append({
                    "start": zone_start,
                    "end": zone_end,
                    "duration": round(zone_dur, 1),
                })
            in_zone = False
        prev_t = s["t"]
    if in_zone:
        zone_end = scan_results[-1]["t"]
        zone_dur = zone_end - zone_start
        if zone_dur >= 5.0:
            hot_zones.append({
                "start": zone_start,
                "end": zone_end,
                "duration": round(zone_dur, 1),
            })

    hot_zones.sort(key=lambda z: z["duration"], reverse=True)
    scored = []
    for z in hot_zones:
        zone_samples = [s for s in scan_results if z["start"] <= s["t"] <= z["end"]]
        avg_worth = np.mean([s["worth"] for s in zone_samples]) if zone_samples else 0
        z["worth_score"] = round(float(avg_worth), 2)
        scored.append(z)

    scored.sort(key=lambda z: z["worth_score"], reverse=True)

    final = []
    for z in scored:
        overlap = False
        for d in final:
            if z["start"] < d["end"] and z["end"] > d["start"]:
                overlap_dur = min(z["end"], d["end"]) - max(z["start"], d["start"])
                if overlap_dur / min(z["duration"], d["duration"]) > 0.3:
                    overlap = True
                    break
        if not overlap:
            final.append(z)

    final.sort(key=lambda z: z["start"])
    return final[:5]
