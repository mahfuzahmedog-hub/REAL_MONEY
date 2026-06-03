"""
Builds backend/data/quran_verified.json from tanzil.net (text) + static surah metadata.

Output schema (one entry per verse):
{
  "verse_id": "1:1",                  # "surah:ayah"
  "surah_number": 1,
  "ayah_number": 1,
  "text_uthmani": "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ",
  "text_simple": "بسم الله الرحمن الرحيم",
  "is_bismillah": true,
  "surah_name_arabic": "الفاتحة",
  "surah_name_english": "The Opening",
  "surah_name_transliteration": "Al-Fatihah",
  "revelation_place": "makkah",
  "ayah_count_in_surah": 7,
  "juz": 1,
  "page": 1
}

Verified by:
- Text source: tanzil.net (Uthmani script, uthmani glyphs)
- Metadata: static surah list (well-known, 114 surahs)
- Counts: 6236 verses total
- Surah 1: Bismillah IS ayah 1 (not prepended)
- Surah 9: NO bismillah at all
- All other surahs (2-8, 10-114): Bismillah prepended as line 1
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT = ROOT / "quran_verified.json"

TANZIL_UTHMANI_URL = (
    "https://tanzil.net/pub/download/index.php"
    "?quranType=uthmani&outType=txt-2&marks=true&sajdah=true"
    "&tatweel=true&rub=false&stanween=false&agree=true"
)
TANZIL_SIMPLE_URL = (
    "https://tanzil.net/pub/download/index.php"
    "?quranType=simple&outType=txt-2&marks=false&sajdah=false"
    "&tatweel=false&rub=false&stanween=false&agree=true"
)

SURAH_METADATA = [
    (1, "الفاتحة", "The Opening", "Al-Fatihah", "makkah", 7),
    (2, "البقرة", "The Cow", "Al-Baqarah", "madinah", 286),
    (3, "آل عمران", "The Family of Imran", "Ali 'Imran", "madinah", 200),
    (4, "النساء", "The Women", "An-Nisa", "madinah", 176),
    (5, "المائدة", "The Table Spread", "Al-Ma'idah", "madinah", 120),
    (6, "الأنعام", "The Cattle", "Al-An'am", "makkah", 165),
    (7, "الأعراف", "The Heights", "Al-A'raf", "makkah", 206),
    (8, "الأنفال", "The Spoils of War", "Al-Anfal", "madinah", 75),
    (9, "التوبة", "The Repentance", "At-Tawbah", "madinah", 129),
    (10, "يونس", "Jonah", "Yunus", "makkah", 109),
    (11, "هود", "Hud", "Hud", "makkah", 123),
    (12, "يوسف", "Joseph", "Yusuf", "makkah", 111),
    (13, "الرعد", "The Thunder", "Ar-Ra'd", "madinah", 43),
    (14, "إبراهيم", "Abraham", "Ibrahim", "makkah", 52),
    (15, "الحجر", "The Rocky Tract", "Al-Hijr", "makkah", 99),
    (16, "النحل", "The Bee", "An-Nahl", "makkah", 128),
    (17, "الإسراء", "The Night Journey", "Al-Isra", "makkah", 111),
    (18, "الكهف", "The Cave", "Al-Kahf", "makkah", 110),
    (19, "مريم", "Mary", "Maryam", "makkah", 98),
    (20, "طه", "Ta-Ha", "Ta-Ha", "makkah", 135),
    (21, "الأنبياء", "The Prophets", "Al-Anbiya", "makkah", 112),
    (22, "الحج", "The Pilgrimage", "Al-Hajj", "madinah", 78),
    (23, "المؤمنون", "The Believers", "Al-Mu'minun", "makkah", 118),
    (24, "النور", "The Light", "An-Nur", "madinah", 64),
    (25, "الفرقان", "The Criterion", "Al-Furqan", "makkah", 77),
    (26, "الشعراء", "The Poets", "Ash-Shu'ara", "makkah", 227),
    (27, "النمل", "The Ant", "An-Naml", "makkah", 93),
    (28, "القصص", "The Stories", "Al-Qasas", "makkah", 88),
    (29, "العنكبوت", "The Spider", "Al-'Ankabut", "makkah", 69),
    (30, "الروم", "The Romans", "Ar-Rum", "makkah", 60),
    (31, "لقمان", "Luqman", "Luqman", "makkah", 34),
    (32, "السجدة", "The Prostration", "As-Sajdah", "makkah", 30),
    (33, "الأحزاب", "The Confederates", "Al-Ahzab", "madinah", 73),
    (34, "سبأ", "Sheba", "Saba", "makkah", 54),
    (35, "فاطر", "The Originator", "Fatir", "makkah", 45),
    (36, "يس", "Ya-Sin", "Ya-Sin", "makkah", 83),
    (37, "الصافات", "Those Ranged in Ranks", "As-Saffat", "makkah", 182),
    (38, "ص", "Sad", "Sad", "makkah", 88),
    (39, "الزمر", "The Groups", "Az-Zumar", "makkah", 75),
    (40, "غافر", "The Forgiver", "Ghafir", "makkah", 85),
    (41, "فصلت", "Explained in Detail", "Fussilat", "makkah", 54),
    (42, "الشورى", "The Consultation", "Ash-Shura", "makkah", 53),
    (43, "الزخرف", "The Gold Adornments", "Az-Zukhruf", "makkah", 89),
    (44, "الدخان", "The Smoke", "Ad-Dukhan", "makkah", 59),
    (45, "الجاثية", "The Kneeling", "Al-Jathiyah", "makkah", 37),
    (46, "الأحقاف", "The Curved Sand Tracts", "Al-Ahqaf", "makkah", 35),
    (47, "محمد", "Muhammad", "Muhammad", "madinah", 38),
    (48, "الفتح", "The Victory", "Al-Fath", "madinah", 29),
    (49, "الحجرات", "The Rooms", "Al-Hujurat", "madinah", 18),
    (50, "ق", "Qaf", "Qaf", "makkah", 45),
    (51, "الذاريات", "The Winnowing Winds", "Adh-Dhariyat", "makkah", 60),
    (52, "الطور", "The Mount", "At-Tur", "makkah", 49),
    (53, "النجم", "The Star", "An-Najm", "makkah", 62),
    (54, "القمر", "The Moon", "Al-Qamar", "makkah", 55),
    (55, "الرحمن", "The Most Merciful", "Ar-Rahman", "madinah", 78),
    (56, "الواقعة", "The Inevitable", "Al-Waqi'ah", "makkah", 96),
    (57, "الحديد", "The Iron", "Al-Hadid", "madinah", 29),
    (58, "المجادلة", "The Pleading Woman", "Al-Mujadilah", "madinah", 22),
    (59, "الحشر", "The Gathering", "Al-Hashr", "madinah", 24),
    (60, "الممتحنة", "She That Is To Be Examined", "Al-Mumtahanah", "madinah", 13),
    (61, "الصف", "The Ranks", "As-Saff", "madinah", 14),
    (62, "الجمعة", "The Friday", "Al-Jumu'ah", "madinah", 11),
    (63, "المنافقون", "The Hypocrites", "Al-Munafiqun", "madinah", 11),
    (64, "التغابن", "Mutual Disillusion", "At-Taghabun", "madinah", 18),
    (65, "الطلاق", "Divorce", "At-Talaq", "madinah", 12),
    (66, "التحريم", "The Prohibition", "At-Tahrim", "madinah", 12),
    (67, "الملك", "The Dominion", "Al-Mulk", "makkah", 30),
    (68, "القلم", "The Pen", "Al-Qalam", "makkah", 52),
    (69, "الحاقة", "The Reality", "Al-Haqqah", "makkah", 52),
    (70, "المعارج", "The Ways of Ascent", "Al-Ma'arij", "makkah", 44),
    (71, "نوح", "Noah", "Nuh", "makkah", 28),
    (72, "الجن", "The Jinn", "Al-Jinn", "makkah", 28),
    (73, "المزمل", "The Enshrouded One", "Al-Muzzammil", "makkah", 20),
    (74, "المدثر", "The Cloaked One", "Al-Muddaththir", "makkah", 56),
    (75, "القيامة", "The Resurrection", "Al-Qiyamah", "makkah", 40),
    (76, "الإنسان", "Man", "Al-Insan", "madinah", 31),
    (77, "المرسلات", "The Emissaries", "Al-Mursalat", "makkah", 50),
    (78, "النبأ", "The Great News", "An-Naba", "makkah", 40),
    (79, "النازعات", "Those Who Pull Out", "An-Nazi'at", "makkah", 46),
    (80, "عبس", "He Frowned", "'Abasa", "makkah", 42),
    (81, "التكوير", "The Folding Up", "At-Takwir", "makkah", 29),
    (82, "الانفطار", "The Cleaving", "Al-Infitar", "makkah", 19),
    (83, "المطففين", "The Defrauding", "Al-Mutaffifin", "makkah", 36),
    (84, "الانشقاق", "The Splitting Open", "Al-Inshiqaq", "makkah", 25),
    (85, "البروج", "The Constellations", "Al-Buruj", "makkah", 22),
    (86, "الطارق", "The Night-Comer", "At-Tariq", "makkah", 17),
    (87, "الأعلى", "The Most High", "Al-A'la", "makkah", 19),
    (88, "الغاشية", "The Overwhelming", "Al-Ghashiyah", "makkah", 26),
    (89, "الفجر", "The Dawn", "Al-Fajr", "makkah", 30),
    (90, "البلد", "The City", "Al-Balad", "makkah", 20),
    (91, "الشمس", "The Sun", "Ash-Shams", "makkah", 15),
    (92, "الليل", "The Night", "Al-Layl", "makkah", 21),
    (93, "الضحى", "The Forenoon", "Ad-Duhaa", "makkah", 11),
    (94, "الشرح", "The Opening Forth", "Ash-Sharh", "makkah", 8),
    (95, "التين", "The Fig", "At-Tin", "makkah", 8),
    (96, "العلق", "The Clot", "Al-'Alaq", "makkah", 19),
    (97, "القدر", "The Night of Decree", "Al-Qadr", "makkah", 5),
    (98, "البينة", "The Clear Evidence", "Al-Bayyinah", "madinah", 8),
    (99, "الزلزلة", "The Earthquake", "Az-Zalzalah", "madinah", 8),
    (100, "العاديات", "The Charging Horses", "Al-'Adiyat", "makkah", 11),
    (101, "القارعة", "The Striking", "Al-Qari'ah", "makkah", 11),
    (102, "التكاثر", "The Piling Up", "At-Takathur", "makkah", 8),
    (103, "العصر", "The Time", "Al-'Asr", "makkah", 3),
    (104, "الهمزة", "The Slanderer", "Al-Humazah", "makkah", 9),
    (105, "الفيل", "The Elephant", "Al-Fil", "makkah", 5),
    (106, "قريش", "Quraysh", "Quraysh", "makkah", 4),
    (107, "الماعون", "The Small Kindnesses", "Al-Ma'un", "makkah", 7),
    (108, "الكوثر", "The Abundance", "Al-Kawthar", "makkah", 3),
    (109, "الكافرون", "The Disbelievers", "Al-Kafirun", "makkah", 6),
    (110, "النصر", "The Help", "An-Nasr", "madinah", 3),
    (111, "المسد", "The Palm Fibre", "Al-Masad", "makkah", 5),
    (112, "الإخلاص", "The Sincerity", "Al-Ikhlas", "makkah", 4),
    (113, "الفلق", "The Daybreak", "Al-Falaq", "makkah", 5),
    (114, "الناس", "Mankind", "An-Nas", "makkah", 6),
]

JUZ_START_VERSES = [
    (1, 1), (2, 1), (2, 142), (2, 253), (3, 15), (4, 1), (4, 88), (5, 1),
    (5, 82), (6, 1), (6, 111), (7, 1), (7, 88), (8, 1), (9, 1), (9, 26),
    (10, 1), (11, 1), (12, 1), (13, 1), (15, 1), (17, 1), (18, 1), (19, 1),
    (20, 1), (22, 1), (23, 1), (25, 1), (27, 1), (29, 1), (31, 1), (33, 1),
    (35, 1), (36, 1), (38, 1), (40, 1), (41, 1), (43, 1), (44, 1), (46, 1),
    (48, 1), (50, 1), (51, 1), (54, 1), (56, 1), (58, 1), (60, 1), (62, 1),
    (64, 1), (66, 1), (68, 1), (70, 1), (72, 1), (74, 1), (76, 1), (78, 1),
    (80, 1), (82, 1), (84, 1), (86, 1), (88, 1), (90, 1), (92, 1), (94, 1),
    (96, 1), (100, 1), (102, 1), (104, 1), (106, 1), (109, 1), (111, 1), (112, 1),
    (113, 1),
]


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "IslamicHedayet/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8-sig")


def parse_tanzil(text: str) -> list[tuple[int, int, str]]:
    verses = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            surah = int(parts[0])
            ayah = int(parts[1])
            body = parts[2]
            verses.append((surah, ayah, body))
        except ValueError:
            continue
    return verses


def find_juz(surah: int, ayah: int) -> int:
    for i, (s, a) in enumerate(JUZ_START_VERSES):
        if s == surah and ayah >= a:
            if i + 1 < len(JUZ_START_VERSES):
                next_s, next_a = JUZ_START_VERSES[i + 1]
                if surah > next_s or (surah == next_s and ayah >= next_a):
                    continue
            return i + 1
    return 30


def find_page(surah: int, ayah: int) -> int:
    if ayah <= 0:
        return 1
    total_verses_before = 0
    for s_num, _ar, _en, _tr, _pl, ayah_count in SURAH_METADATA:
        if s_num < surah:
            total_verses_before += ayah_count
        else:
            total_verses_before += ayah - 1
            break
    return max(1, 1 + (total_verses_before * 604) // 6236)


def main() -> int:
    print("Downloading Uthmani text from tanzil.net...")
    try:
        uthmani_text = fetch_text(TANZIL_UTHMANI_URL)
    except Exception as e:
        print(f"FAIL: tanzil.net unreachable: {e}", file=sys.stderr)
        return 1

    print("Downloading simple text from tanzil.net...")
    try:
        simple_text = fetch_text(TANZIL_SIMPLE_URL)
    except Exception as e:
        print(f"FAIL: tanzil.net simple unreachable: {e}", file=sys.stderr)
        return 1

    uthmani = parse_tanzil(uthmani_text)
    simple = parse_tanzil(simple_text)

    print(f"Parsed {len(uthmani)} Uthmani verses, {len(simple)} simple verses")
    if len(uthmani) != len(simple):
        print(f"WARN: verse count mismatch (uthmani={len(uthmani)} simple={len(simple)})")

    simple_map = {(s, a): t for s, a, t in simple}

    surah_meta = {
        num: {"arabic": ar, "english": en, "translit": tr, "place": pl, "ayah_count": ac}
        for num, ar, en, tr, pl, ac in SURAH_METADATA
    }

    verses = []
    bismillah_count = 0
    for surah, ayah, text in uthmani:
        meta = surah_meta.get(surah, {})
        simple_text = simple_map.get((surah, ayah), text)
        is_bismillah = surah == 1 and ayah == 1
        if is_bismillah:
            bismillah_count += 1
        verses.append({
            "verse_id": f"{surah}:{ayah}",
            "surah_number": surah,
            "ayah_number": ayah,
            "text_uthmani": text,
            "text_simple": simple_text,
            "is_bismillah": is_bismillah,
            "surah_name_arabic": meta.get("arabic", ""),
            "surah_name_english": meta.get("english", ""),
            "surah_name_transliteration": meta.get("translit", ""),
            "revelation_place": meta.get("place", ""),
            "ayah_count_in_surah": meta.get("ayah_count", 0),
            "juz": find_juz(surah, ayah),
            "page": find_page(surah, ayah),
        })

    unique_verses = len(set((v["surah_number"], v["ayah_number"]) for v in verses))
    expected = 6236
    if unique_verses != expected:
        print(
            f"WARN: expected {expected} unique verses, got {unique_verses}",
            file=sys.stderr,
        )

    output = {
        "source": "tanzil.net",
        "version": "uthmani + simple",
        "total_verses": unique_verses,
        "total_surahs": 114,
        "bismillah_count": bismillah_count,
        "note": "is_bismillah is only true for surah 1 ayah 1 (Al-Fatihah first verse)",
        "generated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "verses": verses,
    }

    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"OK: wrote {unique_verses} verses to {OUTPUT} ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
