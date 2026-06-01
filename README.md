# REAL MONEY

AI-powered YouTube → vertical short clips with subtitles & background music.

Paste a YouTube URL, get 15–40s vertical (9:16) clips with burned-in subtitles and AI-matched CC0 background music. One-click ZIP download.

## How it works

1. **Download** — yt-dlp pulls the video
2. **Transcribe** — faster-whisper (tiny model, ~1 GB RAM) generates word-level timestamps
3. **Analyze** — Groq API (Llama 3.1 70B, free tier) picks viral moments: `[{start, end, score, reason, mood}]`
4. **Clip** — OpenCV face detection crops to 9:16 center, ffmpeg re-encodes each segment
5. **Subtitle** — SRT → burned-in white text with black outline via ffmpeg drawtext
6. **Music** — mood-matched CC0 track mixed at 12% volume

## Requirements

- Python 3.11+, Node.js 18+
- ffmpeg (≥ 6.0) on PATH
- Groq API key (free at console.groq.com)

## Setup

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # edit .env → paste your Groq API key

# Frontend
cd ../frontend
npm install
```

## Music

Place CC0-licensed .mp3 files in `backend/assets/music/{chill,hype,emotional,funny,serious}/`.
Or run the helper script (auto-downloads some tracks):

```powershell
cd backend
.\download_music.ps1
```

## Run

```bash
# Terminal 1 — backend
cd backend
venv\Scripts\activate
python main.py

# Terminal 2 — frontend
cd frontend
npm run dev
```

Open `http://localhost:3000`, paste a YouTube URL, wait ~30–90s.

## Stack

- **Backend:** Python, FastAPI, yt-dlp, faster-whisper (tiny), OpenCV, ffmpeg
- **AI:** Groq (Llama 3.1 70B) — free tier
- **Frontend:** Next.js 14, Tailwind CSS, TypeScript
