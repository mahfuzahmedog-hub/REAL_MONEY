import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

load_dotenv()

from pipeline.orchestrator import run_pipeline, get_status, get_clip_path, cancel_job, cleanup_old_outputs, OUTPUT_DIR
from pipeline.music import get_track_counts

@asynccontextmanager
async def lifespan(application: FastAPI):
    cleanup_old_outputs()
    yield

app = FastAPI(title="REAL MONEY", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProcessRequest(BaseModel):
    url: str
    niche: str = "general"
    quick_mode: bool = False
    brand_text: str = ""

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "zen_configured": bool(os.getenv("OPENCODE_API_KEY", "").strip() or os.getenv("OPENCODE_ZEN_API_KEY", "").strip()),
        "music_tracks": get_track_counts()
    }

@app.post("/process")
async def process_video(req: ProcessRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(400, "URL is required")
    job_id = uuid.uuid4().hex[:12]
    asyncio.create_task(run_pipeline(req.url.strip(), job_id, niche=req.niche, quick_mode=req.quick_mode, brand_text=req.brand_text))
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    return get_status(job_id)

@app.post("/cancel/{job_id}")
async def cancel_processing(job_id: str):
    if cancel_job(job_id):
        return {"status": "cancelled"}
    raise HTTPException(400, "Job not found or already completed")

@app.get("/clip/{job_id}/{index}")
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
        headers={"Accept-Ranges": "bytes"}
    )

@app.get("/download/{job_id}")
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
        filename=f"realmoney_{job_id}.zip",
        headers={"Content-Disposition": f'attachment; filename="realmoney_{job_id}.zip"'}
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
