import subprocess
import random
from pathlib import Path

TRACKS_DIR = Path(__file__).resolve().parent.parent / "assets" / "music"

MOOD_TRACKS = {
    "chill": [],
    "hype": [],
    "emotional": [],
    "funny": [],
    "serious": [],
}

def scan_tracks():
    for mood in MOOD_TRACKS:
        mood_dir = TRACKS_DIR / mood
        MOOD_TRACKS[mood] = []
        if mood_dir.exists():
            for ext in ("*.mp3", "*.wav", "*.ogg", "*.m4a"):
                MOOD_TRACKS[mood].extend(str(f) for f in mood_dir.glob(ext))

def get_track_counts() -> dict:
    scan_tracks()
    return {mood: len(tracks) for mood, tracks in MOOD_TRACKS.items()}

def pick_track(mood: str):
    scan_tracks()
    tracks = MOOD_TRACKS.get(mood, [])
    if not tracks:
        all_tracks = []
        for t_list in MOOD_TRACKS.values():
            all_tracks.extend(t_list)
        return random.choice(all_tracks) if all_tracks else None
    return random.choice(tracks)

def mix_music(video_path: str, mood: str) -> str:
    track = pick_track(mood)
    if not track:
        return video_path

    output_path = video_path.replace(".mp4", "_music.mp4")

    result = subprocess.run([
        "ffmpeg", "-i", video_path, "-i", track,
        "-filter_complex",
        "[1:a]volume=0.12[a1];[0:a][a1]amix=inputs=2:duration=first[outa]",
        "-map", "0:v", "-map", "[outa]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        output_path, "-y"
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Music mix failed: {result.stderr[:500]}")

    Path(video_path).unlink(missing_ok=True)
    return output_path
