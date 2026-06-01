import zipfile
import shutil
import time
import asyncio
from pathlib import Path
from . import downloader, transcriber, ai_analyzer, clipper, subtitler, music

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
MAX_DURATION_SEC = 1800
STATUS_TTL_SEC = 1800
MAX_CONCURRENT_JOBS = 1

class PipelineStatus:
    def __init__(self):
        self.progress = 0
        self.stage = "idle"
        self.clips = []
        self.error = None
        self.download_path = None
        self.created_at = time.time()

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
_active_job_count = 0

def _stale_cleanup():
    now = time.time()
    stale = [jid for jid, s in _statuses.items()
             if s.done and now - s.created_at > STATUS_TTL_SEC]
    for jid in stale:
        _statuses.pop(jid, None)

def get_status(job_id: str) -> dict:
    _stale_cleanup()
    s = _statuses.get(job_id)
    if not s:
        return {"progress": 0, "stage": "not_found", "clips": [], "error": "Job not found", "done": False}
    return s.to_dict()

def cleanup_old_outputs():
    cutoff = time.time() - STATUS_TTL_SEC
    for p in OUTPUT_DIR.iterdir():
        if p.is_dir() and p.stat().st_mtime < cutoff:
            shutil.rmtree(p, ignore_errors=True)
        elif p.suffix == ".zip" and p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)

async def run_pipeline(url: str, job_id: str):
    global _active_job_count

    s = PipelineStatus()
    _statuses[job_id] = s

    if _active_job_count >= MAX_CONCURRENT_JOBS:
        s.error = "Another job is already running. Wait for it to finish, then try again."
        s.stage = "error"
        return

    _active_job_count += 1

    raw_paths = []

    try:
        s.stage = "validating"
        s.progress = 2
        if not downloader.is_valid_youtube_url(url):
            raise ValueError("Invalid YouTube URL. Please paste a valid youtube.com or youtu.be link.")

        s.stage = "downloading"
        s.progress = 5
        paths = downloader.download_youtube(url, job_id)
        raw_paths = [paths["video_path"], paths["audio_path"]]
        duration = downloader.get_video_duration(paths["video_path"])
        if duration < 30:
            raise ValueError(f"Video too short ({duration:.0f}s). Minimum 30 seconds.")
        if duration > MAX_DURATION_SEC:
            raise ValueError(f"Video too long ({duration/60:.0f} min). Maximum {MAX_DURATION_SEC//60} minutes.")
        s.progress = 15

        s.stage = "transcribing"
        s.progress = 20
        loop = asyncio.get_event_loop()
        transcript = await loop.run_in_executor(None, transcriber.transcribe, paths["audio_path"])
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

            clip_path = subtitler.burn_subtitles(
                clip_path, transcript, clip_start, clip_end
            )

            clip_path = music.mix_music(clip_path, clip["mood"])

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

        raw_paths.append(str(zip_path))
        s.download_path = str(zip_path)
        s.progress = 100
        s.stage = "done"

    except Exception as e:
        s.error = str(e)
        s.stage = "error"
        s.progress = 0
    finally:
        downloader.cleanup_job_files(raw_paths)
        _active_job_count -= 1

def get_clip_path(job_id: str, index: int) -> str | None:
    s = _statuses.get(job_id)
    if not s or not s.clips:
        return None
    for clip in s.clips:
        if clip["index"] == index:
            return clip.get("path")
    return None
