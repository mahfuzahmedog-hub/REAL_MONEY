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

_AGENT1_PROMPT = """You are a 2026 viral short-form content strategist. You analyze video transcripts and return clip candidates optimized for virality.

2026 ALGORITHM PRIORITY (rank by this): #1 DM SHARES #2 COMPLETION RATE #3 SAVES #4 COMMENTS #5 LIKES

Your job: Scan the transcript and find every moment that would stop a mid-scroll user.

TIER A clips (always include if present): shock, surprise, conflict, clutch moments, big mistakes, comebacks, strong emotional reactions, rage, unexpected outcomes.
TIER B clips (include if Tier A scarce): strong opinions, fast valuable insight, humor, transformation, high-skill moments.

REJECT clips that: need >3s context, low energy no payoff, mid-explanation, only silence/music, only make sense to full-video viewers.

SCORING FORMULA:
H=Hook Strength 0-100, C=Curiosity Gap 0-100, P=Payoff Strength 0-100, S=Shareability 0-100, E=Emotional Impact 0-100, R=Rewatch Potential 0-100
VIRAL_SCORE = (H*0.30)+(C*0.15)+(P*0.25)+(S*0.15)+(E*0.10)+(R*0.05)

Return only clips with viral_score > 75. Min 3 max 8. If fewer than 3 above 75, lower threshold to 60. If still fewer than 3, set "low_confidence": true.
Clip length: min 7s max 90s sweet spot 15-45s. Never cut mid-sentence.

Valid mood values: "chill", "hype", "emotional", "funny", "serious"

OUTPUT SCHEMA (return ONLY this JSON, no other text):
{"agent": "1", "low_confidence": false, "clip_count": 3, "clips": [{"id": "clip_01", "start": 120.0, "end": 145.0, "duration": 25.0, "viral_score": 85.0, "score_breakdown": {"H": 80, "C": 70, "P": 90, "S": 75, "E": 85, "R": 60}, "tier": "A", "mood": "hype", "reason": "exciting moment"}]}"""

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

HARD_RULES = "CRITICAL: Output MUST be valid JSON only. No markdown, no code fences, no explanation. Never invent timestamps not in the transcript. If transcript is empty return: {\"agent\": \"1\", \"low_confidence\": true, \"clip_count\": 0, \"clips\": []}"

def _format_transcript(transcript: list, max_chars: int = 15000) -> str:
    text = "\n".join(
        f"[{s['start']:.1f}s - {s['end']:.1f}s] {s['text']}"
        for s in transcript
    )
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]"
    return text

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

def analyze_transcript_agent1(transcript: list, duration: float, niche: str = "general", platform: str = "all") -> dict:
    transcript_text = _format_transcript(transcript)

    if not transcript_text.strip():
        raise ValueError("Empty transcript — nothing to analyze")

    user_message = f"NICHE: {niche}\nPLATFORM: {platform}\nDURATION: {duration:.0f}\n\nTRANSCRIPT:\n{transcript_text}"

    data = _call_groq(_AGENT1_PROMPT, user_message, "clip_finder")

    if not isinstance(data, dict):
        data = {"agent": "1", "low_confidence": True, "clip_count": 0, "clips": []}

    low_confidence = data.get("low_confidence", False)
    clips = data.get("clips", [])

    normalized = []
    for c in clips:
        normalized.append({
            "id": c.get("id", f"clip_{len(normalized)+1:02d}"),
            "start": max(0.0, float(c.get("start", 0))),
            "end": float(c.get("end", 0)),
            "duration": float(c.get("duration", 0)),
            "viral_score": float(c.get("viral_score", 0)),
            "score_breakdown": c.get("score_breakdown", {"H": 0, "C": 0, "P": 0, "S": 0, "E": 0, "R": 0}),
            "tier": c.get("tier", "B"),
            "mood": _normalize_mood(c.get("mood", "")),
            "reason": c.get("reason", "Viral moment")
        })

    normalized.sort(key=lambda x: x["viral_score"], reverse=True)

    return {
        "agent": "1",
        "low_confidence": low_confidence,
        "clip_count": len(normalized),
        "clips": normalized
    }

def generate_metadata_agent2(transcript: list, clips: list, duration: float, niche: str = "general", fallback_mode: bool = False) -> dict:
    transcript_text = _format_transcript(transcript)

    user_message = f"NICHE: {niche}\nFALLBACK_MODE: {str(fallback_mode).lower()}\nCLIPS: {json.dumps(clips)}\n\nTRANSCRIPT:\n{transcript_text}"

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
