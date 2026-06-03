import subprocess
import re
import os
from pathlib import Path
from ..config import YT_DLP, FFMPEG, FFPROBE, DENO

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


def get_video_info(url: str) -> dict:
    """Get YouTube video metadata: title, uploader/channel, duration.

    Returns dict with keys: title, uploader, channel, duration (any may be empty).
    Uses yt-dlp --print to fetch metadata quickly (no download).
    """
    try:
        result = subprocess.run([
            YT_DLP,
            "--print", "%(title)s|||%(uploader)s|||%(channel)s|||%(duration)s",
            "--no-playlist",
            "--no-warnings",
            "--js-runtimes", f"deno:{DENO}",
            url
        ], capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not result.stdout.strip():
            return {"title": "", "uploader": "", "channel": "", "duration": 0.0}
        parts = result.stdout.strip().split("|||")
        if len(parts) < 4:
            parts = parts + [""] * (4 - len(parts))
        try:
            dur = float(parts[3]) if parts[3] else 0.0
        except ValueError:
            dur = 0.0
        return {
            "title": parts[0].strip(),
            "uploader": parts[1].strip(),
            "channel": parts[2].strip() or parts[1].strip(),
            "duration": dur,
        }
    except Exception:
        return {"title": "", "uploader": "", "channel": "", "duration": 0.0}

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
    """Download the full video at 720p with merged audio. Used as a base for ffmpeg cuts.

    Uses bestvideo (720p MP4 DASH) + bestaudio (m4a) and merges them with
    ffmpeg into a single mp4. This gives us 720p video with audio in one
    file — the section cuts via `-c copy` are then instant and lossless.

    The DASH merge adds ~30s but is done once for all clips. Temp file
    ~420 MB for an 80-min video.
    """
    result = subprocess.run([
        YT_DLP,
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
        "-o", out_path,
        "--no-playlist",
        "--no-part",
        "--merge-output-format", "mp4",
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


def download_clip_section(url: str, start: float, end: float, out_path: str, clip_index: int = 0) -> str:
    """Download only the clip window at 1080p via yt-dlp section download.

    This is the PRIMARY download method. 1080p source means the 9:16 crop
    is 608x1080 before scaling to 1080x1920 — only 1.78x upscale instead
    of 2.7x from 720p. Each 25s section is ~50-80 MB.
    """
    result = subprocess.run([
        YT_DLP,
        "--download-sections", f"*{start}-{end}",
        "-f", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
        "-o", out_path,
        "--no-playlist",
        "--no-part",
        "--js-runtimes", f"deno:{DENO}",
        "--merge-output-format", "mp4",
        url
    ], capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"1080p section download failed: {result.stderr[:500]}")
    if not os.path.exists(out_path):
        raise RuntimeError(f"1080p section download produced no file at {out_path}")
    return out_path

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
