import requests, time, sys, json

API = "http://127.0.0.1:7860/api"
URL = "https://www.youtube.com/watch?v=arp0eBn1nG8"

# Submit first job
print("=== JOB 1 ===")
r = requests.post(f"{API}/process", json={
    "url": URL, "niche": "islamic", "quick_mode": False,
    "brand_text": "Islamic Hedayet", "max_clips": 5, "subtitle_style": "creator",
}, timeout=30)
r.raise_for_status()
j1 = r.json()
print(f"job_id: {j1['job_id']}")
print(f"  cancelled_previous: {j1.get('cancelled_previous')}")
print(f"  killed_orphans: {j1.get('killed_orphans')}")

# Watch job 1 for 30s
for i in range(3):
    time.sleep(10)
    s = requests.get(f"{API}/status/{j1['job_id']}", timeout=5).json()
    print(f"  [t={i*10}s] job1: stage={s.get('stage')} progress={s.get('progress')}")

# Submit job 2 (should cancel job 1 and start fresh)
print("\n=== JOB 2 (should kill job 1 + start fresh) ===")
r = requests.post(f"{API}/process", json={
    "url": URL, "niche": "islamic", "quick_mode": True,
    "brand_text": "Islamic Hedayet", "max_clips": 3, "subtitle_style": "creator",
}, timeout=30)
r.raise_for_status()
j2 = r.json()
print(f"job_id: {j2['job_id']}")
print(f"  cancelled_previous: {j2.get('cancelled_previous')}")
print(f"  killed_orphans: {j2.get('killed_orphans')}")

# Check job 1 is cancelled
s1 = requests.get(f"{API}/status/{j1['job_id']}", timeout=5).json()
print(f"\njob1 status: stage={s1.get('stage')} error={s1.get('error')[:50] if s1.get('error') else None}")

# Watch job 2 for 30s
for i in range(3):
    time.sleep(10)
    s = requests.get(f"{API}/status/{j2['job_id']}", timeout=5).json()
    print(f"  [t={i*10}s] job2: stage={s.get('stage')} progress={s.get('progress')}")
