"""Hadith reference lookup against the verified DB.

The DB is built by backend/data/build_hadith_db.py from
AhmedBaset/hadith-json v1.2.0 (34,178 hadiths across 6 Kutub al-Sittah).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
HADITH_DB_PATH = DATA_DIR / "hadith_verified.json"

COLLECTION_SLUGS = {
    "bukhari": "bukhari",
    "sahih bukhari": "bukhari",
    "muslim": "muslim",
    "sahih muslim": "muslim",
    "abudawud": "abudawud",
    "abu dawud": "abudawud",
    "sunan abi dawud": "abudawud",
    "tirmidhi": "tirmidhi",
    "jami at-tirmidhi": "tirmidhi",
    "nasai": "nasai",
    "an-nasai": "nasai",
    "sunan an-nasai": "nasai",
    "ibnmajah": "ibnmajah",
    "ibn majah": "ibnmajah",
    "sunan ibn majah": "ibnmajah",
}


@dataclass
class HadithReference:
    collection: str
    number: int

    def __str__(self) -> str:
        return f"{self.collection.title()} {self.number}"


@dataclass
class HadithLookupResult:
    reference: HadithReference
    found: bool
    hadith_id: str
    text_arabic: str
    text_english: str
    narrator_english: str
    chapter_english: str
    chapter_arabic: str
    grade: str
    collection_full_english: str


_hadith_db_cache: dict | None = None
_hadith_index: dict[str, dict] | None = None


def load_hadith_db() -> dict:
    global _hadith_db_cache, _hadith_index
    if _hadith_db_cache is None:
        if not HADITH_DB_PATH.exists():
            raise FileNotFoundError(
                f"Hadith DB not found at {HADITH_DB_PATH}. "
                "Run: python backend/data/build_hadith_db.py"
            )
        with open(HADITH_DB_PATH, encoding="utf-8") as f:
            _hadith_db_cache = json.load(f)
        _hadith_index = {}
        for h in _hadith_db_cache["hadiths"]:
            _hadith_index[h["hadith_id"]] = h
    return _hadith_db_cache


def _hadith_index_map() -> dict[str, dict]:
    if _hadith_index is None:
        load_hadith_db()
    return _hadith_index


def find_hadith(ref: HadithReference) -> HadithLookupResult | None:
    """Look up a hadith by collection slug + number."""
    index = _hadith_index_map()
    hid = f"{ref.collection}:{ref.number}"
    h = index.get(hid)
    if h is None:
        return HadithLookupResult(
            reference=ref,
            found=False,
            hadith_id=hid,
            text_arabic="",
            text_english="",
            narrator_english="",
            chapter_english="",
            chapter_arabic="",
            grade="",
            collection_full_english="",
        )
    return HadithLookupResult(
        reference=ref,
        found=True,
        hadith_id=hid,
        text_arabic=h["text_arabic"],
        text_english=h["text_english"],
        narrator_english=h["narrator_english"],
        chapter_english=h["chapter_english"],
        chapter_arabic=h["chapter_arabic"],
        grade=h["grade"],
        collection_full_english=_collection_full_name(ref.collection),
    )


def find_hadiths_by_text(english_substring: str, min_chars: int = 20, max_results: int = 5) -> list[HadithLookupResult]:
    """Find hadiths whose English text contains the given substring.
    Used to verify English hadith quotes the LLM claims are from a specific collection.
    """
    if not english_substring or len(english_substring) < min_chars:
        return []
    index = _hadith_index_map()
    needle = english_substring.lower().strip()
    results = []
    for hid, h in index.items():
        text = h.get("text_english", "").lower()
        if needle in text:
            ref = HadithReference(
                collection=h["collection"],
                number=h["number_in_book"],
            )
            results.append(HadithLookupResult(
                reference=ref,
                found=True,
                hadith_id=hid,
                text_arabic=h["text_arabic"],
                text_english=h["text_english"],
                narrator_english=h["narrator_english"],
                chapter_english=h["chapter_english"],
                chapter_arabic=h["chapter_arabic"],
                grade=h["grade"],
                collection_full_english=_collection_full_name(h["collection"]),
            ))
            if len(results) >= max_results:
                break
    return results


def _collection_full_name(slug: str) -> str:
    return {
        "bukhari": "Sahih al-Bukhari",
        "muslim": "Sahih Muslim",
        "abudawud": "Sunan Abi Dawud",
        "tirmidhi": "Jami at-Tirmidhi",
        "nasai": "Sunan an-Nasai",
        "ibnmajah": "Sunan Ibn Majah",
    }.get(slug, slug)


def _resolve_collection(text: str) -> str | None:
    if not text:
        return None
    t = text.lower().strip()
    for key, slug in COLLECTION_SLUGS.items():
        if key in t:
            return slug
    return None


def extract_hadith_references(text: str) -> list[HadithReference]:
    """Extract hadith references from text. Supports:
    - Bukhari 1
    - Sahih Bukhari: 1
    - Sahih Muslim 53
    - Muslim: 53
    - Hadith in Bukhari 1
    - narrated in Bukhari 1
    - Abu Dawud 1
    - Tirmidhi 1
    - Nasai 1
    - Ibn Majah 1
    """
    if not text:
        return []

    refs = []
    seen = set()

    collection_pattern = r"(sahih\s+)?(al-)?(bukhari|muslim|abu\s*dawud|tirmidhi|nasai|nasāʾi|ibn\s*majah|abu\s*dāwūd|abu\s*dawood)"
    number_pattern = r"(\d{1,5})"

    patterns = [
        rf"(?P<coll>{collection_pattern})\s*[:\-,]?\s*(?:hadith\s+(?:no\.?|number)?\s*)?(?P<num>{number_pattern})",
        rf"(?P<num>{number_pattern})\s+(?P<coll>{collection_pattern})",
        rf"hadith\s+(?P<num>{number_pattern})\s+(?:in\s+|from\s+|of\s+)?(?P<coll>{collection_pattern})",
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, text.lower()):
            groups = m.groupdict()
            coll_raw = groups.get("coll", "")
            num_raw = groups.get("num", "")
            if not coll_raw or not num_raw:
                continue
            coll = _resolve_collection(coll_raw)
            if coll is None:
                continue
            try:
                num = int(num_raw)
                if num < 1:
                    continue
            except ValueError:
                continue
            key = (coll, num)
            if key not in seen:
                seen.add(key)
                refs.append(HadithReference(collection=coll, number=num))

    return refs
