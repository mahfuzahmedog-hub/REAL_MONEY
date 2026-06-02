import os
import json
import re
import itertools
from groq import Groq

AGENTS = {
    "clip_finder": {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "temperature": 0.3,
        "max_tokens": 2000
    },
    "metadata_generator": {
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
        "temperature": 0.4,
        "max_tokens": 4000
    }
}

VALID_MOODS = {"chill", "hype", "emotional", "funny", "serious"}

def _normalize_mood(mood: str) -> str:
    if not mood or mood.lower() not in VALID_MOODS:
        return "hype"
    return mood.lower()

_api_keys = []
_key_cycle = None

def _load_keys():
    global _api_keys, _key_cycle
    primary = os.getenv("GROQ_API_KEY", "")
    if primary and primary != "your_new_groq_api_key_here":
        _api_keys.append(primary)
    for i in itertools.count(2):
        k = os.getenv(f"GROQ_API_KEY_{i}")
        if k:
            _api_keys.append(k)
        else:
            break
    if not _api_keys:
        raise ValueError("No GROQ_API_KEY found. Set GROQ_API_KEY in backend/.env")
    _key_cycle = itertools.cycle(range(len(_api_keys)))

def _get_next_client():
    if not _api_keys:
        _load_keys()
    idx = next(_key_cycle)
    return Groq(api_key=_api_keys[idx]), idx

_VIRAL_PROMPT = """You are a viral short-form video editor who deeply understands what performs on Instagram Reels, TikTok, and YouTube Shorts in 2025.

Your job is to find 3-5 clips from this transcript that will perform well as vertical reels.

A great clip MUST have:
- A strong HOOK in the first 3 seconds: a surprising stat, bold/controversial claim, emotional peak, curiosity gap, or provocative statement
- A clear mini arc: setup -> tension/conflict -> payoff or punchline
- Quotable, shareable language — something people would screenshot or repeat
- High energy delivery (favor moments the speaker sounds most confident, fast-paced, or emotionally charged)
- No slow intros, filler words, or topic transitions at the start

For COMEDY content specifically:
- Favor clips with a clear setup and punchline structure
- The punchline should be in the last 5 seconds of the clip
- Look for callbacks, running jokes, or observations the audience reacted to
- caption_hook should be the provocative premise or setup, not the punchline
- Score punchlines that get audience laughter higher on retention and shareability

Scoring criteria (1-10 each):
- hook_strength: how compelling are the first 3 seconds?
- retention: will viewers watch to the end?
- shareability: would someone send this to a friend?

Also generate:
- caption_hook: a punchy on-screen text overlay for the first 2 seconds (max 8 words, all caps, no hashtags)
- mood: one of [hype, chill, emotional, funny, serious]

Respond ONLY with a valid JSON array. No explanation, no markdown, no preamble.
Format: [{"start": float, "end": float, "hook_strength": int, "retention": int, "shareability": int, "reason": str, "mood": str, "caption_hook": str}]

Rules:
- Each clip must be 15-40 seconds long
- Do not pick clips that start mid-sentence or mid-thought
- Prefer clips where total score (hook_strength + retention + shareability) >= 20
- Return clips sorted by total score descending"""

def _clip_array_to_agent1_format(clips: list) -> dict:
    if not clips:
        return {"agent": "1", "low_confidence": True, "clip_count": 0, "clips": []}

    normalized = []
    for i, c in enumerate(clips):
        hs = int(c.get("hook_strength", 0))
        rt = int(c.get("retention", 0))
        sh = int(c.get("shareability", 0))
        total = hs + rt + sh
        normalized.append({
            "id": f"clip_{i+1:02d}",
            "start": max(0.0, float(c.get("start", 0))),
            "end": float(c.get("end", 0)),
            "duration": float(c.get("end", 0)) - max(0.0, float(c.get("start", 0))),
            "viral_score": round(total * 10 / 3, 1),
            "score_breakdown": {"H": hs * 10, "C": 0, "P": rt * 10, "S": sh * 10, "E": 0, "R": 0},
            "tier": "A" if total >= 25 else "B",
            "mood": _normalize_mood(c.get("mood", "")),
            "reason": c.get("reason", "Viral moment"),
            "caption_hook": c.get("caption_hook", "")
        })

    high_enough = sum(1 for c in normalized if c["viral_score"] >= 20)
    low_confidence = high_enough < 3

    return {
        "agent": "1",
        "low_confidence": low_confidence,
        "clip_count": len(normalized),
        "clips": normalized
    }

HARD_RULES = "CRITICAL: Output MUST be valid JSON array only. No markdown, no code fences, no explanation."

def _call_groq(system_prompt: str, user_message: str, agent_key: str, retry_on_fail: bool = True):
    cfg = AGENTS[agent_key]

    num_keys = len(_api_keys) if _api_keys else 1
    last_error = None
    for attempt in range(num_keys):
        client, key_idx = _get_next_client()
        try:
            response = client.chat.completions.create(
                model=cfg["model"],
                messages=[
                    {"role": "system", "content": system_prompt + "\n\n" + HARD_RULES},
                    {"role": "user", "content": user_message}
                ],
                temperature=cfg["temperature"],
                max_tokens=cfg["max_tokens"]
            )
        except Exception as e:
            err_str = str(e)
            last_error = err_str
            if "429" in err_str or "413" in err_str:
                continue
            raise

        content = response.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        return _parse_groq_response(content, system_prompt, user_message, agent_key, retry_on_fail)

    raise RuntimeError(f"All Groq API keys exhausted. Last error: {last_error[:200]}")

def _parse_groq_response(content: str, system_prompt: str, user_message: str, agent_key: str, retry_on_fail: bool):
    content = content.strip()

    if not content:
        raise ValueError("AI returned empty response")

    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        if not retry_on_fail:
            raise ValueError(f"AI returned invalid JSON: {str(e)[:200]}")
        cfg = AGENTS[agent_key]
        client, _ = _get_next_client()
        response = client.chat.completions.create(
            model=cfg["model"],
            messages=[
                {"role": "system", "content": system_prompt + "\n\nCRITICAL: You MUST return ONLY valid JSON. No explanation, no markdown, no code fences."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.1,
            max_tokens=cfg["max_tokens"]
        )
        content = response.choices[0].message.content.strip()
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content)

def _chunk_transcript(transcript: list, chunk_chars: int = 12000) -> list:
    if not transcript:
        return []
    full_text = "\n".join(
        f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}"
        for s in transcript
    )
    if len(full_text) <= chunk_chars:
        return [transcript]

    chunks = []
    chunk_segs = []
    chunk_len = 0
    overlap_chars = int(chunk_chars * 0.2)

    i = 0
    while i < len(transcript):
        seg = transcript[i]
        line = f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}\n"
        chunk_segs.append(seg)
        chunk_len += len(line)

        if chunk_len >= chunk_chars:
            chunks.append(chunk_segs[:])
            overlap_len = 0
            j = len(chunk_segs) - 1
            while j >= 0 and overlap_len < overlap_chars:
                back_line = f"[{chunk_segs[j]['start']:.1f}s - {chunk_segs[j]['end']:.1f}s] {chunk_segs[j]['text']}\n"
                overlap_len += len(back_line)
                j -= 1
            overlap_start = j + 1
            chunk_segs = chunk_segs[overlap_start:]
            chunk_len = sum(
                len(f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}\n")
                for s in chunk_segs
            )
        i += 1

    if chunk_segs:
        chunks.append(chunk_segs)

    return chunks

def _format_transcript(transcript: list, max_chars: int = 15000) -> str:
    text = "\n".join(
        f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}"
        for s in transcript
    )
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text

def analyze_transcript_agent1(
    transcript: list, duration: float,
    niche: str = "general", platform: str = "all"
) -> dict:

    if not transcript:
        return {"agent": "1", "low_confidence": True, "clip_count": 0, "clips": []}

    from .transcriber import filter_segments
    from . import market
    market_context_str = ""
    try:
        market_ctx = market.get_market_context(niche=niche)
        market_context_str = market.format_market_for_prompt(market_ctx)
    except Exception as e:
        print(f"[ai] market context fetch failed: {e}", flush=True)

    transcript_text = filter_segments(transcript, max_chars=6000)

    if not transcript_text.strip():
        return {"agent": "1", "low_confidence": True, "clip_count": 0, "clips": []}

    chunks = _chunk_transcript(transcript, chunk_chars=12000)

    all_raw_clips = []
    any_failed = False

    for chunk in chunks:
        chunk_text = filter_segments(chunk, max_chars=6000)
        market_block = f"\n\n{market_context_str}" if market_context_str else ""
        user_message = (
            f"NICHE: {niche}\nPLATFORM: {platform}\nDURATION: {duration:.0f}"
            f"{market_block}"
            f"\n\nTRANSCRIPT:\n{chunk_text}"
        )
        try:
            data = _call_groq(_VIRAL_PROMPT, user_message, "clip_finder")
        except Exception:
            any_failed = True
            continue

        if isinstance(data, list):
            all_raw_clips.extend(data)
        elif isinstance(data, dict) and "clips" in data:
            all_raw_clips.extend(data["clips"])

    if not all_raw_clips:
        all_raw_clips = [
            {"start": max(0, duration * 0.1 * i), "end": min(duration, duration * 0.1 * (i + 2)),
             "hook_strength": 5, "retention": 5, "shareability": 5,
             "reason": "Energy-based fallback", "mood": "hype", "caption_hook": "TOP MOMENT"}
            for i in range(3)
        ]
        any_failed = True

    result = _clip_array_to_agent1_format(all_raw_clips)

    if any_failed and result.get("clip_count", 0) < 3:
        result["low_confidence"] = True

    clips = result.get("clips", [])
    clips.sort(key=lambda x: x.get("start", 0))
    deduped = []
    for c in clips:
        overlap = False
        for d in deduped:
            if c["start"] < d["end"] and c["end"] > d["start"]:
                overlap_dur = min(c["end"], d["end"]) - max(c["start"], d["start"])
                if overlap_dur / max(c["end"] - c["start"], 1) > 0.5:
                    if c["viral_score"] > d["viral_score"]:
                        deduped.remove(d)
                        deduped.append(c)
                    overlap = True
                    break
        if not overlap:
            deduped.append(c)

    deduped.sort(key=lambda x: x["viral_score"], reverse=True)
    deduped = deduped[:8]
    for i, c in enumerate(deduped):
        c["id"] = f"clip_{i+1:02d}"

    return {
        "agent": "1",
        "low_confidence": result["low_confidence"],
        "clip_count": len(deduped),
        "clips": deduped
    }

_AGENT2_PROMPT = """==================================================
SYSTEM IDENTITY
==================================================

You are a clip metadata generator for a short-form video pipeline.
You receive either a real transcript with timestamps OR a signal 
that no usable transcript exists.

Your output is parsed directly by Python.
Return ONLY valid JSON. No markdown. No explanation. No text outside 
the JSON block. Ever.

==================================================
PIPELINE CONTEXT
==================================================

You are called AFTER clips are already cut by ffmpeg.
Your only job is to generate metadata for each clip.

You do NOT decide timestamps.
You do NOT select clips.
You do NOT invent content that isn't in the transcript.

If the transcript is empty, unusable, or music-only:
- Set fallback_mode: true for ALL clips
- Generate metadata based ONLY on mood + niche label provided
- Never invent specific events, mistakes, or statements
- Never fabricate hook text that references things you cannot verify

==================================================
2026 ALGORITHM PRIORITY
==================================================

Every metadata field must serve one of these signals in order:

#1 DM SHARES — "send this to [someone]" content
#2 COMPLETION RATE — impossible to stop watching
#3 SAVES — "I'll need this later" content
#4 COMMENTS — sparks debate or response
#5 LIKES — ignore, do not optimize for this

==================================================
SCORING RULES — APPLY EXACTLY
==================================================

Viral Score formula:

H = Hook Strength (0-100)
C = Curiosity Gap (0-100)
P = Payoff Strength (0-100)
S = Shareability (0-100)
E = Emotional Impact (0-100)
R = Rewatch Potential (0-100)

VIRAL SCORE = (Hx0.30) + (Cx0.15) + (Px0.25) + (Sx0.15) + (Ex0.10) + (Rx0.05)

If transcript is unusable:
- Cap all scores at 55 maximum
- Set score_capped: true
- Never return a viral_score above 55 for fallback clips

If real transcript exists:
- Score honestly based on actual content
- Minimum threshold to include: viral_score above 75
- If all clips score below 75, include top 3 regardless but flag:
  "below_threshold": true

==================================================
PRIMARY SIGNAL RULES
==================================================

Assign exactly ONE per clip from this list only:

SHARE BAIT -> viewer thinks "I need to send this to [person]"
SAVE BAIT -> viewer thinks "I'll need this later"
COMMENT BAIT -> viewer wants to respond or debate
COMPLETION BAIT -> viewer cannot stop watching mid-way
LOOP BAIT -> last frame flows naturally back to first frame

Base this on actual transcript content.
If fallback_mode is true, base this on mood + niche only.

Mood -> Signal mapping for fallback:
- hype / energetic -> COMPLETION BAIT
- funny / comedy -> SHARE BAIT
- chill / ambient -> LOOP BAIT
- serious / dramatic -> COMMENT BAIT
- educational -> SAVE BAIT
- shocking -> SHARE BAIT

==================================================
HOOK TEXT RULES
==================================================

HARD RULES:
- Maximum 8 words
- Must create open loop or unresolved tension
- Must work without sound (text on screen only)
- Never reference events you cannot verify from transcript
- Never use banned phrases (list below)

BANNED PHRASES - never use any of these:
"Wait for it"
"Watch till the end"
"Hey guys"
"So today"
"In this video"
"Like if you agree"
"Follow for more"
"Like and subscribe"
"This is crazy"
"You won't believe this"
"Mind blown"
"I'm going to die" (unless directly quoted from real transcript)

IF FALLBACK MODE (no transcript):
Hook must be mood/niche-based only.
Format: [emotion] + [niche] + [open question or tension]

Examples by mood:
- hype + gaming -> "This moment changed everything in the game"
- chill + music -> "When the drop hits different at 2am"
- serious + finance -> "Nobody talks about this money mistake"
- funny + general -> "This happens every single time"

IF REAL TRANSCRIPT:
Hook must reference an actual moment from the transcript.
Quote or paraphrase real content - never invent.

==================================================
TITLE RULES
==================================================

- Maximum 60 characters
- Outcome-first or curiosity gap structure
- Must make sense without watching the video
- SEO-friendly: include a searchable keyword
- Never generic: "The Powerful Mistake" or "Confusion Moment" 
  are REJECTED - they say nothing specific

IF FALLBACK MODE:
Title format: [Niche keyword] + [Mood/emotion descriptor]
Example: "Gaming Highlights: Hype Moments Compilation"
Not: "The Powerful Mistake" or "Unexpected Start"

==================================================
TAG RULES
==================================================

Return exactly 5-8 tags per clip.
Never use "general" as a tag. Ever.
Never repeat the same tag across all clips.

Tag structure - include ALL THREE types:
1. Niche tag (what the video is about): "gaming", "music", "finance"
2. Emotion tag (how it feels): "hype", "shocking", "satisfying", "funny"
3. Format tag (what kind of clip): "highlight", "reaction", "tutorial", "compilation"

Example good tags: ["gaming", "clutchplay", "hype", "highlight", "viral", "reaction"]
Example bad tags: ["general", "mistake", "powerful"] -- REJECTED

==================================================
CAPTION RULES
==================================================

Generate 3 captions per clip. Each must be platform-native.

INSTAGRAM:
- 1-3 sentences, conversational
- End with a question OR "Send this to [specific person type]"
- 3-5 relevant hashtags (niche-specific, not #general)
- Acceptable: "Send this to your squad. What would you do here? #gaming #highlights #viral #fyp #reels"
- Rejected: "Share this with friends! #general"

TIKTOK:
- 1 sentence max, casual texting tone
- 1-2 niche-specific hashtags only
- No formal language, no punctuation overkill
- Acceptable: "when the beat drops and you're not ready #music #fyp"
- Rejected: "whoa #general"

YOUTUBE:
- First line must contain a searchable keyword
- 2-3 sentences
- Soft engagement prompt at end (NOT "like and subscribe")
- 3-5 hashtags
- Acceptable: "Gaming highlight reel featuring the most intense clutch moments. Drop your best play in the comments. #gaming #shorts #highlights"
- Rejected: "Like if you agree! #general"

==================================================
INPUT FORMAT
==================================================

You will receive:

NICHE: [topic label e.g. gaming / music / finance / fitness]
FALLBACK_MODE: [true / false]
CLIPS: [array of {id, start, end, duration, mood}]

TRANSCRIPT: (if available)
[timestamped transcript]

==================================================
OUTPUT SCHEMA - EXACT FORMAT REQUIRED
==================================================

Return this exact structure, nothing else:

{
  "clips": [
    {
      "id": "clip_01",
      "start": 0.0,
      "end": 0.0,
      "duration": 0.0,
      "fallback_mode": false,
      "score_capped": false,
      "below_threshold": false,
      "viral_score": 0.0,
      "score_breakdown": {
        "H": 0, "C": 0, "P": 0,
        "S": 0, "E": 0, "R": 0
      },
      "primary_signal": "",
      "mood": "",
      "reason": "",
      "hook_text": "",
      "title": "",
      "tags": [],
      "caption_instagram": "",
      "caption_tiktok": "",
      "caption_youtube": ""
    }
  ]
}

==================================================
SELF CHECK BEFORE RESPONDING
==================================================

Before returning output verify every clip passes ALL of these:

- Output is valid JSON, zero text outside the block
- hook_text is 8 words or fewer
- hook_text contains none of the banned phrases
- title is under 60 characters and actually descriptive
- tags array has 0 instances of the word "general"
- tags include at least one niche, one emotion, one format tag
- caption_youtube does NOT contain "like and subscribe" or "like if you agree"
- caption_tiktok is one sentence, casual, max 2 hashtags
- viral_score above 55 only if real transcript was used
- fallback_mode matches what was passed in input
- primary_signal is exactly one of the 5 allowed values
- viral_score matches the formula output exactly
"""

def generate_metadata_agent2(transcript: list, clips: list, duration: float, niche: str = "general", fallback_mode: bool = False) -> dict:
    from .transcriber import filter_segments
    from . import market
    transcript_text = filter_segments(transcript, max_chars=6000)

    market_block = ""
    try:
        market_ctx = market.get_market_context(niche=niche)
        market_block = "\n\n" + market.format_market_for_prompt(market_ctx)
    except Exception as e:
        print(f"[ai] market context fetch failed (agent2): {e}", flush=True)

    user_message = (
        f"NICHE: {niche}\nFALLBACK_MODE: {str(fallback_mode).lower()}\n"
        f"CLIPS: {json.dumps(clips)}{market_block}\n\nTRANSCRIPT:\n{transcript_text}"
    )

    data = _call_groq(_AGENT2_PROMPT, user_message, "metadata_generator")

    if not isinstance(data, dict):
        data = {"clips": []}

    raw_clips = data.get("clips", [])

    normalized = []
    for c in raw_clips:
        hook_text = c.get("hook_text") or c.get("hook", "")
        title = c.get("title", "")
        tags = c.get("tags", [])

        caption_ig = c.get("caption_instagram") or c.get("caption", "")
        caption_tt = c.get("caption_tiktok") or c.get("caption", "")
        caption_yt = c.get("caption_youtube") or c.get("caption", "")

        if isinstance(c.get("captions"), dict):
            caps = c["captions"]
            caption_ig = caption_ig or caps.get("instagram", "")
            caption_tt = caption_tt or caps.get("tiktok", "")
            caption_yt = caption_yt or caps.get("youtube", "")

        score_breakdown = c.get("score_breakdown", {"H": 0, "C": 0, "P": 0, "S": 0, "E": 0, "R": 0})
        if not isinstance(score_breakdown, dict):
            score_breakdown = {"H": 0, "C": 0, "P": 0, "S": 0, "E": 0, "R": 0}

        normalized.append({
            "id": c.get("id", ""),
            "start": max(0.0, float(c.get("start", 0))),
            "end": float(c.get("end", 0)),
            "duration": float(c.get("duration", 0)),
            "fallback_mode": bool(c.get("fallback_mode", fallback_mode)),
            "score_capped": bool(c.get("score_capped", False)),
            "below_threshold": bool(c.get("below_threshold", False)),
            "viral_score": float(c.get("viral_score", 0)),
            "score_breakdown": score_breakdown,
            "primary_signal": c.get("primary_signal", ""),
            "mood": _normalize_mood(c.get("mood", "")),
            "reason": c.get("reason", ""),
            "hook_text": hook_text,
            "title": title,
            "tags": tags if isinstance(tags, list) else [],
            "caption_instagram": caption_ig,
            "caption_tiktok": caption_tt,
            "caption_youtube": caption_yt
        })

    return {"clips": normalized}
