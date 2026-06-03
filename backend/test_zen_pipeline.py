"""Quick pipeline test with shorter video."""
import asyncio, time, traceback, sys
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from pipeline.orchestrator import run_pipeline, _statuses


async def test():
    url = 'https://www.youtube.com/watch?v=ScMzIvxBSi4'
    job_id = f'zen_test_{int(time.time())}'
    quick_mode = True

    print('=' * 60)
    print('  ZEN CLIENT TEST - Comedy short')
    print('  Niche: comedy')
    print('  Mode: quick_mode=True')
    print('=' * 60)
    print()
    sys.stdout.flush()

    start_wall = time.time()

    try:
        await run_pipeline(url, job_id, niche='comedy', quick_mode=quick_mode)
    except Exception as e:
        print(f'\n[ERROR] Unhandled exception: {e}')
        traceback.print_exc()
        sys.stdout.flush()
        return

    elapsed = time.time() - start_wall
    s = _statuses.get(job_id)

    print(f'\n{"=" * 60}')
    print(f'  PIPELINE COMPLETE ({elapsed:.0f}s = {elapsed/60:.1f} min)')
    print(f'  Stage: {s.stage}')
    print(f'  Progress: {s.progress}%')
    print(f'  Error: {s.error}')
    print(f'{"=" * 60}')

    if s and s.clips:
        print(f'\nClips produced: {len(s.clips)}')
        print(f'{"-" * 80}')
        for c in s.clips:
            print(f'  [{c["id"]}] {c["duration"]}s  score={c["score"]}  mood={c["mood"]}')
            print(f'         hook: {c["hook_text"]}')
            print(f'         reason: {c["reason"][:200]}')
            print(f'         file: {c.get("filename", "N/A")}')
            print()
        print(f'Download ZIP: {s.download_path}')
        print(f'Metadata: {s.metadata_path}')

asyncio.run(test())
