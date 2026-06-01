from faster_whisper import WhisperModel
import os

_model = None

def get_model():
    global _model
    if _model is None:
        _model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _model

def transcribe(audio_path: str) -> list:
    model = get_model()
    segments, info = model.transcribe(audio_path, beam_size=1, vad_filter=True)

    result = []
    for seg in segments:
        result.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip()
        })
    return result
