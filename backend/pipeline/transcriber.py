from faster_whisper import WhisperModel
from pathlib import Path

_model = None

def get_model():
    global _model
    if _model is None:
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model

def transcribe(audio_path: str) -> list:
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    file_size = Path(audio_path).stat().st_size
    if file_size == 0:
        raise ValueError("Audio file is empty")

    model = get_model()
    segments, _ = model.transcribe(audio_path, beam_size=1, vad_filter=True)

    result = []
    for seg in segments:
        result.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip()
        })

    if not result:
        raise ValueError("No speech detected in audio")

    return result
