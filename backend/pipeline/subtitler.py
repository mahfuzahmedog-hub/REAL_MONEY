import subprocess
from pathlib import Path

def format_ts(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def build_srt(transcript: list, clip_start: float, clip_end: float) -> str:
    lines = []
    idx = 1
    for seg in transcript:
        seg_start = seg["start"]
        seg_end = seg["end"]
        if seg_end <= clip_start or seg_start >= clip_end:
            continue
        adj_start = max(seg_start, clip_start) - clip_start
        adj_end = min(seg_end, clip_end) - clip_start
        if adj_end - adj_start < 0.5:
            continue
        lines.append(str(idx))
        lines.append(f"{format_ts(adj_start)} --> {format_ts(adj_end)}")
        lines.append(seg["text"])
        lines.append("")
        idx += 1
    return "\n".join(lines)

def burn_subtitles(video_path: str, transcript: list,
                    clip_start: float, clip_end: float) -> str:
    srt_content = build_srt(transcript, clip_start, clip_end)
    if not srt_content.strip():
        return video_path

    srt_path = video_path.replace(".mp4", ".srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    output_path = video_path.replace(".mp4", "_subbed.mp4")

    result = subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vf", f"subtitles={srt_path}:force_style='FontName=Arial,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,MarginV=40'",
        "-c:a", "copy", output_path, "-y"
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Subtitle burn failed: {result.stderr[:500]}")

    Path(srt_path).unlink(missing_ok=True)
    Path(video_path).unlink(missing_ok=True)
    return output_path
