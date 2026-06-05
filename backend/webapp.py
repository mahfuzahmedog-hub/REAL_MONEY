"""Islamic Hedayet web app.

Single FastAPI process on port 7860 that:
  - Serves the existing pipeline API (under /api/*)
  - Serves the static SPA (index.html, app.js, style.css)
  - Provides Instagram posting endpoints (added in Step 6)
"""
import os
import uuid
import asyncio
import time
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

# Heavy imports are deferred: importing pipeline.orchestrator pulls in Whisper,
# ffmpeg-python, instagrapi, pydantic, Pillow, etc. — all of which can take
# 5-15s on Windows. We want /api/health to respond in <1s so the launcher
# can confirm the server is up before opening the browser.

BACKEND_DIR = Path(__file__).resolve().parent
STATIC_DIR = BACKEND_DIR / "static"
UI_PORT = int(os.getenv("UI_PORT", "7860"))

_heavy_lock = asyncio.Lock()
_heavy_loaded = False
_run_pipeline = None
_get_status = None
_get_clip_path = None
_cancel_job = None
_cleanup_old_outputs = None
_OUTPUT_DIR = None
_get_track_counts = None
_get_ig_client = None


async def _ensure_heavy():
    global _heavy_loaded, _run_pipeline, _get_status, _get_clip_path
    global _cancel_job, _cleanup_old_outputs, _OUTPUT_DIR
    global _get_track_counts, _get_ig_client
    if _heavy_loaded:
        return
    async with _heavy_lock:
        if _heavy_loaded:
            return
        t0 = time.time()
        from pipeline.orchestrator import (
            run_pipeline,
            get_status,
            get_clip_path,
            cancel_job,
            cleanup_old_outputs,
            OUTPUT_DIR,
        )
        from pipeline.render.music import get_track_counts
        from instagram import get_client as get_ig_client
        _run_pipeline = run_pipeline
        _get_status = get_status
        _get_clip_path = get_clip_path
        _cancel_job = cancel_job
        _cleanup_old_outputs = cleanup_old_outputs
        _OUTPUT_DIR = OUTPUT_DIR
        _get_track_counts = get_track_counts
        _get_ig_client = get_ig_client
        _heavy_loaded = True
        print(f"[webapp] heavy modules loaded in {time.time()-t0:.2f}s", flush=True)


@asynccontextmanager
async def lifespan(application: FastAPI):
    import gc
    gc.collect()
    # Schedule heavy-import + cleanup in background so /api/health responds fast.
    asyncio.create_task(_ensure_heavy())
    yield
    gc.collect()


app = FastAPI(title="Islamic Hedayet - YouTube to Vertical Shorts", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessRequest(BaseModel):
    url: str
    niche: str = "islamic"
    quick_mode: bool = False
    brand_text: str = ""
    max_clips: int = 3
    subtitle_style: str = "reference"


@app.get("/api/health")
async def health():
    payload = {
        "status": "ok",
        "ui_port": UI_PORT,
        "ready": _heavy_loaded,
    }
    if _heavy_loaded:
        payload["tracks"] = _get_track_counts()
    return payload


@app.post("/api/process")
async def process_video(req: ProcessRequest):
    await _ensure_heavy()
    if not req.url or not req.url.strip():
        raise HTTPException(400, "URL is required")
    job_id = uuid.uuid4().hex[:12]
    url = req.url.strip()
    niche = req.niche
    quick_mode = req.quick_mode
    brand_text = req.brand_text
    max_clips = max(1, min(10, int(req.max_clips or 3)))
    subtitle_style = (req.subtitle_style or "reference").lower()
    if subtitle_style not in ("reference", "default", "creator"):
        subtitle_style = "reference"
    asyncio.create_task(
        asyncio.to_thread(
            _run_pipeline_in_thread, url, job_id, niche, quick_mode, brand_text, max_clips, subtitle_style
        )
    )
    return {"job_id": job_id}


def _run_pipeline_in_thread(
    url: str, job_id: str, niche: str, quick_mode: bool, brand_text: str,
    max_clips: int = 3, subtitle_style: str = "reference",
) -> None:
    """Run the async pipeline in a fresh event loop on a background thread.

    This keeps the FastAPI event loop free to serve /api/status, /api/clip,
    and other HTTP requests while the (sync-heavy) pipeline is running.
    """
    if _run_pipeline is None:
        logging.error(f"[pipeline thread] _run_pipeline not loaded; job {job_id} aborted")
        return
    try:
        asyncio.run(_run_pipeline(
            url, job_id,
            niche=niche, quick_mode=quick_mode, brand_text=brand_text,
            max_clips=max_clips, subtitle_style=subtitle_style,
        ))
    except Exception as e:
        logging.getLogger("webapp").exception(f"[pipeline thread] job {job_id} crashed: {e}")


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    await _ensure_heavy()
    return _get_status(job_id)


@app.post("/api/cancel/{job_id}")
async def cancel_processing(job_id: str):
    await _ensure_heavy()
    if _cancel_job(job_id):
        return {"status": "cancelled"}
    raise HTTPException(400, "Job not found or already completed")


@app.get("/api/clip/{job_id}/{index}")
async def serve_clip(job_id: str, index: int):
    await _ensure_heavy()
    status = _get_status(job_id)
    if not status.get("done"):
        raise HTTPException(400, "Processing not complete yet")
    clip_path = _get_clip_path(job_id, index)
    if not clip_path or not Path(clip_path).exists():
        raise HTTPException(404, "Clip not found")
    return FileResponse(
        clip_path,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes", "Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/download/{job_id}")
async def download_results(job_id: str):
    await _ensure_heavy()
    status = _get_status(job_id)
    if not status.get("done"):
        raise HTTPException(400, "Processing not complete yet")
    path = status.get("download_path")
    if not path or not Path(path).exists():
        raise HTTPException(404, "Download file not found")
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"islamic_hedayet_{job_id}.zip",
        headers={"Content-Disposition": f'attachment; filename="islamic_hedayet_{job_id}.zip"'},
    )


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return {"error": "static/index.html not found"}
    # Inject a cache-busting query string for app.js and style.css based on
    # the file mtimes. Forces the browser to download the latest version
    # when files change, even if the HTML itself is cached.
    try:
        app_mtime = int((STATIC_DIR / "app.js").stat().st_mtime)
    except Exception:
        app_mtime = 0
    try:
        css_mtime = int((STATIC_DIR / "style.css").stat().st_mtime)
    except Exception:
        css_mtime = 0
    html = index.read_text(encoding="utf-8")
    html = html.replace(
        'href="/static/style.css"',
        f'href="/static/style.css?v={css_mtime}"',
    ).replace(
        'src="/static/app.js"',
        f'src="/static/app.js?v={app_mtime}"',
    )
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


# ---------- Instagram (Step 6 wire-up — endpoints live, logic lands in Step 6) ----------

class IGLoginRequest(BaseModel):
    username: str
    password: str
    code: str | None = None


class IGPostRequest(BaseModel):
    caption: str | None = None


@app.get("/api/instagram/status")
async def ig_status():
    await _ensure_heavy()
    return _get_ig_client().get_status()


@app.post("/api/instagram/login")
async def ig_login(req: IGLoginRequest):
    await _ensure_heavy()
    client = _get_ig_client()
    try:
        result = client.login(req.username, req.password, req.code)
        return result
    except NotImplementedError:
        return {"ok": False, "error": "Instagram login not yet implemented (lands in Step 6)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/instagram/logout")
async def ig_logout():
    await _ensure_heavy()
    _get_ig_client().logout()
    return {"ok": True}


@app.post("/api/instagram/post/{job_id}/{index}")
async def ig_post(job_id: str, index: int, req: IGPostRequest):
    await _ensure_heavy()
    status = _get_status(job_id)
    if not status.get("done"):
        raise HTTPException(400, "Job not complete")
    clip_path = _get_clip_path(job_id, index)
    if not clip_path or not Path(clip_path).exists():
        raise HTTPException(404, "Clip not found")
    try:
        result = _get_ig_client().post_reel(Path(clip_path), req.caption or "")
        if not result.get("ok") and _is_transient_ig_error(result.get("error", "")):
            logger = logging.getLogger("webapp")
            logger.info(f"[ig] transient error, retrying once: {result.get('error')}")
            time.sleep(2)
            result = _get_ig_client().post_reel(Path(clip_path), req.caption or "")
        return result
    except NotImplementedError:
        return {"ok": False, "error": "Instagram post not yet implemented (lands in Step 6)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _is_transient_ig_error(msg: str) -> bool:
    msg = (msg or "").lower()
    return any(
        token in msg
        for token in ["timeout", "rate limit", "try again", "temporarily", "429", "500", "502", "503", "504", "connection"]
    )


# Custom static handler with Cache-Control (FastAPI StaticFiles doesn't set any).
# Use no-cache (must-revalidate) instead of max-age=3600 so the browser always
# revalidates with the server and gets the latest JS/CSS without forcing a
# 304 round-trip on every request. StaticFiles is bypassed entirely.
if STATIC_DIR.exists():
    from fastapi import Request

    @app.get("/static/{path:path}")
    async def static_files(path: str, request: Request):
        target = (STATIC_DIR / path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            raise HTTPException(404, "Not found")
        ext = target.suffix.lower()
        media = {
            ".js": "application/javascript",
            ".css": "text/css",
            ".html": "text/html",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".json": "application/json",
        }.get(ext, "application/octet-stream")
        # no-cache: serve from cache, but MUST revalidate with the server before using
        # the cached copy. Browser still gets 304 Not Modified if unchanged (fast).
        return FileResponse(
            target,
            media_type=media,
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=UI_PORT)
