import os
import subprocess
from typing import List, Tuple, Optional

from .config import FFMPEG, FFPROBE, NO_WINDOW


TOLERANCE_SEC = 0.030
MIN_MATCHED_WORDS = 5
SEARCH_WINDOW_MS = 200
ANALYSIS_FPS = 30
MOUTH_OPEN_THRESHOLD = 0.35
HOOK_CARD_SKIP_SEC = 1.5

_face_cascade = None
_profile_cascade = None
_smile_cascade = None


def _log(msg: str):
    print(f"  [lip_sync] {msg}", flush=True)


def _load_cascades():
    """Lazy singleton OpenCV cascade loaders."""
    global _face_cascade, _profile_cascade, _smile_cascade
    if _face_cascade is not None:
        return
    try:
        import cv2
        cascade_dir = os.path.dirname(cv2.data.haarcascades)
        _face_cascade = cv2.CascadeClassifier(os.path.join(cascade_dir, "haarcascade_frontalface_default.xml"))
        _profile_cascade = cv2.CascadeClassifier(os.path.join(cascade_dir, "haarcascade_profileface.xml"))
        _smile_cascade = cv2.CascadeClassifier(os.path.join(cascade_dir, "haarcascade_smile.xml"))
    except Exception as e:
        _log(f"OpenCV cascade load failed: {e}")


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run([
            FFPROBE, "-v", "error", "-show_entries",
            "format=duration", "-of", "csv=p=0", path
        ], capture_output=True, text=True, creationflags=NO_WINDOW)
        return float(r.stdout.strip())
    except (ValueError, TypeError):
        return 0.0


def _decode_frames(clip_path: str, start_sec: float, max_seconds: float, fps: int = ANALYSIS_FPS) -> List["object"]:
    """Decode frames at fps using ffmpeg pipe, starting from start_sec."""
    try:
        import numpy as np
    except ImportError:
        return []

    width, height = 480, 270

    cmd = [
        FFMPEG, "-y", "-v", "error",
        "-ss", f"{start_sec:.3f}",
        "-i", clip_path,
        "-t", f"{max_seconds:.3f}",
        "-vf", f"fps={fps},scale={width}:{height}",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-an",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, timeout=60, creationflags=NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        _log("ffmpeg frame decode timed out")
        return []

    if proc.returncode != 0 or not proc.stdout:
        return []

    frame_size = width * height * 3
    expected = (len(proc.stdout) // frame_size)
    if expected <= 0:
        return []

    arr = np.frombuffer(proc.stdout, dtype=np.uint8).reshape(expected, height, width, 3)
    arr = np.ascontiguousarray(arr)
    return [arr[i].copy() for i in range(expected)]


def _detect_mouth_open(gray_frame) -> float:
    """Detect mouth-activity signal (higher = more mouth movement).

    Uses the lower 40% of the largest detected face as the mouth region.
    Returns std deviation of pixels in that region, normalized to 0-1 range.
    High std = mouth is moving (speech onsets, expression changes).
    """
    if _face_cascade is None:
        return 0.0
    try:
        faces = _face_cascade.detectMultiScale(gray_frame, scaleFactor=1.05, minNeighbors=1, minSize=(30, 30))
        if len(faces) == 0 and _profile_cascade is not None:
            faces = _profile_cascade.detectMultiScale(gray_frame, scaleFactor=1.05, minNeighbors=1, minSize=(30, 30))
        if len(faces) == 0:
            return 0.0
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        mouth_y = y + int(h * 0.55)
        mouth_h = max(4, int(h * 0.40))
        mouth_x = x + int(w * 0.10)
        mouth_w = max(4, int(w * 0.80))
        mouth_roi = gray_frame[mouth_y:mouth_y + mouth_h, mouth_x:mouth_x + mouth_w]
        if mouth_roi.size < 16:
            return 0.0
        std = float(mouth_roi.std())
        return min(1.0, std / 50.0)
    except Exception:
        return 0.0


def _compute_mouth_signal(frames: list) -> Optional["object"]:
    """Run face detection on each frame, return mouth-activity signal at fps."""
    if not frames:
        return None
    try:
        import numpy as np
    except ImportError:
        return None
    import cv2

    signal = np.zeros(len(frames), dtype=np.float32)
    detected = 0

    for i, frame in enumerate(frames):
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            v = _detect_mouth_open(gray)
            if v > 0:
                detected += 1
            signal[i] = v
        except Exception:
            pass

    if detected < int(0.30 * len(frames)):
        _log(f"Face detected in only {detected}/{len(frames)} frames (below 30%), aborting")
        return None
    return signal


def _extract_word_times(clip_transcript: list, max_seconds: float) -> List[Tuple[float, str]]:
    """Pull per-word start times (relative to clip start) from the per-clip transcript."""
    words: List[Tuple[float, str]] = []
    for seg in clip_transcript or []:
        for w in seg.get("words", []) or []:
            try:
                t = float(w.get("start", 0.0))
                txt = (w.get("word") or "").strip()
            except (TypeError, ValueError):
                continue
            if not txt:
                continue
            if t < HOOK_CARD_SKIP_SEC:
                continue
            t_adj = t - HOOK_CARD_SKIP_SEC
            if t_adj > max_seconds:
                continue
            words.append((t_adj, txt))
    words.sort(key=lambda x: x[0])
    return words


def _detect_mouth_events(signal, fps: int = ANALYSIS_FPS) -> List[int]:
    """Return frame indices where the mouth state changes (transitions)."""
    try:
        import numpy as np
    except ImportError:
        return []
    if signal is None or len(signal) < 3:
        return []
    smoothed = signal
    state = (smoothed > MOUTH_OPEN_THRESHOLD).astype(np.int32)
    diffs = np.diff(state)
    transitions = (np.where(diffs != 0)[0] + 1).tolist()
    return [t for t in transitions if 0 <= t < len(signal)]


def _match_words_to_mouth(
    word_times: List[Tuple[float, str]],
    mouth_events: List[int],
    fps: int = ANALYSIS_FPS,
    search_ms: int = SEARCH_WINDOW_MS,
) -> List[Tuple[float, float, float, str]]:
    """For each word, find the nearest mouth event within ±search_ms.

    Returns list of (word_time, matched_event_time, offset_seconds, word_text).
    offset = word_time - event_time. Positive => audio ahead of video.
    """
    if not word_times or not mouth_events:
        return []

    search_frames = int(search_ms / 1000 * fps)
    matched = []
    for wt, wtxt in word_times:
        wf = int(wt * fps)
        best = None
        best_dist = search_frames + 1
        for ev in mouth_events:
            d = abs(ev - wf)
            if d <= search_frames and d < best_dist:
                best = ev
                best_dist = d
        if best is not None:
            et = best / fps
            offset = wt - et
            matched.append((wt, et, offset, wtxt))
    return matched


def _aggregate_median_offset(matches) -> float:
    """Return the median offset, or 0.0 if too few matches."""
    if len(matches) < MIN_MATCHED_WORDS:
        return 0.0
    try:
        import numpy as np
    except ImportError:
        return 0.0
    offsets = np.array([m[2] for m in matches], dtype=np.float32)
    median = float(np.median(offsets))
    if abs(median) > 0.500:
        _log(f"Median offset {median*1000:.0f}ms exceeds 500ms cap, treating as unreliable")
        return 0.0
    return median


def detect_av_offset(
    clip_path: str,
    clip_transcript: list,
    max_seconds: float = 10.0,
) -> float:
    """Detect content-level A/V offset using word-level mouth event matching.

    Args:
        clip_path: path to the rendered clip
        clip_transcript: per-clip transcript with word-level timestamps
                        (each word has 'word', 'start', 'end' relative to clip start)
        max_seconds: how much of the clip to analyze (after the hook card)

    Returns:
        Offset in seconds. Positive = audio ahead of video. Negative = video ahead.
        Returns 0.0 if no face, too few words, or unreliable result.
    """
    if not os.path.exists(clip_path):
        _log(f"clip not found: {clip_path}")
        return 0.0

    _load_cascades()
    if _face_cascade is None or _face_cascade.empty():
        _log("OpenCV face cascade not available, skipping")
        return 0.0

    dur = _probe_duration(clip_path)
    if dur <= 0:
        return 0.0

    if dur <= HOOK_CARD_SKIP_SEC + 1.0:
        _log(f"clip too short ({dur:.1f}s), skipping")
        return 0.0

    analysis_window = min(max_seconds, max(1.0, dur - HOOK_CARD_SKIP_SEC - 0.5))
    word_window = min(max_seconds, max(1.0, dur - HOOK_CARD_SKIP_SEC - 0.5))

    frames = _decode_frames(clip_path, HOOK_CARD_SKIP_SEC, analysis_window, fps=ANALYSIS_FPS)
    if not frames:
        _log("no frames decoded")
        return 0.0
    _log(f"decoded {len(frames)} frames at {ANALYSIS_FPS}fps (t={HOOK_CARD_SKIP_SEC:.1f}s..{HOOK_CARD_SKIP_SEC + analysis_window:.1f}s)")

    signal = _compute_mouth_signal(frames)
    if signal is None:
        return 0.0

    events = _detect_mouth_events(signal, fps=ANALYSIS_FPS)
    _log(f"mouth events detected: {len(events)}")

    word_times = _extract_word_times(clip_transcript, word_window)
    _log(f"words in window: {len(word_times)}")

    if not word_times:
        return 0.0

    matches = _match_words_to_mouth(word_times, events, fps=ANALYSIS_FPS)
    _log(f"word-to-mouth matches: {len(matches)}")
    if matches:
        offsets_ms = [m[2] * 1000 for m in matches]
        offsets_ms_sorted = sorted(offsets_ms)
        med = offsets_ms_sorted[len(offsets_ms_sorted) // 2]
        _log(
            f"  per-word offsets (ms): "
            f"min={min(offsets_ms):+.0f} max={max(offsets_ms):+.0f} "
            f"median={med:+.0f}"
        )

    return _aggregate_median_offset(matches)


def apply_offset(clip_path: str, offset_seconds: float) -> str:
    """Re-encode clip with sample-accurate A/V offset correction.

    Positive offset => delay audio to match video (audio is ahead).
    Negative offset => delay video to match audio (video is ahead).
    """
    if not os.path.exists(clip_path):
        _log(f"clip not found: {clip_path}")
        return clip_path

    if abs(offset_seconds) < TOLERANCE_SEC:
        return clip_path

    tmp = clip_path + ".lipsync.mp4"
    offset_ms = offset_seconds * 1000

    if offset_seconds > 0:
        filter_complex = f"[0:a]aresample=async=1:first_pts=0,adelay={offset_ms:.0f}|{offset_ms:.0f}[a]"
        cmd = [
            FFMPEG, "-y", "-v", "error",
            "-i", clip_path,
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            tmp,
        ]
    else:
        abs_offset = -offset_seconds
        filter_complex = f"[0:v]setpts=PTS+{abs_offset:.3f}/TB[v];[0:a]aresample=async=1:first_pts=0[a]"
        cmd = [
            FFMPEG, "-y", "-v", "error",
            "-i", clip_path,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            tmp,
        ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        _log("ffmpeg offset re-encode timed out")
        if os.path.exists(tmp):
            os.remove(tmp)
        return clip_path

    if r.returncode != 0:
        _log(f"ffmpeg offset FAILED: {r.stderr[:300]}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return clip_path

    os.replace(tmp, clip_path)
    direction = "audio delayed" if offset_seconds > 0 else "video delayed"
    _log(f"applied {offset_seconds*1000:+.0f}ms offset ({direction})")
    return clip_path
