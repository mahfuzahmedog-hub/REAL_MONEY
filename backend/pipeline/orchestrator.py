import json
import zipfile
import shutil
import time
import asyncio
import tempfile
import os
import atexit
import sys
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .download import downloader, transcriber, windowed
from .analyze import ai_analyzer, quality, subtitler
from .render import clipper, music
from .render import look
from .verify import (
    verify_clip as verify_clip_safety,
    build_report,
    write_report,
    write_manual_review_segments,
    ClipVerification,
    VerificationReport,
)

_log_start = time.time()

def _log(msg: str):
    elapsed = time.time() - _log_start
    try:
        print(f'  [{elapsed:6.1f}s] {msg}', flush=True)
    except UnicodeEncodeError:
        safe = msg.encode('ascii', errors='backslashreplace').decode('ascii')
        print(f'  [{elapsed:6.1f}s] {safe}', flush=True)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
STATUS_TTL_SEC = 1800

MIN_CLIPS_FOR_GROQ = 3

WORK_DIR = tempfile.mkdtemp(prefix="reels_")
atexit.register(shutil.rmtree, WORK_DIR, ignore_errors=True)

processing_semaphore = asyncio.Semaphore(1)

CLIP_ENCODE_WORKERS = 2
encode_executor = ThreadPoolExecutor(max_workers=CLIP_ENCODE_WORKERS)

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
        self.job_id: str | None = None

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

def _stale_cleanup():
    now = time.time()
    stale = [jid for jid, s in _statuses.items()
             if s.progress == 100 and now - s.created_at > STATUS_TTL_SEC]
    for jid in stale:
        _statuses.pop(jid, None)


def _status_path(job_id: str) -> Path:
    return OUTPUT_DIR / job_id / "status.json"


def _save_status(s: "PipelineStatus"):
    try:
        path = _status_path(s.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(s.to_dict(), indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[orchestrator] failed to save status: {e}", flush=True)


def _load_status(job_id: str) -> "PipelineStatus | None":
    path = _status_path(job_id)
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        s = PipelineStatus()
        s.progress = d.get("progress", 0)
        s.stage = d.get("stage", "unknown")
        s.clips = d.get("clips", [])
        s.error = d.get("error")
        s.download_path = d.get("download_path")
        s.video_title = d.get("video_title")
        s.metadata_path = d.get("metadata_path")
        s.cancelled = False
        s.created_at = path.stat().st_mtime
        s.job_id = job_id
        return s
    except Exception:
        return None


def get_status(job_id: str) -> dict:
    _stale_cleanup()
    s = _statuses.get(job_id)
    if s:
        return s.to_dict()
    s = _load_status(job_id)
    if s:
        _statuses[job_id] = s
        return s.to_dict()
    return {"progress": 0, "stage": "not_found", "clips": [], "error": "Job not found", "download_path": None, "video_title": None, "metadata_path": None, "done": False}

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
        "reason": f"Energy detection: avg={ec['avg_energy']:.3f}, peak={ec['peak_energy']:.3f}",
        "caption_hook": ""
    }

async def run_pipeline(url: str, job_id: str, niche: str = "islamic", quick_mode: bool = False, brand_text: str = ""):
    s = PipelineStatus()
    s.job_id = job_id
    _statuses[job_id] = s
    _save_status(s)

    async with processing_semaphore:
        raw_paths = []
        job_dir = os.path.join(WORK_DIR, os.urandom(4).hex())
        os.makedirs(job_dir, exist_ok=True)

        try:
            _log("Stage 1/8: Validating URL...")
            s.stage = "validating"
            s.progress = 2
            if not downloader.is_valid_youtube_url(url):
                raise ValueError("Invalid YouTube URL. Please paste a valid youtube.com or youtu.be link.")

            _log("Stage 2/8: Checking duration...")
            s.stage = "checking duration"
            s.progress = 3
            duration = downloader.check_duration(url)
            s.video_title = url.split("/")[-1]
            _log(f"Duration: {duration:.0f}s ({duration/60:.0f} min), quick_mode={quick_mode}")
            if duration < 30:
                raise ValueError(f"Video too short ({duration:.0f}s). Minimum 30 seconds.")
            _save_status(s)

            if quick_mode and duration > 1200:
                _log("Auto-enabling quick_mode: video > 20 min")
                quick_mode = True

            _log("Stage 3/8: Downloading audio...")
            s.stage = "downloading"
            s.progress = 5
            audio_path = os.path.join(job_dir, "audio.wav")
            downloader.download_audio_only(url, audio_path)
            raw_paths.append(audio_path)
            audio_size = os.path.getsize(audio_path) / (1024 * 1024)
            _log(f"Audio downloaded: {audio_size:.1f} MB")
            s.progress = 15

            if s.cancelled:
                return

            transcript = []
            used_energy_fallback = False

            if quick_mode:
                _log("Stage 4/8 (FAST): Energy detection first, then transcribe candidate windows only")
                s.stage = "energy detect"
                s.progress = 20
                loop = asyncio.get_event_loop()
                energy_clips = await loop.run_in_executor(None, quality.detect_energy_clips, audio_path, duration)
                _log(f"Energy found {len(energy_clips)} candidate windows")
                if not energy_clips:
                    raise ValueError("Energy detection found no candidate clips")

                s.stage = "transcribing windows"
                s.progress = 30
                windows = [{"start": ec["start"], "end": ec["end"]} for ec in energy_clips]
                window_transcripts = await loop.run_in_executor(None, windowed.transcribe_windowed_with_paths, audio_path, windows, job_dir)
                window_segment_counts = sum(1 for wt in window_transcripts if wt.get("segments"))
                _log(f"Windowed transcription: {window_segment_counts}/{len(windows)} windows had speech")
                transcript = []
                for wt in window_transcripts:
                    transcript.extend(wt["segments"])
                transcript.sort(key=lambda s: s["start"])
                s.progress = 50

                agent1_clips = [_energy_clip_to_agent1(ec, i) for i, ec in enumerate(energy_clips)]
                used_energy_fallback = True
                _log(f"Using {len(agent1_clips)} energy clips")

                if len(transcript) >= MIN_CLIPS_FOR_GROQ:
                    _log("Refining with Agent 1 using windowed transcript...")
                    s.stage = "analyzing"
                    s.progress = 45
                    agent1_result = ai_analyzer.analyze_transcript_agent1(transcript, duration, niche=niche)
                    refined = agent1_result.get("clips", [])
                    _save_status(s)
                    if refined and len(refined) >= 3:
                        agent1_clips = refined
                        used_energy_fallback = False
                        _log(f"Agent 1 refined to {len(agent1_clips)} clips")
                    else:
                        _log(f"Agent 1 returned {len(refined)} clips, keeping energy-based selection")
                else:
                    _log(f"Windowed transcript has {len(transcript)} segments, attempting Agent 1 with sparse data")
                    s.stage = "analyzing"
                    s.progress = 45
                    try:
                        agent1_result = ai_analyzer.analyze_transcript_agent1(transcript, duration, niche=niche)
                        refined = agent1_result.get("clips", [])
                        if refined and len(refined) >= 3:
                            agent1_clips = refined
                            used_energy_fallback = False
                            _log(f"Agent 1 (sparse) refined to {len(agent1_clips)} clips")
                        else:
                            _log(f"Agent 1 returned {len(refined)} clips, keeping energy-based selection")
                    except Exception as e:
                        _log(f"Agent 1 (sparse) failed: {e}, keeping energy-based selection")
            else:
                _log("Stage 4/8: Transcribing full audio...")
                s.stage = "transcribing"
                s.progress = 20
                loop = asyncio.get_event_loop()
                transcript = await loop.run_in_executor(None, transcriber.transcribe, audio_path)
                _log(f"Transcription complete: {len(transcript)} segments")
                s.progress = 50

                if s.cancelled:
                    return

                _log("Stage 5/8: Analyzing with Agent 1 (Zen)...")
                s.stage = "analyzing"
                s.progress = 52
                agent1_result = ai_analyzer.analyze_transcript_agent1(transcript, duration, niche=niche)
                agent1_clips = agent1_result.get("clips", [])
                _log(f"Agent 1 found {len(agent1_clips)} clips, low_confidence={agent1_result.get('low_confidence')}")
                _save_status(s)

                if agent1_result.get("low_confidence") or len(agent1_clips) < MIN_CLIPS_FOR_GROQ:
                    _log("Low confidence from Agent 1, running energy fallback...")
                    s.stage = "energy fallback"
                    s.progress = 54
                    energy_clips = quality.detect_energy_clips(audio_path, duration)
                    if energy_clips:
                        agent1_clips = [_energy_clip_to_agent1(ec, i) for i, ec in enumerate(energy_clips)]
                        used_energy_fallback = True
                        _log(f"Energy fallback found {len(energy_clips)} clips")

            if not agent1_clips:
                raise ValueError("No clips could be identified. Try a different video.")

            s.progress = 56

            if s.cancelled:
                return

            _log(f"Stage 6/8: Running video analyzer on {len(agent1_clips)} clips...")
            s.stage = "video analyzer"
            try:
                from .analyze.video_analyzer import analyze_segment
                updated_clips = []
                for c in agent1_clips:
                    clip_start = c["start"]
                    clip_end = c["end"]
                    seg_text = ""
                    for st in transcript:
                        if st["start"] <= clip_end and st["end"] >= clip_start:
                            seg_text += " " + st.get("text", "")
                    va = await loop.run_in_executor(None, analyze_segment, audio_path, clip_start, clip_end, seg_text)
                    c["video_worth"] = va.get("worth_score", 0.5)
                    c["video_laugh"] = va.get("laugh_score", 0)
                    c["video_mood"] = va.get("mood", c.get("mood", "hype"))
                    if va.get("is_worth_clipping"):
                        score_boost = va["worth_score"] * 0.3
                        c["viral_score"] = c.get("viral_score", 50) + score_boost * 10
                    updated_clips.append(c)
                agent1_clips = sorted(updated_clips, key=lambda x: x.get("viral_score", 0), reverse=True)
                _log(f"Video analyzer adjusted {len(agent1_clips)} clips")
            except Exception as e:
                _log(f"Video analyzer skipped: {e}")

            _log(f"Stage 6/8: Generating metadata with Agent 2 (Zen)...")
            s.stage = "generating metadata"
            s.progress = 57
            transcript_text = " ".join(seg.get("text", "") for seg in transcript) if transcript else ""
            detected_scholar = ai_analyzer.detect_scholar_name(transcript_text)
            if detected_scholar:
                _log(f"  Detected scholar: {detected_scholar}")
            simple_clips = [{"id": c["id"], "start": c["start"], "end": c["end"],
                             "duration": c["duration"], "mood": c.get("mood", "scholarly"),
                             "pillar": c.get("pillar", "REMINDER"),
                             "scholar_name": detected_scholar}
                            for c in agent1_clips]
            fallback_mode = used_energy_fallback or (not transcript)
            agent2_result = ai_analyzer.generate_metadata_agent2(
                transcript, simple_clips, duration, niche, fallback_mode,
                scholar_name=detected_scholar,
            )
            clips_meta = agent2_result.get("clips", [])
            _log(f"Agent 2 generated metadata for {len(clips_meta)} clips (fallback_mode={fallback_mode})")
            _save_status(s)

            metadata_lookup = {}
            for c in clips_meta:
                cid = c.get("id", "")
                if cid:
                    metadata_lookup[cid] = c
            if used_energy_fallback:
                for c in clips_meta:
                    c["fallback_mode"] = True

            caption_hook_lookup = {}
            for c in agent1_clips:
                cid = c.get("id", "")
                ch = c.get("caption_hook", "") or ""
                caption_hook_lookup[cid] = ch

            for c in clips_meta:
                cid = c.get("id", "")
                if cid and c.get("hook_text"):
                    caption_hook_lookup[cid] = c["hook_text"]

            _log(f"Stage 6.5/8: Running theological safety verification...")
            s.stage = "theological verification"
            s.progress = 59
            clip_verifications = []
            for c in clips_meta:
                cid = c.get("id", "")
                if not cid:
                    continue
                cv = verify_clip_safety(
                    clip_id=cid,
                    transcript=transcript,
                    clip_start=float(c.get("start", 0)),
                    clip_end=float(c.get("end", 0)),
                    mood=c.get("mood", "scholarly"),
                    hook_text=c.get("hook_text", "") or c.get("title", ""),
                    title=c.get("title", ""),
                    tags=c.get("tags", []),
                    captions={
                        "instagram": c.get("caption_instagram", ""),
                        "tiktok": c.get("caption_tiktok", ""),
                        "youtube": c.get("caption_youtube", ""),
                    },
                )
                clip_verifications.append(cv)
                if cv.needs_manual_review:
                    c["needs_manual_review"] = True
                    c["verification_reasons"] = cv.reasons
                    _log(f"    [FLAG] {cid}: {cv.reasons[:3]}")
                else:
                    _log(f"    [OK] {cid}: {cv.detected_pillar} ({cv.language_detected})")

            report = build_report(job_id, clip_verifications)
            output_dir_path = Path(OUTPUT_DIR) / job_id
            output_dir_path.mkdir(parents=True, exist_ok=True)
            report_path = write_report(report, output_dir_path)
            flagged = [cv for cv in clip_verifications if cv.needs_manual_review]
            review_path = write_manual_review_segments(flagged, output_dir_path)
            _log(f"Verification: {report.passed_clips}/{report.total_clips} passed, {report.flagged_clips} flagged")
            if report_path:
                _log(f"  Report: {report_path}")
            if review_path:
                _log(f"  Manual review: {review_path}")

            s.progress = 60

            if s.cancelled:
                return

            output_dir_path = Path(OUTPUT_DIR) / job_id
            output_dir_path.mkdir(parents=True, exist_ok=True)

            _log(f"Stage 7/8: Downloading full video (720p DASH merge)...")
            s.stage = "downloading video"
            s.progress = 58
            full_video_path = os.path.join(job_dir, "full.mp4")
            downloader.download_full_video(url, full_video_path)
            raw_paths.append(full_video_path)
            video_size = os.path.getsize(full_video_path) / (1024 * 1024)
            _log(f"Full video downloaded: {video_size:.1f} MB")
            s.progress = 62

            def _find_window_audio(clip_start: float) -> str | None:
                if not quick_mode:
                    return None
                for wt in window_transcripts:
                    if abs(wt["start"] - clip_start) < 2.0:
                        return wt.get("audio_path")
                return None

            def _find_window_segments(clip_start: float) -> list:
                if not quick_mode:
                    return []
                for wt in window_transcripts:
                    if abs(wt["start"] - clip_start) < 2.0:
                        return wt.get("segments", [])
                return []

            _log(f"Stage 7/8: Processing {len(agent1_clips)} clips...")
            clip_results = []
            clip_progress_start = 63
            clip_progress_range = 30
            total_clips = len(agent1_clips)

            def _encode_one(i: int, clip: dict):
                if s.cancelled:
                    return None

                clip_id = clip.get("id", f"clip_{i+1:02d}")
                meta = metadata_lookup.get(clip_id, {})
                caption_hook = caption_hook_lookup.get(clip_id, "")

                MIN_CLIP_SEC = 25
                clip_start = max(0, clip["start"])
                clip_end = min(clip["end"], duration)
                clip_duration = clip_end - clip_start

                if clip_duration < MIN_CLIP_SEC:
                    pad = (MIN_CLIP_SEC - clip_duration) / 2
                    clip_start = max(0, clip_start - pad)
                    clip_end = min(duration, clip_end + pad)
                    clip_duration = clip_end - clip_start
                if clip_duration > 90:
                    clip_end = clip_start + 90
                    clip_duration = clip_end - clip_start
                if clip_duration < MIN_CLIP_SEC:
                    _log(f"  Skip clip {i+1}: too short ({clip_duration:.0f}s)")
                    return None

                _log(f"  Clip {i+1}/{total_clips}: {clip_start:.0f}s-{clip_end:.0f}s ({clip_duration:.0f}s) hook='{caption_hook}'")
                s.stage = f"clipping {i+1}/{total_clips}"

                section_path = os.path.join(job_dir, f"section_{i}.mp4")
                try:
                    downloader.cut_clip_from_video(full_video_path, clip_start, clip_end, section_path)
                except Exception as e:
                    _log(f"  Cut failed for clip {i+1}: {e}, trying yt-dlp section")
                    fallback_path = os.path.join(job_dir, f"section_fb_{i}.mp4")
                    try:
                        section_path = downloader.download_clip_section(url, clip_start, clip_end, fallback_path, i)
                    except Exception as e2:
                        _log(f"  yt-dlp fallback also failed for clip {i+1}: {e2}")
                        return None

                clip_audio_path = os.path.join(job_dir, f"clip_audio_{i}.wav")
                clip_transcript = []
                try:
                    from .download.transcriber import transcribe_clip

                    win_audio = _find_window_audio(clip_start)
                    win_segs = _find_window_segments(clip_start)

                    if win_audio and os.path.exists(win_audio) and win_segs:
                        clip_transcript = win_segs
                        _log(f"    Reusing window transcript: {len(clip_transcript)} segments")
                    else:
                        from .config import FFMPEG
                        cut_result = subprocess.run([
                            FFMPEG, "-y", "-v", "error",
                            "-ss", "0", "-i", section_path,
                            "-t", str(clip_duration),
                            "-vn", "-ac", "1", "-ar", "16000",
                            "-c:a", "pcm_s16le",
                            clip_audio_path
                        ], capture_output=True, text=True)
                        if cut_result.returncode == 0 and os.path.getsize(clip_audio_path) > 1024:
                            clip_transcript = transcribe_clip(clip_audio_path)
                            if clip_transcript:
                                _log(f"    Per-clip transcript: {len(clip_transcript)} segments")
                except Exception as e:
                    _log(f"    Per-clip transcription failed: {e}")

                clip_mood = meta.get("mood") or clip.get("mood", "hype")
                if clip_transcript:
                    first_seg = clip_transcript[0]
                    first_t = first_seg.get("start", 0)
                    last_seg = clip_transcript[-1]
                    last_t = last_seg.get("end", 0)
                    if first_t > 100:
                        rebased = []
                        for seg in clip_transcript:
                            reb = {
                                "start": max(0.0, seg["start"] - clip_start),
                                "end": min(clip_duration, seg["end"] - clip_start),
                                "text": seg["text"],
                            }
                            if "words" in seg:
                                reb["words"] = [
                                    {"word": w.get("word", ""),
                                     "start": max(0.0, w.get("start", 0) - clip_start),
                                     "end": min(clip_duration, w.get("end", 0) - clip_start),
                                     "prob": w.get("prob", 1.0)}
                                    for w in seg["words"]
                                ]
                            rebased.append(reb)
                        ass_path = subtitler.write_ass(rebased, 0, clip_duration, str(output_dir_path), meta.get("hook_text", "") or caption_hook, filename=f"subs_{i:02d}.ass", mood=clip_mood)
                    else:
                        ass_path = subtitler.write_ass(clip_transcript, 0, clip_duration, str(output_dir_path), meta.get("hook_text", "") or caption_hook, filename=f"subs_{i:02d}.ass", mood=clip_mood)
                else:
                    ass_path = subtitler.write_ass(transcript, clip_start, clip_end, str(output_dir_path), meta.get("hook_text", "") or caption_hook, filename=f"subs_{i:02d}.ass", mood=clip_mood)
                if not ass_path:
                    ass_path = os.path.join(str(output_dir_path), f"subs_{i:02d}.ass")
                    Path(ass_path).write_text("", encoding="utf-8")
                if not ass_path:
                    ass_path = os.path.join(str(output_dir_path), "subs.ass")
                    Path(ass_path).write_text("", encoding="utf-8")

                music_path = music.pick_track(meta.get("mood") or clip.get("mood", "chill"))

                final_path = os.path.join(str(output_dir_path), f"clip_{i:02d}.mp4")
                reactions = look.find_punchline_reactions(
                    clip_transcript if clip_transcript else transcript,
                    clip_start, clip_duration,
                )
                if reactions:
                    _log(f"    Punchline reactions: {[(r['emoji'], r['t']) for r in reactions]}")
                from .render.framing import detect_action_center
                action_center = detect_action_center(section_path, sample_seconds=min(2.0, clip_duration / 2))
                if action_center:
                    _log(f"    Action center: w={action_center['w']} h={action_center['h']} x={action_center['x']} y={action_center['y']}")
                clipper.process_clip(section_path, ass_path, music_path, caption_hook, final_path, mood=clip_mood, brand_text=brand_text, punchline_reactions=reactions, action_center=action_center)

                final_size = os.path.getsize(final_path) / (1024 * 1024)
                _log(f"  Clip {i+1} done: {final_size:.1f} MB, mood={clip_mood}")

                hook_text = meta.get("hook_text", "").replace("**", "").replace("__", "").replace("*", "")
                viral_score = meta.get("viral_score") or clip.get("viral_score", 0)

                return {
                    "index": i + 1,
                    "id": clip_id,
                    "score": round(viral_score, 1),
                    "viral_score": round(viral_score, 1),
                    "score_breakdown": meta.get("score_breakdown", clip.get("score_breakdown", {"H": 0, "C": 0, "P": 0, "S": 0, "E": 0, "R": 0})),
                    "reason": meta.get("reason") or clip.get("reason", ""),
                    "mood": meta.get("mood") or clip.get("mood", "chill"),
                    "duration": round(clip_duration, 1),
                    "path": final_path,
                    "filename": Path(final_path).name,
                    "primary_signal": meta.get("primary_signal", ""),
                    "hook_text": hook_text,
                    "title": meta.get("title", ""),
                    "tags": meta.get("tags", []),
                    "caption_instagram": meta.get("caption_instagram", ""),
                    "caption_tiktok": meta.get("caption_tiktok", ""),
                    "caption_youtube": meta.get("caption_youtube", ""),
                    "fallback_mode": fallback_mode or meta.get("fallback_mode", False)
                }

            loop = asyncio.get_event_loop()
            futures = [loop.run_in_executor(encode_executor, _encode_one, i, c) for i, c in enumerate(agent1_clips)]
            results = await asyncio.gather(*futures, return_exceptions=True)
            first_error = None
            for result in results:
                if s.cancelled:
                    return
                if isinstance(result, Exception):
                    _log(f"  Worker error: {result}")
                    if first_error is None:
                        first_error = result
                    continue
                if result is not None:
                    clip_results.append(result)
                    done = len(clip_results)
                    s.progress = clip_progress_start + int(
                        clip_progress_range * done / max(total_clips, 1)
                    )
                    s.stage = f"clipped {done}/{total_clips}"
                    _save_status(s)
            if first_error is not None and not clip_results:
                raise first_error

            clip_results.sort(key=lambda r: r["index"])

            if not clip_results:
                raise ValueError("No valid clips could be created from this video. Try a different video.")

            s.clips = clip_results
            s.progress = 95

            _log(f"Stage 8/8: Packaging {len(clip_results)} clips into ZIP...")
            metadata_path = output_dir_path / "metadata.json"
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
            _save_status(s)
            zip_size = os.path.getsize(zip_path) / (1024 * 1024)
            _log(f"Pipeline complete! ZIP: {zip_size:.1f} MB")

        except Exception as e:
            if s.cancelled:
                return
            _log(f"ERROR: {e}")
            s.error = str(e)
            s.stage = "error"
            s.progress = 0
            _save_status(s)
            error_dir = OUTPUT_DIR / job_id
            if error_dir.exists():
                shutil.rmtree(error_dir, ignore_errors=True)
        finally:
            for p in raw_paths:
                try:
                    if os.path.isfile(p):
                        os.unlink(p)
                except Exception:
                    pass
            try:
                shutil.rmtree(job_dir, ignore_errors=True)
            except Exception:
                pass

def get_clip_path(job_id: str, index: int) -> str | None:
    s = _statuses.get(job_id)
    if not s or not s.clips:
        return None
    for clip in s.clips:
        if clip["index"] == index:
            return clip.get("path")
    return None
