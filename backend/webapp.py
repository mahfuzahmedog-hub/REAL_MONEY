"""Islamic Hedayet web app.

Single FastAPI process on port 7860 that:
  - Serves the existing pipeline API (under /api/*)
  - Serves the static SPA (index.html, app.js, style.css)
  - Provides Instagram posting endpoints (added in Step 6)

Scaffolded in Step 1. Full API wiring in Step 2+.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent
STATIC_DIR = BACKEND_DIR / "static"
UI_PORT = int(os.getenv("UI_PORT", "7860"))

@asynccontextmanager
async def lifespan(application: FastAPI):
    yield

app = FastAPI(title="Islamic Hedayet - YouTube to Vertical Shorts", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "ui_port": UI_PORT}


@app.get("/")
async def root():
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return {"error": "static/index.html not found - run Step 1 scaffold first"}
    return FileResponse(index)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=UI_PORT)
