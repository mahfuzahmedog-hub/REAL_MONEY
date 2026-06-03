"""Quran reference lookup against the verified DB.

The DB is built by backend/data/build_quran_db.py from tanzil.net
(6236 verses, Uthmani + simple scripts, 114 surahs).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
QURAN_DB_PATH = DATA_DIR / "quran_verified.json"


@dataclass
class QuranReference:
    surah: int
    ayah: int
    end_ayah: int | None = None

    def __str__(self) -> str:
        if self.end_ayah and self.end_ayah != self.ayah:
            return f"{self.surah}:{self.ayah}-{self.end_ayah}"
        return f"{self.surah}:{self.ayah}"


@dataclass
class QuranLookupResult:
    reference: QuranReference
    found: bool
    verse_id: str
    text_uthmani: str
    text_simple: str
    surah_name_english: str
    surah_name_arabic: str
    surah_name_transliteration: str
    juz: int
    page: int
    revelation_place: str


_quran_db_cache: dict | None = None
_verse_index: dict[str, dict] | None = None
_text_index: dict[str, list[str]] | None = None


def load_quran_db() -> dict:
    global _quran_db_cache, _verse_index, _text_index
    if _quran_db_cache is None:
        if not QURAN_DB_PATH.exists():
            raise FileNotFoundError(
                f"Quran DB not found at {QURAN_DB_PATH}. "
                "Run: python backend/data/build_quran_db.py"
            )
        with open(QURAN_DB_PATH, encoding="utf-8") as f:
            _quran_db_cache = json.load(f)
        _verse_index = {}
        for v in _quran_db_cache["verses"]:
            _verse_index[v["verse_id"]] = v
        _text_index = {}
    return _quran_db_cache


def _verse_index_map() -> dict[str, dict]:
    if _verse_index is None:
        load_quran_db()
    return _verse_index


def find_verse(ref: QuranReference) -> QuranLookupResult | None:
    """Look up a single verse (or first verse of a range) by reference."""
    index = _verse_index_map()
    if ref.end_ayah is not None and ref.end_ayah != ref.ayah:
        vid_first = f"{ref.surah}:{ref.ayah}"
        if vid_first not in index:
            return None
        verses = []
        for a in range(ref.ayah, ref.end_ayah + 1):
            v = index.get(f"{ref.surah}:{a}")
            if v is None:
                break
            verses.append(v)
        if not verses:
            return None
        first = verses[0]
        return QuranLookupResult(
            reference=ref,
            found=True,
            verse_id=first["verse_id"],
            text_uthmani=" ".join(v["text_uthmani"] for v in verses),
            text_simple=" ".join(v["text_simple"] for v in verses),
            surah_name_english=first["surah_name_english"],
            surah_name_arabic=first["surah_name_arabic"],
            surah_name_transliteration=first["surah_name_transliteration"],
            juz=first["juz"],
            page=first["page"],
            revelation_place=first["revelation_place"],
        )
    vid = f"{ref.surah}:{ref.ayah}"
    v = index.get(vid)
    if v is None:
        return QuranLookupResult(
            reference=ref,
            found=False,
            verse_id=vid,
            text_uthmani="",
            text_simple="",
            surah_name_english="",
            surah_name_arabic="",
            surah_name_transliteration="",
            juz=0,
            page=0,
            revelation_place="",
        )
    return QuranLookupResult(
        reference=ref,
        found=True,
        verse_id=vid,
        text_uthmani=v["text_uthmani"],
        text_simple=v["text_simple"],
        surah_name_english=v["surah_name_english"],
        surah_name_arabic=v["surah_name_arabic"],
        surah_name_transliteration=v["surah_name_transliteration"],
        juz=v["juz"],
        page=v["page"],
        revelation_place=v["revelation_place"],
    )


def _normalize_arabic_for_search(text: str) -> str:
    """Normalize Arabic text for fuzzy matching against Quran DB."""
    if not text:
        return ""
    import unicodedata
    t = unicodedata.normalize("NFKD", text)
    t = re.sub(r"[\u0640-\u065F\u0670\u06D6-\u06ED]", "", t)
    t = t.replace("ٱ", "ا").replace("إ", "ا").replace("أ", "ا").replace("آ", "ا")
    t = t.replace("ى", "ي").replace("ئ", "ي").replace("ؤ", "و")
    t = t.replace("ة", "ه")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def find_verses_by_text(arabic_substring: str, min_chars: int = 8, max_results: int = 5) -> list[QuranLookupResult]:
    """Find Quran verses whose text contains the given Arabic substring.
    Used to verify Arabic Quran text that LLM claims is from a verse.
    Normalizes both sides to handle Unicode variations (alef wasla, hamza, etc).
    """
    if not arabic_substring or len(arabic_substring) < min_chars:
        return []
    index = _verse_index_map()
    needle = _normalize_arabic_for_search(arabic_substring.strip())
    if len(needle) < min_chars:
        return []
    results = []
    for vid, v in index.items():
        haystack_u = _normalize_arabic_for_search(v["text_uthmani"])
        haystack_s = _normalize_arabic_for_search(v["text_simple"])
        if needle in haystack_u or needle in haystack_s:
            results.append(QuranLookupResult(
                reference=QuranReference(surah=v["surah_number"], ayah=v["ayah_number"]),
                found=True,
                verse_id=vid,
                text_uthmani=v["text_uthmani"],
                text_simple=v["text_simple"],
                surah_name_english=v["surah_name_english"],
                surah_name_arabic=v["surah_name_arabic"],
                surah_name_transliteration=v["surah_name_transliteration"],
                juz=v["juz"],
                page=v["page"],
                revelation_place=v["revelation_place"],
            ))
            if len(results) >= max_results:
                break
    return results


_SURAH_NAME_MAP = {
    "fatihah": 1, "baqarah": 2, "imran": 3, "nisa": 4, "maidah": 5,
    "anam": 6, "araf": 7, "anfal": 8, "tawbah": 9, "yunus": 10,
    "hud": 11, "yusuf": 12, "rad": 13, "ibrahim": 14, "hijr": 15,
    "nahl": 16, "isra": 17, "kahf": 18, "maryam": 19, "taha": 20,
    "anbiya": 21, "hajj": 22, "muminun": 23, "nur": 24, "furqan": 25,
    "shuara": 26, "naml": 27, "qasas": 28, "ankabut": 29, "rum": 30,
    "luqman": 31, "sajdah": 32, "ahzab": 33, "saba": 34, "fatir": 35,
    "yasin": 36, "saffat": 37, "sad": 38, "zumar": 39, "ghafir": 40,
    "fussilat": 41, "shura": 42, "zukhruf": 43, "dukhan": 44, "jathiyah": 45,
    "ahqaf": 46, "muhammad": 47, "fath": 48, "hujurat": 49, "qaf": 50,
    "dhariyat": 51, "tur": 52, "najm": 53, "qamar": 54, "rahman": 55,
    "waqiah": 56, "hadid": 57, "mujadilah": 58, "hashr": 59, "mumtahanah": 60,
    "saff": 61, "jumuah": 62, "munafiqun": 63, "taghabun": 64, "talaq": 65,
    "tahrim": 66, "mulk": 67, "qalam": 68, "haqqah": 69, "maarij": 70,
    "nuh": 71, "jinn": 72, "muzzammil": 73, "muddaththir": 74, "qiyamah": 75,
    "insan": 76, "mursalat": 77, "naba": 78, "naziat": 79, "abasa": 80,
    "takwir": 81, "infitar": 82, "mutaffifin": 83, "inshiqaq": 84, "buruj": 85,
    "tariq": 86, "ala": 87, "ghashiyah": 88, "fajr": 89, "balad": 90,
    "shams": 91, "layl": 92, "duha": 93, "sharh": 94, "tin": 95,
    "alaq": 96, "qadr": 97, "bayyinah": 98, "zalzalah": 99, "adiyat": 100,
    "qariah": 101, "takathur": 102, "asr": 103, "humazah": 104, "fil": 105,
    "quraysh": 106, "maun": 107, "kawthar": 108, "kafirun": 109, "nasr": 110,
    "masad": 111, "ikhlas": 112, "falaq": 113, "nas": 114,
}


def _resolve_surah_name(name: str) -> int | None:
    if not name:
        return None
    n = name.lower().strip()
    for prefix in ["al-", "an-", "as-", "ash-", "ad-", "at-", "ar-", "az-", "al ", "an ", "as "]:
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    n = n.replace("-", "").replace("'", "").replace(" ", "").replace("'", "")
    if n in _SURAH_NAME_MAP:
        return _SURAH_NAME_MAP[n]
    for k, v in _SURAH_NAME_MAP.items():
        if n.startswith(k) or k.startswith(n):
            return v
        if k.startswith(n[:4]) and len(n) >= 4:
            return v
    return None


def extract_quran_references(text: str) -> list[QuranReference]:
    """Extract Quran references from text. Supports:
    - Surah 2:255
    - Surah 2, Verse 255
    - 2:255
    - 2:255-257
    - Al-Baqarah 2:255
    - Surah Al-Baqarah Verse 255
    - Quran 2:255
    - Baqarah 255 (just surah name + ayah)
    """
    if not text:
        return []
    refs = []
    text_lower = text.lower()

    patterns = [
        r"(?:surah|soorah|surah)\s+([a-z][a-z\-']+(?:\s+[a-z][a-z\-']+)*?)\s*[,\s]*(?:verse\s+|v\.?\s*|no\.?\s*|number\s*|ayat\s+)?(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?",
        r"(?:quran|qur'an|qur’an)\s+(\d{1,3})\s*[:\-]\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?",
        r"\b(\d{1,3})\s*[:\-]\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?\b",
        r"\bal-([a-z][a-z\-']+)\s+(\d{1,3})\s*[:\-]?\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?",
    ]

    for pi, pattern in enumerate(patterns):
        for m in re.finditer(pattern, text_lower):
            try:
                if pi == 0:
                    name_raw = m.group(1).strip()
                    a = m.group(2)
                    end_a = m.group(3)
                    surah_num = _resolve_surah_name(name_raw)
                    if surah_num is None:
                        for token in name_raw.split():
                            surah_num = _resolve_surah_name(token)
                            if surah_num is not None:
                                break
                    if surah_num is None:
                        continue
                    if int(a) < 1 or int(a) > 300:
                        continue
                    refs.append(QuranReference(
                        surah=surah_num,
                        ayah=int(a),
                        end_ayah=int(end_a) if end_a else None,
                    ))
                elif pi == 1:
                    s, a, end_a = m.group(1), m.group(2), m.group(3)
                    if int(s) < 1 or int(s) > 114:
                        continue
                    if int(a) < 1 or int(a) > 300:
                        continue
                    refs.append(QuranReference(
                        surah=int(s),
                        ayah=int(a),
                        end_ayah=int(end_a) if end_a else None,
                    ))
                elif pi == 2:
                    s, a, end_a = m.group(1), m.group(2), m.group(3)
                    if int(s) < 1 or int(s) > 114:
                        continue
                    if int(a) < 1 or int(a) > 300:
                        continue
                    refs.append(QuranReference(
                        surah=int(s),
                        ayah=int(a),
                        end_ayah=int(end_a) if end_a else None,
                    ))
                else:
                    name = m.group(1)
                    s = m.group(2)
                    a = m.group(3)
                    end_a = m.group(4)
                    surah_num = _resolve_surah_name(name)
                    if surah_num is None:
                        continue
                    if int(a) < 1 or int(a) > 300:
                        continue
                    refs.append(QuranReference(
                        surah=surah_num,
                        ayah=int(a),
                        end_ayah=int(end_a) if end_a else None,
                    ))
            except (ValueError, IndexError):
                continue

    seen = set()
    unique = []
    for r in refs:
        key = (r.surah, r.ayah, r.end_ayah)
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique
