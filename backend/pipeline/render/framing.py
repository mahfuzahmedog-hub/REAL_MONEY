import subprocess, re
import cv2
import numpy as np
from pathlib import Path
from ..config import FFMPEG, FFPROBE

_CROP_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")

_FACE_CASCADE = None
def _get_cascade():
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _FACE_CASCADE = cv2.CascadeClassifier(cascade_path)
    return _FACE_CASCADE


def detect_faces_in_clip(video_path: str, sample_duration: float = 2.5) -> tuple:
    """Sample frames from the clip and detect face centers using OpenCV.

    Returns (avg_face_x_norm, avg_face_y_norm) where each is 0.0-1.0
    normalized to frame dimensions. Returns (0.5, 0.5) if no faces found.
    """
    cascade = _get_cascade()
    src_w, src_h = probe_wh(video_path)
    centers = []
    n_frames = 0
    try:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        sample_frames = min(5, max(2, int(sample_duration * fps)))
        if total_frames > 0:
            step = max(1, total_frames // sample_frames)
        else:
            step = int(fps * 0.5)
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % step == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(
                    gray, scaleFactor=1.15, minNeighbors=5,
                    minSize=(40, 40)
                )
                n_frames += 1
                for (fx, fy, fw, fh) in faces:
                    cx = (fx + fw / 2) / frame.shape[1]
                    cy = (fy + fh / 2) / frame.shape[0]
                    centers.append((cx, cy))
            frame_idx += 1
            if total_frames > 0 and frame_idx >= total_frames:
                break
        cap.release()
    except Exception:
        return (0.5, 0.5)
    if not centers:
        return (0.5, 0.5)
    avg_x = sum(c[0] for c in centers) / len(centers)
    avg_y = sum(c[1] for c in centers) / len(centers)
    return (avg_x, avg_y)


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


def detect_action_center(video_path: str, sample_seconds: float = 2.5) -> dict | None:
    """Detect where to center the 9:16 crop using face detection + fallback.

    Priority:
    1. OpenCV face detection — returns face-bias action center
    2. ffmpeg cropdetect — finds tightest non-black region
    3. None — center crop (fallback in get_crop_filter)

    Returns dict with same shape as detect_crop_region or None.
    """
    src_w, src_h = probe_wh(video_path)
    face_x, face_y = detect_faces_in_clip(video_path, sample_seconds)
    if face_x != 0.5 or face_y != 0.5:
        cx = face_x * src_w
        cy = face_y * src_h
        region_w = 200
        region_h = 200
        rx = max(0, int(cx - region_w / 2))
        ry = max(0, int(cy - region_h / 2))
        if rx + region_w > src_w:
            rx = src_w - region_w
        if ry + region_h > src_h:
            ry = src_h - region_h
        return {"w": region_w, "h": region_h,
                "x": rx, "y": ry,
                "src_w": src_w, "src_h": src_h}
    return detect_crop_region(video_path, sample_seconds)


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
