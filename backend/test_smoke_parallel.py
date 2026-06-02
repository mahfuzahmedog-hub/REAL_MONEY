"""Smoke test: confirm orchestrator imports + parallel executor works.

Tests:
1. Module imports cleanly.
2. _save_status + _load_status round-trip on disk.
3. encode_executor has 2 workers.
4. concurrent.futures ThreadPoolExecutor with 2 workers is faster than 1.
"""
import sys, time, os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent))

print("=" * 60)
print("  Parallel Encoding Smoke Test")
print("=" * 60)

# Test 1: import
print("\n[1/4] Importing orchestrator...")
from pipeline.orchestrator import (
    _save_status, _load_status, _statuses, encode_executor,
    PipelineStatus, run_pipeline
)
print("      OK")

# Test 2: status round-trip
print("\n[2/4] Testing persistent status save/load...")
test_id = "smoke_test_status"
test_dir = Path(__file__).parent / "output" / test_id
test_dir.mkdir(parents=True, exist_ok=True)
try:
    s = PipelineStatus()
    s.job_id = test_id
    s.progress = 42
    s.stage = "test_stage"
    s.video_title = "smoke video"
    _save_status(s)
    print(f"      Saved to: output/{test_id}/status.json")

    loaded = _load_status(test_id)
    assert loaded is not None, "load returned None"
    assert loaded.progress == 42, f"progress mismatch: {loaded.progress}"
    assert loaded.stage == "test_stage", f"stage mismatch: {loaded.stage}"
    print(f"      Loaded: progress={loaded.progress}, stage={loaded.stage}")
    print("      OK")
finally:
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)

# Test 3: thread pool
print("\n[3/4] Verifying encode_executor...")
print(f"      encode_executor: {encode_executor}")
print(f"      max_workers: {encode_executor._max_workers}")
assert encode_executor._max_workers == 2, "expected 2 workers"
print("      OK")

# Test 4: simulated parallel work
print("\n[4/4] Simulating parallel clip encoding (5 fake clips, 1s each)...")
def fake_encode(i):
    time.sleep(1.0)
    return i

start = time.time()
with ThreadPoolExecutor(max_workers=2) as ex:
    futs = [ex.submit(fake_encode, i) for i in range(5)]
    results = [f.result() for f in as_completed(futs)]
parallel_time = time.time() - start

start = time.time()
for i in range(5):
    fake_encode(i)
serial_time = time.time() - start

speedup = serial_time / parallel_time
print(f"      Serial:  {serial_time:.2f}s")
print(f"      Parallel (2 workers): {parallel_time:.2f}s")
print(f"      Speedup:  {speedup:.2f}x")
assert speedup > 1.5, f"expected ~1.67x speedup (5 tasks / 2 workers), got {speedup:.2f}x"
print("      OK")

print("\n" + "=" * 60)
print("  All smoke tests passed!")
print("=" * 60)
