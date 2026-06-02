import subprocess
from pathlib import Path
from ..config import FFMPEG

def get_crop_filter(input_w: int, input_h: int) -> str:
    target_w = int(input_h * 9 / 16)
    target_w = min(target_w, input_w)
    if target_w % 2 != 0:
        target_w -= 1
    x_offset = (input_w - target_w) // 2
    y_offset = int(input_h * 0.02)
    crop_h = input_h - y_offset
    if crop_h % 2 != 0:
        crop_h -= 1
    return f"crop={target_w}:{crop_h}:{x_offset}:{y_offset},scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"

def get_probe(video_path: str) -> dict:
    """Use ffprobe for reliable width/height detection."""
    from .config import FFPROBE
    result = subprocess.run([
        FFPROBE, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        video_path
    ], capture_output=True, text=True)
    if result.returncode == 0 and result.stdout.strip():
        try:
            w, h = result.stdout.strip().split(",")
            return {"width": int(w), "height": int(h)}
        except (ValueError, IndexError):
            pass
    return {"width": 1920, "height": 1080}

def build_hook_filter(caption_hook: str) -> str:
    safe = caption_hook.replace("'", "\\'").replace(":", "\\:")
    return (
        f"drawtext=text='{safe}'"
        ":fontfile=/Windows/Fonts/arialbd.ttf"
        ":fontsize=64"
        ":fontcolor=white"
        ":borderw=4"
        ":bordercolor=black"
        ":shadowx=2"
        ":shadowy=2"
        ":shadowcolor=black"
        ":x=(w-text_w)/2"
        ":y=h/3"
        ":enable='between(t,0,2.5)'"
    )

def _escape_ass_path(ass_path: str) -> str:
    """Escape Windows path for ffmpeg subtitles filter.

    ffmpeg parses colons as option separators, so we must escape them.
    The cleanest way is: backslashes -> forward slashes, then escape colons.
    Also, we wrap the path in single quotes to handle spaces.
    """
    p = ass_path.replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{p}'"


def process_clip(
    video_path: str, ass_path: str, music_path: str | None,
    caption_hook: str, output_path: str, mood: str = "hype"
) -> str:
    probe = get_probe(video_path)
    crop = get_crop_filter(probe["width"], probe["height"])
    hook = build_hook_filter(caption_hook)
    sub_filter = _escape_ass_path(ass_path)
    vf = f"{crop},{hook},{sub_filter}"

    music_volume = "0.08" if mood in ("funny", "chill") else "0.12"

    cmd = [FFMPEG, "-y", "-threads", "4", "-i", video_path]
    filter_complex = f"[0:v]{vf}[v]"

    if music_path:
        cmd.extend(["-i", music_path])
        filter_complex += f";[1:a]volume={music_volume}[music];[0:a][music]amix=inputs=2:duration=first[a]"
        map_flags = ["-map", "[v]", "-map", "[a]"]
    else:
        filter_complex += f";[0:a]acopy[a]"
        map_flags = ["-map", "[v]", "-map", "[a]"]

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(map_flags)
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "24",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        "-threads", "4",
        output_path, "-y"
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err_tail = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr
        raise RuntimeError(f"Clip encoding failed: {err_tail}")
    return output_path
