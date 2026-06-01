import os
import uuid
import asyncio
import time
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

load_dotenv()

from pipeline.orchestrator import run_pipeline, get_status, OUTPUT_DIR

app = FastAPI(title="REAL MONEY")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProcessRequest(BaseModel):
    url: str

@app.get("/health")
async def health():
    return {"status": "ok", "groq_configured": os.getenv("GROQ_API_KEY") not in (None, "", "your_new_groq_api_key_here")}

@app.post("/process")
async def process_video(req: ProcessRequest):
    if not req.url or not req.url.strip():
        raise HTTPException(400, "URL is required")
    job_id = uuid.uuid4().hex[:12]
    asyncio.create_task(run_pipeline(req.url.strip(), job_id))
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    return get_status(job_id)

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
