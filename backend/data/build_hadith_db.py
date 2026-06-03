"""
Builds backend/data/hadith_verified.json from AhmedBaset/hadith-json v1.2.0.

Source: https://github.com/AhmedBaset/hadith-json (v1.2.0)
Why this source: well-maintained, includes all 6 Kutub al-Sittah, has Arabic + English,
public on GitHub raw CDN, AGPL-3 license data under CC BY-SA 4.0.

Output schema (one entry per hadith):
{
  "hadith_id": "bukhari:1",                    # "collection:number_in_book"
  "collection": "bukhari",                     # short slug
  "collection_full_arabic": "صحيح البخاري",
  "collection_full_english": "Sahih al-Bukhari",
  "number_in_book": 1,
  "global_id": 1,                              # continuous id within this collection
  "chapter_id": 1,
  "chapter_arabic": "كتاب بدء الوحى",
  "chapter_english": "Revelation",
  "text_arabic": "...",                        # the full Arabic text including isnad
  "text_english": "...",                       # the full English text
  "narrator_english": "Narrated 'Umar...",     # extracted from english.narrator
  "grade": "sahih",                            # collection-implied grade
  "reference": "Bukhari 1"                     # human-readable reference
}

Collection grades:
  bukhari, muslim              -> all hadiths are sahih (by collection criteria)
  abudawud, tirmidhi, nasai, ibnmajah -> grades vary (sahih/hasan/da'if);
                                       this dataset does not include per-hadith grades
                                       so we mark as "sunan" (collection-level)
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT = ROOT / "hadith_verified.json"
CACHE = ROOT / ".cache_hadith"
CACHE.mkdir(exist_ok=True)

COLLECTIONS = [
    {
        "slug": "bukhari",
        "url": "https://raw.githubusercontent.com/AhmedBaset/hadith-json/v1.2.0/db/by_book/the_9_books/bukhari.json",
        "grade_default": "sahih",
    },
    {
        "slug": "muslim",
        "url": "https://raw.githubusercontent.com/AhmedBaset/hadith-json/v1.2.0/db/by_book/the_9_books/muslim.json",
        "grade_default": "sahih",
    },
    {
        "slug": "abudawud",
        "url": "https://raw.githubusercontent.com/AhmedBaset/hadith-json/v1.2.0/db/by_book/the_9_books/abudawud.json",
        "grade_default": "sunan",
    },
    {
        "slug": "tirmidhi",
        "url": "https://raw.githubusercontent.com/AhmedBaset/hadith-json/v1.2.0/db/by_book/the_9_books/tirmidhi.json",
        "grade_default": "sunan",
    },
    {
        "slug": "nasai",
        "url": "https://raw.githubusercontent.com/AhmedBaset/hadith-json/v1.2.0/db/by_book/the_9_books/nasai.json",
        "grade_default": "sunan",
    },
    {
        "slug": "ibnmajah",
        "url": "https://raw.githubusercontent.com/AhmedBaset/hadith-json/v1.2.0/db/by_book/the_9_books/ibnmajah.json",
        "grade_default": "sunan",
    },
]


def fetch_or_cache(url: str) -> dict:
    cache_file = CACHE / Path(url).name
    if cache_file.exists():
        print(f"  cache hit: {cache_file.name}")
        return json.loads(cache_file.read_text(encoding="utf-8"))
    print(f"  downloading: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    cache_file.write_bytes(data)
    return json.loads(data)


def normalize_hadith(h: dict, collection: dict, chapter_lookup: dict) -> dict:
    chapter_id = h.get("chapterId")
    chapter = chapter_lookup.get(chapter_id, {})
    english = h.get("english") or {}
    text_en = english.get("text", "") if isinstance(english, dict) else ""
    narrator_en = english.get("narrator", "") if isinstance(english, dict) else ""
    return {
        "hadith_id": f"{collection['slug']}:{h.get('idInBook')}",
        "collection": collection["slug"],
        "number_in_book": h.get("idInBook"),
        "global_id": h.get("id"),
        "chapter_id": chapter_id,
        "chapter_arabic": chapter.get("arabic", ""),
        "chapter_english": chapter.get("english", ""),
        "text_arabic": h.get("arabic", ""),
        "text_english": text_en,
        "narrator_english": narrator_en,
        "grade": collection["grade_default"],
        "reference": f"{collection['slug'].title()} {h.get('idInBook')}",
    }


def main() -> int:
    all_hadiths = []
    by_collection = {}

    for col in COLLECTIONS:
        print(f"Processing {col['slug']}...")
        try:
            data = fetch_or_cache(col["url"])
        except Exception as e:
            print(f"FAIL: {col['slug']}: {e}", file=sys.stderr)
            return 1

        meta = data.get("metadata", {})
        arabic_meta = meta.get("arabic", {})
        english_meta = meta.get("english", {})

        chapters = data.get("chapters", [])
        chapter_lookup = {c["id"]: c for c in chapters if isinstance(c, dict) and "id" in c}

        hadiths = data.get("hadiths", [])
        if not hadiths:
            print(f"WARN: {col['slug']} has no hadiths", file=sys.stderr)
            continue

        normalized = [normalize_hadith(h, col, chapter_lookup) for h in hadiths]
        all_hadiths.extend(normalized)
        by_collection[col["slug"]] = {
            "title_arabic": arabic_meta.get("title", ""),
            "title_english": english_meta.get("title", ""),
            "author_arabic": arabic_meta.get("author", ""),
            "author_english": english_meta.get("author", ""),
            "hadith_count": len(normalized),
        }
        print(f"  -> {len(normalized)} hadiths")

    output = {
        "source": "AhmedBaset/hadith-json v1.2.0",
        "source_url": "https://github.com/AhmedBaset/hadith-json/tree/v1.2.0",
        "license_data": "CC BY-SA 4.0",
        "license_code": "AGPL-3",
        "total_hadiths": len(all_hadiths),
        "collections_included": [c["slug"] for c in COLLECTIONS],
        "collection_summary": by_collection,
        "grade_notes": (
            "Bukhari + Muslim: all hadiths marked 'sahih' (per collection criteria). "
            "Abu Dawud + Tirmidhi + Nasai + Ibn Majah: marked 'sunan' because "
            "per-hadith grades are not included in this dataset."
        ),
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "hadiths": all_hadiths,
    }

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"\nOK: wrote {len(all_hadiths)} hadiths to {OUTPUT} ({size_mb:.2f} MB)")
    for slug, info in by_collection.items():
        print(f"  {slug}: {info['hadith_count']} hadiths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
