import os
import subprocess
from .config import FFMPEG, FFPROBE, NO_WINDOW

TOLERANCE = 0.02


def _log(msg: str):
    print(f"  [av_sync] {msg}", flush=True)


def _stream_info(path: str, stream_type: str, index: int = 0) -> dict | None:
    result = subprocess.run([
        FFPROBE, "-v", "error",
        "-select_streams", f"{stream_type}:{index}",
        "-show_entries", "stream=start_time,duration",
        "-of", "csv=p=0",
        path
    ], capture_output=True, text=True, creationflags=NO_WINDOW)
    parts = result.stdout.strip().split(",")
    if not parts or len(parts) < 2 or parts[0] == "N/A" or parts[1] == "N/A":
        return None
    try:
        return {"start": float(parts[0]), "duration": float(parts[1])}
    except (ValueError, IndexError):
        return None


def fix_av_sync(path: str) -> str:
    """Fix A/V sync by trimming both streams to a common content window.

    Probes start_time and duration of video + audio streams, finds the
    overlapping content region, and re-encodes both streams trimmed to
    exactly that region. This eliminates both start-time offsets and
    duration mismatches.
    """
    if not os.path.exists(path):
        _log(f"file not found {path}")
        return path

    vi = _stream_info(path, "v")
    ai = _stream_info(path, "a")

    if vi is None and ai is None:
        _log(f"no video or audio streams in {path}")
        return path
    if vi is None:
        _log(f"{path} has no video stream, skipping")
        return path
    if ai is None:
        _log(f"{path} has no audio stream, skipping")
        return path

    v_start, v_dur = vi["start"], vi["duration"]
    a_start, a_dur = ai["start"], ai["duration"]
    v_end = v_start + v_dur
    a_end = a_start + a_dur

    _log(f"{os.path.basename(path)} probe: v=[{v_start:.6f}..{v_end:.6f}] a=[{a_start:.6f}..{a_end:.6f}]")

    # Find common content window: same content range that both streams cover
    common_start = max(v_start, a_start)
    common_end = min(v_end, a_end)
    common_dur = common_end - common_start

    if common_dur <= 0:
        _log(f"{os.path.basename(path)} no overlapping content window, skipping")
        return path

    start_diff = abs(v_start - a_start)
    dur_diff = abs(v_dur - a_dur)

    if start_diff <= TOLERANCE and dur_diff <= TOLERANCE:
        _log(f"{os.path.basename(path)} in sync (start diff={start_diff:.4f}s dur diff={dur_diff:.4f}s)")
        return path

    msg_parts = []
    if start_diff > TOLERANCE:
        msg_parts.append(f"start offset {start_diff:.4f}s")
    if dur_diff > TOLERANCE:
        msg_parts.append(f"duration diff {dur_diff:.4f}s")
    _log(f"{os.path.basename(path)} FIX: {', '.join(msg_parts)}, common window [{common_start:.4f}..{common_end:.4f}] ({common_dur:.4f}s)")

    tmp = path + ".avfix.mp4"
    vf = f"trim=start={common_start}:end={common_end},setpts=PTS-STARTPTS"
    af = f"atrim=start={common_start}:end={common_end},asetpts=PTS-STARTPTS"
    filter_complex = f"[0:v]{vf}[v];[0:a]{af}[a]"

    r = subprocess.run([
        FFMPEG, "-y", "-v", "error",
        "-i", path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac",
        tmp
    ], capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
    if r.returncode != 0:
        _log(f"ffmpeg fix FAILED for {path}: {r.stderr[:300]}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return path

    os.replace(tmp, path)
    _log(f"FIXED {os.path.basename(path)}")
    return path
