"""Full pipeline test on a real Islamic YouTube video (84s Mufti Menk)."""
import asyncio
import time
import sys
from pathlib import Path

ROOT = Path("C:/Users/User/Desktop/Ridoy/vs code/REAL_MONEY")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv("C:/Users/User/Desktop/Ridoy/vs code/REAL_MONEY/backend/.env")

from backend.pipeline.orchestrator import run_pipeline, get_status

URL = "https://www.youtube.com/watch?v=uDb3fpJyWXE"
JOB_ID = f"islamic_live_{int(time.time())}"
NICHE = "islamic"
QUICK_MODE = True
BRAND_TEXT = "Islamic Hedayet"


async def main():
    print("=" * 70)
    print(f"Islamic Hedayet - Full Pipeline on Real YouTube Video")
    print(f"URL: {URL}")
    print(f"Job: {JOB_ID}")
    print(f"Niche: {NICHE}, Quick mode: {QUICK_MODE}")
    print("=" * 70)

    t0 = time.time()
    try:
        await run_pipeline(URL, JOB_ID, niche=NICHE, quick_mode=QUICK_MODE, brand_text=BRAND_TEXT)
    except Exception as e:
        print(f"\n[!] Pipeline error: {e}")
        import traceback
        traceback.print_exc()
        return

    elapsed = time.time() - t0
    print(f"\nPipeline finished in {elapsed:.1f}s")
    s = get_status(JOB_ID)
    if s:
        print(f"  Stage: {s.stage}")
        print(f"  Progress: {s.progress}")
        print(f"  Cancelled: {s.cancelled}")


if __name__ == "__main__":
    asyncio.run(main())
