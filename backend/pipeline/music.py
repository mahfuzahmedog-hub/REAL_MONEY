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
        if mood_dir.exists():
            MOOD_TRACKS[mood] = sorted([
                str(f) for f in mood_dir.glob("*.mp3")
            ]) + sorted([
                str(f) for f in mood_dir.glob("*.wav")
            ])

def pick_track(mood: str) -> str | None:
    scan_tracks()
    tracks = MOOD_TRACKS.get(mood, [])
    if not tracks:
        all_tracks = []
        for t_list in MOOD_TRACKS.values():
            all_tracks.extend(t_list)
        if not all_tracks:
            return None
        return random.choice(all_tracks)
    return random.choice(tracks)

def mix_music(video_path: str, mood: str) -> str:
    track = pick_track(mood)
    if not track:
        return video_path

    output_path = video_path.replace(".mp4", "_music.mp4")

    subprocess.run([
        "ffmpeg", "-i", video_path, "-i", track,
        "-filter_complex",
        "[1:a]volume=0.15[a1];[0:a][a1]amix=inputs=2:duration=first[outa]",
        "-map", "0:v", "-map", "[outa]",
        "-c:v", "copy", output_path, "-y"
    ], check=True, capture_output=True)

    Path(video_path).unlink(missing_ok=True)
    return output_path
