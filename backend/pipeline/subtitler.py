import re
import shutil
import subprocess
from pathlib import Path
from .config import FFMPEG

MAX_WORDS_PER_CARD = 5
HIGHLIGHT_COLOR = "&H0053A8D4"
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
    clip_duration = clip_end - clip_start

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,32,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2.5,0,2,10,10,80,1

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

def burn_subtitles(video_path: str, transcript: list,
                    clip_start: float, clip_end: float,
                    hook_text: str = "") -> str:
    ass_content = build_ass(transcript, clip_start, clip_end, hook_text)
    if not ass_content.strip():
        return video_path

    output_path = video_path.replace(".mp4", "_subbed.mp4")
    output_dir = Path(video_path).parent
    ass_file = output_dir / "subs.ass"

    ass_file.write_text(ass_content, encoding="utf-8")

    filter_file = output_dir / "vf.txt"
    filter_file.write_text(
        f"subtitles={ass_file.name}\n",
        encoding="utf-8"
    )

    result = subprocess.run([
        FFMPEG, "-i", video_path,
        "-filter_script:v", str(filter_file),
        "-c:a", "copy", output_path, "-y"
    ], capture_output=True, text=True, cwd=str(output_dir))

    ass_file.unlink(missing_ok=True)
    filter_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"Subtitle burn failed: {result.stderr[:1500]}")

    Path(video_path).unlink(missing_ok=True)
    return output_path
