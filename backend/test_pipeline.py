"""CLI test: start a pipeline run and poll /status until done.

Usage:
    python test_pipeline.py [URL] [NICHE] [--quick]

Requires the FastAPI backend to be running on localhost:8000.
"""
import requests
import time
import sys

args = sys.argv[1:]
quick_mode = "--quick" in args
args = [a for a in args if not a.startswith("--")]

url = args[0] if len(args) > 0 else "https://www.youtube.com/watch?v=jNQXAC9IVRw"
niche = args[1] if len(args) > 1 else "general"

r = requests.post("http://localhost:8000/process", json={"url": url, "niche": niche, "quick_mode": quick_mode})
print(f"Status: {r.status_code}")
if r.status_code != 200:
    print(f"Error: {r.text[:500]}")
    sys.exit(1)

jid = r.json()["job_id"]
print(f"Job ID: {jid}, quick_mode={quick_mode}")

start = time.time()
while True:
    time.sleep(5)
    s = requests.get(f"http://localhost:8000/status/{jid}").json()
    elapsed = int(time.time() - start)
    print(f"  [{elapsed}s] {s['stage']} {s['progress']}%")
    if s.get("done"):
        print(f"\nSUCCESS! {len(s.get('clips', []))} clips generated.")
        for c in s.get("clips", []):
            print(f"  Clip {c['index']}: score={c['viral_score']} mood={c['mood']} hook={c.get('hook_text','')[:60]}")
        break
    if s.get("error"):
        print(f"\nERROR: {s['error']}")
        break
    if elapsed > 600:
        print("\nTIMEOUT after 10 minutes")
        break
