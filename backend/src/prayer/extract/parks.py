#!/usr/bin/env python3
"""Extract the Jimmy Parks prayer annotations into a structured dataset.

Usage:
    python -m prayer.extract.parks [--src FILE] [--out DIR] [--quiet]

Reads the cleaned markdown and writes data/build/datasets/sources/parks2021/:

    prayers.jsonl        one JSON record per prayer (canonical form)
    prayers.csv          flat view; list fields joined with "|"
    prayer_contents.csv  long form, one row per (prayer, content label)
    prayer_refs.csv      long form, one row per (prayer, scripture range)
    vocab/*.csv          controlled vocabularies, incl. the source's own
                         definitions for every context and content label
    sources.csv          provenance for the source work
    README.md            generated dataset card

Parsing is strict: anything the grammar does not recognise is collected and
reported, and the script exits 1 rather than writing a partial dataset.
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

DEFAULT_SRC = paths.SOURCE_FILES["parks2021"]
DEFAULT_OUT = paths.DATASETS / "sources/parks2021"

SOURCE = {
    "source_id": "parks2021",
    "title": "All the Prayers in the Bible",
    "author": "Jimmy Parks",
    "publisher": "Faithlife, LLC",
    "publisher_place": "Bellingham, WA",
    "year": "2021",
    "series": "Faithlife Biblical and Theological Lists",
    "citation": ("Jimmy Parks, All the Prayers in the Bible, Faithlife Biblical and "
                 "Theological Lists (Bellingham, WA: Faithlife, 2020)."),
    "derived_from": ("Evans, Eli T., and Jimmy Parks. Speaking to God. "
                     "Faithlife LLC, Bellingham, WA, 2016."),
    "license": "proprietary, (c) Faithlife LLC",
    "has_prayer_text": "false",
}

# --- grammar ---------------------------------------------------------------

# "*Ge 32:9-12 records a [solitary](#solitary) prayer by Jacob to God. The
#   prayer was in Canaan, the fords of the Jordan, and Jordan.*"
DESCRIPTOR_RE = re.compile(
    r"^\*(?P<refs>.+?) records an? \[(?P<context>[a-z]+)\]\(#[a-z0-9-]+\) "
    r"prayer by (?P<speaker>.+?) to (?P<addressee>.+?)\.(?P<tail>.*)\*$"
)
PLACE_RE = re.compile(r"^The prayer was in (?P<places>.+)\.$")
CONTENT_RE = re.compile(r"^\*\*Content:\*\* (?P<labels>.+)$", re.M)
LABEL_RE = re.compile(r"\[([^\]]+)\]\(#[a-z0-9-]+\)")
VOCAB_RE = re.compile(r"^- \*\*(?P<label>[A-Za-z]+)\*\*: (?P<definition>.+)$", re.M)

CANON_SECTIONS = {
    "Old Testament": "OT",
    "Deuterocanon/Apocrypha": "DC",
    "New Testament": "NT",
}

# Speakers/addressees that denote a group rather than one person. Curated
# rather than inferred: "the Israelites" is a group, "the servant of Abraham"
# is not, and no surface rule separates them reliably.
GROUP_AGENTS = frozenset({
    "Disciples", "Ephraimites", "Jerusalem",
    "People", "Priests", "Soldiers", "the 24 Elders", "the Israelites",
    "the Jews", "the Kingdom of Israel", "the Kingdom of Judah", "the Levites",
    "the church at Rome", "the followers of Judas Maccabeus",
    "the four living creatures", "the inhabitants of Jerusalem",
    "the judaizers in Jerusalem", "the multitude", "the priests of Israel",
    "the prophets of Baal", "the remnant in Israel", "the sailors",
})
DEITY_AGENTS = frozenset({"God", "Jesus", "Baal"})


def agent_type(agent: str) -> str:
    if agent in DEITY_AGENTS:
        return "deity"
    return "group" if agent in GROUP_AGENTS else "individual"


def split_agents(raw: str) -> list[str]:
    """'the Israelites and Moses' -> ['the Israelites', 'Moses'].

    Safe for this source: no single agent name contains ' and '.
    """
    parts = re.split(r",\s*and\s+|\s+and\s+|,\s*", raw)
    return [p.strip() for p in parts if p.strip()]


# --- reference parsing -----------------------------------------------------

RANGE_RE = re.compile(
    r"^(?P<c1>\d+)(?::(?P<v1>\d+))?"
    r"(?:[-–](?:(?P<c2>\d+):)?(?P<v2>\d+))?$"
)


def parse_refs(raw: str) -> list[dict]:
    """Parse a descriptor's reference string into normalised ranges.

    Handles every form the source uses:
        Ge 32:9-12                          single range
        Bar 2:11-3:8                        crosses a chapter boundary
        Sus 42-43                           verse-only book (no chapter)
        Mt 26:39, Mk 14:36, and Lk 22:42    several passages, several books
    """
    segments = [s for s in re.split(r",\s*and\s+|\s+and\s+|,\s*", raw) if s.strip()]
    refs = []
    for seg in segments:
        abbr, rest = split_book(seg)
        book = lookup(abbr)
        m = RANGE_RE.match(rest)
        if not m:
            raise ValueError(f"unparseable range {rest!r} in {raw!r}")

        if m["v1"] is None:
            # No colon: the source numbers this work by verse alone. OSIS
            # still addresses it with an explicit chapter 1.
            verse_only = True
            c1, v1 = 1, int(m["c1"])
            c2, v2 = 1, int(m["v2"]) if m["v2"] else v1
            if m["c2"]:
                raise ValueError(f"chapter range on verse-only book: {seg!r}")
        else:
            verse_only = False
            c1, v1 = int(m["c1"]), int(m["v1"])
            v2 = int(m["v2"]) if m["v2"] else v1
            c2 = int(m["c2"]) if m["c2"] else c1

        if book.chapters and max(c1, c2) > book.chapters:
            raise ValueError(f"chapter out of range for {book.name}: {seg!r}")
        if (c2, v2) < (c1, v1):
            raise ValueError(f"range runs backwards: {seg!r}")

        start = f"{book.osis}.{c1}.{v1}"
        end = f"{book.osis}.{c2}.{v2}"
        refs.append({
            "osis": start if start == end else f"{start}-{end}",
            "book": book.osis,
            "book_raw": abbr,
            "book_name": book.name,
            "canon": book.canon,
            "start": {"chapter": c1, "verse": v1},
            "end": {"chapter": c2, "verse": v2},
            "verse_only": verse_only,
            "raw": seg,
        })
    return refs


def count_verses(refs: list[dict]) -> int | None:
    """Verses spanned by the primary reference, or None when it crosses a
    chapter boundary (we carry no versification table, so the span is unknown).

    Deliberately the primary range only, not a sum: where a record cites several
    ranges they are parallel accounts of one prayer (Mt 26:39, Mk 14:36, Lk
    22:42), so adding them up would triple-count the same words.
    """
    primary = refs[0]
    if primary["start"]["chapter"] != primary["end"]["chapter"]:
        return None
    return primary["end"]["verse"] - primary["start"]["verse"] + 1


# --- document parsing ------------------------------------------------------

def parse_vocab(text: str, heading: str) -> list[dict]:
    """Pull the source's own label definitions out of the Introduction."""
    start = text.find(heading)
    if start < 0:
        raise ValueError(f"source is missing its Introduction: no {heading!r}")
    block = text[start:text.index("\n\n", text.index("\n\n", start) + 1)]
    return [{"id": m["label"].lower(),
             "label": m["label"],
             "definition": m["definition"].replace("“", '"').replace("”", '"')}
            for m in VOCAB_RE.finditer(block)]


def parse_entries(text: str) -> tuple[list[dict], list[str]]:
    lines = text.split("\n")
    records, problems, seen_slugs = [], [], {}
    canon = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("## "):
            canon = CANON_SECTIONS.get(line[3:].strip())
            i += 1
            continue
        if not (line.startswith("### ") and canon):
            i += 1
            continue

        title = line[4:].strip()
        heading_line = i + 1  # 1-indexed, for provenance
        block, i = [], i + 1
        while i < len(lines) and not lines[i].startswith(("### ", "## ")):
            block.append(lines[i])
            i += 1
        body = "\n".join(block)

        descriptor = next((l for l in block if DESCRIPTOR_RE.match(l)), None)
        if descriptor is None:
            problems.append(f"line {heading_line}: no descriptor under {title!r}")
            continue
        m = DESCRIPTOR_RE.match(descriptor)

        try:
            refs = parse_refs(m["refs"])
        except (ValueError, KeyError) as exc:
            problems.append(f"line {heading_line}: {exc}")
            continue

        tail = m["tail"].strip()
        places = []
        if tail:
            pm = PLACE_RE.match(tail)
            if not pm:
                problems.append(f"line {heading_line}: unrecognised tail {tail!r}")
                continue
            places = [p.strip() for p in
                      re.split(r",\s*and\s+|\s+and\s+|,\s*", pm["places"]) if p.strip()]

        cm = CONTENT_RE.search(body)
        if not cm:
            problems.append(f"line {heading_line}: no Content line under {title!r}")
            continue
        contents = [c.lower() for c in LABEL_RE.findall(cm["labels"])]

        related = []
        rel = re.search(r"^\*\*Related:\*\*\n((?:- .+\n?)+)", body, re.M)
        if rel:
            related = [r[2:].strip() for r in rel.group(1).strip().split("\n")]

        speaker_raw, addressee_raw = m["speaker"], m["addressee"]
        speakers = split_agents(speaker_raw)
        addressees = split_agents(addressee_raw)

        records.append({
            "id": None,  # assigned after the full pass, in document order
            "source_id": SOURCE["source_id"],
            "title": title,
            "slug": github_slug(title, seen_slugs),
            "canon_section": canon,
            "refs": refs,
            "primary_ref": refs[0]["osis"],
            "verse_count": count_verses(refs),
            "speaker": {
                "raw": speaker_raw,
                "agents": speakers,
                "collective": any(agent_type(a) == "group" for a in speakers),
            },
            "addressee": {"raw": addressee_raw, "agents": addressees},
            "context": m["context"],
            "contents": contents,
            "places": places,
            "related_pericopes": related,
            "provenance": {"source_line": heading_line, "descriptor_raw": descriptor},
        })

    width = len(str(len(records)))
    for n, rec in enumerate(records, 1):
        rec["id"] = f"{SOURCE['source_id']}.{n:0{max(width, 4)}d}"
    return records, problems


# --- output ----------------------------------------------------------------

def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def write_outputs(records: list[dict], contexts: list[dict], contents: list[dict],
                  out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    with (out / "prayers.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    flat_fields = ["id", "source_id", "title", "slug", "canon_section", "primary_ref",
                   "refs_osis", "refs_raw", "book", "n_refs", "verse_count", "speaker_raw",
                   "speaker_agents", "speaker_collective", "addressee_raw",
                   "addressee_agents", "context", "contents", "n_contents", "places",
                   "related_pericopes", "source_line"]
    write_csv(out / "prayers.csv", [{
        "id": r["id"], "source_id": r["source_id"], "title": r["title"],
        "slug": r["slug"], "canon_section": r["canon_section"],
        "primary_ref": r["primary_ref"],
        "refs_osis": "|".join(x["osis"] for x in r["refs"]),
        "refs_raw": "|".join(x["raw"] for x in r["refs"]),
        "book": "|".join(dict.fromkeys(x["book"] for x in r["refs"])),
        "n_refs": len(r["refs"]),
        "verse_count": r["verse_count"] if r["verse_count"] is not None else "",
        "speaker_raw": r["speaker"]["raw"],
        "speaker_agents": "|".join(r["speaker"]["agents"]),
        "speaker_collective": str(r["speaker"]["collective"]).lower(),
        "addressee_raw": r["addressee"]["raw"],
        "addressee_agents": "|".join(r["addressee"]["agents"]),
        "context": r["context"], "contents": "|".join(r["contents"]),
        "n_contents": len(r["contents"]), "places": "|".join(r["places"]),
        "related_pericopes": "|".join(r["related_pericopes"]),
        "source_line": r["provenance"]["source_line"],
    } for r in records], flat_fields)

    write_csv(out / "prayer_contents.csv",
              [{"prayer_id": r["id"], "content": c} for r in records for c in r["contents"]],
              ["prayer_id", "content"])

    write_csv(out / "prayer_refs.csv", [{
        "prayer_id": r["id"], "seq": n, "osis": x["osis"], "book": x["book"],
        "book_name": x["book_name"], "canon": x["canon"],
        "start_chapter": x["start"]["chapter"], "start_verse": x["start"]["verse"],
        "end_chapter": x["end"]["chapter"], "end_verse": x["end"]["verse"],
        "verse_only": str(x["verse_only"]).lower(), "raw": x["raw"],
    } for r in records for n, x in enumerate(r["refs"], 1)],
        ["prayer_id", "seq", "osis", "book", "book_name", "canon", "start_chapter",
         "start_verse", "end_chapter", "end_verse", "verse_only", "raw"])

    ctx_n = Counter(r["context"] for r in records)
    cnt_n = Counter(c for r in records for c in r["contents"])
    write_csv(out / "vocab/contexts.csv",
              [dict(v, n_prayers=ctx_n.get(v["id"], 0)) for v in contexts],
              ["id", "label", "definition", "n_prayers"])
    write_csv(out / "vocab/contents.csv",
              [dict(v, n_prayers=cnt_n.get(v["id"], 0)) for v in contents],
              ["id", "label", "definition", "n_prayers"])

    as_speaker = Counter(a for r in records for a in r["speaker"]["agents"])
    as_addressee = Counter(a for r in records for a in r["addressee"]["agents"])
    write_csv(out / "vocab/agents.csv", [{
        "agent": a, "type": agent_type(a),
        "n_as_speaker": as_speaker.get(a, 0), "n_as_addressee": as_addressee.get(a, 0),
    } for a in sorted(set(as_speaker) | set(as_addressee))],
        ["agent", "type", "n_as_speaker", "n_as_addressee"])

    books = {}
    for r in records:
        for x in r["refs"]:
            books.setdefault(x["book"], {"osis": x["book"], "book_name": x["book_name"],
                                         "logos_abbr": x["book_raw"], "canon": x["canon"],
                                         "n_prayers": 0})["n_prayers"] += 1
    write_csv(out / "vocab/books.csv", list(books.values()),
              ["osis", "book_name", "logos_abbr", "canon", "n_prayers"])

    write_csv(out / "sources.csv", [dict(SOURCE, n_prayers=len(records))],
              list(SOURCE) + ["n_prayers"])

    (out / "README.md").write_text(dataset_card(records, contexts, contents), "utf-8")


def dataset_card(records, contexts, contents) -> str:
    canon_n = Counter(r["canon_section"] for r in records)
    ctx_n = Counter(r["context"] for r in records)
    cnt_n = Counter(c for r in records for c in r["contents"])
    multi = sum(1 for r in records if len(r["contents"]) > 1)
    lines = [
        "# Bible Prayer Dataset - v1", "",
        f"Generated {date.today().isoformat()} by `prayer.extract.parks`. "
        "Do not edit by hand; re-run the extractor.", "",
        f"**{len(records)} prayers** from *{SOURCE['title']}* by {SOURCE['author']} "
        f"({SOURCE['publisher']}, {SOURCE['year']}).", "",
        "## Important: no prayer text", "",
        "This source is an annotation layer only - it records *where* each prayer is",
        "and how it is classified, not the words of the prayer. To get the text,",
        "join `prayer_refs.csv` against a Bible corpus on the OSIS reference. Keep",
        "any such text under `text/`, separate from these files: translation licensing",
        "differs sharply, and the deuterocanonical prayers need a translation that",
        "includes 3-4 Maccabees, Susanna, Bel, and the Prayer of Manasseh.", "",
        "## Files", "",
        "| File | Rows | Contents |", "| --- | --- | --- |",
        f"| `prayers.jsonl` | {len(records)} | canonical records, one JSON object per prayer |",
        f"| `prayers.csv` | {len(records)} | flat view; list fields joined with `\\|` |",
        f"| `prayer_contents.csv` | {sum(len(r['contents']) for r in records)} | long form for multi-label work |",
        f"| `prayer_refs.csv` | {sum(len(r['refs']) for r in records)} | one row per scripture range |",
        "| `vocab/*.csv` | - | contexts, contents, agents, books |",
        "| `sources.csv` | 1 | provenance and licensing |", "",
        "## Distribution", "",
        "Canon section: " + ", ".join(f"{k} {v}" for k, v in canon_n.most_common()), "",
        "### Context (single-label)", "",
        "| label | n | definition |", "| --- | --- | --- |",
    ]
    lines += [f"| {v['label']} | {ctx_n.get(v['id'], 0)} | {v['definition']} |" for v in contexts]
    lines += ["", "### Content (multi-label)", "",
              f"{multi} of {len(records)} prayers carry more than one content label.", "",
              "| label | n | definition |", "| --- | --- | --- |"]
    lines += [f"| {v['label']} | {cnt_n.get(v['id'], 0)} | {v['definition']} |" for v in contents]
    lines += [
        "", "## Notes on the data", "",
        "- `id` is source-scoped. `primary_ref` is the intended join key across sources:",
        "  other works annotate many of the same prayers, and OSIS overlap is how you",
        "  cluster them.",
        "- Titles are not unique (\"The Psalmist Prays for Deliverance\" appears twice);",
        "  `slug` disambiguates the way the source's own table of contents does.",
        "- Every normalised field keeps its `raw` form alongside it. Agent splitting is a",
        "  judgment call, so it stays auditable and re-derivable.",
        "- `verse_count` covers the primary range only, and is empty where that range",
        "  crosses a chapter boundary. Records with `n_refs` > 1 are parallel accounts of",
        "  one prayer (Mt 26:39 / Mk 14:36 / Lk 22:42), so their ranges must not be summed.",
        "- `related_pericopes` are Logos pericope titles, not references. Treat them as a",
        "  weak link, not a citation.", "",
        "## Licensing", "",
        f"The annotations are {SOURCE['license']}. Fine for personal analysis and",
        "derived work; settle the rights question before redistributing them.", "",
        f"> {SOURCE['citation']}", "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    text = args.src.read_text(encoding="utf-8")
    try:
        contexts = parse_vocab(text, "Prayer Context include the following:")
        contents = parse_vocab(text, "Prayer Content include the following:")
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    records, problems = parse_entries(text)

    expected = text.count("**Content:**")
    if len(records) != expected:
        problems.append(f"parsed {len(records)} records but found {expected} Content lines")
    unknown = {c for r in records for c in r["contents"]} - {v["id"] for v in contents}
    if unknown:
        problems.append(f"content labels missing from the vocabulary: {sorted(unknown)}")
    unknown_ctx = {r["context"] for r in records} - {v["id"] for v in contexts}
    if unknown_ctx:
        problems.append(f"contexts missing from the vocabulary: {sorted(unknown_ctx)}")

    if problems:
        print(f"FAILED: {len(problems)} problem(s); nothing written", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    write_outputs(records, contexts, contents, args.out)
    if not args.quiet:
        ctx_n = Counter(r["context"] for r in records)
        cnt_n = Counter(c for r in records for c in r["contents"])
        print(f"wrote {len(records)} prayers to {args.out}")
        print(f"  refs      {sum(len(r['refs']) for r in records)} ranges across "
              f"{len({x['book'] for r in records for x in r['refs']})} books")
        print(f"  canon     {dict(Counter(r['canon_section'] for r in records))}")
        print(f"  context   {dict(ctx_n.most_common())}")
        print(f"  content   {dict(cnt_n.most_common())}")
        print(f"  places    {sum(1 for r in records if r['places'])} prayers located")
        print(f"  related   {sum(1 for r in records if r['related_pericopes'])} prayers linked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
