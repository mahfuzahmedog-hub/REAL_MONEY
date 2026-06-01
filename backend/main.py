import os
import uuid
import asyncio
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

class StatusResponse(BaseModel):
    job_id: str

@app.post("/process")
async def process_video(req: ProcessRequest):
    job_id = uuid.uuid4().hex[:12]
    asyncio.create_task(run_pipeline(req.url, job_id))
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    status = get_status(job_id)
    return status

@app.get("/download/{job_id}")
async def download_results(job_id: str):
    status = get_status(job_id)
    if not status.get("download_path"):
        raise HTTPException(404, "File not ready")
    path = status["download_path"]
    if not Path(path).exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, media_type="application/zip",
                        filename=f"realmoney_{job_id}.zip")

@app.get("/health")
async def health():
    return {"status": "ok"}
