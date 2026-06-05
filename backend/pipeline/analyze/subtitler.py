import re
from pathlib import Path

MAX_WORDS_PER_CARD = 4
MAX_WORDS_PER_CARD_REFERENCE = 3  # tighter, 2-line, like the Mufti Menk reference
MAX_WORDS_PER_CARD_CREATOR = 3   # Hormozi/Abdaal/MrBeast style: 1-3 words per card
HIGHLIGHT_COLOR = "&H00FFD700"  # gold (default)
CREATOR_HIGHLIGHT_COLOR = "&H0000D4FF"  # yellow #FFD400 in BGR (Hormozi/Abdaal style)
CREATOR_ACCENT_COLOR = "&H00FFE500"     # cyan #00E5FF in BGR (alternative)
ISLAMIC_SACRED_COLOR = "&H0000C040"  # green for Allah/Jannah/Quran
ISLAMIC_WARNING_COLOR = "&H004040FF"  # red for Jahannam/sin/warning
HOOK_COLOR = "&H00FFFFFF"  # white hook text
HOOK_BG_COLOR = "&H80000000"  # semi-transparent black
REFERENCE_KEYWORD_COLOR = "&H0000FFFF"  # cyan keyword highlight (Mufti Menk Shorts style)

ACCENT_COLORS = {
    "hype":         "&H0030FFE0",  # cyan
    "funny":        "&H0080FF20",  # green
    "chill":        "&H00FFC840",  # yellow
    "emotional":    "&H00FFA0FF",  # purple
    "serious":      "&H00E0E0E0",  # gray
    # Islamic moods
    "reflective":   "&H00FFD700",  # gold
    "motivational": "&H00FF8000",  # orange
    "peaceful":     "&H0080FFB0",  # soft cyan-green
    "scholarly":    "&H00C0C0FF",  # pale blue
    "devotional":   "&H0000FFC0",  # teal
}
EMOTION_KEYWORDS = {"shock", "surprise", "conflict", "rage", "failure", "win", "loss",
                    "amazing", "incredible", "worst", "best", "never", "always",
                    "terrible", "huge", "massive", "disaster", "genius", "destroyed",
                    "unbelievable", "insane", "crazy", "dangerous", "secret", "betrayed",
                    "love", "hate", "fear", "hope", "truth", "lie", "died", "dead",
                    "killed", "kill", "fire", "slay", "ate", "iconic", "legend"}

# Islamic emotion keywords - color-coded
ISLAMIC_SACRED_WORDS = {
    "allah", "allah's", "allahs", "subhanallah", "mashallah", "alhamdulillah",
    "inshallah", "insha'Allah", "jannah", "jannat", "paradise",
    "quran", "qur'an", "quraan", "ayah", "ayat", "verse", "hadith", "sunnah",
    "prophet", "prophets", "muhammad", "saw", "pbuh", "rasul", "nabi",
    "deen", "iman", "taqwa", "tawheed", "tauhid", "shahada", "shahadah",
    "ramadan", "ramadhan", "eid", "hajj", "umrah", "zakat", "sadaqah",
    "dua", "du'a", "supplication", "mercy", "forgive", "forgiveness", "forgiven",
    "blessed", "blessing", "blessings", "guide", "guided", "guidance", "hidayet",
    "taufique", "repent", "repentance", "taubah", "istighfar", "tawba",
    "scholar", "scholars", "ulema", "imam", "shaykh", "mufti",
    "muslim", "muslims", "ummah", "brother", "sister", "brothers", "sisters",
    "salat", "salah", "prayer", "pray", "fast", "fasting", "hajj",
    "honor", "honour", "modesty", "haya", "sabr", "patience", "shukr", "gratitude",
    "tawakkul", "trust", "rely", "reliance", "ikhlas", "sincere", "taqwa",
    "akhee", "akh", "habibi", "beloved",
}
ISLAMIC_WARNING_WORDS = {
    "jahannam", "jahanna", "hellfire", "hell", "punishment", "torment",
    "shaytan", "shaitan", "satan", "devil", "evil", "sin", "sins", "sinner",
    "wrong", "wrongdoing", "disobey", "disobeyed", "disobedience",
    "backbite", "backbiting", "gossip", "slander", "lie", "lies", "liar",
    "hypocrite", "hypocrisy", "munafiq", "munafiqeen",
    "divided", "division", "fitnah", "trial", "tribulation",
    "enemy", "enemies", "hate", "hatred", "anger", "wrath",
    "forget", "forgotten", "neglect", "abandon", "abandoned",
    "doubt", "doubting", "despair", "hopeless", "lost",
}
ISLAMIC_KEYWORDS = ISLAMIC_SACRED_WORDS | ISLAMIC_WARNING_WORDS

def format_ts_ass(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def _get_highlight_words(hook_text: str) -> set:
    words = set()
    if hook_text:
        for w in hook_text.lower().split():
            clean = re.sub(r"[^a-z0-9]", "", w)
            if len(clean) > 2:
                words.add(clean)
    return words | EMOTION_KEYWORDS | ISLAMIC_KEYWORDS


def _get_word_color(word: str) -> str:
    """Determine color for a word based on Islamic significance."""
    clean = word.lower().strip(".,!?;:'\"()[]{}")
    if clean in ISLAMIC_SACRED_WORDS:
        return ISLAMIC_SACRED_COLOR  # green for sacred terms
    if clean in ISLAMIC_WARNING_WORDS:
        return ISLAMIC_WARNING_COLOR  # red for warnings
    return None  # use default


def _build_hook_card_events(hook_text: str, accent_color: str, duration: float = 2.0) -> list:
    """Build a large hook text overlay that appears for the first `duration` seconds.

    Renders the hook text as a big card centered on screen, similar to high-performer
    Islamic Shorts that show a hook phrase in the first 1-2 seconds.
    """
    if not hook_text or len(hook_text.strip()) < 3:
        return []
    text = hook_text.upper().strip().replace("'", "").replace('"', "")
    # Word-level break for readability: max 5 words per line
    words = text.split()
    if len(words) > 5:
        # Keep the strongest 5 words (first ones usually are)
        text = " ".join(words[:5])
    return [
        f"Dialogue: 0,0:00:00.10,0:00:0{duration:.2f},HookCard,,0,0,0,,{text}"
    ]


def _build_watermark_events(brand_text: str, duration: float) -> list:
    """Small brand watermark at the bottom-right corner throughout the clip."""
    if not brand_text or len(brand_text.strip()) < 2:
        return []
    return [
        f"Dialogue: 0,0:00:00.00,{format_ts_ass(duration)},Watermark,,0,0,0,,{brand_text}"
    ]


def _build_cta_events(duration: float, cta_text: str = "Follow for more") -> list:
    """End-of-clip CTA card. Shows for the last 1.5 seconds of the clip.

    Drives follows/shares by giving viewers a clear next action.
    """
    if duration < 5:
        return []
    cta_start = max(0.0, duration - 1.5)
    cta_start_str = format_ts_ass(cta_start)
    end_str = format_ts_ass(duration)
    return [
        f"Dialogue: 0,{cta_start_str},{end_str},CTACard,,0,0,0,,{cta_text.upper()}"
    ]

def _accent_for(mood: str) -> str:
    return ACCENT_COLORS.get((mood or "").lower(), HIGHLIGHT_COLOR)


def _highlight_word_token(word: str, is_kw: bool, accent_color: str) -> str:
    base = word.upper().replace("'", "")
    if is_kw:
        return f"{{\\c{accent_color}}}{base}{{\\c}}"
    return base


def _build_word_level_events(seg: dict, adj_start: float, adj_end: float,
                              highlight_words: set, accent_color: str) -> list:
    """If whisper gave us word timestamps, emit one Dialogue per word so
    the highlight color travels with the spoken word — the karaoke effect."""
    words = seg.get("words") or []
    if not words:
        return []
    seg_dur = adj_end - adj_start
    if seg_dur <= 0:
        return []
    events = []
    visible = [w for w in words if (w.get("end", 0) - w.get("start", 0)) > 0.05]
    if not visible:
        return []
    n = len(visible)
    if n <= MAX_WORDS_PER_CARD:
        for w in visible:
            ws = max(adj_start, w["start"] - adj_start + adj_start)
            we = min(adj_end, w["end"] - adj_start + adj_start)
            ws = max(adj_start, w["start"] - adj_start)
            we = min(adj_end, w["end"] - adj_start)
            if we <= ws:
                continue
            clean = re.sub(r"[^a-z0-9]", "", (w.get("word", "") or "").lower())
            is_kw = clean in highlight_words
            tok = _highlight_word_token(w.get("word", ""), is_kw, accent_color)
            events.append(
                f"Dialogue: 0,{format_ts_ass(ws)},{format_ts_ass(we)},Default,,0,0,0,,{tok}"
            )
        return events
    chunk_dur = seg_dur / n
    for i, w in enumerate(visible):
        ws = adj_start + i * chunk_dur
        we = ws + chunk_dur
        clean = re.sub(r"[^a-z0-9]", "", (w.get("word", "") or "").lower())
        is_kw = clean in highlight_words
        tok = _highlight_word_token(w.get("word", ""), is_kw, accent_color)
        events.append(
            f"Dialogue: 0,{format_ts_ass(ws)},{format_ts_ass(we)},Default,,0,0,0,,{tok}"
        )
    return events


def _split_into_cards(text: str, style: str = "default") -> list:
    words = text.split()
    if style == "creator":
        cap = MAX_WORDS_PER_CARD_CREATOR
    elif style == "reference":
        cap = MAX_WORDS_PER_CARD_REFERENCE
    else:
        cap = MAX_WORDS_PER_CARD
    cards = []
    for i in range(0, len(words), cap):
        chunk = words[i:i + cap]
        cards.append(" ".join(chunk))
    return cards

def _highlight_text(text: str, highlight_words: set, accent_color: str = HIGHLIGHT_COLOR) -> str:
    words = text.split()
    result = []
    for w in words:
        clean = w.lower().strip(".,!?;:'\"()[]{}")
        is_number = bool(re.search(r"\d", clean))
        is_keyword = clean in highlight_words
        # Islamic color override
        islamic_color = _get_word_color(w)
        if islamic_color:
            base = w.upper().replace("'", "")
            result.append(f"{{\\c{islamic_color}}}{base}{{\\c}}")
        elif is_number or is_keyword:
            base = w.upper().replace("'", "")
            result.append(f"{{\\c{accent_color}}}{base}{{\\c}}")
        else:
            result.append(w)
    return " ".join(result)

def _time_slice(seg_start: float, seg_end: float, card_index: int, total_cards: int) -> tuple:
    seg_dur = seg_end - seg_start
    card_dur = seg_dur / max(total_cards, 1)
    s = seg_start + card_index * card_dur
    e = s + card_dur
    return (s, e)

def build_ass(transcript: list, clip_start: float, clip_end: float,
              hook_text: str = "", mood: str = "hype", brand_text: str = "",
              style: str = "default") -> str:
    """Build an ASS subtitle file.

    style="creator"    -> Hormozi/Abdaal/MrBeast creator style: bold Anton, white text
                          with thick black stroke, NO box, 1-3 words per line, ONE
                          impact word per line in yellow/cyan and 115% scaled, pop-in
                          animation. Pairs with a bottom gradient overlay.
    style="reference"  -> Mufti Menk Shorts style: white 150px text with cyan keyword
                          highlight, tight 3-word 2-line layout, center-low position.
    style="default"    -> bottom-anchored gold-highlight subtitles (original).
    """
    highlight_words = _get_highlight_words(hook_text)
    accent = _accent_for(mood)
    duration = clip_end - clip_start
    style_lc = (style or "default").lower()
    is_ref = style_lc == "reference"
    is_creator = style_lc == "creator"

    if is_creator:
        # Creator / Hormozi/Abdaal/MrBeast style:
        #   - Anton (tall, condensed, super-bold modern font) for max impact
        #   - White text with 8px black stroke + 1px soft shadow, NO box
        #   - BorderStyle=1 (no opaque background), BackColour=transparent
        #   - One impact word per line in yellow (#FFD400) or cyan (#00E5FF)
        #     at 115% scale (applied per-line via _highlight_creator)
        #   - Pop-in animation per caption (90% -> 100% over 180ms)
        #   - Bottom-of-frame position (MarginV 600) so it sits above IG/TT/YT UI
        #     and is paired with the bottom_gradient.png overlay for readability
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Creator,Anton,130,&H00FFFFFF,&H00FFD400,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,1,2,40,40,600,1
Style: CreatorAccent,Anton,150,&H0000D4FF,&H00FFD400,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,8,1,2,40,40,600,1
Style: HookCard,Anton,200,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,10,1,5,40,40,1000,1
Style: Watermark,Poppins,55,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,4,0,3,40,80,90,1
Style: CTACard,Anton,160,&H00FFFFFF,&H00FFD400,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,6,0,5,40,40,700,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        main_style = "Creator"
        main_margin_v = 600
        creator_accent = CREATOR_HIGHLIGHT_COLOR  # yellow #FFD400
    elif is_ref:
        # Reference style: white 150px Arial Black, thick black outline, back pad, bottom-center.
        # Use ReferenceDefault for 2-line white + cyan keyword (the Mufti Menk Shorts look).
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ReferenceDefault,Arial Black,150,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,8,2,2,40,40,520,1
Style: HookCard,Arial Black,180,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,0,0,5,40,40,780,1
Style: Watermark,Arial,55,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,3,0,0,3,40,80,90,1
Style: CTACard,Arial Black,140,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,0,0,5,40,40,700,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        main_style = "ReferenceDefault"
        main_margin_v = 520
    else:
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,130,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,0,0,2,40,40,180,1
Style: HookCard,Arial Black,180,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,0,0,5,40,40,780,1
Style: Watermark,Arial,55,&H00FFFFFF,&H00FFFFFF,&H00000000,&H40000000,0,0,0,0,100,100,0,0,3,0,0,3,40,80,90,1
Style: CTACard,Arial Black,140,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,0,0,5,40,40,700,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        main_style = "Default"
        main_margin_v = 180

    events = []

    # 1) Hook card at start (large white text, centered, 0-2s)
    hook_events = _build_hook_card_events(hook_text, accent, duration=2.0)
    events.extend(hook_events)

    # 2) Watermark throughout (small brand text, bottom-right)
    wm_events = _build_watermark_events(brand_text, duration)
    events.extend(wm_events)

    # 3) CTA card at end (last 1.5s, drives follow/share action)
    cta_events = _build_cta_events(duration, "Follow for more")
    events.extend(cta_events)

    # 4) Main subtitles
    for seg in transcript:
        seg_start = seg["start"]
        seg_end = seg["end"]
        if seg_end <= clip_start or seg_start >= clip_end:
            continue
        adj_start = max(seg_start, clip_start) - clip_start
        adj_end = min(seg_end, clip_end) - clip_start
        if adj_end - adj_start < 0.3:
            continue

        text_upper = seg["text"].upper().strip().replace("'", "")
        if not text_upper:
            continue

        cards = _split_into_cards(text_upper, style)
        total_cards = len(cards)

        for i, card_text in enumerate(cards):
            s, e = _time_slice(adj_start, adj_end, i, total_cards)
            if e - s < 0.3:
                continue
            if is_creator:
                # Creator style: 1-3 words, yellow impact word, pop-in animation
                highlighted = _highlight_creator(card_text, creator_accent)
                # Wrap in pop-in animation: 90% scale -> 100% over 180ms with fade
                text_with_anim = (
                    f"{{\\fscx90\\fscy90\\fad(120,80)}}"
                    f"{highlighted}"
                    f"{{\\t(0,180,\\fscx100\\fscy100)}}"
                )
            elif is_ref:
                # Highlight the LAST word of the line in cyan (the "punch word")
                highlighted = _highlight_last_word_cyan(card_text)
                text_with_anim = highlighted
            else:
                highlighted = _highlight_text(card_text, highlight_words, accent)
                text_with_anim = highlighted
            events.append(
                f"Dialogue: 0,{format_ts_ass(s)},{format_ts_ass(e)},{main_style},,0,0,{main_margin_v},,{text_with_anim}"
            )

    if not events:
        return ""

    return header + "\n".join(events)


def _highlight_last_word_cyan(text: str) -> str:
    """Reference-style highlight: white text with the LAST word in cyan.

    Matches the Mufti Menk Shorts look: e.g. "and success in the" / "next world".
    The last word of each line is the punch word and gets cyan (REFERENCE_KEYWORD_COLOR).
    """
    words = text.split()
    if not words:
        return text
    out = []
    for i, w in enumerate(words):
        clean = w.lower().strip(".,!?;:'\"()[]{}")
        islamic_color = _get_word_color(w)
        if islamic_color:
            base = w.upper().replace("'", "")
            out.append(f"{{\\c{islamic_color}}}{base}{{\\c}}")
        elif i == len(words) - 1:
            base = w.upper().replace("'", "")
            out.append(f"{{\\c{REFERENCE_KEYWORD_COLOR}}}{base}{{\\c}}")
        else:
            out.append(w.upper().replace("'", ""))
    return " ".join(out)


def _highlight_creator(text: str, accent_color: str = CREATOR_HIGHLIGHT_COLOR) -> str:
    """Creator-style highlight (Hormozi/Abdaal/MrBeast look):

    - 1-3 short words per line
    - WHITE bold text with thick black stroke
    - EXACTLY ONE word per line is the IMPACT word — colored yellow
      (#FFD400) or cyan (#00E5FF) and scaled 115% larger
    - No background box; relies on a bottom gradient overlay for readability
    - Pop-in animation: starts at 90% scale, eases to 100% over 180ms

    Selection priority (exactly one word wins):
      1. An Islamic sacred word (Allah, Quran, Jannah, ...) -> green
      2. An Islamic warning word (hell, sin, ...) -> red
      3. An emotion keyword (never, always, ...) -> yellow accent
      4. The LAST word of the line -> yellow accent (default punch word)
    """
    words = text.split()
    if not words:
        return text
    # Find exactly one impact word
    chosen_idx = -1
    chosen_color = accent_color
    for i, w in enumerate(words):
        islamic_color = _get_word_color(w)
        if islamic_color:
            chosen_idx = i
            chosen_color = islamic_color
            break  # sacred/warning wins, take the first one
    if chosen_idx == -1:
        # Look for an emotion keyword
        for i, w in enumerate(words):
            clean = w.lower().strip(".,!?;:'\"()[]{}")
            if clean in EMOTION_KEYWORDS:
                chosen_idx = i
                break
    if chosen_idx == -1:
        # Default: last word of the line
        chosen_idx = len(words) - 1
    out = []
    for i, w in enumerate(words):
        base = w.upper().replace("'", "")
        if i == chosen_idx:
            out.append(f"{{\\fscx115\\fscy115}}{{\\c{chosen_color}}}{base}{{\\c}}{{\\fscx100\\fscy100}}")
        else:
            out.append(base)
    return " ".join(out)


def _pop_in_wrap(text: str) -> str:
    """Wrap text in a smooth pop-in animation: scale 90% -> 100% over 180ms."""
    return f"{{\\fscx90\\fscy90\\fad(120,80)\\t(0,180,\\fscx100\\fscy100)}}{text}{{\\fad}}"


def write_ass(transcript: list, clip_start: float, clip_end: float, output_dir: str,
              hook_text: str = "", filename: str = "subs.ass", mood: str = "hype",
              brand_text: str = "", style: str = "default") -> str:
    ass_content = build_ass(transcript, clip_start, clip_end, hook_text, mood=mood, brand_text=brand_text, style=style)
    ass_path = Path(output_dir) / filename
    if not ass_content.strip():
        return ""
    ass_path.write_text(ass_content, encoding="utf-8")
    return str(ass_path)
