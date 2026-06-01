import subprocess
import os
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def download_youtube(url: str, job_id: str) -> dict:
    ensure_output_dir()
    video_path = OUTPUT_DIR / f"{job_id}_video.mp4"
    audio_path = OUTPUT_DIR / f"{job_id}_audio.wav"

    subprocess.run([
        "yt-dlp", "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "-o", str(video_path),
        "--merge-output-format", "mp4",
        url
    ], check=True, capture_output=True)

    subprocess.run([
        "ffmpeg", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path), "-y"
    ], check=True, capture_output=True)

    original_name = Path(video_path).name
    return {
        "video_path": str(video_path),
        "audio_path": str(audio_path),
        "original_name": original_name
    }

def get_video_duration(video_path: str) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", video_path
    ], check=True, capture_output=True, text=True)
    return float(result.stdout.strip())
