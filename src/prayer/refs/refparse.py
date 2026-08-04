#!/usr/bin/env python3
"""Parse printed scripture references into normalised OSIS ranges.

Covers the grammar shared by the Lockyer and Watters sources, both of which
spell books out and separate passages with semicolons:

    Genesis 15                                    whole chapter
    Genesis 12-13                                 chapter range
    Ezra 9:5-10:4                                 crosses a chapter boundary
    Jonah 2:2, 4, 6-7                             comma verse list
    Nehemiah 1:3-4; 9:36-37                       book carries across segments
    Genesis 5:21-24; Hebrews 11:5, 6; Jude 14, 15 several books
    Jude 14, 15                                   single-chapter book: verses

`parse` never raises: it returns whatever it could resolve plus a list of
problem strings, so a caller extracting OCR'd print can record the failures
rather than abort. Callers that want strictness check `problems` themselves.
"""
import re

from prayer.refs.bible_books import lookup, split_book

# One numeric item: '11', '1-11', '26b', '5–7'.
_ITEM_RE = re.compile(r"(\d+)[a-z]?(?:\s*[-–]\s*(\d+)[a-z]?)?$")
# A whole segment that crosses a chapter boundary: '9:5-10:4'.
_CROSS_RE = re.compile(r"(\d+):(\d+)[a-z]?\s*[-–]\s*(\d+):(\d+)[a-z]?$")


def _items(spec: str) -> list[tuple[int, int]]:
    """'5, 7, 8' -> [(5,5),(7,7),(8,8)]; '1-11' -> [(1,11)]."""
    out = []
    for raw in (p.strip() for p in spec.split(",") if p.strip()):
        m = _ITEM_RE.fullmatch(raw)
        if not m:
            raise ValueError(f"unparseable number {raw!r}")
        lo = int(m.group(1))
        out.append((lo, int(m.group(2)) if m.group(2) else lo))
    if not out:
        raise ValueError(f"no numbers in {spec!r}")
    return out


def _ranges(rest: str, book) -> list[dict]:
    """Numeric tail of one segment -> range dicts.

    A bare number is a chapter, except in a single-chapter book where it can
    only be a verse (Jude, Obadiah, Philemon, 2-3 John).
    """
    rest = rest.strip().rstrip(".,;:")
    out = []
    cross = _CROSS_RE.fullmatch(rest)
    if cross:
        c1, v1, c2, v2 = (int(g) for g in cross.groups())
        out.append({"start": {"chapter": c1, "verse": v1},
                    "end": {"chapter": c2, "verse": v2},
                    "granularity": "verse_range"})
    elif ":" in rest:
        # A comma item may open a new chapter of its own:
        # 'Exodus 33:15-16, 34:8-9' is two chapters, not a verse list.
        ch = None
        for chunk in (c.strip() for c in rest.split(",") if c.strip()):
            if ":" in chunk:
                m = re.fullmatch(r"(\d+):(.+)", chunk)
                if not m:
                    raise ValueError(f"unparseable chapter:verse {chunk!r}")
                ch, spec = int(m.group(1)), m.group(2)
            else:
                if ch is None:
                    raise ValueError(f"no chapter in scope for {chunk!r}")
                spec = chunk
            for v1, v2 in _items(spec):
                out.append({"start": {"chapter": ch, "verse": v1},
                            "end": {"chapter": ch, "verse": v2},
                            "granularity": "verse" if v1 == v2 else "verse_range"})
    elif book.chapters == 1:
        for v1, v2 in _items(rest):
            out.append({"start": {"chapter": 1, "verse": v1},
                        "end": {"chapter": 1, "verse": v2},
                        "granularity": "verse" if v1 == v2 else "verse_range"})
    else:
        for c1, c2 in _items(rest):
            out.append({"start": {"chapter": c1, "verse": None},
                        "end": {"chapter": c2, "verse": None},
                        "granularity": "chapter" if c1 == c2 else "chapter_range"})
    for r in out:
        top = max(r["start"]["chapter"], r["end"]["chapter"])
        if book.chapters and top > book.chapters:
            raise ValueError(f"chapter {top} out of range for {book.name}")
    return out


def osis(book, r: dict) -> str:
    s, e = r["start"], r["end"]
    if s["verse"] is None:
        a, b = f"{book.osis}.{s['chapter']}", f"{book.osis}.{e['chapter']}"
    else:
        a = f"{book.osis}.{s['chapter']}.{s['verse']}"
        b = f"{book.osis}.{e['chapter']}.{e['verse']}"
    return a if a == b else f"{a}-{b}"


def parse(raw: str, default_book: str | None = None) -> tuple[list[dict], list[str]]:
    """Parse a full reference string. Returns (refs, problems).

    A segment with no book name inherits the last book seen — the source prints
    'Nehemiah 1:3-4; 9:36-37' meaning two passages in Nehemiah. `default_book`
    seeds that state for sources where the book comes from an enclosing heading.
    """
    refs, problems = [], []
    current = default_book
    anchor = None          # first book named in this string
    seen: list[str] = []   # every book named so far, in order
    for seg_raw in raw.split(";"):
        seg = seg_raw.strip()
        if not seg:
            continue
        inherited = False
        try:
            book_key, rest = split_book(seg)
            current = book_key
            anchor = anchor or book_key
            if book_key not in seen:
                seen.append(book_key)
        except KeyError:
            if current is None:
                problems.append(f"no book in scope for {seg!r}")
                refs.append({"osis": None, "raw": seg, "unresolved": True,
                             "reason": "no book in scope"})
                continue
            book_key, rest, inherited = current, seg, True

        parsed = book = None
        last = None
        origin = None
        for cand, why in ([(book_key, "stated")] if not inherited
                          else [(book_key, "carried"), (anchor, "anchor_fallback")]):
            if not cand:
                continue
            try:
                b = lookup(cand)
                parsed, book, book_key, origin = _ranges(rest, b), b, cand, why
                break
            except (KeyError, ValueError) as exc:
                last = exc
        if parsed is None and inherited:
            # Bare numbers valid for exactly one other book already named in
            # this citation ('Isaiah 50:10; 78:34' -> Psalm 78, the only book
            # named here with that many chapters). Require uniqueness: a guess
            # with two candidates would be a fabricated reference.
            hits = []
            for cand in seen:
                try:
                    b = lookup(cand)
                    hits.append((_ranges(rest, b), b, cand))
                except (KeyError, ValueError):
                    pass
            if len(hits) == 1:
                parsed, book, book_key = hits[0]
                origin = "named_in_citation"
        if parsed is None:
            # Keep the segment rather than dropping it: an unresolved reference
            # is still information, a missing one is a silent hole.
            problems.append(f"{seg!r}: {last}")
            refs.append({"osis": None, "raw": seg, "unresolved": True,
                         "reason": str(last)})
            continue

        # Bare numbers out of range for the preceding book but valid for the
        # citation's anchor book: the 1883 compiler reverts to the anchor
        # mid-string ('Job 7:11; 10:1; 69:9-10' -> Psalm 69).
        inferred = origin if origin in ("anchor_fallback", "named_in_citation") else None
        if inferred:
            current = book_key
        for r in parsed:
            refs.append({
                "osis": osis(book, r), "book": book.osis, "book_name": book.name,
                "canon": book.canon, "granularity": r["granularity"],
                "start": r["start"], "end": r["end"], "raw": seg,
                "book_inherited": inherited, "unresolved": False,
                "book_inferred": inferred,
            })
    return refs, problems
