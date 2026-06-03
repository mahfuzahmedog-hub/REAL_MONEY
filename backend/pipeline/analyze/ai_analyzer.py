import os
import json
import re
import itertools
import logging
from .zen_client import call_with_rotation, ZenAllModelsExhausted, ZenError, list_available_models

log = logging.getLogger("ai_analyzer")

AGENTS = {
    "clip_finder": {
        "temperature": 0.3,
        "max_tokens": 2000
    },
    "metadata_generator": {
        "temperature": 0.4,
        "max_tokens": 4000
    }
}

VALID_MOODS = {"reflective", "motivational", "peaceful", "scholarly", "devotional"}

ISLAMIC_PILLARS = [
    "QURAN_VERSE",
    "HADITH",
    "DUA",
    "REMINDER",
    "STORY_OF_PROPHET",
    "STORY_OF_COMPANION",
    "SCHOLAR_QUOTE",
    "ISLAMIC_LIFESTYLE",
]

ISLAMIC_HOOK_FORMULAS = {
    "QURAN_OPENER": "Allah says: {verse_excerpt}...",
    "HADITH_OPENER": "The Prophet ﷺ said: {hadith_excerpt}...",
    "REFLECTION": "Reflect on this: {emotional_truth}...",
    "REMINDER": "Remember: {core_message}...",
    "STORY": "They didn't know {till_this_happened}...",
}

ISLAMIC_BANNED_HOOK_PATTERNS = [
    r"\bwait\s+for\s+it\b",
    r"\bwatch\s+till\s+the\s+end\b",
    r"\bthis\s+is\s+crazy\b",
    r"\bmind\s+blown\b",
    r"\bgoing\s+viral\b",
    r"\bsubscribe\b",
    r"\blike\s+and\s+subscribe\b",
    r"\blike\s+if\s+you\s+agree\b",
    r"\bfollow\s+for\s+more\b",
    r"\bhey\s+guys\b",
    r"\bso\s+today\b",
    r"\bin\s+this\s+video\b",
    r"\bfunny\b",
    r"\bcomedy\b",
    r"\bcomedic\b",
    r"\bhilarious\b",
    r"\blaugh\b",
    r"\blaughs\b",
    r"\blaughed\b",
    r"\blaughter\b",
    r"\bbeat\s+drop\b",
    r"\bvibe\b",
    r"\binstrumental\b",
    r"\bedm\b",
    r"\bmukbang\b",
]


def _normalize_mood(mood: str, niche: str = "") -> str:
    if not mood:
        return "scholarly"
    mood = mood.lower().strip()
    if mood in VALID_MOODS:
        return mood
    legacy_to_islamic = {
        "hype": "motivational",
        "chill": "peaceful",
        "emotional": "devotional",
        "funny": "scholarly",
        "serious": "scholarly",
    }
    if mood in legacy_to_islamic:
        return legacy_to_islamic[mood]
    return "scholarly"

_api_keys = []
_key_cycle = None

def _load_keys():
    """
    Backward-compat shim. We now use OpenCode Zen (single key) but keep this
    function so older callers that imported it don't break.
    """
    has_key = (
        os.getenv("OPENCODE_API_KEY", "").strip()
        or os.getenv("OPENCODE_ZEN_API_KEY", "").strip()
    )
    if not has_key:
        raise ValueError(
            "OPENCODE_API_KEY (or OPENCODE_ZEN_API_KEY) not set. "
            "Add it to backend/.env (get a key at https://opencode.ai/auth). "
            "GROQ_API_KEY is no longer used."
        )

_VIRAL_PROMPT = """You are a short-form video editor for Islamic Hedayet, an Instagram page sharing Islamic reminders, Quran verses, hadith, and scholar quotes. You understand what performs on Instagram Reels, TikTok, and YouTube Shorts in 2026.

Your job is to find 3-5 clips from this transcript that will perform well as vertical reels for Muslim audiences seeking authentic Islamic content.

A great Islamic clip MUST have:
- A strong HOOK in the first 3 seconds that creates reflection, curiosity, or emotional pull
- A clear mini arc: setup -> reflection/reminder -> takeaway or du'a
- Quotable, shareable language (something people would send to family, save, or comment "SubhanAllah")
- A spiritually meaningful moment: Quran verse, hadith, scholar quote, dua, or powerful reflection
- Content that builds iman (faith), increases taqwa (God-consciousness), or reminds of akhira (hereafter)
- No slow intros, no rambling transitions

THEOLOGICAL SAFETY RULES (HARD GATES - violations will be rejected):
- NEVER invent or fabricate Quran verses. If you reference a verse, use real surah:ayah from the verified DB
- NEVER invent or fabricate hadith. If you reference a hadith, use real collection+number from the verified DB
- NEVER generate Arabic Quran or Hadith text directly. The Arabic text is rendered separately from the verified DB
- NEVER use music, beat drops, or instrumental references. This page uses vocal nasheeds and Quran recitation only
- NEVER use comedy/punchline structure. This is NOT a comedy page

ISLAMIC HOOK FORMULAS (use one per clip):
- QURAN_OPENER: "Allah says: {verse excerpt}..." (real verse only)
- HADITH_OPENER: "The Prophet ﷺ said: {hadith excerpt}..." (real hadith only)
- REFLECTION: a thoughtful question or observation that prompts reflection
- REMINDER: a short, direct reminder of faith, prayer, gratitude, or patience
- STORY: a brief story of a Prophet, Companion, or righteous person

VALID MOODS (pick exactly one per clip):
- reflective: thoughtful, contemplative content (e.g., Quran reflection)
- motivational: energizing, action-prompting (e.g., "don't give up, keep praying")
- peaceful: calm, serene (e.g., dhikr, nature + recitation)
- scholarly: educational, lecture-based (e.g., fiqh explanation, tafsir)
- devotional: worship-focused (e.g., dua, salah tips, Quran recitation)

CONTENT PILLARS (pick exactly one per clip, indicates the type of content):
- QURAN_VERSE: clip is centered on a Quran verse
- HADITH: clip is centered on a hadith
- DUA: clip is centered on a dua/supplication
- REMINDER: general reminder, lecture, or reflection
- STORY_OF_PROPHET: story of a Prophet
- STORY_OF_COMPANION: story of a Sahabi
- SCHOLAR_QUOTE: quote from a known Islamic scholar
- ISLAMIC_LIFESTYLE: practice, etiquette, or lifestyle guidance

Scoring criteria (1-10 each):
- hook_strength: how compelling are the first 3 seconds for a Muslim audience?
- retention: will viewers watch to the end (often saves, comments, shares)?
- shareability: would a Muslim send this to family/WhatsApp group?

Also generate:
- caption_hook: a punchy on-screen text overlay for the first 2 seconds (max 8 words, Islamic-friendly, no hashtags, no "subscribe", no "like if you agree")
- mood: one of [reflective, motivational, peaceful, scholarly, devotional]
- pillar: one of the 8 content pillars above
- reference_claim: if the clip mentions a specific Quran verse or hadith, include the reference EXACTLY as it appears in the transcript (e.g., "Quran 2:255" or "Bukhari 1"). If no specific reference, leave empty string. DO NOT INVENT REFERENCES.

Respond ONLY with a valid JSON array. No explanation, no markdown, no preamble.
Format: [{"start": float, "end": float, "hook_strength": int, "retention": int, "shareability": int, "reason": str, "mood": str, "pillar": str, "caption_hook": str, "reference_claim": str}]

Rules:
- Each clip must be 15-40 seconds long
- Do not pick clips that start mid-sentence or mid-thought
- Prefer clips where total score (hook_strength + retention + shareability) >= 20
- Return clips sorted by total score descending
- If the transcript contains Arabic, the first 3 seconds should often start with the Arabic (for the dual-frame overlay)
"""

def _clip_array_to_agent1_format(clips: list, niche: str = "") -> dict:
    if not clips:
        return {"agent": "1", "low_confidence": True, "clip_count": 0, "clips": []}

    normalized = []
    for i, c in enumerate(clips):
        hs = int(c.get("hook_strength", 0))
        rt = int(c.get("retention", 0))
        sh = int(c.get("shareability", 0))
        total = hs + rt + sh
        pillar = c.get("pillar", "REMINDER")
        if pillar not in ISLAMIC_PILLARS:
            pillar = "REMINDER"
        normalized.append({
            "id": f"clip_{i+1:02d}",
            "start": max(0.0, float(c.get("start", 0))),
            "end": float(c.get("end", 0)),
            "duration": float(c.get("end", 0)) - max(0.0, float(c.get("start", 0))),
            "viral_score": round(total * 10 / 3, 1),
            "score_breakdown": {"H": hs * 10, "C": 0, "P": rt * 10, "S": sh * 10, "E": 0, "R": 0},
            "tier": "A" if total >= 25 else "B",
            "mood": _normalize_mood(c.get("mood", ""), niche),
            "pillar": pillar,
            "reason": c.get("reason", "Meaningful Islamic moment"),
            "caption_hook": c.get("caption_hook", ""),
            "reference_claim": c.get("reference_claim", ""),
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

def _call_ai(system_prompt: str, user_message: str, agent_key: str, retry_on_fail: bool = True):
    """
    Call OpenCode Zen with model rotation + automatic fallback.

    Tries models in the agent's tier list (best reasoning first, free models last).
    On rate-limit, timeout, or 5xx, rotates to next model.
    On invalid JSON, retries the same model with stricter prompt; if that fails, rotates.

    Returns the parsed JSON dict (with extra '_model' key indicating which model answered).
    Raises ZenAllModelsExhausted if every tier fails.
    """
    if agent_key not in AGENTS:
        raise ValueError(f"Unknown agent_key: {agent_key}")

    try:
        return call_with_rotation(
            agent_key=agent_key,
            system_prompt=system_prompt,
            user_message=user_message,
            parse_json=True,
        )
    except ZenAllModelsExhausted as e:
        log.error(f"[ai] {e}")
        raise
    except ZenError as e:
        log.error(f"[ai] zen error: {e}")
        raise

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

    from ..download.transcriber import filter_segments
    from ..download import market
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
            data = _call_ai(_VIRAL_PROMPT, user_message, "clip_finder")
        except Exception:
            any_failed = True
            continue

        if isinstance(data, list):
            all_raw_clips.extend(data)
        elif isinstance(data, dict) and "clips" in data:
            all_raw_clips.extend(data["clips"])
        elif isinstance(data, dict) and "_raw_list" in data:
            all_raw_clips.extend(data["_raw_list"])
            log.info(f"[ai] clip_finder used model: {data.get('_model', '?')}")

    if not all_raw_clips:
        all_raw_clips = [
            {"start": max(0, duration * 0.1 * i), "end": min(duration, duration * 0.1 * (i + 2)),
             "hook_strength": 5, "retention": 5, "shareability": 5,
             "reason": "Energy-based fallback", "mood": "hype", "caption_hook": "TOP MOMENT"}
            for i in range(3)
        ]
        any_failed = True

    result = _clip_array_to_agent1_format(all_raw_clips, niche)

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

You are a clip metadata generator for Islamic Hedayet, an Instagram page sharing authentic Islamic content (Quran verses, hadith, dua, scholar reminders, Islamic lifestyle).

You receive either a real transcript with timestamps OR a signal that no usable transcript exists.

Your output is parsed directly by Python.
Return ONLY valid JSON. No markdown. No explanation. No text outside the JSON block. Ever.

==================================================
THEOLOGICAL SAFETY (HARD GATES)
==================================================

NEVER, under any circumstance:
- Generate Arabic Quran text directly. Arabic Quran text is rendered from the verified DB separately.
- Generate Arabic Hadith text directly. Arabic Hadith text is rendered from the verified DB separately.
- Fabricate a specific Quran reference (e.g., "Quran 99:99" or "Surah 12:999"). If the transcript mentions a real reference, copy it exactly.
- Fabricate a specific hadith reference (e.g., "Bukhari 9999" or "Sahih Muslim 12345"). If the transcript mentions a real reference, copy it exactly.
- Reference music, beats, drops, or instruments. The page is vocal-only (Quran recitation + nasheeds).
- Use comedy/punchline/joke language. This is NOT a comedy page.
- Claim a verse is from a specific surah/ayah unless the transcript EXPLICITLY says so.

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
- Generate metadata based ONLY on mood + pillar + niche label provided
- Never invent specific events, verses, hadith, or statements
- Never fabricate hook text that references things you cannot verify

==================================================
2026 ALGORITHM PRIORITY
==================================================

Every metadata field must serve one of these signals in order:

#1 DM SHARES — "send this to family/WhatsApp" content
#2 COMPLETION RATE — impossible to stop watching
#3 SAVES — "I'll need this later / bookmark for reflection" content
#4 COMMENTS — sparks "SubhanAllah", "Allahu Akbar", or sincere debate
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

SHARE BAIT -> viewer thinks "I need to send this to family/WhatsApp"
SAVE BAIT -> viewer thinks "I'll bookmark this for later reflection"
COMMENT BAIT -> viewer wants to respond (SubhanAllah, reflection, dua request)
COMPLETION BAIT -> viewer cannot stop watching mid-way
LOOP BAIT -> last frame flows naturally back to first frame

Base this on actual transcript content.
If fallback_mode is true, base this on mood + pillar only.

Mood -> Signal mapping for fallback:
- motivational / energizing -> SHARE BAIT
- reflective / contemplative -> SAVE BAIT
- peaceful / serene -> LOOP BAIT
- scholarly / educational -> SAVE BAIT
- devotional / worship -> SHARE BAIT

==================================================
HOOK TEXT RULES
==================================================

HARD RULES:
- Maximum 8 words
- Must create open loop or unresolved reflection
- Must work without sound (text on screen only)
- Never reference events you cannot verify from transcript
- NEVER use these phrases (Islamic content is serious, not clickbait):
  "wait for it", "watch till the end", "this is crazy", "mind blown",
  "subscribe", "like and subscribe", "like if you agree", "follow for more",
  "hey guys", "so today", "in this video", "going viral", "you won't believe",
  "funny", "comedy", "lol", "lmao", "hilarious"

IF FALLBACK MODE (no transcript):
Hook must be mood + pillar-based only.
Format: [emotion word] + [spiritual action] + [open reflection]

Examples by mood/pillar (Islamic only):
- reflective + QURAN_VERSE -> "Reflect on this verse daily"
- reflective + HADITH -> "The Prophet ﷺ reminded us of this"
- motivational + REMINDER -> "Your heart needs this reminder"
- motivational + ISLAMIC_LIFESTYLE -> "Start doing this today"
- peaceful + DUA -> "Make this dua before sleeping"
- peaceful + QURAN_VERSE -> "The verse that calms the heart"
- scholarly + HADITH -> "A hadith you should know"
- scholarly + ISLAMIC_LIFESTYLE -> "Did you know this about wudu?"
- devotional + QURAN_VERSE -> "Recite this in every prayer"
- devotional + DUA -> "The dua that opens doors"

IF REAL TRANSCRIPT:
Hook must reference an actual moment from the transcript.
Quote or paraphrase real content - never invent.
NEVER translate or paraphrase Arabic verses — Arabic verses are rendered separately.

==================================================
TITLE RULES
==================================================

- Maximum 60 characters
- Outcome-first or reflection-first structure
- Must make sense without watching the video
- SEO-friendly: include a searchable Islamic keyword (e.g., "Quran", "Hadith", "Dua", "Reminder")
- Never generic: "The Powerful Reminder" is REJECTED
- Include the pillar or scholar name when relevant

Examples of good titles:
- "The Hadith on Intentions - Sahih Bukhari 1"
- "Ayat al-Kursi: The Throne Verse Explained"
- "A Reminder on Patience from Surah Al-Baqarah"
- "The Dua Before Sleeping - Prophet's Teaching"

IF FALLBACK MODE:
Title format: [Islamic keyword] + [Mood/reflection descriptor]
Example: "Daily Quran Reminder: Reflect on Allah's Mercy"
Not: "The Powerful Reminder" or "This Will Change You"

==================================================
TAG RULES
==================================================

Return exactly 5-8 tags per clip.
Never use "general" as a tag. Ever.
Never repeat the same tag across all clips.

Tag structure - include ALL THREE types:
1. Niche tag (Islamic content type): "quran", "hadith", "dua", "reminder", "islamiclifestyle"
2. Emotion tag (how it feels): "reflective", "peaceful", "motivational", "devotional", "scholarly"
3. Format tag (what kind of clip): "lecture", "recitation", "reflection", "qa", "story"

Example good tags: ["quran", "reminder", "scholarly", "lecture", "islam", "tafsir", "verseoftheday"]
Example bad tags: ["general", "powerful", "viral"] -- REJECTED

==================================================
CAPTION RULES
==================================================

Generate 3 captions per clip. Each must be platform-native AND Islamic.

INSTAGRAM:
- 1-3 sentences, sincere tone
- End with a reflection prompt OR "Send this to [family member]" 
- 3-5 Islamic-specific hashtags (NOT #general, NOT #viral, NOT #fyp)
- Acceptable: "SubhanAllah. The verse that reminds us of His mercy. Send this to someone who needs it today. #quran #islam #reminder #islamicreminder #deen"
- Rejected: "Share this with friends! #general #viral"

TIKTOK:
- 1 sentence max, sincere but conversational
- 1-2 Islamic-specific hashtags only
- No emojis overload, no clickbait
- Acceptable: "The verse that calms every anxious heart #quran #islam"
- Rejected: "wait for it #fyp #viral"

YOUTUBE:
- First line must contain a searchable Islamic keyword
- 2-3 sentences
- Soft engagement prompt (NOT "like and subscribe")
- 3-5 Islamic hashtags
- Acceptable: "Quran reflection on the verse of the throne. A reminder for every believer. Drop a SubhanAllah in the comments. #quran #islam #shorts #islamicreminder #deen"
- Rejected: "Like if you agree! #general"

==================================================
INPUT FORMAT
==================================================

You will receive:

NICHE: islamic
FALLBACK_MODE: [true / false]
CLIPS: [array of {id, start, end, duration, mood, pillar}]

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
      "pillar": "",
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
- title includes an Islamic keyword
- tags array has 0 instances of the word "general" or "viral"
- tags include at least one Islamic niche, one emotion, one format tag
- caption_youtube does NOT contain "like and subscribe" or "like if you agree"
- caption_tiktok is one sentence, sincere, max 2 hashtags
- viral_score above 55 only if real transcript was used
- fallback_mode matches what was passed in input
- primary_signal is exactly one of the 5 allowed values
- viral_score matches the formula output exactly
- mood is one of: reflective, motivational, peaceful, scholarly, devotional
- pillar is one of: QURAN_VERSE, HADITH, DUA, REMINDER, STORY_OF_PROPHET, STORY_OF_COMPANION, SCHOLAR_QUOTE, ISLAMIC_LIFESTYLE
"""

def generate_metadata_agent2(transcript: list, clips: list, duration: float, niche: str = "general", fallback_mode: bool = False) -> dict:
    from ..download.transcriber import filter_segments
    from ..download import market
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

    data = _call_ai(_AGENT2_PROMPT, user_message, "metadata_generator")

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

        pillar = c.get("pillar", "REMINDER")
        if pillar not in ISLAMIC_PILLARS:
            pillar = "REMINDER"

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
            "mood": _normalize_mood(c.get("mood", ""), niche),
            "pillar": pillar,
            "reason": c.get("reason", ""),
            "hook_text": hook_text,
            "title": title,
            "tags": tags if isinstance(tags, list) else [],
            "caption_instagram": caption_ig,
            "caption_tiktok": caption_tt,
            "caption_youtube": caption_yt
        })

    return {"clips": normalized}
