import json
import zipfile
import shutil
from pathlib import Path
from . import downloader, transcriber, ai_analyzer, clipper, subtitler, music

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

class PipelineStatus:
    def __init__(self):
        self.progress = 0
        self.stage = "idle"
        self.clips = []
        self.error = None
        self.download_path = None

    def to_dict(self):
        return {
            "progress": self.progress,
            "stage": self.stage,
            "clips": self.clips,
            "error": self.error,
            "download_path": self.download_path,
            "done": self.progress == 100
        }

_statuses: dict[str, PipelineStatus] = {}

def get_status(job_id: str) -> dict:
    s = _statuses.get(job_id)
    if not s:
        return {"progress": 0, "stage": "not_found", "clips": [], "error": "Job not found", "done": False}
    return s.to_dict()

async def run_pipeline(url: str, job_id: str):
    s = PipelineStatus()
    _statuses[job_id] = s

    paths_to_clean = []

    try:
        s.stage = "validating"
        s.progress = 2
        if not downloader.is_valid_youtube_url(url):
            raise ValueError("Invalid YouTube URL. Please paste a valid youtube.com or youtu.be link.")

        s.stage = "downloading"
        s.progress = 5
        paths = downloader.download_youtube(url, job_id)
        paths_to_clean = [paths["video_path"], paths["audio_path"]]
        duration = downloader.get_video_duration(paths["video_path"])
        if duration < 30:
            raise ValueError(f"Video too short ({duration:.0f}s). Minimum 30 seconds.")
        s.progress = 15

        s.stage = "transcribing"
        s.progress = 20
        transcript = transcriber.transcribe(paths["audio_path"])
        s.progress = 45

        s.stage = "analyzing"
        s.progress = 50
        clips = ai_analyzer.analyze_transcript(transcript, duration)
        s.progress = 60

        output_dir = OUTPUT_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        clip_results = []
        for i, clip in enumerate(clips):
            clip_start = max(0, clip["start"])
            clip_end = min(clip["end"], duration)
            clip_duration = clip_end - clip_start

            if clip_duration < 15:
                clip_end = min(clip_start + 15, duration)
                clip_duration = clip_end - clip_start
            if clip_duration > 40:
                clip_end = clip_start + 40
            if clip_duration < 15:
                continue

            s.stage = f"clipping {i+1}/{len(clips)}"
            s.progress = 60 + int(30 * (i + 1) / len(clips))

            clip_path = clipper.cut_and_crop_clip(
                paths["video_path"], job_id, i,
                clip_start, clip_end, str(output_dir)
            )
            paths_to_clean.append(clip_path)

            clip_path = subtitler.burn_subtitles(
                clip_path, transcript, clip_start, clip_end
            )
            paths_to_clean.append(clip_path)

            clip_path = music.mix_music(clip_path, clip["mood"])
            paths_to_clean.append(clip_path)

            clip_results.append({
                "index": i + 1,
                "score": clip["score"],
                "reason": clip["reason"],
                "mood": clip["mood"],
                "duration": round(clip_duration, 1),
                "path": clip_path,
                "filename": Path(clip_path).name
            })

        if not clip_results:
            raise ValueError("No valid clips could be created from this video. Try a different video.")

        s.clips = clip_results
        s.progress = 95

        zip_path = OUTPUT_DIR / f"{job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for clip in clip_results:
                clip_file = Path(clip["path"])
                if clip_file.exists():
                    zf.write(clip_file, arcname=clip["filename"])

        paths_to_clean.append(str(zip_path))
        s.download_path = str(zip_path)
        s.progress = 100
        s.stage = "done"

    except Exception as e:
        s.error = str(e)
        s.stage = "error"
        s.progress = 0
    finally:
        downloader.cleanup_job_files(job_id, paths_to_clean)
