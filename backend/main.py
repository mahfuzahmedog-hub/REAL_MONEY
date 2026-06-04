"""Backward-compat shim. The web app now lives in webapp.py.

This module re-exports the FastAPI `app` and runs it on the legacy port 8000
when invoked directly, so existing scripts that do `python main.py` keep
working. New code should use `python start.py` (serves on :7860).
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from webapp import app  # noqa: F401  re-export

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8000"))
    print(f"[main.py] Legacy entry point. Use 'python start.py' for the web UI on :7860.")
    print(f"[main.py] Serving on :{port} (no static UI here).")
    uvicorn.run(app, host="0.0.0.0", port=port)
