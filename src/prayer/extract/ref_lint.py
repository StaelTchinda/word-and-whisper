#!/usr/bin/env python3
"""Validate normalized scripture references embedded as `<!-- ref: ... -->` comments.

Usage: python -m prayer.extract.ref_lint FILE [FILE...]
Writes a report to stdout; exit code 1 if any problems found.

Accepted ref grammar (after `ref:`), semicolon-separated segments:
    Book CHAPTER[:VERSE[-VERSE]][, VERSE|CHAPTER...]
Examples: "Genesis 14:18", "Numbers 12", "Genesis 39-41", "Exodus 32:9-14",
          "Psalm 90", "1 Samuel 1:9-18", "Genesis 45:5-8; Genesis 50:20"
"""
import re
import sys

# KJV chapter counts, canonical 66 books + common Apocrypha
CHAPTERS = {
    "Genesis": 50, "Exodus": 40, "Leviticus": 27, "Numbers": 36, "Deuteronomy": 34,
    "Joshua": 24, "Judges": 21, "Ruth": 4, "1 Samuel": 31, "2 Samuel": 24,
    "1 Kings": 22, "2 Kings": 25, "1 Chronicles": 29, "2 Chronicles": 36,
    "Ezra": 10, "Nehemiah": 13, "Esther": 10, "Job": 42, "Psalm": 150,
    "Proverbs": 31, "Ecclesiastes": 12, "Song of Solomon": 8, "Isaiah": 66,
    "Jeremiah": 52, "Lamentations": 5, "Ezekiel": 48, "Daniel": 12, "Hosea": 14,
    "Joel": 3, "Amos": 9, "Obadiah": 1, "Jonah": 4, "Micah": 7, "Nahum": 3,
    "Habakkuk": 3, "Zephaniah": 3, "Haggai": 2, "Zechariah": 14, "Malachi": 4,
    "Matthew": 28, "Mark": 16, "Luke": 24, "John": 21, "Acts": 28, "Romans": 16,
    "1 Corinthians": 16, "2 Corinthians": 13, "Galatians": 6, "Ephesians": 6,
    "Philippians": 4, "Colossians": 4, "1 Thessalonians": 5, "2 Thessalonians": 3,
    "1 Timothy": 6, "2 Timothy": 4, "Titus": 3, "Philemon": 1, "Hebrews": 13,
    "James": 5, "1 Peter": 5, "2 Peter": 3, "1 John": 5, "2 John": 1, "3 John": 1,
    "Jude": 1, "Revelation": 22,
    # Apocrypha (KJV 1611 versification, rough upper bounds)
    "Tobit": 14, "Judith": 16, "Wisdom of Solomon": 19, "Sirach": 51,
    "Baruch": 6, "1 Maccabees": 16, "2 Maccabees": 15, "1 Esdras": 9,
    "2 Esdras": 16, "Prayer of Manasseh": 1,
}

REF_RE = re.compile(r"<!--\s*ref:\s*(.*?)\s*-->")
SEG_RE = re.compile(
    r"^(?P<book>(?:[123]\s)?[A-Za-z][A-Za-z ]*?)\s+(?P<rest>\d[\d:,\s\-–]*)$"
)


def check_segment(seg: str):
    """Return list of problem strings for one 'Book nums' segment."""
    seg = seg.strip()
    if not seg:
        return ["empty segment"]
    m = SEG_RE.match(seg)
    if not m:
        return [f"unparseable: {seg!r}"]
    book = m.group("book").strip()
    if book not in CHAPTERS:
        return [f"unknown book: {book!r}"]
    problems = []
    rest = m.group("rest").replace("–", "-").strip()
    # split on commas: each piece is chapter, chapter-range, verse ref, or verse list item
    # track whether we've seen a colon (=> comma pieces are verses of that chapter)
    max_ch = CHAPTERS[book]
    in_verses = False
    for piece in (p.strip() for p in rest.split(",")):
        if not piece:
            problems.append(f"dangling comma in {seg!r}")
            continue
        if ":" in piece:
            ch_part, _, v_part = piece.partition(":")
            in_verses = True
            try:
                ch = int(ch_part.split("-")[0])
            except ValueError:
                problems.append(f"bad chapter {ch_part!r} in {seg!r}")
                continue
            if not 1 <= ch <= max_ch:
                problems.append(f"{book} has {max_ch} chapters, got {ch}")
            if not re.fullmatch(r"\d+(-\d+)?", v_part):
                problems.append(f"bad verse part {v_part!r} in {seg!r}")
        else:
            if in_verses:
                # verse list item like the '22' in 'Genesis 14:18, 22'
                if not re.fullmatch(r"\d+(-\d+)?", piece):
                    problems.append(f"bad verse item {piece!r} in {seg!r}")
            else:
                # chapter or chapter range
                if not re.fullmatch(r"\d+(-\d+)?", piece):
                    problems.append(f"bad chapter item {piece!r} in {seg!r}")
                    continue
                for ch in map(int, piece.split("-")):
                    if not 1 <= ch <= max_ch:
                        problems.append(f"{book} has {max_ch} chapters, got {ch}")
    return problems


def main(paths):
    total, bad = 0, 0
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                for ref in REF_RE.findall(line):
                    total += 1
                    problems = []
                    for seg in ref.split(";"):
                        problems.extend(check_segment(seg))
                    if problems:
                        bad += 1
                        print(f"{path}:{lineno}: ref '{ref}': " + "; ".join(problems))
    print(f"\nChecked {total} refs across {len(paths)} file(s): {bad} problem(s).")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1:]))
