import re
from pathlib import Path

MAX_WORDS_PER_CARD = 4
HIGHLIGHT_COLOR = "&H00FFD700"
ACCENT_COLORS = {
    "hype":      "&H0030FFE0",
    "funny":     "&H0080FF20",
    "chill":     "&H00FFC840",
    "emotional": "&H00FFA0FF",
    "serious":   "&H00E0E0E0",
}
EMOTION_KEYWORDS = {"shock", "surprise", "conflict", "rage", "failure", "win", "loss",
                    "amazing", "incredible", "worst", "best", "never", "always",
                    "terrible", "huge", "massive", "disaster", "genius", "destroyed",
                    "unbelievable", "insane", "crazy", "dangerous", "secret", "betrayed",
                    "love", "hate", "fear", "hope", "truth", "lie", "died", "dead",
                    "killed", "kill", "fire", "slay", "ate", "iconic", "legend"}

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
    return words | EMOTION_KEYWORDS

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


def _split_into_cards(text: str) -> list:
    words = text.split()
    cards = []
    for i in range(0, len(words), MAX_WORDS_PER_CARD):
        chunk = words[i:i + MAX_WORDS_PER_CARD]
        cards.append(" ".join(chunk))
    return cards

def _highlight_text(text: str, highlight_words: set, accent_color: str = HIGHLIGHT_COLOR) -> str:
    words = text.split()
    result = []
    for w in words:
        clean = w.lower().strip(".,!?;:'\"()[]{}")
        is_number = bool(re.search(r"\d", clean))
        is_keyword = clean in highlight_words
        if is_number or is_keyword:
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
              hook_text: str = "", mood: str = "hype") -> str:
    highlight_words = _get_highlight_words(hook_text)
    accent = _accent_for(mood)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,130,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,3,0,0,2,40,40,180,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for seg in transcript:
        seg_start = seg["start"]
        seg_end = seg["end"]
        if seg_end <= clip_start or seg_start >= clip_end:
            continue
        adj_start = max(seg_start, clip_start) - clip_start
        adj_end = min(seg_end, clip_end) - clip_start
        if adj_end - adj_start < 0.3:
            continue

        word_events = _build_word_level_events(seg, adj_start, adj_end, highlight_words, accent)
        if word_events:
            events.extend(word_events)
            continue

        text_upper = seg["text"].upper().strip().replace("'", "")
        if not text_upper:
            continue

        cards = _split_into_cards(text_upper)
        total_cards = len(cards)

        for i, card_text in enumerate(cards):
            s, e = _time_slice(adj_start, adj_end, i, total_cards)
            if e - s < 0.3:
                continue
            highlighted = _highlight_text(card_text, highlight_words, accent)
            events.append(
                f"Dialogue: 0,{format_ts_ass(s)},{format_ts_ass(e)},Default,,0,0,0,,{highlighted}"
            )

    if not events:
        return ""

    return header + "\n".join(events)

def write_ass(transcript: list, clip_start: float, clip_end: float, output_dir: str,
              hook_text: str = "", filename: str = "subs.ass", mood: str = "hype") -> str:
    ass_content = build_ass(transcript, clip_start, clip_end, hook_text, mood=mood)
    ass_path = Path(output_dir) / filename
    if not ass_content.strip():
        return ""
    ass_path.write_text(ass_content, encoding="utf-8")
    return str(ass_path)
