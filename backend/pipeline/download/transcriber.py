from faster_whisper import WhisperModel
from pathlib import Path

_model = None

def get_model():
    global _model
    if _model is None:
        _model = WhisperModel(
            "tiny", device="cpu", compute_type="int8",
            cpu_threads=4, num_workers=1
        )
    return _model

def transcribe(audio_path: str) -> list:
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    file_size = Path(audio_path).stat().st_size
    if file_size == 0:
        raise ValueError("Audio file is empty")

    model = get_model()
    segments, _ = model.transcribe(
        audio_path,
        beam_size=1,
        best_of=1,
        temperature=0,
        vad_filter=True,
        vad_parameters=dict(
            min_silence_duration_ms=400,
            speech_pad_ms=200
        ),
        condition_on_previous_text=False
    )
    segments = list(segments)

    result = []
    for seg in segments:
        result.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "no_speech_prob": getattr(seg, "no_speech_prob", 0.0)
        })

    return result

def filter_segments(segments: list, max_chars: int = 6000) -> str:
    filtered = [s for s in segments if s.get("no_speech_prob", 1.0) < 0.3]
    if not filtered:
        filtered = segments
    text = " ".join([f"[{s['start']:.1f}] {s['text']}" for s in filtered])
    if len(text) > max_chars:
        text = text[:max_chars] + "...[truncated]"
    return text
