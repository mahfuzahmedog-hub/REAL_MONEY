import requests, time, sys, json

URL = "https://www.youtube.com/watch?v=arp0eBn1nG8"
API = "http://127.0.0.1:7860/api"

r = requests.post(f"{API}/process", json={
    "url": URL,
    "niche": "islamic",
    "quick_mode": False,
    "brand_text": "Islamic Hedayet",
    "max_clips": 5,
    "subtitle_style": "creator",
}, timeout=30)
r.raise_for_status()
job = r.json()
job_id = job["job_id"]
print(f"job_id: {job_id}")
print(json.dumps(job, indent=2)[:600])

last_stage = None
start = time.time()
while True:
    s = requests.get(f"{API}/status/{job_id}", timeout=10).json()
    stage, prog, err = s.get("stage"), s.get("progress"), s.get("error")
    elapsed = time.time() - start
    rendered = sum(1 for c in s.get("clips", []) if c.get("path") and __import__("os").path.exists(c["path"]))
    total = len(s.get("clips", []))
    if stage != last_stage:
        print(f"  [{elapsed:5.0f}s] stage={stage}  progress={prog}  rendered={rendered}/{total}")
        last_stage = stage
    if err:
        print(f"ERROR: {err[:500]}")
        sys.exit(1)
    if stage == "done":
        print(f"DONE in {elapsed:.0f}s — {rendered}/{total} clips")
        break
    time.sleep(15)
