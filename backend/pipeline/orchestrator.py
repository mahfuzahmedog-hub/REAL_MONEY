import json
import zipfile
import shutil
import time
import asyncio
from pathlib import Path
from . import downloader, transcriber, ai_analyzer, clipper, subtitler, music, quality

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
MAX_DURATION_SEC = 1800  # 30 minutes — base Whisper on CPU limit
STATUS_TTL_SEC = 1800
MAX_CONCURRENT_JOBS = 1

MIN_CLIPS_FOR_GROQ = 3
ENERGY_FALLBACK_CLIP_COUNT = 5

class PipelineStatus:
    def __init__(self):
        self.progress = 0
        self.stage = "idle"
        self.clips = []
        self.error = None
        self.download_path = None
        self.video_title = None
        self.metadata_path = None
        self.cancelled = False
        self.created_at = time.time()

    def to_dict(self):
        return {
            "progress": self.progress,
            "stage": self.stage,
            "clips": self.clips,
            "error": self.error,
            "download_path": self.download_path,
            "video_title": self.video_title,
            "metadata_path": self.metadata_path,
            "done": self.progress == 100
        }

_statuses: dict[str, PipelineStatus] = {}
_active_job_count = 0

def _stale_cleanup():
    now = time.time()
    stale = [jid for jid, s in _statuses.items()
             if s.progress == 100 and now - s.created_at > STATUS_TTL_SEC]
    for jid in stale:
        _statuses.pop(jid, None)

def get_status(job_id: str) -> dict:
    _stale_cleanup()
    s = _statuses.get(job_id)
    if not s:
        return {"progress": 0, "stage": "not_found", "clips": [], "error": "Job not found", "download_path": None, "video_title": None, "metadata_path": None, "done": False}
    return s.to_dict()

def cancel_job(job_id: str) -> bool:
    s = _statuses.get(job_id)
    if not s or s.done or s.cancelled:
        return False
    s.cancelled = True
    s.error = "Cancelled by user"
    s.stage = "cancelled"
    s.progress = 0
    error_dir = OUTPUT_DIR / job_id
    if error_dir.exists():
        shutil.rmtree(error_dir, ignore_errors=True)
    return True

def cleanup_old_outputs():
    if not OUTPUT_DIR.exists():
        return
    cutoff = time.time() - STATUS_TTL_SEC
    for p in OUTPUT_DIR.iterdir():
        if p.is_dir() and p.stat().st_mtime < cutoff:
            shutil.rmtree(p, ignore_errors=True)
        elif p.suffix == ".zip" and p.stat().st_mtime < cutoff:
            p.unlink(missing_ok=True)

def _energy_clip_to_agent1(ec: dict, index: int) -> dict:
    return {
        "id": f"clip_{index+1:02d}",
        "start": ec["start"],
        "end": ec["end"],
        "duration": ec["duration"],
        "viral_score": round(ec["energy_score"] * 500, 1),
        "score_breakdown": {"H": 0, "C": 0, "P": 0, "S": 0, "E": 0, "R": 0},
        "tier": "B",
        "mood": ec.get("mood", "hype"),
        "reason": f"Energy detection: avg={ec['avg_energy']:.3f}, peak={ec['peak_energy']:.3f}"
    }

async def run_pipeline(url: str, job_id: str, niche: str = "general"):
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
        s.video_title = paths.get("title")
        duration = downloader.get_video_duration(paths["video_path"])
        if duration < 30:
            raise ValueError(f"Video too short ({duration:.0f}s). Minimum 30 seconds.")
        if duration > MAX_DURATION_SEC:
            raise ValueError(
                f"Video too long ({duration/60:.0f} min). "
                f"Maximum {MAX_DURATION_SEC//60} minutes. "
                f"For longer videos, trim to the best section first."
            )
        s.progress = 15

        if s.cancelled:
            return

        s.stage = "transcribing"
        s.progress = 20
        loop = asyncio.get_event_loop()
        transcript = await loop.run_in_executor(None, transcriber.transcribe, paths["audio_path"])
        s.progress = 45

        if s.cancelled:
            return

        s.stage = "analyzing"
        s.progress = 50
        agent1_result = ai_analyzer.analyze_transcript_agent1(transcript, duration, niche=niche)
        agent1_clips = agent1_result.get("clips", [])
        used_energy_fallback = False

        if agent1_result.get("low_confidence") or len(agent1_clips) < MIN_CLIPS_FOR_GROQ:
            s.stage = "energy fallback"
            s.progress = 52
            energy_clips = quality.detect_energy_clips(paths["audio_path"], duration)
            if energy_clips:
                agent1_clips = [_energy_clip_to_agent1(ec, i) for i, ec in enumerate(energy_clips)]
                used_energy_fallback = True

        if not agent1_clips:
            raise ValueError("No clips could be identified. Try a different video.")

        s.progress = 55

        if s.cancelled:
            return

        s.stage = "generating metadata"
        s.progress = 56
        simple_clips = [{"id": c["id"], "start": c["start"], "end": c["end"],
                         "duration": c["duration"], "mood": c.get("mood", "hype")}
                        for c in agent1_clips]
        fallback_mode = used_energy_fallback or agent1_result.get("low_confidence", False)
        agent2_result = ai_analyzer.generate_metadata_agent2(transcript, simple_clips, duration, niche, fallback_mode)
        clips_meta = agent2_result.get("clips", [])

        metadata_lookup = {}
        for c in clips_meta:
            cid = c.get("id", "")
            if cid:
                metadata_lookup[cid] = c
        if used_energy_fallback:
            for c in clips_meta:
                c["fallback_mode"] = True

        s.progress = 60

        if s.cancelled:
            return

        output_dir = OUTPUT_DIR / job_id
        output_dir.mkdir(parents=True, exist_ok=True)

        clip_results = []
        for i, clip in enumerate(agent1_clips):
            if s.cancelled:
                return

            clip_id = clip.get("id", f"clip_{i+1:02d}")
            meta = metadata_lookup.get(clip_id, {})

            clip_start = max(0, clip["start"])
            clip_end = min(clip["end"], duration)
            clip_duration = clip_end - clip_start

            if clip_duration < 7:
                clip_end = min(clip_start + 7, duration)
                clip_duration = clip_end - clip_start
            if clip_duration > 90:
                clip_end = clip_start + 90
            if clip_duration < 7:
                continue

            clip_progress_start = 60
            clip_progress_range = 25
            clip_progress = clip_progress_start + int(
                clip_progress_range * i / max(len(agent1_clips), 1)
            )
            s.stage = f"clipping {i+1}/{len(agent1_clips)}"
            s.progress = clip_progress

            clip_path = clipper.cut_and_crop_clip(
                paths["video_path"], job_id, i,
                clip_start, clip_end, str(output_dir)
            )

            hook_text = meta.get("hook_text", "").replace("**", "").replace("__", "").replace("*", "")
            clip_path = subtitler.burn_subtitles(
                clip_path, transcript, clip_start, clip_end,
                hook_text=hook_text
            )

            mood = meta.get("mood") or clip.get("mood", "chill")
            clip_path = music.mix_music(clip_path, mood)

            s.stage = f"clipping {i+1}/{len(agent1_clips)}"
            s.progress = clip_progress_start + int(
                clip_progress_range * (i + 1) / max(len(agent1_clips), 1)
            )

            viral_score = meta.get("viral_score") or clip.get("viral_score", 0)

            clip_results.append({
                "index": i + 1,
                "id": clip_id,
                "score": round(viral_score, 1),
                "viral_score": round(viral_score, 1),
                "score_breakdown": meta.get("score_breakdown", clip.get("score_breakdown", {"H": 0, "C": 0, "P": 0, "S": 0, "E": 0, "R": 0})),
                "reason": meta.get("reason") or clip.get("reason", ""),
                "mood": mood,
                "duration": round(clip_duration, 1),
                "path": clip_path,
                "filename": Path(clip_path).name,
                "primary_signal": meta.get("primary_signal", ""),
                "hook_text": hook_text,
                "title": meta.get("title", ""),
                "tags": meta.get("tags", []),
                "caption_instagram": meta.get("caption_instagram", ""),
                "caption_tiktok": meta.get("caption_tiktok", ""),
                "caption_youtube": meta.get("caption_youtube", ""),
                "fallback_mode": fallback_mode or meta.get("fallback_mode", False)
            })

        if not clip_results:
            raise ValueError("No valid clips could be created from this video. Try a different video.")

        s.clips = clip_results
        s.progress = 95

        metadata_path = output_dir / "metadata.json"
        metadata_export = []
        for cr in clip_results:
            metadata_export.append({
                "index": cr["index"],
                "id": cr["id"],
                "score": cr["score"],
                "viral_score": cr["viral_score"],
                "score_breakdown": cr["score_breakdown"],
                "reason": cr["reason"],
                "mood": cr["mood"],
                "duration": cr["duration"],
                "filename": cr["filename"],
                "primary_signal": cr["primary_signal"],
                "hook_text": cr["hook_text"],
                "title": cr["title"],
                "tags": cr["tags"],
                "caption_instagram": cr["caption_instagram"],
                "caption_tiktok": cr["caption_tiktok"],
                "caption_youtube": cr["caption_youtube"],
                "fallback_mode": cr["fallback_mode"]
            })
        metadata_path.write_text(json.dumps(metadata_export, indent=2), encoding="utf-8")
        s.metadata_path = str(metadata_path)

        zip_path = OUTPUT_DIR / f"{job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for clip in clip_results:
                clip_file = Path(clip["path"])
                if clip_file.exists():
                    zf.write(clip_file, arcname=clip["filename"])
            if metadata_path.exists():
                zf.write(metadata_path, arcname="metadata.json")

        s.download_path = str(zip_path)
        s.progress = 100
        s.stage = "done"

    except Exception as e:
        if s.cancelled:
            return
        s.error = str(e)
        s.stage = "error"
        s.progress = 0
        error_dir = OUTPUT_DIR / job_id
        if error_dir.exists():
            shutil.rmtree(error_dir, ignore_errors=True)
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
