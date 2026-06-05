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


SCHOLAR_ALLOWLIST = {
    "muftimenk": "Mufti Menk",
    "mufti_menk": "Mufti Menk",
    "omarsuleiman": "Omar Suleiman",
    "omar_suleiman": "Omar Suleiman",
    "noumanalikhan": "Nouman Ali Khan",
    "nouman_ali_khan": "Nouman Ali Khan",
    "yasirqadhi": "Yasir Qadhi",
    "yasir_qadhi": "Yasir Qadhi",
    "mohamedhoblos": "Mohamed Hoblos",
    "alimhammuda": "Ali Hammuda",
    "muhammadsalah": "Muhammad Salah",
    "mishary": "Mishary Rashid Alafasy",
    "maher": "Maher Al Muaiqly",
    "husary": "Al-Husary",
    "sudais": "Sudais",
    "tariqjameel": "Tariq Jameel",
    "javedghamidi": "Javed Ahmed Ghamidi",
    "israrahmed": "Dr. Israr Ahmed",
    "akhtaruzzaman": "Dr. Akhtaruzzaman",
}


def detect_scholar_name(text: str) -> str:
    """Detect scholar name from transcript or source metadata.

    Returns the display name (e.g., "Mufti Menk") or empty string.
    """
    if not text:
        return ""
    text_lower = text.lower()
    for handle, display in SCHOLAR_ALLOWLIST.items():
        if handle in text_lower.replace(" ", "_") or handle in text_lower.replace("_", " "):
            return display
    name_keys = ["mufti menk", "omar suleiman", "nouman ali khan", "yasir qadhi",
                 "mohamed hoblos", "ali hammuda", "muhammad salah",
                 "mishary rashid", "maher al muaiqly", "tariq jameel",
                 "javed ghamidi", "dr. israr", "akhtaruzzaman"]
    for n in name_keys:
        if n in text_lower:
            return n.title() if not n.startswith("dr") else "Dr. " + n.split(" ", 1)[1].title()
    return ""


TRENDING_ISLAMIC_TAGS = [
    "islamicstatus", "islamicreminder", "islamiclifestyle",
    "islamiclectures", "islamicvideo", "islamicshorts",
    "allah", "allahuakbar", "subhanallah", "mashallah",
    "quran", "hadith", "dua", "deen", "iman", "taqwa",
    "muslim", "muslimtiktok", "muslimreminder",
    "palestine", "freepalestine",
    "scholar", "lecture", "reminder", "motivation",
    "patience", "sabr", "tawakkul", "shukr",
]


def generate_trending_tags(pillar: str, scholar_name: str = "", count: int = 3) -> list:
    """Generate trending tag list based on pillar + scholar.

    Returns 2-3 trending tags that boost discoverability.
    """
    tags = []
    pillar_tag_map = {
        "QURAN_VERSE": ["quran", "allah", "islamicreminder"],
        "HADITH": ["hadith", "deen", "iman"],
        "DUA": ["dua", "islamiclifestyle", "allah"],
        "REMINDER": ["reminder", "islamicstatus", "muslimreminder"],
        "STORY_OF_PROPHET": ["quran", "scholar", "islamiclectures"],
        "STORY_OF_COMPANION": ["islamicstatus", "scholar", "deen"],
        "SCHOLAR_QUOTE": ["scholar", "lecture", "islamiclectures"],
        "ISLAMIC_LIFESTYLE": ["islamiclifestyle", "deen", "muslim"],
    }
    tags.extend(pillar_tag_map.get(pillar, ["reminder", "islamicstatus"]))
    if scholar_name:
        handle = scholar_name.lower().replace(" ", "").replace(".", "")
        tags.append(handle[:14])
    return tags[:count]


def cross_promotion_tag(current_scholar: str) -> str:
    """Pick 1 cross-promotion scholar name for reach (different from current)."""
    if not current_scholar:
        return ""
    others = [
        ("Mufti Menk", "muftimenk"),
        ("Omar Suleiman", "omarsuleiman"),
        ("Nouman Ali Khan", "noumanalikhan"),
        ("Yasir Qadhi", "yasirqadhi"),
    ]
    for display, handle in others:
        if display.lower() != current_scholar.lower():
            return handle
    return ""


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

Your job is to find EXACTLY {max_clips} clips from this transcript that will perform well as vertical reels for Muslim audiences seeking authentic Islamic content. Return EXACTLY {max_clips} clips — no more, no fewer.

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

ISLAMIC HOOK FORMULAS (pick the strongest one per clip — preference order below):
1. DECLARATIVE_STATEMENT (HIGHEST CONVERSION — style: "X is Y"): a single bold truth, 3-6 words, no preamble.
   Examples: "Real Success is the Hereafter", "Patience is a form of Worship", "Dunya is a Test, Jannah is the Goal"
2. QURAN_OPENER: "Allah says: <verse excerpt>..." (real verse only)
3. HADITH_OPENER: "The Prophet ﷺ said: <hadith excerpt>..." (real hadith only)
4. REFLECTION: a thoughtful question that prompts reflection (e.g., "What if the thing you lost was protecting you?")
5. REMINDER: a short, direct reminder of faith, prayer, gratitude, or patience
6. STORY: a brief story of a Prophet, Companion, or righteous person

The DECLARATIVE_STATEMENT style is the new gold standard. Look for the moment in the transcript where the speaker states a clear, powerful truth in 4-7 words. That becomes the entire caption_hook. Examples of what works:
- "The Prophet ﷺ smiled before he spoke" → "He Smiled Before He Spoke"
- "Everything happens for a reason, we just don't know it" → "Allah's Plan is Always Better"
- "If you want peace, make dhikr" → "Peace Lives in Dhikr"
- "Paradise is under the feet of mothers" → "Jannah is Under Her Feet"
- "Dua is the weapon of the believer" → "Your Weapon is Dua"

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
- caption_hook: a punchy on-screen text overlay for the first 2 seconds (3-7 words, ISLAMIC-FRIENDLY, declarative or strong imperative, no hashtags, no "subscribe", no "like if you agree", no "wait for it", no "watch till the end", no "you won't believe"). Examples that work: "Real Success is the Hereafter", "Your Duas Are Not Wasted", "Trust Allah's Timing", "Jannah is Worth the Wait"
- mood: one of [reflective, motivational, peaceful, scholarly, devotional]
- pillar: one of the 8 content pillars above
- reference_claim: if the clip mentions a specific Quran verse or hadith, include the reference EXACTLY as it appears in the transcript (e.g., "Quran 2:255" or "Bukhari 1"). If no specific reference, leave empty string. DO NOT INVENT REFERENCES.

Respond ONLY with a valid JSON array. No explanation, no markdown, no preamble.
Format: [array of objects with keys: start, end, hook_strength, retention, shareability, reason, mood, pillar, caption_hook, reference_claim]

Rules:
- Return EXACTLY {max_clips} clips
- Each clip must be 15-40 seconds long (cap at 40s even if transcript segment is longer)
- Do not pick clips that start mid-sentence or mid-thought
- Prefer clips where total score (hook_strength + retention + shareability) >= 20
- If the transcript contains Arabic, the first 3 seconds should often start with the Arabic (for the dual-frame overlay)
- Prioritize clips that contain a DECLARATIVE_STATEMENT (X is Y pattern) — these have the highest viral potential
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
    niche: str = "general", platform: str = "all", max_clips: int = 3,
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
    max_clips_int = max(1, min(10, int(max_clips or 3)))
    viral_prompt = _VIRAL_PROMPT.format(max_clips=max_clips_int)

    for chunk in chunks:
        chunk_text = filter_segments(chunk, max_chars=6000)
        market_block = f"\n\n{market_context_str}" if market_context_str else ""
        user_message = (
            f"NICHE: {niche}\nPLATFORM: {platform}\nDURATION: {duration:.0f}"
            f"{market_block}"
            f"\n\nTRANSCRIPT:\n{chunk_text}"
        )
        try:
            data = _call_ai(viral_prompt, user_message, "clip_finder")
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
    max_keep = max(1, min(10, int(max_clips or 3)))
    deduped = deduped[:max_keep]
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

HIGH-PERFORMING HOOK PATTERNS (learned from 7 reference Shorts with 200K-2.4M views):

Pattern A — IMPERATIVE + EMOTION + CONSEQUENCE:
  "Beg Allah till he gives you what your heart wants"
  "Trust Allah for everything - No matter what"

Pattern B — TIME MARKER + ACTION + RESULT:
  "The moment you give up, that's when the door closes"
  "The day you stop worrying, that's the day peace arrives"

Pattern C — STATEMENT + DIVINE PROMISE:
  "Nothing is impossible for Allah"
  "Allah is the planner, not you"

Pattern D — DIRECT ADDRESS + REASSURANCE:
  "Don't stress, Allah is the planner"
  "You are not alone, Allah is with you"

IF FALLBACK MODE (no transcript):
Hook must be mood + pillar-based only.
Format: [imperative/emotion word] + [spiritual action] + [open reflection]

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
Prefer Pattern A, B, C, or D from the high-performer list above.

==================================================
TITLE RULES
==================================================

CRITICAL FORMAT (learned from 7 reference Shorts with 200K-2.4M views):

Format:  [Hook] - [Scholar Name]
Example: "Trust Allah for everything - No matter what - Mufti Menk"
Example: "Beg Allah till he gives you what your heart wants - Mufti Menk"
Example: "The moment you give up, that's when the door closes - Mufti Menk"

ALTERNATIVE FORMATS (use only if scholar not detected):
  [Hook] - [Islamic keyword]   e.g. "Trust Allah for everything - Quran Reflection"
  [Hook] | [Pillar]            e.g. "Don't stress, Allah is the planner | Hadith"

TITLE HARD RULES:
- 30-65 characters (sweet spot 40-55)
- Hook phrase IS the title (not "Reminder:" or "Quran Verse:" prefix)
- Scholar name ALWAYS at the end after a dash (trust signal + searchability)
- NEVER use these prefixes: "Reminder:", "Quran Verse:", "Scholar Quote:", "Islamic:", "Daily:"
- NEVER use these patterns: "This will change you", "You need to hear this", "Powerful reminder"
- The title should be a scroll-stopper AND a searchable keyword

SCHOLAR NAME DETECTION:
- If transcript mentions "Mufti Menk", "Omar Suleiman", "Nouman Ali Khan",
  "Yasir Qadhi", "Mishary", "Maher", "Husary", "Sudais", "Tariq Jameel",
  "Javed Ghamidi", "Dr. Israr", "Akhtaruzzaman" — use that name
- If no scholar detected, use the pillar name as suffix:
  "Quran Reflection" / "Hadith Reminder" / "Dua Reminder"

IF FALLBACK MODE:
Title = [Hook] - Islamic Reminder
Example: "Your heart needs this reminder - Islamic Reminder"
Not: "The Powerful Reminder" or "This Will Change You"

==================================================
TAG RULES
==================================================

Return exactly 6-10 tags per clip. More than 5 is now expected.

TAG STRATEGY (learned from 7 reference Shorts):
Tags must include ALL FOUR types:

1. SCHOLAR TAG (if detected): "muftimenk", "omarsuleiman", "noumanalikhan"
   — Critical for reach within scholar fanbase
2. NICHE TAG (content type): "quran", "hadith", "dua", "reminder", "islamiclifestyle"
3. TRENDING TAG (discoverability): "islamicstatus", "islamicreminder",
   "islamiclifestyle", "islamiclectures", "islamicvideo", "allah", "muslimreminder"
4. CROSS-PROMO TAG (one other scholar): "omarsuleiman" (when clip is mufti menk)
   — Algorithm surfaces your video in other scholar communities

TRENDING TAG POOL (pick 2-3 from this list per clip):
islamicstatus, islamicreminder, islamiclifestyle, islamiclectures,
islamicvideo, allah, allahuakbar, subhanallah, quran, hadith, dua,
deen, iman, taqwa, muslim, muslimtiktok, muslimreminder, palestine,
scholar, lecture, reminder, motivation, patience, sabr, tawakkul, shukr

GOOD TAG EXAMPLES:
["muftimenk", "quran", "reminder", "islamicstatus", "islamiclifestyle",
 "allah", "omarsuleiman", "muslimreminder"]
["muftimenk", "hadith", "scholar", "islamiclectures", "deen",
 "islamicreminder", "subhanallah", "noumanalikhan"]
["muftimenk", "dua", "peaceful", "islamiclifestyle", "allah",
 "islamicstatus", "muslim", "mashallah"]

BAD TAGS (REJECTED):
["general", "powerful", "viral", "fyp", "trending", "motivation" alone]

NEVER repeat the same tag across all clips — each clip needs unique trending tag.

==================================================
CAPTION RULES
==================================================

Generate 3 captions per clip. Each must be platform-native AND Islamic.
Reference Shorts use EMPTY descriptions on YouTube — keep captions PUNCHY.

INSTAGRAM (1-2 sentences + 5-7 hashtags):
- 1-2 sentences max, sincere tone
- End with reflection prompt OR "Send this to [family member]"
- 5-7 Islamic-specific hashtags (NOT #general, NOT #viral, NOT #fyp)
- Acceptable: "SubhanAllah. The verse that reminds us of His mercy. Send this to someone who needs it today. #quran #islam #reminder #islamicreminder #islamicstatus #deen #allah"
- Rejected: "Share this with friends! #general #viral"

TIKTOK (1 sentence + 2-3 hashtags):
- 1 sentence max, sincere but conversational
- 2-3 Islamic-specific hashtags only
- No emojis overload, no clickbait
- Acceptable: "The verse that calms every anxious heart #quran #islam #islamicreminder"
- Rejected: "wait for it #fyp #viral"

YOUTUBE (1 sentence + 3-5 hashtags):
- 1-2 sentences MAX (reference uses empty descriptions)
- First line contains searchable Islamic keyword
- Soft engagement prompt (NOT "like and subscribe")
- 3-5 Islamic hashtags
- Acceptable: "Quran reflection on the verse of the throne. Drop a SubhanAllah in the comments. #quran #islam #shorts #islamicreminder"
- Rejected: "Like if you agree! #general"

==================================================
INPUT FORMAT
==================================================

You will receive:

NICHE: islamic
FALLBACK_MODE: [true / false]
SCHOLAR_NAME: [e.g. "Mufti Menk" — use this in EVERY title with format " - [Scholar Name]"]
CLIPS: [array of {id, start, end, duration, mood, pillar, scholar_name}]

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


BANNED_TITLE_PREFIXES = (
    "Reminder:", "Quran Verse:", "Scholar Quote:", "Islamic:",
    "Daily:", "Powerful:", "Islamic Reminder:", "Today:", "Watch:",
    "This Will", "You Need To", "Listen:", "Important:", "Lesson:",
    "Beautiful:", "Amazing:", "Incredible:", "Must Watch:",
)

SCHOLAR_TAG_MAP = {
    "Mufti Menk": "muftimenk",
    "Omar Suleiman": "omarsuleiman",
    "Nouman Ali Khan": "noumanalikhan",
    "Yasir Qadhi": "yasirqadhi",
    "Mohamed Hoblos": "mohamedhoblos",
    "Ali Hammuda": "alimhammuda",
    "Muhammad Salah": "muhammadsalah",
    "Mishary Rashid Alafasy": "misharyrashid",
    "Maher Al Muaiqly": "maheralmuaiqly",
}

# Arabic tag equivalents (from reference Shorts like 2.4M-view "Trust Allah...")
SCHOLAR_ARABIC_TAGS = {
    "Mufti Menk": ["مفتي منك", "اسماعيل منك", "اسماعيل بن موسى منك"],
    "Omar Suleiman": ["عمر سليمان", "الدكتور عمر"],
    "Nouman Ali Khan": ["نعمان علي خان"],
    "Yasir Qadhi": ["ياسر قادري"],
    "Mishary Rashid Alafasy": ["مشاري العفاسي", "مشاري راشد"],
    "Maher Al Muaiqly": ["ماهر المعيقلي"],
    "Muhammad Salah": ["محمد صلاح"],
}


def _enforce_title_pattern(title: str, scholar_name: str = "", pillar: str = "") -> str:
    """Force title to [Hook] - [Scholar Name] or [Hook] - [Pillar] pattern.

    Strips banned prefixes (Reminder:, Quran Verse:, etc.), truncates if too long,
    and appends scholar name if not already present.
    """
    if not title:
        title = "Islamic Reminder"
    title = title.strip().strip('"').strip("'")
    title_lower = title.lower()
    for prefix in BANNED_TITLE_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix):].lstrip(" :|-")
            break
    for prefix_lower in [p.lower() for p in BANNED_TITLE_PREFIXES]:
        if title_lower.startswith(prefix_lower):
            title = title[len(prefix_lower):].lstrip(" :|-")
            break
    if scholar_name and scholar_name.lower() not in title.lower():
        suffix = f" - {scholar_name}"
        if len(title) + len(suffix) <= 70:
            title = title.rstrip(" -|") + suffix
        else:
            max_hook = 70 - len(suffix) - 1
            if len(title) > max_hook:
                title = title[:max_hook].rstrip(" ,;:-")
            title = title + suffix
    elif pillar and not scholar_name:
        pillar_suffix = {
            "QURAN_VERSE": "Quran Reflection",
            "HADITH": "Hadith Reminder",
            "DUA": "Dua Reminder",
            "REMINDER": "Islamic Reminder",
            "STORY_OF_PROPHET": "Prophetic Story",
            "STORY_OF_COMPANION": "Companion Story",
            "SCHOLAR_QUOTE": "Scholar Reminder",
            "ISLAMIC_LIFESTYLE": "Islamic Lifestyle",
        }.get(pillar, "Islamic Reminder")
        if pillar_suffix.lower() not in title.lower():
            suffix = f" - {pillar_suffix}"
            if len(title) + len(suffix) <= 70:
                title = title.rstrip(" -|") + suffix
    if len(title) > 80:
        title = title[:80].rstrip(" ,;:-")
    return title


def _enforce_hook(hook: str) -> str:
    """Enforce hook rules: max 8 words, no banned phrases, strip quotes."""
    if not hook:
        return ""
    hook = hook.strip().strip('"').strip("'")
    banned_hooks = [
        "wait for it", "watch till the end", "this is crazy", "mind blown",
        "subscribe", "like and subscribe", "like if you agree", "follow for more",
        "hey guys", "so today", "in this video", "going viral", "you won't believe",
        "funny", "comedy", "lol", "lmao", "hilarious",
    ]
    hook_lower = hook.lower()
    for b in banned_hooks:
        if b in hook_lower:
            return ""
    words = hook.split()
    if len(words) > 8:
        hook = " ".join(words[:8])
    return hook


def _enforce_tags(tags: list, pillar: str = "", scholar_name: str = "", all_clips: list = None) -> list:
    """Enforce tag rules: 6-10 tags, no generic, include scholar + pillar + trending.

    all_clips is used to avoid duplicating trending tags across clips.
    """
    if not isinstance(tags, list):
        tags = []
    out = []
    seen = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        t_clean = t.lower().strip().lstrip("#").replace(" ", "")
        if not t_clean or t_clean in seen:
            continue
        if t_clean in {"general", "viral", "fyp", "foryou", "trending", "powerful", "motivation"}:
            continue
        seen.add(t_clean)
        out.append(t_clean)
    if scholar_name:
        handle = SCHOLAR_TAG_MAP.get(scholar_name, scholar_name.lower().replace(" ", "").replace(".", ""))[:14]
        if handle and handle not in seen:
            out.insert(0, handle)
            seen.add(handle)
    if pillar and pillar not in seen:
        out.append(pillar.lower().replace("_", ""))
        seen.add(pillar.lower().replace("_", ""))
    used_trending = set()
    if all_clips:
        for prev in all_clips:
            for pt in prev.get("tags", []):
                if pt in TRENDING_ISLAMIC_TAGS:
                    used_trending.add(pt)
    pillar_pool = generate_trending_tags(pillar, scholar_name, count=4)
    for pt in pillar_pool:
        if pt not in used_trending and pt not in seen and len(out) < 10:
            out.append(pt)
            seen.add(pt)
            used_trending.add(pt)
    if scholar_name and len(out) < 10:
        cross = cross_promotion_tag(scholar_name)
        if cross and cross not in seen:
            out.append(cross)
            seen.add(cross)
    # Add Arabic scholar tag (matches reference Shorts like 2.4M-view "Trust Allah...")
    if scholar_name and len(out) < 11:
        arabic_tags = SCHOLAR_ARABIC_TAGS.get(scholar_name, [])
        if arabic_tags:
            arb = arabic_tags[0]
            if arb not in seen:
                out.append(arb)
                seen.add(arb)
    return out[:11]


def generate_metadata_agent2(transcript: list, clips: list, duration: float, niche: str = "general", fallback_mode: bool = False, scholar_name: str = "") -> dict:
    from ..download.transcriber import filter_segments
    from ..download import market
    transcript_text = filter_segments(transcript, max_chars=6000)

    market_block = ""
    try:
        market_ctx = market.get_market_context(niche=niche)
        market_block = "\n\n" + market.format_market_for_prompt(market_ctx)
    except Exception as e:
        print(f"[ai] market context fetch failed (agent2): {e}", flush=True)

    if not scholar_name and clips and isinstance(clips[0], dict):
        scholar_name = clips[0].get("scholar_name", "") or ""

    user_message = (
        f"NICHE: {niche}\nFALLBACK_MODE: {str(fallback_mode).lower()}\n"
        f"SCHOLAR_NAME: {scholar_name or '(none detected — use pillar as suffix)'}\n"
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

        clip_scholar = c.get("scholar_name", "") or scholar_name

        title = _enforce_title_pattern(title, clip_scholar, pillar)
        hook_text = _enforce_hook(hook_text)
        tags = _enforce_tags(tags, pillar, clip_scholar, all_clips=normalized)

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
            "scholar_name": clip_scholar,
            "reason": c.get("reason", ""),
            "hook_text": hook_text,
            "title": title,
            "tags": tags if isinstance(tags, list) else [],
            "caption_instagram": caption_ig,
            "caption_tiktok": caption_tt,
            "caption_youtube": caption_yt
        })

    return {"clips": normalized}
