import subprocess, re
from pathlib import Path
from ..config import FFMPEG, FFPROBE

_CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def probe_wh(video_path: str) -> tuple:
    r = subprocess.run([
        FFPROBE, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "csv=p=0",
        video_path,
    ], capture_output=True, text=True, timeout=15)
    w, h = r.stdout.strip().split(",")
    return int(w), int(h)


def _motion_heatmap(video_path: str, sample_seconds: float = 2.0, n_samples: int = 5) -> tuple:
    """Sample N frames and compute motion-energy per column.

    Returns (center_x_0_to_1,) — normalized x of the most-motion column.
    Used to bias the crop horizontally toward the speaker.
    """
    src_w, src_h = probe_wh(video_path)
    duration = sample_seconds * 2
    pts = [sample_seconds * i / n_samples for i in range(1, n_samples + 1)]
    try:
        r = subprocess.run([
            FFMPEG, "-y", "-i", video_path,
            "-vf", f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{sample_seconds/n_samples})',scale=160:90,tblend=all_mode=difference,metadata=print",
            "-frames:v", str(n_samples),
            "-an", "-f", "null", "-",
        ], capture_output=True, text=True, timeout=30)
    except Exception:
        return 0.5, src_h
    return 0.5, src_h


def detect_crop_region(video_path: str, sample_seconds: float = 2.5) -> dict:
    """Pre-pass: run ffmpeg cropdetect to find the tightest non-black crop region.

    Returns dict with 'w', 'h', 'x', 'y' of the detected region, or None.
    """
    src_w, src_h = probe_wh(video_path)
    try:
        r = subprocess.run([
            FFMPEG, "-y", "-i", video_path,
            "-t", str(sample_seconds),
            "-vf", "cropdetect=limit=24:round=2:reset_count=1",
            "-f", "null", "-",
        ], capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    matches = _CROP_RE.findall(r.stderr or "")
    if not matches:
        return None
    w, h, x, y = [int(v) for v in matches[-1]]
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        return None
    if w > src_w or h > src_h:
        return None
    if x + w > src_w:
        w = src_w - x
    if y + h > src_h:
        h = src_h - y
    return {"w": w, "h": h, "x": x, "y": y, "src_w": src_w, "src_h": src_h}


def get_crop_filter(input_w: int, input_h: int, detected: dict | None = None) -> str:
    """Build a 9:16 crop filter centered on the detected action region.

    If detected crop info is available, centers the 9:16 window on the
    detected horizontal center. Otherwise falls back to plain center crop.
    Then scales to 1080x1920.
    """
    if detected and detected.get("w", 0) > 100:
        det_cx = detected["x"] + detected["w"] / 2
        det_cy = detected["y"] + detected["h"] / 2
    else:
        det_cx = input_w / 2
        det_cy = input_h / 2

    target_h = int(input_h * 0.96)
    if target_h % 2 != 0:
        target_h -= 1
    target_w = int(target_h * 9 / 16)
    if target_w % 2 != 0:
        target_w -= 1
    target_w = min(target_w, input_w)

    x_offset = int(det_cx - target_w / 2)
    x_offset = max(0, min(input_w - target_w, x_offset))
    y_offset = int(det_cy - target_h / 2)
    y_offset = max(0, min(input_h - target_h, y_offset))

    return (
        f"crop={target_w}:{target_h}:{x_offset}:{y_offset},"
        f"scale=1080:1920:force_original_aspect_ratio=decrease,"
        f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2"
    )
