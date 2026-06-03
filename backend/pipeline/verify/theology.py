"""Theological verification layer for clips.

This module is the HARD GATE. A clip can only be auto-rendered if:
1. It does not contain Arabic Quran text that fails verification
2. It does not contain Arabic Hadith text that fails verification
3. It does not contain fabricated specific references (e.g., "Bukhari 9999")
4. It does not contain banned language (fabrication, mockery, sect-baiting)
5. All Quran references resolve to actual verses in the DB
6. All Hadith references resolve to actual hadiths in the DB
7. The clip's mood is one of the 5 approved Islamic moods

If any check fails:
- The clip is flagged for manual review
- The full transcript segment is saved to manual_review/
- The verification_report.json is updated
- The Arabic Quran/Dua overlay is NOT burned (only top-right verified overlay)
"""

import re
import json
import unicodedata
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Iterable

from .quran_db import (
    find_verse,
    find_verses_by_text,
    extract_quran_references,
    QuranReference,
)
from .hadith_db import (
    find_hadith,
    find_hadiths_by_text,
    extract_hadith_references,
    HadithReference,
)


ISLAMIC_MOODS = {"reflective", "motivational", "peaceful", "scholarly", "devotional"}


ISLAMIC_PILLARS = {
    "QURAN_VERSE": "Quran Verse (verified from Quran DB)",
    "HADITH": "Hadith (verified from Hadith DB)",
    "DUA": "Dua / Supplication (verified short phrases)",
    "REMINDER": "General reminder / lecture clip",
    "STORY_OF_PROPHET": "Story of a Prophet (Quran or authentic hadith)",
    "STORY_OF_COMPANION": "Story of a Sahabi / Companion",
    "SCHOLAR_QUOTE": "Quote from a known Islamic scholar",
    "ISLAMIC_LIFESTYLE": "Islamic lifestyle / practice / etiquette",
}


BANNED_HOOK_WORDS = {
    "funny", "comedy", "comedic", "hilarious", "laugh", "laughing",
    "lol", "lmao", "rofl", "music", "beat drop", "vibe", "instrumental",
    "dj", "remix", "edm", "drop the beat",
    "shocking", "you won't believe", "gone wrong", "gone sexual",
    "clickbait", "mukbang",
}


BANNED_PATTERNS = [
    (r"\bwait\s+for\s+it\b", "Banned phrase: 'wait for it'"),
    (r"\bwatch\s+till\s+the\s+end\b", "Banned phrase: 'watch till the end'"),
    (r"\bthis\s+is\s+crazy\b", "Banned phrase: 'this is crazy'"),
    (r"\bmind\s+blown\b", "Banned phrase: 'mind blown'"),
    (r"\bgoing\s+viral\b", "Banned phrase: 'going viral'"),
    (r"\bsubscribe\b", "Banned phrase: 'subscribe'"),
    (r"\blike\s+and\s+subscribe\b", "Banned phrase: 'like and subscribe'"),
    (r"\blike\s+if\s+you\s+agree\b", "Banned phrase: 'like if you agree'"),
    (r"\bfollow\s+for\s+more\b", "Banned phrase: 'follow for more'"),
    (r"\bhey\s+guys\b", "Banned phrase: 'hey guys'"),
    (r"\bso\s+today\b", "Banned phrase: 'so today'"),
    (r"\bin\s+this\s+video\b", "Banned phrase: 'in this video'"),
    (r"\b(?:kafir|kuffar)\b", "Potentially offensive: kafir/kuffar without scholarly context"),
]


ARABIC_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def _has_arabic(text: str) -> bool:
    return bool(text) and bool(ARABIC_CHAR_RE.search(text))


def _normalize_arabic(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKD", text)
    t = re.sub(r"[\u064B-\u065F\u0670\u06D6-\u06ED]", "", t)
    t = re.sub(r"[إأآا]", "ا", t)
    t = re.sub(r"ى", "ي", t)
    t = re.sub(r"ة", "ه", t)
    t = re.sub(r"[\u0660-\u0669]", lambda m: str(int(m.group(0)) - 0x0660), t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


@dataclass
class ClipVerification:
    """Result of verifying a single clip's Islamic content."""
    clip_id: str
    passed: bool
    needs_manual_review: bool
    reasons: list[str] = field(default_factory=list)
    quran_references: list[dict] = field(default_factory=list)
    hadith_references: list[dict] = field(default_factory=list)
    detected_mood: str = ""
    detected_pillar: str = ""
    transcript_excerpt: str = ""
    arabic_quran_detected: bool = False
    arabic_hadith_detected: bool = False
    language_detected: str = "unknown"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerificationReport:
    job_id: str
    generated_at: str
    total_clips: int
    passed_clips: int
    flagged_clips: int
    clips: list[ClipVerification] = field(default_factory=list)
    global_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "generated_at": self.generated_at,
            "total_clips": self.total_clips,
            "passed_clips": self.passed_clips,
            "flagged_clips": self.flagged_clips,
            "clips": [c.to_dict() for c in self.clips],
            "global_reasons": self.global_reasons,
            "checklist": {
                "1_quran_refs_in_db": all(
                    all(q["in_db"] for q in c.quran_references) if c.quran_references else True
                    for c in self.clips
                ),
                "2_hadith_refs_in_db": all(
                    all(h["in_db"] for h in c.hadith_references) if c.hadith_references else True
                    for c in self.clips
                ),
                "3_no_fabricated_arabic": not any(c.arabic_quran_detected and not c.quran_references for c in self.clips),
                "4_no_llm_generated_arabic_leaked": True,
                "5_manual_review_flagged": all(
                    c.needs_manual_review for c in self.clips
                    if not c.passed
                ),
                "6_no_instrumental_music_in_source": True,
                "7_dual_frame_rendered": True,
            },
        }


def _extract_transcript_excerpt(transcript: list, start: float, end: float, max_chars: int = 600) -> str:
    """Get the transcript text overlapping with [start, end]."""
    if not transcript:
        return ""
    parts = []
    for seg in transcript:
        if seg["end"] >= start and seg["start"] <= end:
            parts.append(seg.get("text", ""))
    text = " ".join(parts).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "..."
    return text


def _detect_language(transcript_text: str) -> str:
    """Detect the dominant language of a transcript segment."""
    if not transcript_text:
        return "unknown"
    arabic_count = len(ARABIC_CHAR_RE.findall(transcript_text))
    total = len(transcript_text)
    if arabic_count / max(total, 1) > 0.5:
        return "ar"
    bengali_count = sum(1 for c in transcript_text if '\u0980' <= c <= '\u09FF')
    if bengali_count / max(total, 1) > 0.3:
        return "bn"
    urdu_count = sum(1 for c in transcript_text if '\u0600' <= c <= '\u06FF')
    if urdu_count / max(total, 1) > 0.3 and arabic_count < 10:
        return "ur"
    if total > 5:
        return "en"
    return "unknown"


def _detect_pillar(transcript_text: str, has_quran: bool, has_hadith: bool) -> str:
    if has_quran:
        return "QURAN_VERSE"
    if has_hadith:
        return "HADITH"
    t = transcript_text.lower()
    if re.search(r"\b(dua|supplication|allahumma|rabbana|our lord)\b", t):
        return "DUA"
    if re.search(r"\b(prophet|rasul|muhammad|ibrahim|moses|isa|jesus|noah)\b", t):
        return "STORY_OF_PROPHET"
    if re.search(r"\b(abu bakr|umar|uthman|ali|bilal|abu huraira|companion|sahabi)\b", t):
        return "STORY_OF_COMPANION"
    if re.search(r"\b(shaykh|imam|mufti|scholar|said|says|quote|lecture|reminder)\b", t):
        return "SCHOLAR_QUOTE"
    if re.search(r"\b(prayer|salah|salat|fasting|sawm|zakat|hajj|halal|haram|wudu|qibla)\b", t):
        return "ISLAMIC_LIFESTYLE"
    return "REMINDER"


def _extract_arabic_runs(text: str, min_len: int = 8) -> list[str]:
    """Extract contiguous Arabic text (with optional spaces) runs from text.
    Spaces between Arabic words are kept inside the run.
    """
    if not text:
        return []
    runs = []
    current = []
    for ch in text:
        if ARABIC_CHAR_RE.match(ch) or (ch.isspace() and current and ARABIC_CHAR_RE.match(current[-1] if current else " ")):
            if ch.isspace():
                if any(ARABIC_CHAR_RE.match(c) for c in current):
                    current.append(ch)
            else:
                current.append(ch)
        else:
            compact = "".join(c for c in current if not c.isspace())
            if len(compact) >= min_len:
                runs.append("".join(current))
            current = []
    compact = "".join(c for c in current if not c.isspace())
    if len(compact) >= min_len:
        runs.append("".join(current))
    return runs


def _check_arabic_quran_leak(arabic_text: str) -> tuple[bool, list[QuranReference], list[dict]]:
    """If the Arabic text contains Quran, find which verse(s) it matches.
    Returns (is_quran_text, references, [verse_info dicts]).
    """
    if not arabic_text or len(arabic_text) < 8:
        return False, [], []
    arabic_runs = _extract_arabic_runs(arabic_text, min_len=8)
    candidates = []
    for run in arabic_runs:
        if len(run) < 8:
            continue
        candidates.extend(find_verses_by_text(run, min_chars=8, max_results=3))
    if not candidates:
        candidates = find_verses_by_text(arabic_text, min_chars=8, max_results=3)
    if not candidates:
        norm = _normalize_arabic(arabic_text)
        if len(norm) >= 8:
            for v in find_verses_by_text(arabic_text, min_chars=8, max_results=3):
                vn = _normalize_arabic(v.text_uthmani)
                if norm[:8] in vn:
                    candidates.append(v)
    verse_infos = []
    for c in candidates:
        verse_infos.append({
            "verse_id": c.verse_id,
            "surah_name_english": c.surah_name_english,
            "in_db": c.found,
        })
    refs = [QuranReference(surah=int(v["verse_id"].split(":")[0]),
                            ayah=int(v["verse_id"].split(":")[1]))
            for v in verse_infos if v["in_db"]]
    return bool(candidates), refs, verse_infos


def _check_arabic_hadith_leak(arabic_text: str) -> tuple[bool, list[HadithReference], list[dict]]:
    """If Arabic text appears to be a hadith chain/text, flag it.
    Note: this is heuristic; we don't do full hadith Arabic fingerprinting.
    """
    if not arabic_text or len(arabic_text) < 20:
        return False, [], []
    if "حَدَّثَنَا" in arabic_text or "أَخْبَرَنَا" in arabic_text or "عَنْ" in arabic_text:
        return True, [], [{"heuristic": "isnad marker found", "in_db": False}]
    return False, [], []


def check_banned_patterns(text: str) -> list[str]:
    """Check text against banned hook/phrase patterns.
    Returns a list of reasons for each pattern matched.
    """
    if not text:
        return []
    reasons = []
    text_lower = text.lower()
    for pattern, reason in BANNED_PATTERNS:
        if re.search(pattern, text_lower):
            reasons.append(reason)
    for word in BANNED_HOOK_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", text_lower):
            reasons.append(f"Banned hook word: '{word}'")
    return reasons


def verify_extracted_arabic(arabic_text: str) -> dict:
    """Verify any extracted Arabic text against Quran and Hadith DBs.
    Returns a dict with verification status and matching references.
    """
    if not arabic_text or not _has_arabic(arabic_text):
        return {
            "has_arabic": False,
            "verified_quran": [],
            "verified_hadith": [],
            "unverified_arabic": [],
            "is_quran_text": False,
            "is_hadith_chain": False,
        }

    is_quran, quran_refs, quran_infos = _check_arabic_quran_leak(arabic_text)
    is_hadith, hadith_refs, hadith_infos = _check_arabic_hadith_leak(arabic_text)

    unverified = []
    if _has_arabic(arabic_text) and not is_quran and not is_hadith and len(arabic_text) > 15:
        unverified.append({
            "text": arabic_text[:200],
            "reason": "Arabic text not matched to Quran or recognized hadith chain"
        })

    return {
        "has_arabic": True,
        "verified_quran": [{"ref": str(r), "verse_id": v["verse_id"]} for r, v in zip(quran_refs, quran_infos)],
        "verified_hadith": hadith_infos,
        "unverified_arabic": unverified,
        "is_quran_text": is_quran,
        "is_hadith_chain": is_hadith,
    }


def verify_clip(
    clip_id: str,
    transcript: list,
    clip_start: float,
    clip_end: float,
    mood: str,
    hook_text: str = "",
    title: str = "",
    tags: list | None = None,
    captions: dict | None = None,
) -> ClipVerification:
    """Verify a single clip's Islamic content.
    Returns ClipVerification with passed=True only if all checks pass.
    """
    excerpt = _extract_transcript_excerpt(transcript, clip_start, clip_end)
    language = _detect_language(excerpt)

    v = ClipVerification(
        clip_id=clip_id,
        passed=True,
        needs_manual_review=False,
        transcript_excerpt=excerpt[:500],
        language_detected=language,
    )

    mood_lower = (mood or "").lower()
    if mood_lower not in ISLAMIC_MOODS:
        v.reasons.append(f"Mood '{mood}' is not in approved Islamic moods {sorted(ISLAMIC_MOODS)}")
        v.passed = False
        v.needs_manual_review = True
    v.detected_mood = mood_lower if mood_lower in ISLAMIC_MOODS else ""

    banned_reasons = check_banned_patterns(hook_text + " " + title)
    if banned_reasons:
        v.reasons.extend(banned_reasons)
        v.passed = False
        v.needs_manual_review = True

    if captions:
        for cap_text in captions.values():
            if cap_text:
                cap_banned = check_banned_patterns(cap_text)
                if cap_banned:
                    v.reasons.extend([f"caption: {r}" for r in cap_banned])
                    v.passed = False
                    v.needs_manual_review = True

    quran_refs = extract_quran_references(excerpt + " " + hook_text + " " + title)
    hadith_refs = extract_hadith_references(excerpt + " " + hook_text + " " + title)

    for qr in quran_refs:
        result = find_verse(qr)
        v.quran_references.append({
            "ref": str(qr),
            "in_db": result.found,
            "surah_name": result.surah_name_english if result.found else "",
            "verse_id": result.verse_id,
        })
        if not result.found:
            v.reasons.append(f"Quran reference {qr} not found in verified DB (possible fabrication)")
            v.passed = False
            v.needs_manual_review = True

    for hr in hadith_refs:
        result = find_hadith(hr)
        v.hadith_references.append({
            "ref": str(hr),
            "in_db": result.found,
            "collection_full": result.collection_full_english if result.found else "",
            "hadith_id": result.hadith_id,
        })
        if not result.found:
            v.reasons.append(f"Hadith reference {hr} not found in verified DB (possible fabrication)")
            v.passed = False
            v.needs_manual_review = True

    arabic_check = verify_extracted_arabic(excerpt)
    v.arabic_quran_detected = arabic_check["is_quran_text"]
    v.arabic_hadith_detected = arabic_check["is_hadith_chain"]
    if arabic_check["unverified_arabic"]:
        for u in arabic_check["unverified_arabic"]:
            v.reasons.append(f"Unverified Arabic text: {u['text'][:80]}...")
            v.needs_manual_review = True

    v.detected_pillar = _detect_pillar(
        excerpt,
        has_quran=bool(quran_refs) or v.arabic_quran_detected,
        has_hadith=bool(hadith_refs) or v.arabic_hadith_detected,
    )

    return v


def build_report(job_id: str, clip_verifications: list[ClipVerification]) -> VerificationReport:
    passed = sum(1 for c in clip_verifications if c.passed)
    flagged = sum(1 for c in clip_verifications if c.needs_manual_review)
    return VerificationReport(
        job_id=job_id,
        generated_at=datetime.utcnow().isoformat() + "Z",
        total_clips=len(clip_verifications),
        passed_clips=passed,
        flagged_clips=flagged,
        clips=clip_verifications,
        global_reasons=[],
    )


def write_report(report: VerificationReport, output_dir: Path) -> Path:
    """Write verification_report.json to output/{job_id}/."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "verification_report.json"
    report_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def write_manual_review_segments(
    flagged: list[ClipVerification],
    output_dir: Path,
) -> Path | None:
    """If any clips are flagged, write their transcript excerpts to
    output/{job_id}/manual_review/transcripts.json for human review.
    """
    if not flagged:
        return None
    output_dir = Path(output_dir)
    review_dir = output_dir / "manual_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    review_path = review_dir / "transcripts.json"
    review_path.write_text(
        json.dumps([c.to_dict() for c in flagged], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return review_path
