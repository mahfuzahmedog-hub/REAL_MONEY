import subprocess
import cv2
import numpy as np
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

def ensure_output_dir(job_id: str):
    d = OUTPUT_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def detect_smart_crop(video_path: str, start: float, end: float) -> tuple:
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    faces_x = []
    frame_count = 0
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )

    while True:
        ret, frame = cap.read()
        if not ret or cap.get(cv2.CAP_PROP_POS_MSEC) / 1000 > end:
            break
        if frame_count % 5 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.1, 4)
            for (x, y, w, h) in faces:
                faces_x.append(x + w // 2)
        frame_count += 1

    cap.release()

    h, w = frame.shape[:2] if frame_count > 0 else (1080, 1920)
    target_w = int(h * 9 / 16)

    if faces_x:
        center_x = int(np.median(faces_x))
        crop_x = max(0, min(center_x - target_w // 2, w - target_w))
    else:
        crop_x = (w - target_w) // 2

    return crop_x, target_w, h

def cut_and_crop_clip(video_path: str, job_id: str, clip_index: int,
                       start: float, end: float, output_dir: str) -> str:
    output_path = Path(output_dir) / f"clip_{clip_index:02d}.mp4"
    temp_path = Path(output_dir) / f"clip_{clip_index:02d}_temp.mp4"

    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-ss", str(start), "-to", str(end),
        "-c", "copy", str(temp_path), "-y"
    ], check=True, capture_output=True)

    crop_x, crop_w, crop_h = detect_smart_crop(str(temp_path), 0, end - start)

    subprocess.run([
        "ffmpeg", "-i", str(temp_path),
        "-vf", f"crop={crop_w}:{crop_h}:{crop_x}:0,scale=608:1080",
        "-c:a", "aac", str(output_path), "-y"
    ], check=True, capture_output=True)

    temp_path.unlink(missing_ok=True)
    return str(output_path)
