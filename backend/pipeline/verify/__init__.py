"""Theological safety layer for Islamic Hedayet pipeline.

This module is the HARD GATE for all Arabic Quran/Hadith content.
No Arabic Quran or Hadith text is ever rendered without first passing
through verification against the verified DBs in backend/data/.

Hard rules:
- LLM is FORBIDDEN from generating Arabic Quran text directly.
- LLM is FORBIDDEN from generating Arabic Hadith text directly.
- LLM is FORBIDDEN from fabricating specific references (e.g., "Bukhari 9999").
- All Arabic Quran text must come from backend/data/quran_verified.json
- All Arabic Hadith text must come from backend/data/hadith_verified.json
- All references (Surah 2:255, Bukhari 1) must resolve to entries in those DBs
"""

from .quran_db import (
    QuranReference,
    QuranLookupResult,
    load_quran_db,
    find_verse,
    find_verses_by_text,
    extract_quran_references,
)
from .hadith_db import (
    HadithReference,
    HadithLookupResult,
    load_hadith_db,
    find_hadith,
    find_hadiths_by_text,
    extract_hadith_references,
)
from .theology import (
    VerificationReport,
    ClipVerification,
    verify_clip,
    verify_extracted_arabic,
    check_banned_patterns,
    build_report,
    write_report,
    write_manual_review_segments,
    BANNED_PATTERNS,
    ISLAMIC_MOODS,
    ISLAMIC_PILLARS,
    BANNED_HOOK_WORDS,
)

__all__ = [
    "QuranReference",
    "QuranLookupResult",
    "load_quran_db",
    "find_verse",
    "find_verses_by_text",
    "extract_quran_references",
    "HadithReference",
    "HadithLookupResult",
    "load_hadith_db",
    "find_hadith",
    "find_hadiths_by_text",
    "extract_hadith_references",
    "VerificationReport",
    "ClipVerification",
    "verify_clip",
    "verify_extracted_arabic",
    "check_banned_patterns",
    "build_report",
    "write_report",
    "write_manual_review_segments",
    "BANNED_PATTERNS",
    "ISLAMIC_MOODS",
    "ISLAMIC_PILLARS",
    "BANNED_HOOK_WORDS",
]
