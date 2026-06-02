import subprocess
import re
import os
from pathlib import Path
from .config import YT_DLP, FFMPEG, FFPROBE, DENO

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
VIDEO_REGEX = re.compile(
    r"(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)"
    r"[\w-]{11}"
)

def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def is_valid_youtube_url(url: str) -> bool:
    return bool(VIDEO_REGEX.match(url.strip()))

def check_duration(url: str) -> float:
    result = subprocess.run([
        YT_DLP, "--print", "duration",
        "--no-playlist",
        "--js-runtimes", f"deno:{DENO}",
        url
    ], capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp duration check failed: {result.stderr[:300]}")
    duration = float(result.stdout.strip() or 0)
    if duration > 6000:
        raise ValueError(
            f"Video too long ({duration/60:.0f} min). "
            f"Maximum 30 minutes. "
            f"For longer videos, trim to the best section first."
        )
    return duration

def download_audio_only(url: str, out_path: str) -> str:
    result = subprocess.run([
        YT_DLP, "-x", "--audio-format", "wav",
        "--audio-quality", "0",
        "--postprocessor-args", "ExtractAudio:-ac 1 -ar 16000",
        "-o", out_path,
        "--no-playlist",
        "--js-runtimes", f"deno:{DENO}",
        url
    ], capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Audio download failed: {result.stderr[:500]}")
    return out_path

def download_full_video(url: str, out_path: str) -> str:
    """Download the full video in a small, fast format. Used as a base for ffmpeg cuts."""
    result = subprocess.run([
        YT_DLP,
        "-f", "worst[ext=mp4]/worst",
        "-o", out_path,
        "--no-playlist",
        "--no-part",
        "--js-runtimes", f"deno:{DENO}",
        url
    ], capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Full video download failed: {result.stderr[:500]}")
    if not os.path.exists(out_path):
        raise RuntimeError(f"Full video download produced no file at {out_path}")
    return out_path


def cut_clip_from_video(video_path: str, start: float, end: float, out_path: str) -> str:
    """Cut a clip from a locally-downloaded video using ffmpeg. No network needed."""
    duration = end - start
    r = subprocess.run([
        FFMPEG, "-y", "-v", "error",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        out_path
    ], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {r.stderr[:200]}")
    return out_path


def download_clip_section(url: str, start: float, end: float, out_path: str, clip_index: int) -> str:
    """Legacy per-section download. Slow, kept for fallback only."""
    output = out_path.replace(".mp4", f"_clip{clip_index}.mp4")
    result = subprocess.run([
        YT_DLP,
        "--download-sections", f"*{start}-{end}",
        "-S", "res:1080,ext:mp4:m4a",
        "-o", output,
        "--no-playlist",
        "--no-part",
        "--js-runtimes", f"deno:{DENO}",
        url
    ], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"Section download failed: {result.stderr[:500]}")
    return output

def get_video_duration(video_path: str) -> float:
    result = subprocess.run([
        FFPROBE, "-v", "error",
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
