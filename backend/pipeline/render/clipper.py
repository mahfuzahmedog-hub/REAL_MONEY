import subprocess
import re
from pathlib import Path
from ..config import FFMPEG
from . import look
from . import framing

BACKEND_DIR = Path(__file__).resolve().parents[2]
FONTS_DIR = BACKEND_DIR / "assets" / "fonts"
OVERLAYS_DIR = BACKEND_DIR / "assets" / "overlays"
BOTTOM_GRADIENT_PNG = OVERLAYS_DIR / "bottom_gradient.png"


def get_duration(video_path: str) -> float:
    from ..config import FFPROBE
    r = subprocess.run([
        FFPROBE, "-v", "error", "-show_entries",
        "format=duration", "-of", "csv=p=0", video_path
    ], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except (ValueError, TypeError):
        return 10.0


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
    fontsdir = str(FONTS_DIR).replace("\\", "/").replace(":", "\\:")
    return f"subtitles='{p}':original_size=1080x1920:fontsdir='{fontsdir}'"


def _build_bottom_gradient_overlay() -> str:
    """Return an ffmpeg filter that overlays the static bottom-gradient PNG.

    The PNG is 1080x1920 (full frame) with a cinematic vignette:
    transparent at the top, ~92% black at the bottom. This darkens the
    lower 75% of the frame just enough to make white Anton subtitles
    readable on light/cream/white source footage (e.g. podiums, sky),
    while leaving the subject's face untouched.
    """
    if not BOTTOM_GRADIENT_PNG.exists():
        return ""
    p = str(BOTTOM_GRADIENT_PNG).replace("\\", "/").replace(":", "\\:")
    return f"movie='{p}'[bg];[v][bg]overlay=0:0[v]"


def process_clip(
    video_path: str, ass_path: str, music_path: str | None,
    caption_hook: str, output_path: str, mood: str = "hype",
    brand_text: str = "",
    punchline_reactions: list | None = None,
    action_center: dict | None = None,
    source_is_vertical: bool = False,
    subtitle_style: str = "default",
    clip_duration: float | None = None,
) -> str:
    probe = get_probe(video_path)
    duration = get_duration(video_path)
    if clip_duration is not None and clip_duration > 0:
        encode_duration = min(clip_duration, duration)
    else:
        encode_duration = duration
    # If source is already 9:16 vertical, skip the smart-crop and just scale.
    # Preserves quality (no re-encoding crop) and respects the original framing.
    if source_is_vertical or (probe["height"] > probe["width"] and probe["width"] >= 540):
        crop = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black"
    else:
        crop = framing.get_crop_filter(probe["width"], probe["height"], detected=action_center)
    grade = look.get_grade_filter(mood)
    zoom = look.build_zoom_filter(encode_duration, punchline_reactions)
    hook = look.build_hook_filter(caption_hook, mood, style=subtitle_style)
    watermark = look.build_brand_watermark_filter(brand_text, mood, style=subtitle_style) if brand_text else ""
    sub_filter = _escape_ass_path(ass_path) if ass_path and Path(ass_path).exists() and Path(ass_path).stat().st_size > 0 else ""
    emojis = look.build_emoji_reaction_filter(punchline_reactions or [])

    endcard = look.build_endcard_filter(brand_text, encode_duration, mood, style=subtitle_style)
    progress_bar = look.build_progress_bar_filter(encode_duration)
    parts = [crop, grade, zoom, "unsharp=5:5:1.0:5:5:0.0"]
    if hook:
        parts.append(hook)
    if watermark:
        parts.append(watermark)
    if emojis:
        parts.append(emojis)
    if endcard:
        parts.append(endcard)
    if progress_bar:
        parts.append(progress_bar)
    if sub_filter:
        parts.append(sub_filter)
    vf = ",".join(parts)

    music_volume = "0.08" if mood in ("funny", "chill") else "0.12"

    # Build filter_complex. The subtitle and gradient layers both write to [v].
    # If we have a bottom gradient (for the creator style), we need to chain the
    # gradient overlay AFTER the rest of the [v] pipeline. So:
    #   1. Apply all main filters -> [v]
    #   2. (creator only) Overlay bottom gradient on top of [v] -> [v]
    use_gradient = (subtitle_style or "").lower() == "creator"

    cmd = [FFMPEG, "-y", "-threads", "2", "-i", video_path]
    filter_complex = f"[0:v]{vf}[v]"

    if use_gradient and BOTTOM_GRADIENT_PNG.exists():
        # Need the gradient as a 2nd input (movie filter doesn't need -i)
        bg_path = str(BOTTOM_GRADIENT_PNG).replace("\\", "/").replace(":", "\\:")
        filter_complex = (
            f"movie='{bg_path}'[bg];"
            f"[0:v]{vf}[base];"
            f"[base][bg]overlay=0:0[v]"
        )

    trim = f"atrim=0:{encode_duration:.3f},asetpts=PTS-STARTPTS"
    if music_path:
        cmd.extend(["-i", music_path])
        filter_complex += (
            f";[0:a]{trim},asplit=2[side][speech]"
            f";[1:a]{trim},volume={music_volume}[music_raw]"
            f";[music_raw][side]sidechaincompress="
            f"threshold=0.1:ratio=5:attack=25:release=300"
            f":level_sc=1.0[ducked]"
            f";[speech][ducked]amix=inputs=2:duration=first[mixed]"
            f";[mixed]loudnorm=I=-14:LRA=11:TP=-1.5[a]"
        )
        map_flags = ["-map", "[v]", "-map", "[a]"]
    else:
        filter_complex += (
            f";[0:a]{trim},loudnorm=I=-14:LRA=11:TP=-1.5[a]"
        )
        map_flags = ["-map", "[v]", "-map", "[a]"]

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(map_flags)
    if encode_duration and encode_duration > 0:
        cmd.extend(["-t", f"{encode_duration:.3f}"])
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-b:v", "2500k",
        "-minrate", "1500k",
        "-maxrate", "5000k",
        "-bufsize", "5000k",
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
