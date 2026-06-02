import subprocess
import re
from pathlib import Path
from ..config import FFMPEG
from . import look

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
    from ..config import FFPROBE
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

def _escape_ass_path(ass_path: str) -> str:
    p = ass_path.replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{p}':original_size=1080x1920"


def process_clip(
    video_path: str, ass_path: str, music_path: str | None,
    caption_hook: str, output_path: str, mood: str = "hype",
    brand_text: str = "",
    punchline_reactions: list | None = None,
) -> str:
    probe = get_probe(video_path)
    crop = get_crop_filter(probe["width"], probe["height"])
    grade = look.get_grade_filter(mood)
    hook = look.build_hook_filter(caption_hook, mood)
    watermark = look.build_brand_watermark_filter(brand_text, mood) if brand_text else ""
    sub_filter = _escape_ass_path(ass_path) if ass_path and Path(ass_path).exists() and Path(ass_path).stat().st_size > 0 else ""
    emojis = look.build_emoji_reaction_filter(punchline_reactions or [])

    parts = [crop, grade]
    if hook:
        parts.append(hook)
    if watermark:
        parts.append(watermark)
    if emojis:
        parts.append(emojis)
    if sub_filter:
        parts.append(sub_filter)
    vf = ",".join(parts)

    music_volume = "0.08" if mood in ("funny", "chill") else "0.12"

    cmd = [FFMPEG, "-y", "-threads", "2", "-i", video_path]
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
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        "-threads", "2",
        output_path, "-y"
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        err = result.stderr or ""
        lines = err.splitlines()
        error_markers = ("error", "Error", "ERROR", "failed", "Failed", "FAILED",
                         "Invalid", "invalid", "No such", "no such",
                         "Conversion failed", "Impossible", "missing")
        err_lines = [
            ln for ln in lines
            if any(m in ln for m in error_markers)
        ]
        if not err_lines:
            err_lines = [
                ln for ln in lines
                if not ln.strip().startswith("--enable-")
                and not ln.strip().startswith("configuration:")
                and not ln.strip().startswith("ffmpeg version")
                and "Copyright (c)" not in ln
                and "built with" not in ln
                and not re.match(r"^\s*lib\w+\s+\d", ln)
                and "libass API version" not in ln
                and "libass direct render" not in ln
            ]
        if not err_lines:
            err_lines = lines
        err_tail = "\n".join(err_lines[-30:]) if err_lines else err[-1500:]
        raise RuntimeError(f"Clip encoding failed: {err_tail}")
    return output_path
