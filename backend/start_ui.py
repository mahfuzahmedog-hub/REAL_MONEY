"""Launch REAL_MONEY UI: starts FastAPI backend in subprocess, then Gradio UI.

Usage:
    python start_ui.py

Then open http://127.0.0.1:7860 in your browser.
"""
import os
import sys
import time
import signal
import socket
import subprocess
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
API_PORT = int(os.getenv("API_PORT", "8000"))
UI_PORT = int(os.getenv("UI_PORT", "7860"))

VENV_PYTHON = BACKEND_DIR / "venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = sys.executable


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False


def wait_for_backend(timeout: int = 15) -> bool:
    import urllib.request
    import urllib.error
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/health", timeout=2)
            return True
        except (urllib.error.URLError, ConnectionResetError, OSError):
            time.sleep(0.5)
    return False


def main():
    backend_proc = None
    if port_in_use(API_PORT):
        print(f"[start_ui] Backend already on :{API_PORT}, not starting subprocess")
    else:
        print(f"[start_ui] Starting FastAPI backend on :{API_PORT}...")
        backend_proc = subprocess.Popen(
            [str(VENV_PYTHON), str(BACKEND_DIR / "main.py")],
            cwd=str(BACKEND_DIR),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        if not wait_for_backend(timeout=15):
            print(f"[start_ui] Backend failed to start within 15s")
            if backend_proc:
                backend_proc.terminate()
            sys.exit(1)
        print(f"[start_ui] Backend ready (PID {backend_proc.pid})")

    print(f"[start_ui] Starting Gradio UI on :{UI_PORT}...")
    print(f"[start_ui] Open http://127.0.0.1:{UI_PORT} in your browser")
    try:
        subprocess.run(
            [str(VENV_PYTHON), str(BACKEND_DIR / "pipeline_ui.py")],
            cwd=str(BACKEND_DIR),
        )
    finally:
        if backend_proc:
            print("[start_ui] Stopping backend...")
            try:
                backend_proc.terminate()
                backend_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                backend_proc.kill()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        if backend_proc:
            backend_proc.terminate()
