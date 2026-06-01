import subprocess
import os
import re
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
YOUTUBE_REGEX = r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+"

def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def is_valid_youtube_url(url: str) -> bool:
    return bool(re.match(YOUTUBE_REGEX, url.strip()))

def download_youtube(url: str, job_id: str) -> dict:
    ensure_output_dir()
    video_path = OUTPUT_DIR / f"{job_id}_video.mp4"
    audio_path = OUTPUT_DIR / f"{job_id}_audio.wav"

    result = subprocess.run([
        "yt-dlp", "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "-o", str(video_path),
        "--merge-output-format", "mp4",
        "--no-playlist",
        url
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[:500]}")

    result = subprocess.run([
        "ffmpeg", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path), "-y"
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio extraction failed: {result.stderr[:500]}")

    return {
        "video_path": str(video_path),
        "audio_path": str(audio_path),
        "original_name": Path(video_path).name
    }

def get_video_duration(video_path: str) -> float:
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", video_path
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr[:200]}")
    return float(result.stdout.strip())

def cleanup_job_files(paths: list):
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass
