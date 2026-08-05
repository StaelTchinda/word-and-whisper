#!/usr/bin/env python3
"""Extract Herbert Lockyer's *All the Prayers of the Bible* (1959) into a dataset.

Usage:
    python -m prayer.extract.lockyer [--src FILE] [--out DIR] [--strict] [--quiet]

Writes data/build/datasets/sources/lockyer1959/:

    entries.jsonl   one record per entry (canonical form)
    entries.csv     flat view; list fields joined with "|"
    quotes.csv      long form, one row per blockquote (scripture or poetry)
    refs.csv        long form, one row per scripture range
    COVERAGE.md     generated report: what parsed, what did not, and why

Unlike `extract_parks.py`, this source is OCR'd 1959 print, so partial failure is
expected and tolerated: unparseable references are recorded on the entry as
`parse_problems` and summarised in COVERAGE.md rather than aborting the run.
Pass --strict to fail the run instead, once the report is clean enough to hold.

The reference grammar here is genuinely different from the Parks source (chapter
level rather than verse level, semicolon segments, "see" cross-references, comma
verse lists, verse letter suffixes), so the range parser is deliberately local
rather than shared with `extract_parks.py`.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from prayer.extract.assemble import github_slug
from prayer.refs.bible_books import lookup, split_book

from prayer import paths

DEFAULT_SRC = paths.SOURCE_FILES["lockyer1959"]
DEFAULT_OUT = paths.DATASETS / "sources/lockyer1959"

SOURCE = {
    "source_id": "lockyer1959",
    "title": "All the Prayers of the Bible",
    "author": "Herbert Lockyer",
    "publisher": "Zondervan Publishing House",
    "publisher_place": "Grand Rapids, MI",
    "year": "1959",
    "edition_note": "Pickering & Inglis (London/Glasgow) edition, by arrangement",
    "citation": ("Herbert Lockyer, All the Prayers of the Bible "
                 "(Grand Rapids: Zondervan, 1959)."),
    # The exposition is protected expression still in copyright; the quoted
    # scripture is KJV and is public domain. See `redistributable` per field
    # group in the records and the licensing note in COVERAGE.md.
    "license": "in copyright, (c) 1959 Zondervan",
    "scripture_translation": "KJV",
    "has_prayer_text": "true",
}

# --- document grammar ------------------------------------------------------

TESTAMENTS = {
    "Prayers and Prayer in the Old Testament": "OT",
    "Prayers and Prayer in the New Testament": "NT",
}
SKIP_SECTIONS = {"A Companion Book"}          # publisher advertisement

TITLE_REF_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<ref>[^()]+)\)\s*$")
ATTRIB_RE = re.compile(r"^>\s*—\s*(?P<attrib>.+?)\s*$")
OUTLINE_RE = re.compile(r"^(?P<n>\d+)\.\s+(?P<text>.+)$")
TOC_RE = re.compile(r"^- \[(?P<label>[^\]]+)\]\(#(?P<anchor>[^)]+)\)\s*—\s*(?P<page>\d+)")
# Parenthetical scripture cross-references inside the prose: (v. 20), (15:6),
# (James 2:23), (12:1-3). Deliberately conservative — prose is full of other
# parentheses that are not references.
INLINE_REF_RE = re.compile(
    r"\((?:(?:vv?\.\s*\d[\d,\s-]*)"
    r"|(?:\d+:\d[\d,\s:-]*)"
    r"|(?:(?:[123I]{1,3}\s+)?[A-Z][a-z]+\.?\s+\d+[:\d][\d,\s:-]*))\)"
)
AUTHORITY_RE = re.compile(r"(?:Dr|Rev|Prof|Professor)\.?\s+([A-Z]\.?\s?){0,3}[A-Z][a-z]+")

TITLE_PATTERN_RE = re.compile(
    r"^(?:The\s+)?Prayers?\s+(for|of|as|in|and|about|after|to|with|by|from|on|out)\b\s*",
    re.I,
)
ARTICLE_RE = re.compile(r"^(?:a|an|the)\s+", re.I)
APPLICATION_RE = re.compile(r"\b(we|us|our|ourselves)\b", re.I)
STOPWORDS = frozenset("""a an the of for in on to and or as is are was were be been being
    with by from at it its this that these those he she they them his her their who whom
    not no nor but if then than so such very more most own same can will just don should now
    prayer prayers pray prayed praying""".split())


# --- reference parsing -----------------------------------------------------

def _verse_items(spec: str) -> list[tuple[int, int]]:
    """'1-11' -> [(1,11)];  '5, 7, 8' -> [(5,5),(7,7),(8,8)];  '26b' -> [(26,26)]."""
    out = []
    for item in (p.strip() for p in spec.split(",") if p.strip()):
        m = re.fullmatch(r"(\d+)[a-z]?\s*[-–]\s*(\d+)[a-z]?", item)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
            continue
        m = re.fullmatch(r"(\d+)[a-z]?", item)
        if not m:
            raise ValueError(f"unparseable verse item {item!r}")
        out.append((int(m.group(1)), int(m.group(1))))
    if not out:
        raise ValueError(f"no verses in {spec!r}")
    return out


def _ranges(rest: str, book) -> list[dict]:
    """Parse the numeric tail of one segment into range dicts.

    Chapter-level ('15', '12-13') and verse-level ('20:1-11', '45:5, 7, 8') both
    occur. In a single-chapter book a bare number is a verse, not a chapter.
    """
    rest = rest.strip().rstrip(".,;")
    out = []
    cross = re.fullmatch(r"(\d+):(\d+)[a-z]?\s*[-–]\s*(\d+):(\d+)[a-z]?", rest)
    if cross:
        # A range that crosses a chapter boundary, e.g. 'Ezra 9:5-10:4'.
        c1, v1, c2, v2 = (int(g) for g in cross.groups())
        out.append({"start": {"chapter": c1, "verse": v1},
                    "end": {"chapter": c2, "verse": v2},
                    "granularity": "verse_range"})
    elif ":" in rest:
        m = re.match(r"^(\d+):(.+)$", rest)
        if not m:
            raise ValueError(f"unparseable chapter:verse {rest!r}")
        ch = int(m.group(1))
        for v1, v2 in _verse_items(m.group(2)):
            out.append({"start": {"chapter": ch, "verse": v1},
                        "end": {"chapter": ch, "verse": v2},
                        "granularity": "verse" if v1 == v2 else "verse_range"})
    elif book.chapters == 1:
        for v1, v2 in _verse_items(rest):
            out.append({"start": {"chapter": 1, "verse": v1},
                        "end": {"chapter": 1, "verse": v2},
                        "granularity": "verse" if v1 == v2 else "verse_range"})
    else:
        for c1, c2 in _verse_items(rest):          # same shape, chapters not verses
            out.append({"start": {"chapter": c1, "verse": None},
                        "end": {"chapter": c2, "verse": None},
                        "granularity": "chapter" if c1 == c2 else "chapter_range"})
    for r in out:
        top = max(r["start"]["chapter"], r["end"]["chapter"])
        if book.chapters and top > book.chapters:
            raise ValueError(f"chapter {top} out of range for {book.name}")
    return out


def _osis(book, r: dict) -> str:
    s, e = r["start"], r["end"]
    if s["verse"] is None:
        a, b = f"{book.osis}.{s['chapter']}", f"{book.osis}.{e['chapter']}"
    else:
        a = f"{book.osis}.{s['chapter']}.{s['verse']}"
        b = f"{book.osis}.{e['chapter']}.{e['verse']}"
    return a if a == b else f"{a}-{b}"


def parse_ref_string(raw: str, default_book: str | None) -> tuple[list[dict], list[str]]:
    """Parse a title's parenthetical reference into normalised ranges.

    Handles every form the book uses:
        Genesis 15                                    whole chapter
        Genesis 12-13                                 chapter range
        Genesis 5:21-24; Hebrews 11:5, 6; Jude 14, 15 several books
        Genesis 39-41; 45:5, 7, 8; 50:20, 24          book carries across segments
        4:26                                          book inherited from section
        Deuteronomy 3:23-29; see Numbers 20:1-13      cross-reference

    `role` is positional: the first segment is primary, later ones parallel, and
    everything from a "see"/"cf." onward is a see_also.
    """
    refs, problems = [], []
    current = default_book
    role = "primary"
    saw_see = False
    for seg_raw in raw.split(";"):
        seg = seg_raw.strip()
        if not seg:
            continue
        if re.match(r"^(see|cf\.?)\b", seg, re.I):
            saw_see = True
            seg = re.sub(r"^(see|cf\.?)\b\s*", "", seg, flags=re.I).strip()
        try:
            book_key, rest = split_book(seg)
            current = book_key
        except KeyError:
            rest = seg                      # no book named: carries from the last one
            if current is None:
                problems.append(f"no book in scope for segment {seg!r}")
                continue
            book_key = current
        try:
            book = lookup(book_key)
            parsed = _ranges(rest, book)
        except (KeyError, ValueError) as exc:
            problems.append(f"segment {seg!r}: {exc}")
            continue
        for r in parsed:
            refs.append({
                "osis": _osis(book, r), "book": book.osis, "book_name": book.name,
                "canon": book.canon, "role": "see_also" if saw_see else role,
                "granularity": r["granularity"], "start": r["start"], "end": r["end"],
                "raw": seg,
            })
        role = "parallel"
    return refs, problems


# --- entry body ------------------------------------------------------------

def parse_body(lines: list[str], default_book: str | None) -> dict:
    """Split an entry's lines into quotes, poetry, prose, outline and OCR notes."""
    quotes, poetry, paragraphs, outline, notes = [], [], [], [], []
    problems = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("<!--"):
            buf = [line]
            while "-->" not in buf[-1] and i + 1 < len(lines):
                i += 1
                buf.append(lines[i])
            notes.append(" ".join(buf).strip())
        elif line.startswith(">"):
            block = []
            while i < len(lines) and lines[i].startswith(">"):
                block.append(lines[i])
                i += 1
            i -= 1
            attrib, text_lines = None, []
            for bl in block:
                m = ATTRIB_RE.match(bl)
                if m:
                    attrib = m.group("attrib")
                else:
                    text_lines.append(re.sub(r"^>\s?", "", bl))
            text_lines = [t for t in text_lines if t.strip()]
            # An attribution that resolves as scripture makes this a quotation;
            # anything else (e.g. "— D. W. L.") is a poem with a credit line.
            ref, ref_problems = ([], [])
            if attrib:
                ref, ref_problems = parse_ref_string(attrib, default_book)
            if ref:
                quotes.append({
                    "position": len(quotes) + len(poetry),
                    "text": " ".join(t.strip() for t in text_lines),
                    "attribution_raw": attrib, "osis": ref[0]["osis"],
                    "refs": ref, "translation": "KJV",
                })
            else:
                if attrib and ref_problems and re.search(r"\d", attrib):
                    problems.extend(f"quote attribution {attrib!r}: {p}"
                                    for p in ref_problems)
                poetry.append({
                    "position": len(quotes) + len(poetry),
                    "text": "\n".join(t.rstrip() for t in text_lines),
                    "lines": len(text_lines), "attribution": attrib,
                })
        elif line.strip():
            m = OUTLINE_RE.match(line.strip())
            if m:
                outline.append({"n": int(m.group("n")), "text": m.group("text").strip()})
            else:
                paragraphs.append(line.strip())
        i += 1
    return {"quotes": quotes, "poetry": poetry, "paragraphs": paragraphs,
            "outline": outline, "ocr_notes": notes, "problems": problems}


# --- derived fields --------------------------------------------------------

def derive(title: str, paragraphs: list[str]) -> dict:
    """Layer-2 fields: the situation-facing view of an entry.

    Lockyer's titles are already situation-shaped ("Prayer for an Unborn Child",
    "Prayer of a Discouraged Heart"), which makes them the most useful retrieval
    signal in the source. `theme` is the complement of that title pattern.
    """
    m = TITLE_PATTERN_RE.match(title)
    if m:
        pattern = m.group(1).lower()
        theme_raw = title[m.end():].strip()
    else:
        pattern, theme_raw = "other", re.sub(r"^(?:The\s+)?Prayers?\b[\s—-]*", "", title)
    theme = ARTICLE_RE.sub("", theme_raw).strip().lower()

    prose = " ".join(paragraphs)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", prose) if s.strip()]
    application = [s for s in sentences if APPLICATION_RE.search(s) and 40 <= len(s) <= 400]

    terms = {w for w in re.findall(r"[a-z]+", f"{title} {theme}".lower())
             if w not in STOPWORDS and len(w) > 2}
    return {"title_pattern": pattern, "theme_raw": theme_raw, "theme": theme,
            "situation_terms": sorted(terms), "application_sentences": application}


# --- document walk ---------------------------------------------------------

def parse_toc(lines: list[str]) -> dict[str, int]:
    """anchor -> original printed page number."""
    pages = {}
    for line in lines:
        m = TOC_RE.match(line.strip())
        if m:
            pages[m.group("anchor")] = int(m.group("page"))
    return pages


def parse_document(text: str) -> tuple[list[dict], list[dict], dict]:
    lines = text.split("\n")
    pages = parse_toc(lines)
    entries, sections, seen_slugs = [], [], {}
    canon = book_section = default_book = None
    skipping = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# ") or line.startswith("## "):
            # The OT part opens with an H1 (repeated as H2); the NT part opens
            # with an H2 only. Accept either level.
            canon = TESTAMENTS.get(line.lstrip("#").strip(), canon)
            skipping = False
        elif line.startswith("### "):
            book_section = line[4:].strip()
            skipping = book_section in SKIP_SECTIONS
            try:
                default_book = split_book(book_section + " 1")[0]
            except KeyError:
                default_book = None
            if not skipping and canon:
                # Every book heading carries an introduction before its first
                # prayer — and for books with no recorded prayers at all
                # (Leviticus, Ruth, Esther, Proverbs, Jude...) that prose is the
                # only content Lockyer gives. Capture it or lose it.
                intro, j = [], i + 1
                while j < len(lines) and not lines[j].startswith(("####", "###", "##", "#")):
                    intro.append(lines[j])
                    j += 1
                body = parse_body(intro, default_book)
                if body["paragraphs"]:
                    sections.append({
                        "id": None, "source_id": SOURCE["source_id"],
                        "record_type": "book_section",
                        "book_section": book_section, "canon_section": canon,
                        "book": lookup(default_book).osis if default_book else None,
                        "intro": {
                            "paragraphs": body["paragraphs"],
                            "word_count": sum(len(p.split()) for p in body["paragraphs"]),
                            "inline_refs": sorted({r for p in body["paragraphs"]
                                                   for r in INLINE_REF_RE.findall(p)}),
                        },
                        "poetry": body["poetry"],
                        "application_sentences":
                            derive("", body["paragraphs"])["application_sentences"],
                        "provenance": {"source_line": i + 1,
                                       "ocr_notes": body["ocr_notes"]},
                    })
        elif line.startswith("#### ") and canon and not skipping:
            title_raw = line[5:].strip()
            heading_line = i + 1
            block, i = [], i + 1
            while i < len(lines) and not lines[i].startswith(("#### ", "### ", "## ", "# ")):
                block.append(lines[i])
                i += 1
            i -= 1

            m = TITLE_REF_RE.match(title_raw)
            title = m.group("title").strip() if m else title_raw
            ref_raw = m.group("ref").strip() if m else None
            refs, problems = ([], [])
            if ref_raw:
                refs, problems = parse_ref_string(ref_raw, default_book)

            body = parse_body(block, default_book)
            problems += body["problems"]
            slug = github_slug(title_raw, seen_slugs)
            entries.append({
                "id": None,
                "source_id": SOURCE["source_id"],
                # A #### without a parenthetical reference is a structural
                # heading ("A. Prayer in the Precepts of Christ"), not a prayer.
                "entry_type": "prayer" if ref_raw else "section_header",
                "title": title, "title_raw": title_raw, "slug": slug,
                "canon_section": canon, "book_section": book_section,
                "refs": refs, "primary_ref": refs[0]["osis"] if refs else None,
                "ref_raw": ref_raw,
                "scripture_quotes": body["quotes"],
                "poetry": body["poetry"],
                "exposition": {
                    "paragraphs": body["paragraphs"],
                    "word_count": sum(len(p.split()) for p in body["paragraphs"]),
                    "outline": body["outline"],
                    "inline_refs": sorted({r for p in body["paragraphs"]
                                           for r in INLINE_REF_RE.findall(p)}),
                    "cited_authorities": sorted({m.group(0) for p in body["paragraphs"]
                                                 for m in AUTHORITY_RE.finditer(p)}),
                },
                "derived": derive(title, body["paragraphs"]),
                "page": {"original": pages.get(slug)},
                "parse_problems": problems,
                "provenance": {"source_line": heading_line,
                               "ocr_notes": body["ocr_notes"]},
            })
        i += 1

    for n, e in enumerate(entries, 1):
        e["id"] = f"{SOURCE['source_id']}.{n:04d}"
    with_prayers = {e["book_section"] for e in entries}
    for sec in sections:
        sec["id"] = f"{SOURCE['source_id']}.book.{sec['book'] or sec['book_section']}"
        sec["n_prayer_entries"] = sum(1 for e in entries
                                      if e["book_section"] == sec["book_section"])
        sec["has_prayers"] = sec["book_section"] in with_prayers

    # TOC anchors pointing at a book section are contents links, not missing
    # prayers — Lockyer lists "Absence of Prayers in Leviticus" that way.
    section_anchors = {github_slug(s["book_section"], {}) for s in sections}
    unmatched = set(pages) - {e["slug"] for e in entries}
    stats = {"toc_anchors": len(pages),
             "toc_section_links": sorted(unmatched & section_anchors),
             "toc_unmatched": sorted(unmatched - section_anchors)}
    return entries, sections, stats


# --- output ----------------------------------------------------------------

def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_outputs(entries: list[dict], sections: list[dict], stats: dict,
                  out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "entries.jsonl").open("w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    with (out / "book_sections.jsonl").open("w", encoding="utf-8") as fh:
        for sec in sections:
            fh.write(json.dumps(sec, ensure_ascii=False) + "\n")

    write_csv(out / "entries.csv", [{
        "id": e["id"], "entry_type": e["entry_type"], "title": e["title"],
        "slug": e["slug"], "canon_section": e["canon_section"],
        "book_section": e["book_section"], "ref_raw": e["ref_raw"] or "",
        "primary_ref": e["primary_ref"] or "",
        "refs_osis": "|".join(r["osis"] for r in e["refs"]),
        "granularity": "|".join(dict.fromkeys(r["granularity"] for r in e["refs"])),
        "n_quotes": len(e["scripture_quotes"]), "n_poems": len(e["poetry"]),
        "n_outline": len(e["exposition"]["outline"]),
        "word_count": e["exposition"]["word_count"],
        "title_pattern": e["derived"]["title_pattern"], "theme": e["derived"]["theme"],
        "situation_terms": "|".join(e["derived"]["situation_terms"]),
        "n_application_sentences": len(e["derived"]["application_sentences"]),
        "page": e["page"]["original"] or "",
        "n_problems": len(e["parse_problems"]), "source_line": e["provenance"]["source_line"],
    } for e in entries],
        ["id", "entry_type", "title", "slug", "canon_section", "book_section", "ref_raw",
         "primary_ref", "refs_osis", "granularity", "n_quotes", "n_poems", "n_outline",
         "word_count", "title_pattern", "theme", "situation_terms",
         "n_application_sentences", "page", "n_problems", "source_line"])

    write_csv(out / "quotes.csv",
              [{"entry_id": e["id"], "position": q["position"], "kind": "scripture",
                "osis": q["osis"], "attribution": q["attribution_raw"],
                "translation": q["translation"], "text": q["text"]}
               for e in entries for q in e["scripture_quotes"]] +
              [{"entry_id": e["id"], "position": p["position"], "kind": "poetry",
                "osis": "", "attribution": p["attribution"] or "",
                "translation": "", "text": p["text"]}
               for e in entries for p in e["poetry"]],
              ["entry_id", "position", "kind", "osis", "attribution", "translation", "text"])

    write_csv(out / "refs.csv", [{
        "entry_id": e["id"], "seq": n, "osis": r["osis"], "book": r["book"],
        "book_name": r["book_name"], "canon": r["canon"], "role": r["role"],
        "granularity": r["granularity"],
        "start_chapter": r["start"]["chapter"],
        "start_verse": r["start"]["verse"] if r["start"]["verse"] is not None else "",
        "end_chapter": r["end"]["chapter"],
        "end_verse": r["end"]["verse"] if r["end"]["verse"] is not None else "",
        "raw": r["raw"],
    } for e in entries for n, r in enumerate(e["refs"], 1)],
        ["entry_id", "seq", "osis", "book", "book_name", "canon", "role", "granularity",
         "start_chapter", "start_verse", "end_chapter", "end_verse", "raw"])

    (out / "COVERAGE.md").write_text(coverage(entries, sections, stats), "utf-8")


def coverage(entries: list[dict], sections: list[dict], stats: dict) -> str:
    prayers = [e for e in entries if e["entry_type"] == "prayer"]
    bad = [e for e in entries if e["parse_problems"]]
    no_ref = [e for e in prayers if not e["refs"]]
    no_quote = [e for e in prayers if not e["scripture_quotes"]]
    no_page = [e for e in prayers if e["page"]["original"] is None]
    gran = Counter(r["granularity"] for e in entries for r in e["refs"])
    pat = Counter(e["derived"]["title_pattern"] for e in prayers)
    L = [
        "# Lockyer 1959 — extraction coverage", "",
        f"Generated {date.today().isoformat()} by `prayer.extract.lockyer`. "
        "Do not edit by hand.", "",
        "## Totals", "",
        f"- entries parsed: **{len(entries)}** ({len(prayers)} prayers, "
        f"{len(entries) - len(prayers)} structural headings)",
        f"- OT {sum(1 for e in prayers if e['canon_section'] == 'OT')} · "
        f"NT {sum(1 for e in prayers if e['canon_section'] == 'NT')}",
        f"- scripture quotes: {sum(len(e['scripture_quotes']) for e in entries)}",
        f"- poems / hymn stanzas: {sum(len(e['poetry']) for e in entries)}",
        f"- expository outlines: {sum(1 for e in entries if e['exposition']['outline'])} entries, "
        f"{sum(len(e['exposition']['outline']) for e in entries)} points",
        f"- exposition: {sum(e['exposition']['word_count'] for e in entries):,} words",
        f"- inline cross-references: {sum(len(e['exposition']['inline_refs']) for e in entries)}",
        f"- application sentences: {sum(len(e['derived']['application_sentences']) for e in entries)}",
        f"- book-section introductions: **{len(sections)}** "
        f"({sum(1 for s in sections if not s['has_prayers'])} for books with no recorded "
        f"prayers), {sum(s['intro']['word_count'] for s in sections):,} words",
        "", "## Reference granularity", "",
        "| granularity | ranges |", "| --- | --- |",
    ]
    L += [f"| {k} | {v} |" for k, v in gran.most_common()]
    L += ["", "## Title patterns (the situation-retrieval signal)", "",
          "| pattern | entries |", "| --- | --- |"]
    L += [f"| Prayer {k} … | {v} |" for k, v in pat.most_common()]
    L += ["", "## Gaps", "",
          f"- prayers with no parseable reference: **{len(no_ref)}**",
          f"- prayers with no scripture quote: **{len(no_quote)}**",
          f"- prayers with no page number matched from the TOC: **{len(no_page)}**",
          f"- TOC links pointing at a book section rather than a prayer: "
          f"**{len(stats['toc_section_links'])}** (expected — these are Lockyer's "
          f"notes on books with no recorded prayers, captured in `book_sections.jsonl`)",
          f"- TOC anchors genuinely unaccounted for: **{len(stats['toc_unmatched'])}** "
          f"(of {stats['toc_anchors']} TOC entries)",
          f"- entries with parse problems: **{len(bad)}**", ""]
    if bad:
        L += ["### Parse problems", ""]
        L += [f"- `{e['id']}` line {e['provenance']['source_line']} — {e['title_raw']}\n"
              f"  - {p}" for e in bad for p in e["parse_problems"]]
        L += [""]
    if stats["toc_unmatched"]:
        L += ["### TOC anchors without an entry", "",
              "These are listed in the printed contents but have no body entry in the",
              "OCR — most likely pages the scan lost. Investigate before treating the",
              "entry count as complete.", ""]
        L += [f"- `{a}`" for a in stats["toc_unmatched"]] + [""]
    L += [
        "## Licensing", "",
        f"The exposition is {SOURCE['license']} — protected expression, not fact.",
        "The quoted scripture is KJV and is public domain. Treat `refs`, `title`,",
        "`derived.theme` and `scripture_quotes` as freely usable; treat `exposition`",
        "and `poetry` as local-only and exclude them from anything published.", "",
        f"> {SOURCE['citation']}", "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any entry has a parse problem")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    entries, sections, stats = parse_document(args.src.read_text(encoding="utf-8"))
    if not entries:
        print("FAILED: no entries found — check the source structure", file=sys.stderr)
        return 1

    bad = [e for e in entries if e["parse_problems"]]
    if args.strict and bad:
        print(f"FAILED (--strict): {len(bad)} entries with parse problems",
              file=sys.stderr)
        for e in bad:
            for p in e["parse_problems"]:
                print(f"  - {e['id']} line {e['provenance']['source_line']}: {p}",
                      file=sys.stderr)
        return 1

    write_outputs(entries, sections, stats, args.out)
    if not args.quiet:
        prayers = [e for e in entries if e["entry_type"] == "prayer"]
        print(f"wrote {len(entries)} entries ({len(prayers)} prayers) to {args.out}")
        print(f"  refs      {sum(len(e['refs']) for e in entries)} ranges, "
              f"{len({r['book'] for e in entries for r in e['refs']})} books")
        print(f"  quotes    {sum(len(e['scripture_quotes']) for e in entries)} scripture, "
              f"{sum(len(e['poetry']) for e in entries)} poetry")
        print(f"  prose     {sum(e['exposition']['word_count'] for e in entries):,} words, "
              f"{sum(len(e['derived']['application_sentences']) for e in entries)} "
              f"application sentences")
        print(f"  outlines  {sum(len(e['exposition']['outline']) for e in entries)} points")
        print(f"  sections  {len(sections)} book introductions, "
              f"{sum(s['intro']['word_count'] for s in sections):,} words "
              f"({sum(1 for s in sections if not s['has_prayers'])} books have no prayers)")
        print(f"  problems  {len(bad)} entries — see {args.out}/COVERAGE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
