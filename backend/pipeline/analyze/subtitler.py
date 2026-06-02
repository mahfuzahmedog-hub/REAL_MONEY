import re
from pathlib import Path

MAX_WORDS_PER_CARD = 4
HIGHLIGHT_COLOR = "&H00FFD700"
EMOTION_KEYWORDS = {"shock", "surprise", "conflict", "rage", "failure", "win", "loss",
                    "amazing", "incredible", "worst", "best", "never", "always",
                    "terrible", "huge", "massive", "disaster", "genius", "destroyed",
                    "unbelievable", "insane", "crazy", "dangerous", "secret", "betrayed"}

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

def _split_into_cards(text: str) -> list:
    words = text.split()
    cards = []
    for i in range(0, len(words), MAX_WORDS_PER_CARD):
        chunk = words[i:i + MAX_WORDS_PER_CARD]
        cards.append(" ".join(chunk))
    return cards

def _highlight_text(text: str, highlight_words: set) -> str:
    words = text.split()
    result = []
    for w in words:
        clean = w.lower().strip(".,!?;:'\"()[]{}")
        is_number = bool(re.search(r"\d", clean))
        is_keyword = clean in highlight_words
        if is_number or is_keyword:
            result.append(f"{{\\c{HIGHLIGHT_COLOR}}}{w}{{\\c}}")
        else:
            result.append(w)
    return " ".join(result)

def _time_slice(seg_start: float, seg_end: float, card_index: int, total_cards: int) -> tuple:
    seg_dur = seg_end - seg_start
    card_dur = seg_dur / max(total_cards, 1)
    s = seg_start + card_index * card_dur
    e = s + card_dur
    return (s, e)

def build_ass(transcript: list, clip_start: float, clip_end: float, hook_text: str = "") -> str:
    highlight_words = _get_highlight_words(hook_text)

    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,62,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,2,2,20,20,120,1

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

        text_upper = seg["text"].upper().strip()
        if not text_upper:
            continue

        cards = _split_into_cards(text_upper)
        total_cards = len(cards)

        for i, card_text in enumerate(cards):
            s, e = _time_slice(adj_start, adj_end, i, total_cards)
            if e - s < 0.3:
                continue
            highlighted = _highlight_text(card_text, highlight_words)
            events.append(
                f"Dialogue: 0,{format_ts_ass(s)},{format_ts_ass(e)},Default,,0,0,0,,{highlighted}"
            )

    if not events:
        return ""

    return header + "\n".join(events)

def write_ass(transcript: list, clip_start: float, clip_end: float, output_dir: str, hook_text: str = "", filename: str = "subs.ass") -> str:
    ass_content = build_ass(transcript, clip_start, clip_end, hook_text)
    ass_path = Path(output_dir) / filename
    if not ass_content.strip():
        return ""
    ass_path.write_text(ass_content, encoding="utf-8")
    return str(ass_path)
