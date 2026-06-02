import subprocess
from pathlib import Path
from .config import FFMPEG

def get_crop_filter(input_w: int, input_h: int) -> str:
    target_w = int(input_h * 9 / 16)
    target_w = min(target_w, input_w)
    if target_w % 2 != 0:
        target_w -= 1
    x_offset = (input_w - target_w) // 2
    y_offset = int(input_h * 0.05)
    crop_h = input_h - y_offset
    if crop_h % 2 != 0:
        crop_h -= 1
    return f"crop={target_w}:{crop_h}:{x_offset}:{y_offset},scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2"

def get_probe(video_path: str) -> dict:
    result = subprocess.run([
        FFMPEG, "-i", video_path
    ], capture_output=True, text=True)
    for line in result.stderr.split("\n"):
        if "Stream #0:0" in line and "Video" in line:
            parts = line.split(",")
            for p in parts:
                p = p.strip()
                if "x" in p and p.split("x")[0].isdigit():
                    w, h = p.split("x")[:2]
                    return {"width": int(w), "height": int(h)}
    return {"width": 1920, "height": 1080}

def build_hook_filter(caption_hook: str) -> str:
    safe = caption_hook.replace("'", "\\'").replace(":", "\\:")
    return (
        f"drawtext=text='{safe}'"
        ":fontfile=/Windows/Fonts/arialbd.ttf"
        ":fontsize=56"
        ":fontcolor=white"
        ":borderw=3"
        ":bordercolor=black"
        ":x=(w-text_w)/2"
        ":y=h/4"
        ":enable='between(t,0,2)'"
    )

def process_clip(
    video_path: str, ass_path: str, music_path: str | None,
    caption_hook: str, output_path: str
) -> str:
    probe = get_probe(video_path)
    crop = get_crop_filter(probe["width"], probe["height"])
    hook = build_hook_filter(caption_hook)
    vf = f"{crop},{hook},subtitles={ass_path}"

    cmd = [FFMPEG, "-y", "-threads", "4", "-i", video_path]
    filter_complex = f"[0:v]{vf}[v]"

    if music_path:
        cmd.extend(["-i", music_path])
        filter_complex += f";[1:a]volume=0.12[music];[0:a][music]amix=inputs=2:duration=first[a]"
        map_flags = ["-map", "[v]", "-map", "[a]"]
    else:
        filter_complex += f";[0:a]acopy[a]"
        map_flags = ["-map", "[v]", "-map", "[a]"]

    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(map_flags)
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "26",
        "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart",
        "-threads", "4",
        output_path, "-y"
    ])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Clip encoding failed: {result.stderr[:500]}")
    return output_path
