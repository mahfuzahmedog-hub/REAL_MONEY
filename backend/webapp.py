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
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

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

BACKEND_DIR = Path(__file__).resolve().parent
STATIC_DIR = BACKEND_DIR / "static"
UI_PORT = int(os.getenv("UI_PORT", "7860"))


@asynccontextmanager
async def lifespan(application: FastAPI):
    cleanup_old_outputs()
    yield


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
    return {
        "status": "ok",
        "ui_port": UI_PORT,
        "tracks": get_track_counts(),
    }


@app.post("/api/process")
async def process_video(req: ProcessRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(400, "URL is required")
    job_id = uuid.uuid4().hex[:12]
    url = req.url.strip()
    niche = req.niche
    quick_mode = req.quick_mode
    brand_text = req.brand_text
    max_clips = max(1, min(10, int(req.max_clips or 3)))
    subtitle_style = (req.subtitle_style or "reference").lower()
    if subtitle_style not in ("reference", "default"):
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
    try:
        asyncio.run(run_pipeline(
            url, job_id,
            niche=niche, quick_mode=quick_mode, brand_text=brand_text,
            max_clips=max_clips, subtitle_style=subtitle_style,
        ))
    except Exception as e:
        import logging
        logging.getLogger("webapp").exception(f"[pipeline thread] job {job_id} crashed: {e}")


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    return get_status(job_id)


@app.post("/api/cancel/{job_id}")
async def cancel_processing(job_id: str):
    if cancel_job(job_id):
        return {"status": "cancelled"}
    raise HTTPException(400, "Job not found or already completed")


@app.get("/api/clip/{job_id}/{index}")
async def serve_clip(job_id: str, index: int):
    status = get_status(job_id)
    if not status.get("done"):
        raise HTTPException(400, "Processing not complete yet")
    clip_path = get_clip_path(job_id, index)
    if not clip_path or not Path(clip_path).exists():
        raise HTTPException(404, "Clip not found")
    return FileResponse(
        clip_path,
        media_type="video/mp4",
        headers={"Accept-Ranges": "bytes"},
    )


@app.get("/api/download/{job_id}")
async def download_results(job_id: str):
    status = get_status(job_id)
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
    return FileResponse(index)


# ---------- Instagram (Step 6 wire-up — endpoints live, logic lands in Step 6) ----------

class IGLoginRequest(BaseModel):
    username: str
    password: str
    code: str | None = None


class IGPostRequest(BaseModel):
    caption: str | None = None


@app.get("/api/instagram/status")
async def ig_status():
    return get_ig_client().get_status()


@app.post("/api/instagram/login")
async def ig_login(req: IGLoginRequest):
    client = get_ig_client()
    try:
        result = client.login(req.username, req.password, req.code)
        return result
    except NotImplementedError:
        return {"ok": False, "error": "Instagram login not yet implemented (lands in Step 6)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/instagram/logout")
async def ig_logout():
    get_ig_client().logout()
    return {"ok": True}


@app.post("/api/instagram/post/{job_id}/{index}")
async def ig_post(job_id: str, index: int, req: IGPostRequest):
    status = get_status(job_id)
    if not status.get("done"):
        raise HTTPException(400, "Job not complete")
    clip_path = get_clip_path(job_id, index)
    if not clip_path or not Path(clip_path).exists():
        raise HTTPException(404, "Clip not found")
    try:
        result = get_ig_client().post_reel(Path(clip_path), req.caption or "")
        if not result.get("ok") and _is_transient_ig_error(result.get("error", "")):
            logger = logging.getLogger("webapp")
            logger.info(f"[ig] transient error, retrying once: {result.get('error')}")
            time.sleep(2)
            result = get_ig_client().post_reel(Path(clip_path), req.caption or "")
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


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=UI_PORT)
