import subprocess
from pathlib import Path

def find_subtitle_segment(transcript: list, time: float) -> str:
    for seg in transcript:
        if seg["start"] <= time <= seg["end"]:
            return seg["text"]
    return ""

def build_srt(transcript: list, clip_start: float, clip_end: float) -> str:
    srt_lines = []
    index = 1
    for seg in transcript:
        if seg["start"] >= clip_start and seg["end"] <= clip_end:
            adj_start = seg["start"] - clip_start
            adj_end = seg["end"] - clip_start

            start_ts = f"{int(adj_start//3600):02d}:{int((adj_start%3600)//60):02d}:{int(adj_start%60):02d},{int((adj_start%1)*1000):03d}"
            end_ts = f"{int(adj_end//3600):02d}:{int((adj_end%3600)//60):02d}:{int(adj_end%60):02d},{int((adj_end%1)*1000):03d}"

            srt_lines.append(str(index))
            srt_lines.append(f"{start_ts} --> {end_ts}")
            srt_lines.append(seg["text"])
            srt_lines.append("")
            index += 1
    return "\n".join(srt_lines)

def burn_subtitles(video_path: str, transcript: list,
                    clip_start: float, clip_end: float) -> str:
    srt_content = build_srt(transcript, clip_start, clip_end)
    if not srt_content.strip():
        return video_path

    srt_path = video_path.replace(".mp4", "_subs.srt")
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)

    output_path = video_path.replace(".mp4", "_subbed.mp4")

    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vf", f"subtitles={srt_path}:force_style='FontName=Arial,FontSize=14,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1,MarginV=40'",
        "-c:a", "copy", output_path, "-y"
    ], check=True, capture_output=True)

    Path(srt_path).unlink(missing_ok=True)
    Path(video_path).unlink(missing_ok=True)
    return output_path
