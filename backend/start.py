"""Launch Islamic Hedayet web app.

Single-command launcher:
  - Kills any process on UI_PORT
  - Spawns python webapp.py as a detached subprocess
  - Waits for /api/health to return 200
  - Opens browser to http://127.0.0.1:UI_PORT
  - Writes PID to start.py.pid for clean shutdown

Usage:
  python start.py
  python start.py --stop      # kill the running webapp
  python start.py --status    # check if running
"""
import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
UI_PORT = int(os.getenv("UI_PORT", "7860"))
PID_FILE = BACKEND_DIR / "start.py.pid"
VENV_PYTHON = BACKEND_DIR / "venv" / "Scripts" / "python.exe"

if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False


def kill_pid(pid: int) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def wait_for_health(timeout: int = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{UI_PORT}/api/health", timeout=2)
            return True
        except (urllib.error.URLError, ConnectionResetError, OSError):
            time.sleep(0.5)
    return False


def start() -> None:
    existing = read_pid()
    if existing is not None:
        if port_in_use(UI_PORT):
            print(f"[start.py] Webapp already running on :{UI_PORT} (PID {existing}).")
            print(f"[start.py] Open http://127.0.0.1:{UI_PORT} in your browser.")
            return
        else:
            print(f"[start.py] Stale PID {existing}, removing.")
            PID_FILE.unlink(missing_ok=True)

    if port_in_use(UI_PORT):
        print(f"[start.py] Port {UI_PORT} is in use by another process. Stop it first:")
        print(f"          python start.py --stop")
        sys.exit(1)

    print(f"[start.py] Starting Islamic Hedayet on http://127.0.0.1:{UI_PORT}")

    flags = 0
    if sys.platform == "win32":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW

    p = subprocess.Popen(
        [str(VENV_PYTHON), "-u", str(BACKEND_DIR / "webapp.py")],
        cwd=str(BACKEND_DIR),
        stdout=open(BACKEND_DIR / "webapp.log", "ab"),
        stderr=subprocess.STDOUT,
        creationflags=flags,
        close_fds=True,
    )
    PID_FILE.write_text(str(p.pid), encoding="utf-8")
    print(f"[start.py] Webapp PID: {p.pid} (logs: backend/webapp.log)")

    if not wait_for_health(timeout=20):
        print(f"[start.py] Webapp failed to start within 20s. Check webapp.log")
        kill_pid(p.pid)
        PID_FILE.unlink(missing_ok=True)
        sys.exit(1)

    url = f"http://127.0.0.1:{UI_PORT}"
    print(f"[start.py] Ready at {url}")
    print(f"[start.py] Opening browser...")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(f"[start.py] Press Ctrl+C to stop (or run 'python start.py --stop')")


def stop() -> None:
    pid = read_pid()
    if pid is None:
        print("[start.py] No PID file. Nothing to stop.")
        return
    print(f"[start.py] Killing PID {pid}")
    kill_pid(pid)
    PID_FILE.unlink(missing_ok=True)
    time.sleep(1)
    if port_in_use(UI_PORT):
        print("[start.py] Port still in use. Force:")
        print(f"          taskkill /F /IM python.exe /FI \"PID ne {os.getpid()}\"")
    else:
        print("[start.py] Stopped.")


def status() -> None:
    pid = read_pid()
    running = port_in_use(UI_PORT)
    if running and pid:
        print(f"[start.py] Running on :{UI_PORT} (PID {pid})")
    elif running:
        print(f"[start.py] Port :{UI_PORT} is in use but no PID file (orphan process).")
    else:
        print(f"[start.py] Not running.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stop", action="store_true", help="Stop the running webapp")
    ap.add_argument("--status", action="store_true", help="Check if webapp is running")
    args = ap.parse_args()
    if args.stop:
        stop()
    elif args.status:
        status()
    else:
        start()


if __name__ == "__main__":
    main()
