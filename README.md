# REAL MONEY

AI-powered YouTube → vertical short clips with burned-in subtitles, AI-matched background music, and per-clip viral metadata.

Paste a YouTube URL, get 15–90s vertical (9:16) clips with subtitles, hook text overlay, AI-picked viral moments, and platform-specific captions. Free, local, no subscriptions.

## Features

- **Vertical (9:16) output** — ffmpeg smart-crop with face-aware bias
- **Burned-in subtitles** — ASS styled (bold white text, black outline, gold highlight), word-level timing
- **Hook text overlay** — first 2.5s per clip, large yellow text
- **AI-matched music** — mood-picked CC0 tracks, auto-mixed at 8–12% volume
- **AI clip selection** — Groq Llama 4 Scout 17B (free tier) picks viral moments
- **Per-clip metadata** — title, tags, hook text, IG/TikTok/YT captions, viral score
- **Quick mode** — energy-detect + windowed transcription (saves ~3 min on 81-min videos)
- **Parallel encoding** — 2 ffmpeg workers, ~2x faster multi-clip runs
- **Persistent status** — survives server restarts (`output/{job_id}/status.json`)
- **Optional market context** — Firecrawl trending crawl injected into Agent 2 (graceful degrade without API key)

## Pipeline

1. **Download** — yt-dlp pulls audio (mono 16kHz, 3x smaller) and full video (worst quality, fast)
2. **Energy detect** — locate candidate windows from audio energy peaks
3. **Transcribe** — faster-whisper (tiny model, ~1 GB RAM) on the candidate windows
4. **AI select (Agent 1)** — Groq picks viral clips with scores and mood
5. **AI metadata (Agent 2)** — Groq generates per-clip titles, tags, captions
6. **Cut + render** — ffmpeg cuts section, crops to 9:16, burns subtitles + hook, mixes music (2 parallel workers)
7. **Package** — metadata.json + ZIP of all clips

## Requirements

- **Python 3.11+**
- **ffmpeg ≥ 6.0** on PATH (Windows: download from gyan.dev, extract, add `bin/` to PATH)
- **Groq API key(s)** — free at [console.groq.com](https://console.groq.com). 4 keys recommended for the free tier rate limits.
- **8 GB RAM minimum** (tested on Ryzen 5 PRO 2400G + 8 GB)

Optional:
- **Firecrawl API key** — for trending context in metadata. Free at [firecrawl.dev](https://firecrawl.dev).
- **yt-dlp Deno runtime** — speeds up YouTube extraction. `deno` binary on PATH.

## Setup

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
copy .env.example .env         # then paste your Groq API key(s)
```

### `backend/.env`

```env
# 1 to 4 keys. Multiple keys share the rate-limit pool per model.
GROQ_API_KEY=your_key_here
GROQ_API_KEY_2=
GROQ_API_KEY_3=
GROQ_API_KEY_4=

# Optional: trending context for metadata
FIRECRAWL_API_KEY=
```

## Music

Generate CC0 background tracks programmatically (no downloads needed):

```bash
cd backend
venv\Scripts\activate
python generate_music.py
```

Or place your own CC0 .mp3/.wav files in `backend/assets/music/{chill,hype,emotional,funny,serious}/`.

## Run

```bash
cd backend
venv\Scripts\activate
python start_ui.py
```

This launches the FastAPI backend on port 8000 and the Gradio UI on port 7860. Open <http://127.0.0.1:7860> in your browser.

Or run them separately:

```bash
# Terminal 1 - backend
python main.py

# Terminal 2 - UI
python pipeline_ui.py
```

## Usage

1. Open <http://127.0.0.1:7860>
2. Paste a YouTube URL
3. Pick a niche (helps metadata generation)
4. **Quick mode** (default on) — recommended for videos > 20 min. Skips full audio transcription, uses energy-detected windows instead.
5. Click **Start**
6. Watch progress, cancel anytime
7. Click the ZIP file in the gallery to download all clips + metadata.json

A typical 81-min video:
- Quick mode: ~5-8 min end-to-end
- Full mode: ~8-12 min

## Project layout

```
backend/
  main.py                  # FastAPI server (port 8000)
  pipeline_ui.py           # Gradio UI (port 7860)
  start_ui.py              # Launches both
  pipeline/
    orchestrator.py        # Top-level run_pipeline() - ties everything together
    config.py              # Shared paths (ffmpeg, yt-dlp)
    download/              # External fetchers
      downloader.py        # yt-dlp + ffmpeg cut
      transcriber.py       # Whisper tiny
      windowed.py          # Windowed Whisper (energy-driven)
      market.py            # Firecrawl trending crawl
    analyze/               # AI/scoring
      ai_analyzer.py       # Groq Agent 1 + 2
      quality.py           # Energy detection
      subtitler.py         # ASS generation
    render/                # ffmpeg production
      clipper.py           # Crop + subtitle burn + hook + music mix
      music.py             # CC0 track picker
  output/                  # Generated clips + ZIPs (gitignored)
  assets/music/            # CC0 music tracks
  venv/                    # Python venv (gitignored)
```

## Stack

- **Backend:** Python, FastAPI, yt-dlp, faster-whisper (tiny), ffmpeg
- **AI:** Groq (Llama 4 Scout 17B) — free tier, 4 rotating keys
- **UI:** Gradio 4.44
- **Optional:** Firecrawl (trending context)

## License

CC0 for generated music. Code: see LICENSE.
