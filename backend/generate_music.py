"""Generate CC0 mood-based background music tracks using numpy + wave.
No external dependencies beyond what's already installed."""

import numpy as np
import wave
import struct
import shutil
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "music"
SAMPLE_RATE = 44100
DURATION = 30
AMPLITUDE = 0.3

def ensure_dirs():
    for mood in ("chill", "hype", "emotional", "funny", "serious"):
        (ASSETS_DIR / mood).mkdir(parents=True, exist_ok=True)

def write_wav(path: Path, samples: np.ndarray):
    samples = np.clip(samples, -1.0, 1.0)
    samples_int = (samples * 32767).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples_int.tobytes())

def sine(freq, t):
    return np.sin(2 * np.pi * freq * t)

def square(freq, t):
    return np.sign(np.sin(2 * np.pi * freq * t))

def saw(freq, t):
    return 2 * (t * freq - np.floor(t * freq + 0.5))

def generate_chill():
    t = np.linspace(0, DURATION, int(SAMPLE_RATE * DURATION), endpoint=False)
    chord = (
        sine(261.63, t) +   # C4
        sine(329.63, t) +   # E4
        sine(392.00, t)     # G4
    ) / 3
    tremolo = 1 + 0.3 * np.sin(2 * np.pi * 0.5 * t)
    noise = np.random.normal(0, 0.02, len(t))
    envelope = np.minimum(t / 2, 1) * np.minimum((DURATION - t) / 2, 1)
    return AMPLITUDE * 0.7 * chord * tremolo * envelope + noise

def generate_hype():
    t = np.linspace(0, DURATION, int(SAMPLE_RATE * DURATION), endpoint=False)
    bass = saw(110.0, t) * 0.4
    stab_freqs = [220.0, 277.18, 329.63]
    stab = sum(square(f, t) for f in stab_freqs) / 3
    pulse = (np.sin(2 * np.pi * 2.13 * t) > 0.5).astype(float)
    envelope = np.minimum(t / 0.5, 1) * np.minimum((DURATION - t) / 2, 1)
    return AMPLITUDE * (bass * 0.5 + stab * 0.3 * pulse + pulse * 0.2) * envelope

def generate_emotional():
    t = np.linspace(0, DURATION, int(SAMPLE_RATE * DURATION), endpoint=False)
    chord = (
        sine(293.66, t) +   # D4
        sine(349.23, t) +   # F4
        sine(440.00, t)     # A4
    ) / 3
    modulation = 1 + 0.2 * np.sin(2 * np.pi * 0.3 * t)
    envelope = np.minimum(t / 3, 1) * np.minimum((DURATION - t) / 4, 1)
    return AMPLITUDE * 0.6 * chord * modulation * envelope

def generate_funny():
    t = np.linspace(0, DURATION, int(SAMPLE_RATE * DURATION), endpoint=False)
    notes = [523.25, 659.25, 783.99, 1046.50, 783.99, 659.25, 523.25]
    note_len = len(t) // len(notes)
    arp = np.zeros_like(t)
    for i, freq in enumerate(notes):
        start = i * note_len
        end = min((i + 1) * note_len, len(t))
        seg = t[start:end] - t[start]
        arp[start:end] = square(freq, seg) * (1 - seg / (note_len / SAMPLE_RATE))
    envelope = np.minimum(t / 1, 1) * np.minimum((DURATION - t) / 1, 1)
    return AMPLITUDE * 0.5 * arp * envelope

def generate_serious():
    t = np.linspace(0, DURATION, int(SAMPLE_RATE * DURATION), endpoint=False)
    drone = sine(55.0, t)  # A1
    pad = (
        saw(110.0, t) +    # A2
        saw(130.81, t) +   # C3
        saw(164.81, t)     # E3
    ) / 3
    sweep = 1 + 0.5 * np.sin(2 * np.pi * 0.15 * t)
    envelope = np.minimum(t / 4, 1) * np.minimum((DURATION - t) / 4, 1)
    return AMPLITUDE * (drone * 0.6 + pad * 0.3 * sweep) * envelope

if __name__ == "__main__":
    ensure_dirs()

    generators = [
        ("chill", "chill_pad.wav", generate_chill),
        ("hype", "hype_rhythm.wav", generate_hype),
        ("emotional", "emotional_pad.wav", generate_emotional),
        ("funny", "funny_arp.wav", generate_funny),
        ("serious", "serious_drone.wav", generate_serious),
    ]
    for mood, filename, gen_fn in generators:
        out_path = ASSETS_DIR / mood / filename
        if out_path.exists():
            print(f"  [SKIP] {mood}/{filename} exists")
            continue
        print(f"  Generating {mood}/{filename}...")
        samples = gen_fn()
        write_wav(out_path, samples)
        print(f"    Done ({len(samples)} samples, {len(samples)/SAMPLE_RATE:.0f}s)")

    total = sum(1 for p in ASSETS_DIR.rglob("*.wav"))
    print(f"\n{total} tracks generated in mood folders:")
    for mood in ("chill", "hype", "emotional", "funny", "serious"):
        count = len(list((ASSETS_DIR / mood).glob("*.wav")))
        print(f"  {mood}: {count}")
