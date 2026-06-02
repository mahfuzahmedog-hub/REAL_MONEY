"""Subpackage: download - everything that fetches from external sources.

Modules:
- downloader: YouTube download via yt-dlp + ffmpeg cut
- transcriber: faster-whisper tiny model
- windowed: windowed Whisper transcription (energy-detect-driven)
- market: Firecrawl trending crawl (graceful degrade without API key)
"""
from . import downloader, transcriber, windowed, market

__all__ = ["downloader", "transcriber", "windowed", "market"]
