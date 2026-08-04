#!/usr/bin/env python3
"""Extract Philip Watters' *The Prayers of the Bible* (1883) into a dataset.

Usage:
    python -m prayer.extract.watters [--src FILE] [--out DIR] [--quiet]
                                     [--allow-unaccounted N]

Writes data/build/datasets/sources/watters1883/:

    citations.jsonl        every **Reference** line, inline text or back-reference
    topics.jsonl           the ### / #### taxonomy under each chapter
    chapters.jsonl         30 chapters, with the facet each is mapped to
    passages.jsonl         citations inverted and grouped by OSIS reference
    cross_references.jsonl topic -> topic edges the author drew by hand
    toc.jsonl              the printed contents, with original page numbers
    front_matter.jsonl     title page, subtitle, preface
    back_matter.jsonl      general index note, endorsements
    editorial_notes.jsonl  page markers and the cleaner's OCR notes
    COVERAGE.md            generated report, including the line accounting

This source is a topical index rather than a collection of prayers: the atomic
record is a *citation* — one scripture reference under one topic — and the same
passage recurs under many topics by design. That repetition is the labelling
signal; never deduplicate it.

The build is accounted line by line. Every line of the source is assigned either
to a record or to an explicit structural bucket, and the run FAILS if any line is
left over. That check is what caught 249 citations written as
`**Ref** *(as above under Affliction)*` rather than `**Ref** — text`.
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from prayer.refs.refparse import parse as parse_refs

from prayer import paths

DEFAULT_SRC = paths.SOURCE_FILES["watters1883"]
DEFAULT_OUT = paths.DATASETS / "sources/watters1883"

SOURCE = {
    "source_id": "watters1883",
    "title": "The Prayers of the Bible",
    "subtitle": ("Showing How to Pray, What to Pray For, "
                 "and How God Answers Prayer"),
    "author": "Philip Watters",
    "role": "compiler",
    "publisher": "Phillips & Hunt",
    "publisher_place": "New York",
    "year": "1883",
    "citation": ("Philip Watters, comp., The Prayers of the Bible "
                 "(New York: Phillips & Hunt, 1883)."),
    # 1883: copyright long expired. This is the only source in the repo whose
    # text and taxonomy may be redistributed and shipped in a product.
    "license": "public domain",
    "scripture_translation": "KJV",
    "has_prayer_text": "true",
}

# Each chapter gets its own facet. There is deliberately no residual bucket:
# collapsing chapters into a catch-all would discard distinctions the author
# built the book around. `chapter_n` and `chapter_title` are always preserved
# verbatim on every record, so this mapping stays a queryable convenience that
# can be revised without losing anything.
CHAPTER_FACETS = {
    1: "agent", 2: "duty", 3: "ground", 4: "divine_preparation",
    5: "divine_willingness", 6: "time", 7: "place", 8: "outward_condition",
    9: "spiritual_condition", 10: "object", 11: "duration", 12: "encouragement",
    13: "answer_mode", 14: "answer_timing", 15: "answer_timing",
    16: "answer_extent", 17: "answer_extent", 18: "answer_refusal",
    19: "answer_refusal", 20: "answer_timing", 21: "answer_extent",
    22: "answer_extent", 23: "hindrance", 24: "hindrance",
    25: "intercession_duty", 26: "intercession_request", 27: "necessity",
    28: "promise", 29: "advantage", 30: "neglect",
}

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
         "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
         "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21,
         "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25, "XXVI": 26,
         "XXVII": 27, "XXVIII": 28, "XXIX": 29, "XXX": 30}

CHAPTER_RE = re.compile(r"^Chapter\s+(?P<roman>[IVX]+)[.\s—-]+(?P<title>.+?)\s*$")
CITATION_RE = re.compile(r"^\*\*(?P<ref>[^*]+)\*\*\s*(?P<rest>.*)$")
TOC_ROW_RE = re.compile(r"^\|\s*(?P<roman>[IVX]+)\s*\|\s*(?P<title>[^|]+?)\s*\|"
                        r"\s*(?P<page>\d+)\s*\|$")
# A contents entry may cite several pages ("- Elders — 28, 29") and may carry a
# trailing italic note from the cleaning pass flagging a suspect page number.
TOC_ITEM_RE = re.compile(r"^-\s*(?P<label>.+?)\s*—\s*(?P<pages>\d+(?:\s*,\s*\d+)*)"
                         r"\s*(?:\*\((?P<note>.+)\)\*)?\s*$")
PAGE_RE = re.compile(r"^<!--\s*page\s+(?P<n>\d+)")
# Any italic parenthetical tail stands in for text quoted elsewhere. The forms
# vary too much to pin down with one rigid pattern -- "(as above)", "(as
# previously quoted under The Apostles)", "(as previously quoted, condensed)",
# "(see Blessing on Children, above)" -- so capture the whole thing verbatim and
# classify what is recognisable, rather than dropping what is not.
BACKREF_RE = re.compile(r"^\*\((?P<inner>.+)\)\*$", re.S)
BACKREF_TARGET_RE = re.compile(r"\b(?:under|see)\s+(?P<target>[^;,)]+?)"
                               r"\s*(?:,\s*above|[;,)]|$)", re.I)
XREF_ONLY_RE = re.compile(r"^\*\(\s*See\s+(?P<target>[^)]+?)\s*\.?\s*\)\*$", re.I)


def slug(*parts: str) -> str:
    s = "-".join(p for p in parts if p)
    s = re.sub(r"[^\w\s-]", "", s.lower())
    return re.sub(r"[\s_]+", "-", s).strip("-")


class Accounting:
    """Assigns every source line to a record or an explicit structural bucket."""

    def __init__(self, n_lines: int):
        self.owner: list[str | None] = [None] * n_lines

    def claim(self, i: int, what: str) -> None:
        self.owner[i] = what

    def unaccounted(self) -> list[int]:
        return [i for i, o in enumerate(self.owner) if o is None]

    def summary(self) -> Counter:
        return Counter(o for o in self.owner if o)


def extract(text: str) -> tuple[dict, Accounting]:
    lines = text.split("\n")
    acct = Accounting(len(lines))
    out = defaultdict(list)
    problems: list[str] = []

    # ---- pass 1: structural lines every region shares ---------------------
    comment_spans: list[tuple[int, int, str]] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            acct.claim(i, "blank")
        elif s in ("---", "***"):
            acct.claim(i, "rule")
        elif s.startswith("<!--"):
            start, buf = i, [s]
            while "-->" not in buf[-1] and i + 1 < len(lines):
                i += 1
                buf.append(lines[i].strip())
            comment_spans.append((start, i, " ".join(buf)))
            for j in range(start, i + 1):
                acct.claim(j, "editorial_note")
        i += 1

    # Page markers give every later record its printed page number.
    page_at: dict[int, int] = {}
    for start, end, body in comment_spans:
        m = PAGE_RE.match(body)
        if m:
            page_at[start] = int(m.group("n"))
        note_id = f"{SOURCE['source_id']}.note.{start + 1:05d}"
        out["editorial_notes"].append({
            "id": note_id, "source_id": SOURCE["source_id"],
            "kind": "page_marker" if m else "editorial",
            "page": int(m.group("n")) if m else None,
            "text": re.sub(r"^<!--\s*|\s*-->$", "", body).strip(),
            "provenance": {"source_line": start + 1, "end_line": end + 1},
        })

    def page_for(line_idx: int) -> int | None:
        best = None
        for ln, pg in page_at.items():
            if ln <= line_idx and (best is None or ln > best[0]):
                best = (ln, pg)
        return best[1] if best else None

    # ---- region boundaries ------------------------------------------------
    def find(pred, start=0):
        return next((n for n in range(start, len(lines)) if pred(lines[n])), None)

    toc_chapters_at = find(lambda l: l.strip() == "## Contents")
    toc_detail_at = find(lambda l: l.strip() == "## Contents of Chapters")
    body_at = find(lambda l: l.strip() == "# The Prayers of the Bible",
                   (toc_detail_at or 0) + 1)
    back_at = find(lambda l: l.strip() == "## Back Matter")

    missing = [name for name, at in (("## Contents", toc_chapters_at),
                                     ("## Contents of Chapters", toc_detail_at),
                                     ("the body's '# The Prayers of the Bible'",
                                      body_at)) if at is None]
    if missing:
        raise ValueError("source is missing its expected structure: "
                         + ", ".join(missing))

    # ---- front matter -----------------------------------------------------
    para, para_start = [], None
    for n in range(0, toc_chapters_at):
        if acct.owner[n]:
            continue
        s = lines[n].strip()
        if s.startswith("#"):
            acct.claim(n, "front_matter:heading")
            continue
        if para_start is None:
            para_start = n
        para.append(s)
        acct.claim(n, "front_matter")
    if para:
        out["front_matter"].append({
            "id": f"{SOURCE['source_id']}.front", "source_id": SOURCE["source_id"],
            "headings": [lines[n].strip().lstrip("# ")
                         for n in range(0, toc_chapters_at)
                         if lines[n].strip().startswith("#")],
            "paragraphs": para, "word_count": sum(len(p.split()) for p in para),
            "provenance": {"source_line": (para_start or 0) + 1},
        })

    # ---- chapter contents table ------------------------------------------
    chapter_pages: dict[int, int] = {}
    for n in range(toc_chapters_at, toc_detail_at):
        if acct.owner[n]:
            continue
        s = lines[n].strip()
        m = TOC_ROW_RE.match(s)
        if m:
            num = ROMAN[m.group("roman")]
            chapter_pages[num] = int(m.group("page"))
            out["toc"].append({
                "id": f"{SOURCE['source_id']}.toc.ch{num:02d}",
                "source_id": SOURCE["source_id"], "level": "chapter",
                "chapter_n": num, "label": m.group("title").strip(),
                "page": int(m.group("page")), "pages": [int(m.group("page"))],
                "note": None,
                "provenance": {"source_line": n + 1},
            })
            acct.claim(n, "toc")
        elif s.startswith("|") or s.startswith("#"):
            acct.claim(n, "toc:structure")

    # ---- detailed contents ------------------------------------------------
    toc_chapter = None
    for n in range(toc_detail_at, body_at):
        if acct.owner[n]:
            continue
        s = lines[n].strip()
        if s.startswith("#"):
            m = CHAPTER_RE.match(s.lstrip("# ").strip())
            toc_chapter = ROMAN.get(m.group("roman")) if m else None
            acct.claim(n, "toc:structure")
            continue
        m = TOC_ITEM_RE.match(s)
        if m:
            pages = [int(x) for x in m.group("pages").split(",")]
            out["toc"].append({
                "id": f"{SOURCE['source_id']}.toc.{n + 1:05d}",
                "source_id": SOURCE["source_id"], "level": "topic",
                "chapter_n": toc_chapter, "label": m.group("label").strip(),
                "page": pages[0], "pages": pages, "note": m.group("note"),
                "provenance": {"source_line": n + 1},
            })
            acct.claim(n, "toc")

    # ---- back matter ------------------------------------------------------
    if back_at is not None:
        heads, paras, start = [], [], back_at
        for n in range(back_at, len(lines)):
            if acct.owner[n]:
                continue
            s = lines[n].strip()
            (heads if s.startswith("#") else paras).append(s.lstrip("# "))
            acct.claim(n, "back_matter")
        out["back_matter"].append({
            "id": f"{SOURCE['source_id']}.back", "source_id": SOURCE["source_id"],
            "content_type": "endorsement_and_index_note",
            "headings": heads, "paragraphs": paras,
            "note": ("The general index and the clergymen's endorsements were "
                     "not transcribed by the cleaning pass; see the editorial "
                     "notes in this range for what the source pages contain."),
            "provenance": {"source_line": start + 1},
        })

    # ---- body -------------------------------------------------------------
    chapter = topic = subtopic = None
    chapter_rec = None
    pending_prose: list[str] = []

    def topic_path() -> list[str]:
        return [p for p in (topic, subtopic) if p]

    def flush_prose(anchor_line: int) -> None:
        """Prose with no citation of its own: a narrative note the cleaner added,
        or scripture text continuing the citation above it."""
        nonlocal pending_prose
        for text in pending_prose:
            is_note = text.startswith("*(") and text.endswith(")*")
            xr = XREF_ONLY_RE.match(text)
            if xr and chapter_rec:
                out["cross_references"].append({
                    "id": f"{SOURCE['source_id']}.xref.{anchor_line:05d}",
                    "source_id": SOURCE["source_id"], "kind": "topic_pointer",
                    "from_chapter_n": chapter_rec["chapter_n"],
                    "from_topic_path": topic_path(),
                    "to_topic_raw": xr.group("target").strip(),
                    "from_citation_id": None,
                    "provenance": {"source_line": anchor_line, "raw": text},
                })
            else:
                out["body_prose"].append({
                    "id": f"{SOURCE['source_id']}.prose.{anchor_line:05d}",
                    "source_id": SOURCE["source_id"],
                    "kind": "editorial_narrative" if is_note else "continuation_text",
                    "chapter_n": chapter_rec["chapter_n"] if chapter_rec else None,
                    "topic_path": topic_path(),
                    "attaches_to": out["citations"][-1]["id"]
                    if (not is_note and out["citations"]) else None,
                    "text": text.strip("*()") if is_note else text,
                    "provenance": {"source_line": anchor_line, "raw": text},
                })
        pending_prose = []

    for n in range(body_at, back_at if back_at is not None else len(lines)):
        if acct.owner[n]:
            continue
        s = lines[n].strip()

        if s.startswith("## "):
            flush_prose(n)
            m = CHAPTER_RE.match(s[3:].strip())
            if m:
                num = ROMAN[m.group("roman")]
                chapter = m.group("title").strip().rstrip(".")
                topic = subtopic = None
                chapter_rec = {
                    "id": f"{SOURCE['source_id']}.ch{num:02d}",
                    "source_id": SOURCE["source_id"], "chapter_n": num,
                    "roman": m.group("roman"), "title": chapter,
                    "facet": CHAPTER_FACETS[num],
                    "page": chapter_pages.get(num),
                    "provenance": {"source_line": n + 1, "raw": s},
                }
                out["chapters"].append(chapter_rec)
            acct.claim(n, "chapter:heading")
            continue

        if s.startswith("#### ") or s.startswith("### "):
            flush_prose(n)
            level = 4 if s.startswith("#### ") else 3
            label = s.lstrip("# ").strip()
            if level == 3:
                topic, subtopic = label, None
            else:
                subtopic = label
            if chapter_rec:
                out["topics"].append({
                    "id": f"{SOURCE['source_id']}.topic."
                          f"{chapter_rec['chapter_n']:02d}.{slug(*topic_path())}",
                    "source_id": SOURCE["source_id"],
                    "chapter_n": chapter_rec["chapter_n"],
                    "chapter_title": chapter_rec["title"],
                    "facet": chapter_rec["facet"],
                    "level": level, "topic": topic, "subtopic": subtopic,
                    "path": topic_path(), "page": page_for(n),
                    "provenance": {"source_line": n + 1},
                })
            acct.claim(n, "topic:heading")
            continue

        if s.startswith("#"):
            acct.claim(n, "body:structure")
            continue

        m = CITATION_RE.match(s)
        if m and chapter_rec:
            flush_prose(n)
            ref_raw, rest = m.group("ref").strip(), m.group("rest").strip()

            # Two source lines fold a topic heading into the bold reference:
            # "**Any Good Thing — Psalm 34:10** — ...". Recover the topic
            # rather than losing both it and the reference.
            lead = re.match(r"^(?P<topic>[A-Z][^—]*?)\s+—\s+(?P<ref>.+)$", ref_raw)
            if lead and not re.match(r"^[0-9IVX]", lead.group("topic")):
                topic, subtopic = lead.group("topic").strip(), None
                ref_raw = lead.group("ref").strip()
                out["topics"].append({
                    "id": f"{SOURCE['source_id']}.topic."
                          f"{chapter_rec['chapter_n']:02d}.{slug(topic)}",
                    "source_id": SOURCE["source_id"],
                    "chapter_n": chapter_rec["chapter_n"],
                    "chapter_title": chapter_rec["title"],
                    "facet": chapter_rec["facet"], "level": 3,
                    "topic": topic, "subtopic": None, "path": [topic],
                    "page": page_for(n), "recovered_from_citation_line": True,
                    "provenance": {"source_line": n + 1},
                })

            # An inline "(see Other Topic, above)" inside the reference string is
            # a cross-reference, not a passage.
            inline_xref = re.search(r"\(see\s+([^)]+?)(?:,\s*above)?"
                                    r"(?:,[^)]*)?\)", ref_raw, re.I)
            if inline_xref:
                out["cross_references"].append({
                    "id": f"{SOURCE['source_id']}.xref.{n + 1:05d}b",
                    "source_id": SOURCE["source_id"], "kind": "inline_in_reference",
                    "back_reference_kind": "see_topic",
                    "from_chapter_n": chapter_rec["chapter_n"],
                    "from_topic_path": topic_path(),
                    "to_topic_raw": inline_xref.group(1).strip(),
                    "from_citation_id": None, "raw_note": inline_xref.group(0),
                    "provenance": {"source_line": n + 1, "raw": s},
                })
                ref_raw = re.sub(r"[;,]?\s*[A-Za-z]*\s*\(see[^)]*\)", "",
                                 ref_raw, flags=re.I).strip().rstrip(";,")

            refs, probs = parse_refs(ref_raw)
            problems += [f"line {n + 1}: {p}" for p in probs]

            back = BACKREF_RE.match(rest)
            back_kind = back_raw = None
            if rest.startswith("—"):
                text_source, text = "inline", rest.lstrip("—").strip()
                target = None
            elif back:
                text_source, text = "back_reference", None
                back_raw = back.group("inner").strip()
                tm = BACKREF_TARGET_RE.search(back_raw)
                target = tm.group("target").strip() if tm else None
                low = back_raw.lower()
                if "previously quoted" in low:
                    back_kind = "previously_quoted"
                elif "as above" in low or low.startswith("as "):
                    back_kind = "as_above"
                elif low.startswith("see"):
                    back_kind = "see_topic"
                else:
                    back_kind = "editorial_summary"
            elif not rest:
                text_source, text, target = "none", None, None
            else:
                text_source, text, target = "other", rest, None
                problems.append(f"line {n + 1}: unrecognised citation tail {rest!r}")

            cid = f"{SOURCE['source_id']}.{len(out['citations']) + 1:05d}"
            out["citations"].append({
                "id": cid, "source_id": SOURCE["source_id"],
                "chapter_n": chapter_rec["chapter_n"],
                "chapter_title": chapter_rec["title"],
                "facet": chapter_rec["facet"],
                "topic": topic, "subtopic": subtopic, "topic_path": topic_path(),
                "ref_raw": ref_raw, "refs": refs,
                "primary_ref": next((r["osis"] for r in refs if r.get("osis")), None),
                "n_refs": len(refs),
                "n_refs_unresolved": sum(1 for r in refs if r.get("unresolved")),
                "text": text, "translation": "KJV" if text else None,
                "text_source": text_source,
                # One text blob covering several references cannot be split back
                # per reference without aligning against a full KJV corpus.
                "text_is_concatenated": bool(text) and len(refs) > 1,
                "word_count": len(text.split()) if text else 0,
                "resolved_text_from": None,     # filled in below
                "resolved_how": None,
                "back_reference_target": target,
                "back_reference_kind": back_kind,
                "back_reference_raw": back_raw,
                "page": page_for(n),
                "provenance": {"source_line": n + 1, "raw": s},
            })
            if text_source == "back_reference":
                out["cross_references"].append({
                    "id": f"{SOURCE['source_id']}.xref.{n + 1:05d}",
                    "source_id": SOURCE["source_id"], "kind": "back_reference",
                    "back_reference_kind": back_kind,
                    "from_chapter_n": chapter_rec["chapter_n"],
                    "from_topic_path": topic_path(), "to_topic_raw": target,
                    "raw_note": back_raw,
                    "from_citation_id": cid,
                    "provenance": {"source_line": n + 1, "raw": s},
                })
            acct.claim(n, "citation")
            continue

        pending_prose.append(s)
        acct.claim(n, "body_prose")
    flush_prose(len(lines))

    # ---- resolve back-references -----------------------------------------
    # A back-reference quotes no words; recover them from the same OSIS
    # reference quoted inline elsewhere. Where that fails the citation keeps a
    # reference and a topic but no text, and says so.
    def span(r: dict):
        return ((r["start"]["chapter"], r["start"]["verse"] or 0),
                (r["end"]["chapter"],
                 r["end"]["verse"] if r["end"]["verse"] is not None else 10**6))

    by_osis: dict[str, str] = {}
    by_book: dict[str, list] = defaultdict(list)
    text_by_id = {c["id"]: c["text"] for c in out["citations"]}
    for c in out["citations"]:
        if c["text_source"] != "inline":
            continue
        for r in c["refs"]:
            if not r.get("osis"):
                continue
            by_osis.setdefault(r["osis"], c["id"])
            # Only single-reference citations quote one passage exactly; a
            # bundled one covers several and cannot stand in for any single one.
            if c["n_refs"] == 1:
                by_book[r["book"]].append((span(r), c["id"]))

    for c in out["citations"]:
        if c["text_source"] != "back_reference":
            continue
        target = next((r for r in c["refs"] if r.get("osis")), None)
        src = by_osis.get(c["primary_ref"]) if c["primary_ref"] else None
        how = "exact" if src else None
        if not src and target:
            # Fall back to an inline quotation whose range contains this one:
            # the book cites "Genesis 32:9-11" where it earlier quoted 32:9-12.
            lo, hi = span(target)
            best = None
            for (s2, e2), cid in by_book.get(target["book"], []):
                if s2 <= lo and hi <= e2:
                    size = (e2[0] - s2[0], e2[1] - s2[1])
                    if best is None or size < best[0]:
                        best = (size, cid)
            if best:
                src, how = best[1], "containing_range"
        if src and text_by_id.get(src):
            c["resolved_text_from"] = src
            c["resolved_how"] = how
            c["text"] = text_by_id[src]
            c["translation"] = "KJV"
            c["word_count"] = len(c["text"].split())
        else:
            c["text_source"] = "unresolved"

    # ---- roll-ups ---------------------------------------------------------
    cites_by_topic = defaultdict(list)
    for c in out["citations"]:
        cites_by_topic[(c["chapter_n"], tuple(c["topic_path"]))].append(c)
    for t in out["topics"]:
        rel = cites_by_topic.get((t["chapter_n"], tuple(t["path"])), [])
        t["n_citations"] = len(rel)
        t["citation_ids"] = [c["id"] for c in rel]
        t["refs"] = sorted({r["osis"] for c in rel for r in c["refs"] if r.get("osis")})
        t["situation_terms"] = sorted(
            {w for w in re.findall(r"[a-z]+", " ".join(t["path"]).lower())
             if len(w) > 2})
    for ch in out["chapters"]:
        ch["n_topics"] = sum(1 for t in out["topics"]
                             if t["chapter_n"] == ch["chapter_n"])
        ch["n_citations"] = sum(1 for c in out["citations"]
                                if c["chapter_n"] == ch["chapter_n"])

    passages = defaultdict(list)
    for c in out["citations"]:
        for r in c["refs"]:
            if r.get("osis"):
                passages[r["osis"]].append((c, r))
    for osis_id, pairs in sorted(passages.items()):
        rel = [c for c, _ in pairs]
        inline = next((c["text"] for c in rel
                       if c["text_source"] == "inline" and c["n_refs"] == 1), None)
        out["passages"].append({
            "osis": osis_id, "source_id": SOURCE["source_id"],
            "book": pairs[0][1]["book"],
            "text": inline, "text_is_exact": inline is not None,
            "n_citations": len(rel),
            "citation_ids": [c["id"] for c in rel],
            "topics": sorted({(c["chapter_n"], " > ".join(c["topic_path"]),
                               c["facet"]) for c in rel}),
            "facets": sorted({c["facet"] for c in rel}),
        })
    for p in out["passages"]:
        p["topics"] = [{"chapter_n": a, "path": b, "facet": f}
                       for a, b, f in p["topics"]]
        p["n_topics"] = len(p["topics"])

    out["problems"] = problems
    return out, acct


# --- output ----------------------------------------------------------------

def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_outputs(out: dict, acct: Accounting, n_lines: int, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("citations", "topics", "chapters", "passages", "cross_references",
                 "toc", "front_matter", "back_matter", "editorial_notes",
                 "body_prose"):
        write_jsonl(dest / f"{name}.jsonl", out[name])

    write_csv(dest / "citations.csv", [{
        **c, "topic_path": " > ".join(c["topic_path"]),
        "refs_osis": "|".join(r["osis"] for r in c["refs"] if r.get("osis")),
        "books": "|".join(dict.fromkeys(r["book"] for r in c["refs"] if r.get("book"))),
    } for c in out["citations"]],
        ["id", "chapter_n", "chapter_title", "facet", "topic", "subtopic",
         "topic_path", "ref_raw", "refs_osis", "books", "primary_ref", "n_refs",
         "n_refs_unresolved", "text_source", "text_is_concatenated", "word_count",
         "resolved_text_from", "resolved_how", "back_reference_kind",
         "back_reference_target",
         "back_reference_raw", "page", "text"])

    write_csv(dest / "topics.csv", [{
        **t, "path": " > ".join(t["path"]),
        "situation_terms": "|".join(t["situation_terms"]),
        "refs": "|".join(t["refs"]),
    } for t in out["topics"]],
        ["id", "chapter_n", "chapter_title", "facet", "level", "topic", "subtopic",
         "path", "n_citations", "situation_terms", "refs", "page"])

    write_csv(dest / "chapters.csv", out["chapters"],
              ["id", "chapter_n", "roman", "title", "facet", "n_topics",
               "n_citations", "page"])

    (dest / "COVERAGE.md").write_text(coverage(out, acct, n_lines), "utf-8")


def coverage(out: dict, acct: Accounting, n_lines: int) -> str:
    cits = out["citations"]
    ts = Counter(c["text_source"] for c in cits)
    facets = Counter(c["facet"] for c in cits)
    summary = acct.summary()
    unacc = acct.unaccounted()
    L = [
        "# Watters 1883 — extraction coverage", "",
        f"Generated {date.today().isoformat()} by `prayer.extract.watters`. "
        "Do not edit by hand.", "",
        "## Line accounting", "",
        "Every line of the source is assigned to a record or to an explicit",
        "structural bucket. The build fails if any line is left over — that check",
        "is what caught the 249 citations written as back-references rather than",
        "as `**Ref** — text`.", "",
        f"- source lines: **{n_lines}**",
        f"- unaccounted: **{len(unacc)}**"
        + (f" — lines {[i + 1 for i in unacc[:20]]}" if unacc else " ✓"), "",
        "| bucket | lines |", "| --- | --- |",
    ]
    L += [f"| {k} | {v} |" for k, v in summary.most_common()]
    L += [
        "", "## Records", "", "| file | records |", "| --- | --- |",
        f"| `citations.jsonl` | {len(cits)} |",
        f"| `topics.jsonl` | {len(out['topics'])} |",
        f"| `chapters.jsonl` | {len(out['chapters'])} |",
        f"| `passages.jsonl` | {len(out['passages'])} |",
        f"| `cross_references.jsonl` | {len(out['cross_references'])} |",
        f"| `toc.jsonl` | {len(out['toc'])} |",
        f"| `front_matter.jsonl` | {len(out['front_matter'])} |",
        f"| `back_matter.jsonl` | {len(out['back_matter'])} |",
        f"| `editorial_notes.jsonl` | {len(out['editorial_notes'])} |",
        f"| `body_prose.jsonl` | {len(out['body_prose'])} |",
        "", "## Citation text", "", "| source | n |", "| --- | --- |",
    ]
    L += [f"| {k} | {v} |" for k, v in ts.most_common()]
    L += [
        "", f"- references parsed: {sum(c['n_refs'] for c in cits)} across "
        f"{len({r['book'] for c in cits for r in c['refs'] if r.get('book')})} books",
        f"- citations bundling several references under one text blob: "
        f"{sum(1 for c in cits if c['text_is_concatenated'])} "
        "(`text_is_concatenated`; cannot be split per reference without a full "
        "KJV corpus)",
        f"- back-references resolved to an inline quotation elsewhere: "
        f"{sum(1 for c in cits if c['resolved_text_from'])}",
        f"- citations left with a reference but no text: {ts.get('unresolved', 0)}",
        "", "## Chapters — every chapter carries its own facet", "",
        "`chapter_n` and `chapter_title` are preserved verbatim on every record.",
        "`facet` is a derived convenience for querying and can be revised without",
        "losing anything.", "",
        "| ch | title | facet | topics | citations |", "| --- | --- | --- | --- | --- |",
    ]
    L += [f"| {c['roman']} | {c['title']} | `{c['facet']}` | {c['n_topics']} "
          f"| {c['n_citations']} |" for c in out["chapters"]]
    L += ["", "## Citations per facet", "", "| facet | n |", "| --- | --- |"]
    L += [f"| {k} | {v} |" for k, v in facets.most_common()]
    if out["problems"]:
        L += ["", "## Parse problems", ""]
        L += [f"- {p}" for p in out["problems"]]
    L += [
        "", "## Notes", "",
        "- The same passage recurs under many topics **by design** — that is the",
        "  labelling signal, not duplication. `passages.jsonl` inverts it.",
        "- `passages.jsonl` carries `text` only where a single-reference citation",
        "  quoted that passage exactly; `text_is_exact` says which.",
        "- `cross_references.jsonl` holds the topic-to-topic edges the author drew",
        "  by hand, from both back-referenced citations and bare \"see X\" pointers.",
        "", "## Licensing", "",
        "**Public domain** (1883). The only source in this repo whose text and",
        "taxonomy may be redistributed and shipped in a product.", "",
        f"> {SOURCE['citation']}", "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--allow-unaccounted", type=int, default=0,
                    help="tolerate up to N unaccounted source lines")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    text = args.src.read_text(encoding="utf-8")
    try:
        out, acct = extract(text)
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    n_lines = len(text.split("\n"))
    unacc = acct.unaccounted()

    if len(unacc) > args.allow_unaccounted:
        print(f"FAILED: {len(unacc)} unaccounted source lines "
              f"(limit {args.allow_unaccounted}); nothing written", file=sys.stderr)
        for i in unacc[:20]:
            print(f"  line {i + 1}: {text.splitlines()[i][:110]!r}", file=sys.stderr)
        return 1

    write_outputs(out, acct, n_lines, args.out)
    if not args.quiet:
        ts = Counter(c["text_source"] for c in out["citations"])
        print(f"wrote {len(out['citations'])} citations to {args.out}")
        print(f"  lines     {n_lines} accounted, {len(unacc)} unaccounted")
        print(f"  taxonomy  {len(out['chapters'])} chapters, "
              f"{len(out['topics'])} topics, {len(out['passages'])} passages")
        print(f"  text      {dict(ts.most_common())}")
        print(f"  xrefs     {len(out['cross_references'])} topic edges")
        print(f"  other     {len(out['toc'])} toc, "
              f"{len(out['editorial_notes'])} notes, "
              f"{len(out['body_prose'])} prose")
        print(f"  problems  {len(out['problems'])} — see {args.out}/COVERAGE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
