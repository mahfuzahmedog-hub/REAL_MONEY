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


def kill_pid(pid: int) -> bool:
    """Force-kill a process. Returns True if it was likely killed.

    Uses ctypes TerminateProcess directly (synchronous, no shell, no
    hang). taskkill on Win11 24H2+ hangs when killing zombie python.exe.
    """
    if sys.platform != "win32":
        try:
            os.kill(pid, 15)
        except Exception:
            pass
        return True
    try:
        import ctypes
        from ctypes import wintypes
        PROCESS_TERMINATE = 0x0001
        kernel32 = ctypes.windll.kernel32
        OpenProcess = kernel32.OpenProcess
        OpenProcess.restype = wintypes.HANDLE
        OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        TerminateProcess = kernel32.TerminateProcess
        TerminateProcess.restype = wintypes.BOOL
        TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        CloseHandle = kernel32.CloseHandle
        CloseHandle.restype = wintypes.BOOL
        CloseHandle.argtypes = [wintypes.HANDLE]
        h = OpenProcess(PROCESS_TERMINATE, False, pid)
        if h:
            ok = TerminateProcess(h, 1)
            CloseHandle(h)
            return bool(ok)
    except Exception:
        pass
    return False


def get_cmdline(pid: int) -> str:
    """Read the full command line of `pid` from its PEB (no WMI / no shell).

    Returns "" on any failure (process gone, access denied, etc.).
    Works on Windows 7+ and 11 24H2+. Uses NtQueryInformationProcess +
    ReadProcessMemory to read RTL_USER_PROCESS_PARAMETERS->CommandLine.
    """
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        PROCESS_BASIC_INFORMATION = 0

        kernel32 = ctypes.windll.kernel32
        ntdll = ctypes.windll.ntdll

        # PEB offsets (64-bit)
        PEB_ProcessParameters_off = 0x20
        RtlUserProcessParameters_CommandLine_off = 0x70

        class UNICODE_STRING(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.USHORT),
                ("MaxLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p),
            ]

        class PROCESS_BASIC_INFORMATION_RAW(ctypes.Structure):
            _fields_ = [
                ("Reserved1", ctypes.c_void_p),
                ("PebBaseAddress", ctypes.c_void_p),
                ("Reserved2", ctypes.c_void_p * 2),
                ("UniqueProcessId", ctypes.c_void_p),
                ("Reserved3", ctypes.c_void_p),
            ]

        NtQueryInformationProcess = ntdll.NtQueryInformationProcess
        NtQueryInformationProcess.restype = wintypes.LONG
        NtQueryInformationProcess.argtypes = [
            wintypes.HANDLE,
            wintypes.ULONG,
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        OpenProcess = kernel32.OpenProcess
        OpenProcess.restype = wintypes.HANDLE
        OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        ReadProcessMemory = kernel32.ReadProcessMemory
        ReadProcessMemory.restype = wintypes.BOOL
        ReadProcessMemory.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        CloseHandle = kernel32.CloseHandle
        CloseHandle.restype = wintypes.BOOL
        CloseHandle.argtypes = [wintypes.HANDLE]

        h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            return ""
        try:
            pbi = PROCESS_BASIC_INFORMATION_RAW()
            retlen = wintypes.ULONG()
            status = NtQueryInformationProcess(
                h, PROCESS_BASIC_INFORMATION,
                ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(retlen),
            )
            if status != 0:
                return ""
            peb = pbi.PebBaseAddress
            if not peb:
                return ""
            # Read PEB to get ProcessParameters pointer
            proc_params_ptr = ctypes.c_void_p()
            n = ctypes.c_size_t()
            if not ReadProcessMemory(h, peb + PEB_ProcessParameters_off,
                                     ctypes.byref(proc_params_ptr),
                                     ctypes.sizeof(proc_params_ptr),
                                     ctypes.byref(n)):
                return ""
            # Read RTL_USER_PROCESS_PARAMETERS to get UNICODE_STRING CommandLine
            cmdline = UNICODE_STRING()
            if not ReadProcessMemory(h, proc_params_ptr.value + RtlUserProcessParameters_CommandLine_off,
                                     ctypes.byref(cmdline),
                                     ctypes.sizeof(cmdline),
                                     ctypes.byref(n)):
                return ""
            if not cmdline.Buffer or cmdline.Length == 0:
                return ""
            # Read the wide string buffer
            buf = ctypes.create_unicode_buffer(cmdline.Length // 2 + 1)
            if not ReadProcessMemory(h, cmdline.Buffer,
                                     ctypes.cast(buf, ctypes.c_void_p),
                                     cmdline.Length,
                                     ctypes.byref(n)):
                return ""
            return buf.value
        finally:
            CloseHandle(h)
    except Exception:
        return ""


def _process_parents(pid: int, max_depth: int = 4) -> set[int]:
    """Return set of PIDs in the ancestor chain of `pid` (up to max_depth)."""
    if sys.platform != "win32":
        return set()
    try:
        import ctypes
        from ctypes import wintypes
        TH32CS_SNAPPROCESS = 0x00000002
        kernel32 = ctypes.windll.kernel32
        CreateToolhelp32Snapshot = kernel32.CreateToolhelp32Snapshot
        CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        Process32FirstW = kernel32.Process32FirstW
        Process32FirstW.restype = wintypes.BOOL
        Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        Process32NextW = kernel32.Process32NextW
        Process32NextW.restype = wintypes.BOOL
        Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        CloseHandle = kernel32.CloseHandle
        CloseHandle.restype = wintypes.BOOL
        CloseHandle.argtypes = [wintypes.HANDLE]

        # PROCESSENTRY32 layout
        class PE32(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]
        snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == wintypes.HANDLE(-1).value:
            return set()
        parent_of = {}
        pe = PE32()
        pe.dwSize = ctypes.sizeof(PE32)
        if not Process32FirstW(snap, ctypes.byref(pe)):
            CloseHandle(snap)
            return set()
        while True:
            parent_of[pe.th32ProcessID] = pe.th32ParentProcessID
            if not Process32NextW(snap, ctypes.byref(pe)):
                break
        CloseHandle(snap)
        # Walk up from pid
        result = {pid}
        cur = pid
        for _ in range(max_depth):
            parent = parent_of.get(cur)
            if not parent or parent in result:
                break
            result.add(parent)
            cur = parent
        return result
    except Exception:
        return set()


def kill_orphans(debug: bool = False) -> int:
    """Kill any stale python.exe that look like ours (REAL_MONEY backend).

    Past shell teardowns can leave orphan webapp processes eating RAM.
    Strategy: use ctypes + PSAPI (always available, fast) to enumerate
    python.exe processes, then check the executable path via the
    ProcessImageFileName Win32 call. Much smaller surface than wmic /
    PowerShell WMI (both slow / deprecated on Win11 24H2+).
    """
    if sys.platform != "win32":
        return 0
    if debug:
        print(f"  [kill_orphans] platform=win32", flush=True)
    try:
        import ctypes
        from ctypes import wintypes
        my_pid = ctypes.windll.kernel32.GetCurrentProcessId()
        my_pid_os = os.getpid()
        if debug:
            print(f"  [kill_orphans] my_pid={my_pid} os.getpid={my_pid_os}", flush=True)
    except Exception as e:
        if debug:
            print(f"  [kill_orphans] ctypes import failed: {e}", flush=True)
        return 0

    psapi = ctypes.windll.psapi
    kernel32 = ctypes.windll.kernel32
    EnumProcesses = psapi.EnumProcesses
    EnumProcesses.restype = wintypes.BOOL
    EnumProcesses.argtypes = [
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    GetProcessImageFileNameW = psapi.GetProcessImageFileNameW
    GetProcessImageFileNameW.restype = wintypes.DWORD
    GetProcessImageFileNameW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_wchar_p,
        wintypes.DWORD,
    ]
    QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
    QueryFullProcessImageNameW.restype = wintypes.BOOL
    QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_wchar_p,
        ctypes.POINTER(wintypes.DWORD),
    ]
    OpenProcess = kernel32.OpenProcess
    OpenProcess.restype = wintypes.HANDLE
    OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    CloseHandle = kernel32.CloseHandle
    CloseHandle.restype = wintypes.BOOL
    CloseHandle.argtypes = [wintypes.HANDLE]
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    pids = (wintypes.DWORD * 4096)()
    cb = wintypes.DWORD()
    if not EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(cb)):
        if debug:
            print(f"  [kill_orphans] EnumProcesses failed", flush=True)
        return 0
    count = cb.value // ctypes.sizeof(wintypes.DWORD)
    if debug:
        print(f"  [kill_orphans] scanning {count} processes", flush=True)
    # Skip ourselves + all our ancestors (in case PIDs are wrapped/mismatched)
    protected_pids = _process_parents(my_pid) | {my_pid}
    if debug:
        print(f"  [kill_orphans] protected={protected_pids}", flush=True)
    # Strict marker: anything launched from this backend dir
    backend_lower = str(BACKEND_DIR).lower()
    webapp_script = str(BACKEND_DIR / "webapp.py").lower()
    killed = 0
    for i in range(count):
        pid = pids[i]
        if not pid or pid in protected_pids:
            continue
        h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            continue
        try:
            buf = ctypes.create_unicode_buffer(512)
            sz = wintypes.DWORD(512)
            if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(sz)):
                path = buf.value
            else:
                # Fallback: device path like \Device\HarddiskVolume3\...
                buf2 = ctypes.create_unicode_buffer(512)
                if GetProcessImageFileNameW(h, buf2, 512):
                    path = buf2.value
                else:
                    path = ""
            if not path:
                continue
            # Real python.exe is something like "...\python.exe" — filter
            if not path.lower().endswith("python.exe"):
                continue
            is_ours = False
            reason = ""
            # (a) Exe path is inside our backend dir (rare — only true for venv pythonw.exe)
            if backend_lower in path.lower():
                is_ours = True
                reason = "exe in backend"
            if not is_ours:
                # (b) Cmdline references our webapp.py — this catches ANY python
                #     interpreter (global Python, Anaconda, venv, etc.) invoking it.
                cmd = get_cmdline(pid)
                if cmd and webapp_script in cmd.lower():
                    is_ours = True
                    reason = f"cmdline hits webapp.py ({cmd[:80]})"
            if is_ours:
                if debug:
                    print(f"  [kill_orphans] ORPHAN: {pid} reason={reason}", flush=True)
                if kill_pid(pid):
                    killed += 1
        finally:
            CloseHandle(h)
    if debug:
        print(f"  [kill_orphans] done, killed {killed}", flush=True)
    return killed


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
    print("[start.py] Cleaning up orphan python processes from previous starts...")
    n = kill_orphans()
    if n:
        print(f"[start.py] Killed {n} orphan process(es).")
        time.sleep(0.5)

    # If a webapp is still listening on the port (e.g. a non-python process,
    # or a python we couldn't identify), abort loudly rather than racing.
    if port_in_use(UI_PORT):
        existing = read_pid()
        if existing is not None:
            print(f"[start.py] Webapp already running on :{UI_PORT} (PID {existing}).")
            print(f"[start.py] Open http://127.0.0.1:{UI_PORT} in your browser.")
            return
        print(f"[start.py] Port {UI_PORT} is in use by another process. Stop it first:")
        print(f"          python start.py --stop")
        sys.exit(1)

    print(f"[start.py] Starting Islamic Hedayet on http://127.0.0.1:{UI_PORT}")

    flags = 0
    if sys.platform == "win32":
        # Use pythonw.exe if available (no console at all -> immune to console-close events)
        python_exe = str(VENV_PYTHON)
        pythonw = VENV_PYTHON.parent / "pythonw.exe"
        if pythonw.exists():
            python_exe = str(pythonw)
        # CREATE_NO_WINDOW alone: process gets a hidden console, NO parent console inheritance.
        # Don't combine with DETACHED_PROCESS (mutually exclusive on Windows).
        # CREATE_NEW_PROCESS_GROUP: immune to CTRL+C from parent's console.
        # CREATE_BREAKAWAY_FROM_JOB: escape parent's job object (required so the webapp
        #   outlives opencode's bash tool closing its PowerShell process).
        CREATE_NO_WINDOW = 0x08000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        flags = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
    else:
        python_exe = str(VENV_PYTHON)

    p = subprocess.Popen(
        [python_exe, "-u", str(BACKEND_DIR / "webapp.py")],
        cwd=str(BACKEND_DIR),
        stdin=subprocess.DEVNULL,
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
    # Don't block on webbrowser.open (it can hang on Windows if the default browser
    # is misconfigured). Fire-and-forget via thread.
    import threading
    def _open_browser():
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=_open_browser, daemon=True).start()
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
