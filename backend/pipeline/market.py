import os
import re
import json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

MARKET_CACHE_PATH = Path(__file__).resolve().parent.parent / "output" / "market_cache.json"
MARKET_CACHE_TTL = 86400

_FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY", "")

_firecrawl_client = None
_firecrawl_unavailable = False

def _get_firecrawl():
    global _firecrawl_client, _firecrawl_unavailable
    if _firecrawl_client is not None:
        return _firecrawl_client
    if _firecrawl_unavailable:
        return None
    if not _FIRECRAWL_KEY or _FIRECRAWL_KEY == "your_firecrawl_api_key_here":
        print("[market] No FIRECRAWL_API_KEY in .env, market analysis disabled", flush=True)
        _firecrawl_unavailable = True
        return None
    try:
        from firecrawl import FirecrawlApp
        _firecrawl_client = FirecrawlApp(api_key=_FIRECRAWL_KEY)
        return _firecrawl_client
    except Exception as e:
        print(f"[market] Firecrawl init failed: {e}", flush=True)
        _firecrawl_unavailable = True
        return None


def _scrape(url: str) -> Optional[dict]:
    client = _get_firecrawl()
    if not client:
        return None
    try:
        result = client.scrape(
            url,
            formats=["markdown"],
            only_main_content=True,
            timeout=30000
        )
        return result
    except Exception as e:
        print(f"[market] Scrape failed for {url}: {e}", flush=True)
        return None


def crawl_youtube_trending(limit: int = 5) -> list:
    """Scrape YouTube trending shorts and return structured data."""
    cached = _load_cache("trending")
    if cached:
        return cached

    urls = [
        "https://www.youtube.com/feed/trending?bp=4gINGgt5dG1hX2NoYXJ0cw%3D%3D",
    ]

    results = []
    for url in urls:
        data = _scrape(url)
        if not data:
            continue
        markdown = data.get("markdown", "") or data.get("content", "")
        titles = _extract_video_titles(markdown)
        for t in titles[:limit]:
            results.append({
                "title": t["title"],
                "channel": t.get("channel", ""),
                "url": t.get("url", ""),
                "source": "trending"
            })

    if results:
        _save_cache("trending", results)
    return results


def crawl_channel(channel_handle: str, limit: int = 10) -> list:
    """Scrape a YouTube channel's Shorts tab and return top videos."""
    cache_key = f"channel_{channel_handle}"
    cached = _load_cache(cache_key)
    if cached:
        return cached

    handle = channel_handle.lstrip("@")
    url = f"https://www.youtube.com/@{handle}/shorts"
    data = _scrape(url)
    if not data:
        return []

    markdown = data.get("markdown", "") or data.get("content", "")
    titles = _extract_video_titles(markdown)

    results = []
    for t in titles[:limit]:
        results.append({
            "title": t["title"],
            "channel": handle,
            "url": t.get("url", ""),
            "source": f"channel:{handle}"
        })

    if results:
        _save_cache(cache_key, results)
    return results


def _extract_video_titles(markdown: str) -> list:
    """Extract video titles and links from YouTube markdown."""
    titles = []
    seen = set()
    lines = markdown.split("\n")
    for line in lines:
        line = line.strip()
        if not line or len(line) < 8:
            continue
        if line.startswith("![") and "](" in line:
            continue
        if "ago" in line and len(line) < 30:
            continue
        url_match = re.search(r'https?://(?:www\.)?youtube\.com/(?:shorts/|watch\?v=)([\w-]{11})', line)
        clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', line)
        clean = re.sub(r'[#*`]', '', clean).strip()
        if not clean or len(clean) < 8 or len(clean) > 200:
            continue
        if clean.lower() in {"trending", "shorts", "music", "gaming", "movies", "news"}:
            continue
        if clean in seen:
            continue
        seen.add(clean)
        titles.append({
            "title": clean,
            "url": url_match.group(0) if url_match else ""
        })
        if len(titles) >= 30:
            break
    return titles


def _extract_hashtags(text: str) -> list:
    return [t.lower() for t in re.findall(r'#\w+', text)]


def _extract_hooks(titles: list) -> list:
    """Identify hook patterns in titles (questions, commands, all caps, etc)."""
    hooks = []
    for t in titles:
        title = t.get("title", "")
        if not title:
            continue
        if "?" in title:
            hooks.append({"pattern": "question", "example": title})
        elif title.isupper() and len(title) > 5:
            hooks.append({"pattern": "all_caps", "example": title})
        elif re.match(r'^(stop|wait|don\'t|never|always)', title, re.I):
            hooks.append({"pattern": "command", "example": title})
        elif any(w in title.lower() for w in ["you won't believe", "shocking", "secret", "truth", "mistake"]):
            hooks.append({"pattern": "curiosity_gap", "example": title})
    return hooks[:10]


def get_market_context(niche: str = "comedy", channel: Optional[str] = None) -> dict:
    """
    Build a market context dict with trending hooks, titles, and patterns
    to feed into Agent prompts.
    """
    context = {
        "niche": niche,
        "trending_titles": [],
        "hook_patterns": [],
        "channel_titles": [],
        "hashtags": []
    }

    try:
        trending = crawl_youtube_trending(limit=10)
        context["trending_titles"] = [t["title"] for t in trending if t.get("title")]
        context["hook_patterns"] = _extract_hooks(trending)
    except Exception as e:
        print(f"[market] Trending crawl failed: {e}", flush=True)

    if channel:
        try:
            channel_data = crawl_channel(channel, limit=10)
            context["channel_titles"] = [t["title"] for t in channel_data if t.get("title")]
            more_hooks = _extract_hooks(channel_data)
            context["hook_patterns"].extend(more_hooks)
        except Exception as e:
            print(f"[market] Channel crawl failed: {e}", flush=True)

    for t in context["trending_titles"] + context["channel_titles"]:
        context["hashtags"].extend(_extract_hashtags(t))
    from collections import Counter
    context["hashtags"] = [h for h, _ in Counter(context["hashtags"]).most_common(10)]

    return context


def format_market_for_prompt(context: dict) -> str:
    """Format the market context as a string to inject into LLM prompts."""
    if not context or not any([context.get("trending_titles"), context.get("channel_titles")]):
        return ""

    parts = ["MARKET CONTEXT (trending reels right now):"]
    if context.get("trending_titles"):
        parts.append("Trending titles:")
        for t in context["trending_titles"][:5]:
            parts.append(f'  - "{t}"')
    if context.get("channel_titles"):
        parts.append(f"Top titles from {context.get('niche', 'this niche')}:")
        for t in context["channel_titles"][:5]:
            parts.append(f'  - "{t}"')
    if context.get("hook_patterns"):
        patterns = list({h["pattern"] for h in context["hook_patterns"]})
        parts.append(f"Hook patterns working: {', '.join(patterns)}")
    if context.get("hashtags"):
        parts.append(f"Popular hashtags: {' '.join(context['hashtags'][:5])}")
    return "\n".join(parts)


def _load_cache(key: str):
    if not MARKET_CACHE_PATH.exists():
        return None
    try:
        all_cache = json.loads(MARKET_CACHE_PATH.read_text())
        entry = all_cache.get(key)
        if not entry:
            return None
        import time
        if time.time() - entry.get("ts", 0) > MARKET_CACHE_TTL:
            return None
        return entry.get("data")
    except Exception:
        return None


def _save_cache(key: str, data):
    try:
        MARKET_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        all_cache = {}
        if MARKET_CACHE_PATH.exists():
            try:
                all_cache = json.loads(MARKET_CACHE_PATH.read_text())
            except Exception:
                all_cache = {}
        import time
        all_cache[key] = {"ts": time.time(), "data": data}
        MARKET_CACHE_PATH.write_text(json.dumps(all_cache, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[market] Cache save failed: {e}", flush=True)
