import subprocess
import os
import wave
import numpy as np
from pathlib import Path
from ..config import FFMPEG, FFPROBE

SAMPLE_RATE = 16000


def extract_audio_segment(audio_path: str, start: float, end: float, out_path: str) -> str:
    duration = end - start
    r = subprocess.run([
        FFMPEG, "-y", "-v", "error",
        "-i", audio_path,
        "-ss", str(start),
        "-t", str(duration),
        "-ac", "1", "-ar", str(SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        out_path
    ], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to extract audio segment {start}-{end}: {r.stderr[:200]}")
    return out_path


def transcribe_windowed(audio_path: str, windows: list, job_dir: str) -> list:
    """
    Transcribe only the given time windows from a large audio file.
    Returns concatenated transcript with absolute timestamps.
    windows: list of {"start": float, "end": float}
    """
    from .transcriber import get_model

    model = get_model()
    all_segments = []

    for i, w in enumerate(windows):
        seg_path = os.path.join(job_dir, f"win_{i}.wav")
        try:
            extract_audio_segment(audio_path, w["start"], w["end"], seg_path)
        except Exception as e:
            print(f"[transcribe_windowed] extract failed for {w}: {e}", flush=True)
            continue

        try:
            segments, _ = model.transcribe(
                seg_path,
                beam_size=1,
                best_of=1,
                temperature=0,
                vad_filter=False,
                condition_on_previous_text=False
            )
            segments = list(segments)
        except Exception as e:
            print(f"[transcribe_windowed] transcribe failed for window {i}: {e}", flush=True)
            continue

        for seg in segments:
            all_segments.append({
                "start": round(seg.start + w["start"], 2),
                "end": round(seg.end + w["start"], 2),
                "text": seg.text.strip(),
                "no_speech_prob": getattr(seg, "no_speech_prob", 0.0)
            })

        try:
            os.unlink(seg_path)
        except Exception:
            pass

    all_segments.sort(key=lambda s: s["start"])
    return all_segments
