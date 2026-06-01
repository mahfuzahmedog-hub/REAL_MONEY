import subprocess
import cv2
import numpy as np
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

def detect_smart_crop(video_path: str) -> tuple:
    cap = cv2.VideoCapture(video_path)
    faces_x = []
    frame_count = 0
    h, w = 1080, 1920
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if frame_count == 0:
            h, w = frame.shape[:2]
        if frame_count % 5 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            for (x, y, fw, fh) in faces:
                faces_x.append(x + fw // 2)
        frame_count += 1

    cap.release()

    target_w = int(h * 9 / 16)
    if target_w > w:
        target_w = w

    if faces_x and len(faces_x) > 2:
        center_x = int(np.median(faces_x))
        crop_x = max(0, min(center_x - target_w // 2, w - target_w))
    else:
        crop_x = (w - target_w) // 2

    return crop_x, target_w, h

def cut_and_crop_clip(video_path: str, job_id: str, clip_index: int,
                       start: float, end: float, output_dir: str) -> str:
    output_path = Path(output_dir) / f"clip_{clip_index:02d}.mp4"
    temp_path = Path(output_dir) / f"clip_{clip_index:02d}_temp.mp4"

    duration = end - start
    if duration < 0.5:
        raise ValueError(f"Clip too short: {duration}s")

    result = subprocess.run([
        "ffmpeg", "-ss", str(start), "-i", video_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        str(temp_path), "-y"
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg cut failed: {result.stderr[:500]}")

    crop_x, crop_w, crop_h = detect_smart_crop(str(temp_path))

    result = subprocess.run([
        "ffmpeg", "-i", str(temp_path),
        "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:0,scale=608:1080",
        "-c:a", "aac", "-b:a", "128k",
        str(output_path), "-y"
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg crop failed: {result.stderr[:500]}")

    temp_path.unlink(missing_ok=True)
    return str(output_path)
