import subprocess
import re
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
        "--postprocessor-args", "ffmpeg:-ac 1",
        "-o", out_path,
        "--no-playlist",
        "--js-runtimes", f"deno:{DENO}",
        url
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Audio download failed: {result.stderr[:500]}")
    return out_path

def download_clip_section(url: str, start: float, end: float, out_path: str, clip_index: int) -> str:
    output = out_path.replace(".mp4", f"_clip{clip_index}.mp4")
    result = subprocess.run([
        YT_DLP,
        "--download-sections", f"*{start}-{end}",
        "--force-keyframes-at-cuts",
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "-o", output,
        "--no-playlist",
        "--js-runtimes", f"deno:{DENO}",
        "--merge-output-format", "mp4",
        url
    ], capture_output=True, text=True)
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
