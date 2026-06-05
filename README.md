# Islamic Hedayet

> Local AI pipeline that turns long-form Islamic YouTube lectures into 25-second vertical reels — with burned-in subtitles, AI-matched background music, verified Quran/Hadith, scholar detection, and one-click Instagram posting.

Open the app, paste a YouTube link from a scholar you trust, get 3–4 ready-to-post reels.

## Features

- **Vertical 9:16 output** with face-aware smart-crop
- **Burned-in subtitles** in ASS (bold white text, black outline, green for sacred Arabic) with per-source-language and Arabic Quran/Dua overlays
- **AI clip selection** — Groq `llama-3.1-8b-instant` (free tier) with energy-detect + windowed Whisper for ~5-8 min end-to-end on 45-min videos
- **Auto-detected scholar** — `[Hook] - Mufti Menk`, Arabic tag `مفتي منك`, cross-promo to other channels
- **Verified Quran + Hadith** — only tanzil.net (6,236 verses) and AhmedBaset/hadith-json v1.2.0 (34,178 hadiths). LLM cannot generate fake Arabic.
- **Theological safety check** — 7-point verification per clip, flags anything suspicious for manual review
- **5 Islamic moods** (reflective, motivational, peaceful, scholarly, devotional) → matched CC0 music track per mood
- **Per-clip metadata** — title, tags, hook text, IG/TikTok/YT captions, viral score, mood, calendar relevance
- **One-click Instagram posting** via `instagrapi` (reel upload with caption + retry)
- **Modern web UI** — vanilla HTML/JS/CSS, dark mode, no React/Node, single FastAPI process on port 7860
- **Persistent status** — survives restarts (`output/{job_id}/status.json`)

## Run

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt
copy .env.example .env           # paste your Groq API key(s) (1-4)
python start.py
```

This launches the webapp on http://127.0.0.1:7860 and opens your browser automatically. That's the only process — no separate backend, no separate UI.

```bash
python start.py --status    # is it running?
python start.py --stop      # stop it
```

## Usage

1. Open http://127.0.0.1:7860
2. Paste a YouTube URL from a scholar (e.g. Mufti Menk, Omar Suleiman, Nouman Ali Khan, Yasir Qadhi)
3. **Niche**: `islamic` (default) | `general` | `comedy` | ... | `fitness`
4. **Quick mode** (default on, auto-enabled for videos > 20 min) — energy-detect + windowed Whisper, ~3x faster
5. **Brand text** — watermark at bottom-right of every clip
6. Click **Start**
7. Watch progress: `idle → checking duration → downloading → energy detect → transcribing windows → analyzing → metadata → verifying → rendering → done`
8. Click a clip to preview, or download the ZIP (all clips + `metadata.json`)
9. Optional: open the post modal, click **Post to Instagram** (requires IG login in Settings)

A typical 45-min video: ~5-8 min end-to-end (quick mode).

## Instagram posting

1. Settings → Instagram → enter your username + password
2. If 2FA is on, you'll be prompted for the 6-digit code
3. Session is cached to `backend/.ig_session.json` (gitignored) so you only log in once
4. On a finished job, click the post icon on any clip → caption is auto-filled from `metadata.json` → click **Post**
5. Failures auto-retry once on transient errors (timeout, rate-limit, 5xx)

> **Risk note**: `instagrapi` is an unofficial 3rd-party Instagram client. First login may trigger Meta's "Was this you?" security alert on your account. Use a secondary account if you're worried.

## Project layout

```
backend/
  webapp.py                    # FastAPI on :7860 with /api/* routes
  instagram.py                 # InstagramClient (instagrapi wrapper, session cache)
  start.py                     # Detached launcher (--status, --stop, --help)
  main.py                      # Legacy shim — re-exports webapp.app on :8000
  pipeline_ui.py               # Legacy Gradio UI (kept, not auto-launched)
  start_ui.py                  # Legacy 2-process launcher (kept, not auto-launched)
  static/
    index.html                 # SPA shell (topbar, #app, #toast-container)
    app.js                     # Hash router, views, polling, dark mode, IG modal
    style.css                  # CSS variables, light + dark themes, components
  pipeline/
    orchestrator.py            # Top-level run_pipeline() - ties all 8 stages
    config.py                  # Shared paths (ffmpeg, yt-dlp, fonts)
    download/
      downloader.py            # yt-dlp audio + video (720p DASH merge), get_video_info
      transcriber.py           # Whisper base/int8/VAD
      windowed.py              # Windowed Whisper (energy-driven, quick mode)
      market.py                # Firecrawl trending crawl (optional)
    analyze/
      ai_analyzer.py           # Groq Agent 1 + 2, Islamic prompts, scholar detection
      quality.py               # Energy detection
      subtitler.py             # ASS with HookCard + Watermark + CTACard styles
      zen_client.py            # Groq client (4-key rotation, 4-model tier fallback)
    render/
      clipper.py               # Cut + crop + subtitle burn + hook + music mix
      framing.py               # Face-aware smart-crop
      look.py                  # Color grading
      ocr.py                   # On-screen text OCR (Phase 6, planned)
      music.py                 # CC0 track picker (5 Islamic moods)
    verify/                    # 7-point theological safety check
      __init__.py              # verify_clips() orchestrator
      theology.py              # Pillar classification
      quran_db.py              # tanzil.net loader (6266 verses)
      hadith_db.py             # AhmedBaset loader (34,178 hadiths)
  data/
    quran_verified.json        # Built from tanzil.net
    hadith_verified.json       # Built from AhmedBaset/hadith-json v1.2.0
    build_quran_db.py          # Regenerates quran_verified.json
    build_hadith_db.py         # Regenerates hadith_verified.json
    trusted_channels.json      # 25-channel allowlist
    music_crawler.py           # Phase 5 (planned)
  assets/
    fonts/                     # Amiri (Arabic), NotoSansBengali, NotoSansUrdu
    music/{chill,hype,emotional,funny,serious}/*.wav  # 5 CC0 tracks
  output/
    {job_id}/                  # Per-run: source.mp4, clips/*.mp4, metadata.json, status.json
  tests/                       # Quick smoke tests
  venv/                        # Python venv (gitignored)
  .env                         # 1-4 GROQ_API_KEY values (gitignored)
  .env.example                 # Template with INSTAGRAM_USERNAME/PASSWORD
  requirements.txt             # pinned: instagrapi==2.0.3, pydantic 2.5.3, etc.
  .gitignore                   # + .ig_session.json, start.py.pid, webapp.log, output/
  start.py.pid                 # Runtime PID file (gitignored)
  webapp.log                   # Runtime log (gitignored)
  .ig_session.json             # Runtime IG session (gitignored)
  SHORTS_ANALYSIS.md           # Reference vs generated output comparison
```

## API endpoints

All under `/api/*`. The webapp's own JS uses these; they're stable.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service alive + music track counts |
| POST | `/api/process` | Start pipeline (`{url, niche, quick_mode, brand_text}`) |
| GET | `/api/status/{job_id}` | Live status (stage, progress, clips, error) |
| POST | `/api/cancel/{job_id}` | Cancel running pipeline |
| GET | `/api/clip/{job_id}/{n}` | Stream clip n as video/mp4 |
| GET | `/api/download/{job_id}` | Stream ZIP of all clips + metadata.json |
| GET | `/api/instagram/status` | IG login state |
| POST | `/api/instagram/login` | `{username, password, code?}` |
| POST | `/api/instagram/logout` | Drop session |
| POST | `/api/instagram/post/{job_id}/{n}` | Post clip n as IG reel (`{caption?}`) |

## Pipeline stages (8 total)

1. **Validate URL** — yt-dlp probe
2. **Check duration** — auto-enable quick_mode for > 20 min
2.5 **Fetch source metadata** — channel/uploader for scholar detection
3. **Download audio** — mono 16kHz
4. **Energy detect + windowed Whisper** (FAST, quick mode) — only transcribe high-energy candidate windows
4-alt. **Full Whisper** (slow mode) — transcribe entire audio
5. **AI select (Agent 1)** — Groq picks viral clips with scores, mood, hooks
6. **AI metadata (Agent 2)** — Groq generates titles, tags, captions
6.5 **Theological safety check** — 7-point verification (Quran ref → DB, Hadith ref → DB, no LLM Arabic leak, etc.)
7. **Download full video** (720p DASH merge)
7.5 **Render clips** — 2 parallel ffmpeg workers (cut + crop + burn subtitles + overlay hook + mix music)
8. **Package** — metadata.json + ZIP

## Scholar detection

Built-in allowlist of 17 scholar name patterns (case-insensitive, transcript + source channel/uploader/title). When matched:
- Title: `[Hook] - Mufti Menk`
- Tags: scholar + 3 pillar trending + 1 cross-promo + 1 Arabic scholar name
- Arabic tag: `مفتي منك` (or whichever scholar)

Scholar allowlist covers: Mufti Menk, Omar Suleiman, Nouman Ali Khan, Yasir Qadhi, Mishary Rashid Alafasy, Maher Al-Muaiqly, Muhammad Salah, Hamza Yusuf, Jonathan Brown, Timothy Winter (Abdal Hakim Murad), Yasmin Mogahed, Khalid Yasin, Bilal Philips, Mufti Taqi Usmani, Sheikh Assim Al-Hakeem, Omar Abdel Kafi, Iyad Qarni.

Trusted channels (25): 8 English, 7 Arabic, 5 Bengali, 5 Urdu.

## Stack

- **Backend:** Python 3.11, FastAPI 0.115, Uvicorn, yt-dlp, faster-whisper (base), ffmpeg
- **AI:** Groq (4-key rotation, 4-model tier fallback: `llama-3.1-8b-instant` → `llama-4-scout-17b` → `llama-4-maverick-17b` → `llama-3.3-70b-versatile`)
- **UI:** Vanilla HTML/JS/CSS (zero build step, ~640 lines total)
- **IG posting:** `instagrapi==2.0.3` (3rd-party, unofficial)
- **Verified DBs:** tanzil.net Quran (6,236 verses), AhmedBaset/hadith-json v1.2.0 (34,178 hadiths)

## Requirements

- **Python 3.11+**
- **ffmpeg ≥ 6.0** on PATH (Windows: download from gyan.dev, extract, add `bin/` to PATH)
- **Groq API key(s)** — free at [console.groq.com](https://console.groq.com). 4 keys recommended.
- **8 GB RAM minimum** (tested on Ryzen 5 PRO 2400G + 8 GB)

Optional:
- **Firecrawl API key** — trending context in metadata
- **yt-dlp Deno runtime** — faster YouTube extraction

## License

CC0 for generated music. Code: see LICENSE.
