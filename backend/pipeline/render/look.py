"""Look & feel module: color grading, watermarks, emoji reactions, hook text styling.

All filters are pure ffmpeg filter-graph strings so they can be composed
into the existing drawtext/crop chain without changing orchestration logic.
"""

MOOD_COLORS = {
    "hype":      {"primary": "0xFF3030", "accent": "0xFFD000", "grade": "hype"},
    "funny":     {"primary": "0xFFD000", "accent": "0x00FF80", "grade": "funny"},
    "chill":     {"primary": "0x40C8FF", "accent": "0xFFFFFF", "grade": "chill"},
    "emotional": {"primary": "0xFF60A0", "accent": "0xFFFFFF", "grade": "emotional"},
    "serious":   {"primary": "0xFFFFFF", "accent": "0xC0C0C0", "grade": "serious"},
}

MOOD_GRADE = {
    "hype":      "eq=brightness=0.04:saturation=1.45:contrast=1.08:gamma=0.95,colorbalance=rs=0.18:bs=-0.10:gs=-0.05,curves=preset=cross_process",
    "funny":     "eq=brightness=0.06:saturation=1.35:contrast=1.05:gamma=0.98,colorbalance=rs=0.05:bs=0.10:gs=-0.05,curves=preset=increase_contrast",
    "chill":     "eq=brightness=0.02:saturation=0.85:contrast=1.02:gamma=1.02,colorbalance=rs=-0.05:bs=0.12:gs=0.05,curves=preset=darker",
    "emotional": "eq=brightness=-0.02:saturation=0.95:contrast=1.10:gamma=1.05,colorbalance=rs=0.12:bs=-0.15:gs=-0.05,curves=preset=cross_process",
    "serious":   "eq=brightness=-0.04:saturation=0.75:contrast=1.15:gamma=1.05,colorbalance=rs=-0.10:bs=-0.05:gs=0.08,curves=darker",
    "default":   "eq=saturation=1.15:contrast=1.03",
}

PUNCHLINE_EMOJIS = ["\U0001F480", "\U0001F525", "\U0001F4AF", "\U0001F923", "\U0001F62D", "\U0001F44F"]
PUNCHLINE_KEYWORDS = {
    "\U0001F480": ["died", "dead", "kill", "killed", "skull", "casket", "coffin", "rip", "💀", "ghost", "crazy", "insane", "wild",
                   "mara", "mari", "mrityu", "khatam", "gaya", "band", "bando"],
    "\U0001F525": ["fire", "lit", "hot", "burn", "flame", "cook", "cooked", "slay", "slayed", "ate", "spicy", "heat",
                   "ag", "jala", "jalaa", "jalwa", "mast", "jhakaas", "dhamaka", "kamaal"],
    "\U0001F4AF": ["hundred", "100", "perfect", "flawless", "ace", "bullseye", "nailed",
                   "sau", "pura", "pakka", "perfect"],
    "\U0001F923": ["lol", "lmao", "haha", "rofl", "😂", "🤣", "hilarious", "joke",
                   "hassi", "hansi", "hasa", "hasi", "mazaak", "majak", "funn", "pagal", "pagol"],
    "\U0001F62D": ["crying", "tears", "broke", "broke me", "sob", "😭", "pain",
                   "ro", "roi", "rona", "aansu", "dard", "dil"],
    "\U0001F44F": ["clap", "respect", "salute", "👏", "bravo", "king", "queen", "goat",
                   "wah", "wahh", "wahji", "kya baat", "kya baat hai", "shabaash", "zabardast"],
}


def get_grade_filter(mood: str) -> str:
    return MOOD_GRADE.get((mood or "").lower(), MOOD_GRADE["default"])


def get_hook_color(mood: str) -> str:
    return MOOD_COLORS.get((mood or "").lower(), MOOD_COLORS["hype"])["primary"]


def get_accent_color(mood: str) -> str:
    return MOOD_COLORS.get((mood or "").lower(), MOOD_COLORS["hype"])["accent"]


def build_brand_watermark_filter(brand_text: str, mood: str = "hype") -> str:
    if not brand_text:
        return ""
    safe = (
        brand_text.replace("\\", " ")
        .replace("'", " ")
        .replace(":", "\\:")
        .replace("\n", " ")
    )
    color = get_hook_color(mood)
    return (
        f"drawtext=text='{safe}'"
        f":fontfile=/Windows/Fonts/impact.ttf"
        f":fontsize=34"
        f":fontcolor={color}"
        f":borderw=3"
        f":bordercolor=black@0.85"
        f":shadowx=2:shadowy=2:shadowcolor=black@0.7"
        f":x=w-tw-30"
        f":y=30"
        f":enable='gte(t,0.5)'"
    )


def build_hook_filter(caption_hook: str, mood: str = "hype") -> str:
    if not caption_hook:
        return ""
    safe = (
        caption_hook.replace("\\", " ")
        .replace("'", " ")
        .replace(":", "\\:")
    )
    color = get_hook_color(mood)
    accent = get_accent_color(mood)
    return (
        f"drawtext=text='{safe}'"
        f":fontfile=/Windows/Fonts/impact.ttf"
        f":fontsize=78"
        f":fontcolor={color}"
        f":borderw=5"
        f":bordercolor=black@0.95"
        f":shadowx=3:shadowy=3:shadowcolor={accent}@0.6"
        f":x=(w-text_w)/2"
        f":y=h*0.12"
        f":enable='between(t,0,2.8)'"
    )


def find_punchline_reactions(transcript: list, clip_start: float, clip_duration: float) -> list:
    import re
    out = []
    if not transcript:
        return out
    for seg in transcript:
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        if seg_end <= clip_start or seg_start >= clip_start + clip_duration:
            continue
        text = (seg.get("text", "") or "").lower()
        if not text:
            continue
        for emoji, kws in PUNCHLINE_KEYWORDS.items():
            for kw in kws:
                pattern = r"\b" + re.escape(kw.lower())
                if len(kw) >= 4 and kw.endswith("y"):
                    pattern = r"\b" + re.escape(kw[:-1].lower()) + r"\w*"
                if re.search(pattern, text):
                    trigger_t = (seg_start + seg_end) / 2 - clip_start
                    if 0.5 < trigger_t < clip_duration - 0.3:
                        out.append({"emoji": emoji, "t": round(trigger_t, 2)})
                        break
            if out and out[-1]["emoji"] == emoji:
                break
    seen = set()
    deduped = []
    for r in out:
        key = (r["emoji"], round(r["t"], 1))
        if key in seen:
            continue
        if any(abs(r["t"] - d["t"]) < 1.5 and r["emoji"] == d["emoji"] for d in deduped):
            continue
        seen.add(key)
        deduped.append(r)
    return deduped[:3]


def build_zoom_filter(clip_duration: float, punchline_reactions: list | None = None) -> str:
    """Ken Burns slow zoom (1.0x -> 1.15x over clip) + punchline zoom spikes.

    At punchline timestamps, briefly zooms to ~1.3x with a triangular ease,
    then resumes the slow Ken Burns zoom. Falls back to pure Ken Burns if no
    reactions provided.
    """
    rate = 0.15 / max(clip_duration, 1.0)

    spike_parts = []
    for r in (punchline_reactions or []):
        t = r["t"]
        spike_parts.append(f"max(0,0.3*(1-abs(time-{t:.1f})/0.5))")
    spike_expr = "+".join(spike_parts) if spike_parts else "0"

    z = f"min(1.5,1+{rate:.5f}*time+({spike_expr}))"
    return (
        f"zoompan=z='{z}'"
        f":x='iw/2-(iw/zoom/2)'"
        f":y='ih/2-(ih/zoom/2)'"
        f":d=1:fps=30:s=1080x1920"
    )


def build_emoji_reaction_filter(reactions: list) -> str:
    if not reactions:
        return ""
    parts = []
    for r in reactions:
        emoji = r["emoji"]
        t = r["t"]
        parts.append(
            f"drawtext=text='{emoji}'"
            f":fontfile=/Windows/Fonts/seguiemj.ttf"
            f":fontsize=160"
            f":x=(w-text_w)/2"
            f":y=h*0.60"
            f":enable='between(t,{t:.2f},{t+0.9:.2f})'"
        )
    return ",".join(parts)
