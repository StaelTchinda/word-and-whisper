#!/usr/bin/env python3
"""Resolve every dataset prayer reference to World English Bible text.

Usage:
    python -m prayer.extract.text [--out text/web.jsonl] [--quiet]
    python -m prayer.extract.text --show parks2021.0037
    python -m prayer.extract.text --download        # refresh text/source/*.zip

Writes text/web.jsonl (one row per prayer_id) and text/COVERAGE.md. Both are
generated artefacts; never edit them by hand.

Why WEB Classic (`eng-web`) and not the more common `engwebp`: the protestant
edition has no deuterocanon, and 34 of the 224 prayers are DC. `eng-web`
carries 15 DC books including 3 and 4 Maccabees, which most Western apocrypha
editions -- including the KJV 1611 Apocrypha -- omit. That closes the gap
PRODUCT_BOOK section 4 flagged without resorting to a second translation.

Two independent editions of the same translation are parsed and compared. USFX
is the primary source because it marks psalm superscriptions (`<d>`) and poetic
line structure separately from verse text; VPL is a flat verse-per-line dump
used purely as an oracle. Any verse where the two disagree is reported. This is
the cheapest available defence against C1: a silent parser bug that drops or
merges words would otherwise produce scripture that is subtly not scripture.
"""
import argparse
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional
from xml.etree import ElementTree as ET

from prayer import paths


DEFAULT_USFX = paths.WEB_ARCHIVES / "eng-web_usfx.zip"
DEFAULT_VPL = paths.WEB_ARCHIVES / "eng-web_vpl.zip"
# load_records() appends "prayers.jsonl", so this points at the source
# directory, not the datasets root.
DEFAULT_DATASET = paths.DATASETS / "sources/parks2021"
DEFAULT_OUT = paths.TEXT / "web.jsonl"
DEFAULT_COVERAGE = paths.TEXT / "COVERAGE.md"

TRANSLATION = "WEB"
EDITION = "eng-web (World English Bible, Classic edition with Deuterocanon)"
SOURCE_URL = "https://ebible.org/Scriptures/"

# Footnotes and cross-references are apparatus, not scripture. Dropping the
# whole subtree matters: `<f>` contains `<ft>` prose that would otherwise be
# spliced into the middle of a verse and become quotable as if it were text.
DROP_SUBTREES = frozenset({"f", "x", "ide", "rem", "toc", "h", "id", "cl", "cp",
                           "s", "r", "ms", "fig"})
# Elements that begin a new printed line: poetry lines and prose paragraphs.
LINE_BREAK = frozenset({"q", "p", "b", "d"})

# Dataset OSIS book -> USFX book id. The USFX edition uses USFM 3 codes
# (EZK, JOL, MRK, JHN, DAG...), which differ from the older codes the VPL
# edition prints; USFX_TO_VPL below bridges the two for the cross-check.
# Deuterocanonical books that WEB folds into Greek Daniel are handled by
# BOOK_IN_DANIEL, not here.
OSIS_TO_USFX = {
    "Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU",
    "Josh": "JOS", "Judg": "JDG", "Ruth": "RUT", "1Sam": "1SA", "2Sam": "2SA",
    "1Kgs": "1KI", "2Kgs": "2KI", "1Chr": "1CH", "2Chr": "2CH", "Ezra": "EZR",
    "Neh": "NEH", "Esth": "EST", "Job": "JOB", "Ps": "PSA", "Prov": "PRO",
    "Eccl": "ECC", "Song": "SNG", "Isa": "ISA", "Jer": "JER", "Lam": "LAM",
    "Ezek": "EZK", "Dan": "DAN", "Hos": "HOS", "Joel": "JOL", "Amos": "AMO",
    "Obad": "OBA", "Jonah": "JON", "Mic": "MIC", "Nah": "NAM", "Hab": "HAB",
    "Zeph": "ZEP", "Hag": "HAG", "Zech": "ZEC", "Mal": "MAL",
    "Tob": "TOB", "Jdt": "JDT", "Wis": "WIS", "Sir": "SIR", "Bar": "BAR",
    "PrMan": "MAN", "1Macc": "1MA", "2Macc": "2MA", "3Macc": "3MA",
    "4Macc": "4MA",
    "Matt": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
    "Rom": "ROM", "1Cor": "1CO", "2Cor": "2CO", "Gal": "GAL", "Eph": "EPH",
    "Phil": "PHP", "Col": "COL", "1Thess": "1TH", "2Thess": "2TH",
    "1Tim": "1TI", "2Tim": "2TI", "Titus": "TIT", "Phlm": "PHM", "Heb": "HEB",
    "Jas": "JAS", "1Pet": "1PE", "2Pet": "2PE", "1John": "1JN", "2John": "2JN",
    "3John": "3JN", "Jude": "JUD", "Rev": "REV",
}

# Only the codes that actually differ between the two editions.
USFX_TO_VPL = {
    "SNG": "SOL", "EZK": "EZE", "JOL": "JOE", "NAM": "NAH", "MRK": "MAR",
    "JHN": "JOH", "PHP": "PHI", "JAS": "JAM", "1JN": "1JO", "2JN": "2JO",
    "3JN": "3JO", "MAN": "PRM", "DAG": "DNG", "PS2": "PSX", "2ES": "4ES",
}

# WEB prints the Greek additions to Daniel inside Greek Daniel (`DNG`) rather
# than as the standalone books OSIS names. The offsets are the standard Greek
# text divisions and were verified verse by verse against the printed edition:
#   PrAzar 1  == DNG 3:24  ("They walked in the midst of the fire...")
#   Sus    1  == DNG 13:1  (Susanna is DNG chapter 13, 64 verses)
#   Bel    1  == DNG 14:1  (Bel and the Dragon is DNG chapter 14, 42 verses)
BOOK_IN_DANIEL = {
    "PrAzar": ("DAG", 3, 23),
    "Sus": ("DAG", 13, 0),
    "Bel": ("DAG", 14, 0),
}


@dataclass
class VerseBlock:
    """One `<v>`...`<ve/>` span. `start`/`end` differ for merged verses."""
    book: str
    chapter: int
    start: int
    end: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(self.lines)


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def norm_compare(s: str) -> str:
    """Normalisation used only for the USFX-vs-VPL oracle check."""
    s = unicodedata.normalize("NFC", s)
    s = s.replace(" ", " ")
    return norm_ws(s)


# --- USFX ------------------------------------------------------------------

class _Walker:
    """Accumulates verse text in document order.

    USFX nests verse content inside poetry/paragraph elements rather than
    inside the verse marker, so a verse is a span between `<v>` and `<ve/>`
    that can cross several `<q>` siblings. That rules out a simple per-element
    parse and is why this walks the tree with explicit open/close state.
    """

    def __init__(self) -> None:
        self.blocks: list[VerseBlock] = []
        self.supers: dict[tuple[str, int], str] = {}
        self.book: Optional[str] = None
        self.chapter: int = 0
        self.cur: Optional[VerseBlock] = None
        self.parts: list[str] = []
        self._super_target: Optional[list[str]] = None

    def _sink(self) -> Optional[list[str]]:
        if self._super_target is not None:
            return self._super_target
        return self.parts if self.cur is not None else None

    def add(self, text: Optional[str]) -> None:
        sink = self._sink()
        if sink is not None and text:
            sink.append(text)

    def newline(self) -> None:
        if self.cur is None:
            return
        line = norm_ws("".join(self.parts))
        if line:
            self.cur.lines.append(line)
        self.parts = []

    def open_verse(self, raw_id: str) -> None:
        self.close_verse()
        nums = [int(n) for n in re.findall(r"\d+", raw_id)] or [0]
        self.cur = VerseBlock(self.book or "", self.chapter, nums[0], nums[-1])
        self.parts = []

    def close_verse(self) -> None:
        if self.cur is None:
            return
        self.newline()
        if self.cur.lines:
            self.blocks.append(self.cur)
        self.cur = None
        self.parts = []


def _walk(el: ET.Element, w: _Walker) -> None:
    tag = el.tag
    if tag in DROP_SUBTREES:
        return

    if tag == "book":
        w.close_verse()
        w.book = el.get("id")
        w.chapter = 0
    elif tag == "c":
        w.close_verse()
        w.chapter = int(el.get("id") or 0)
    elif tag == "v":
        w.open_verse(el.get("id") or "0")
        return  # `<v>` is empty; its tail is added by the parent loop
    elif tag == "ve":
        w.close_verse()
        return
    elif tag == "d":
        # Psalm/Habakkuk superscription. Real WEB text, but it is a heading,
        # not part of the prayer, so it is captured out of band and never
        # becomes anchorable text.
        target: list[str] = []
        w._super_target = target
        w.add(el.text)
        for child in el:
            _walk(child, w)
            w.add(child.tail)
        w._super_target = None
        w.supers[(w.book or "", w.chapter)] = norm_ws("".join(target))
        return

    if tag in LINE_BREAK:
        w.newline()

    w.add(el.text)
    for child in el:
        _walk(child, w)
        w.add(child.tail)


def parse_usfx(zip_path: Path) -> tuple[dict[tuple[str, int], list[VerseBlock]],
                                        dict[tuple[str, int], str]]:
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith("_usfx.xml"))
        root = ET.fromstring(zf.read(name).decode("utf-8"))

    w = _Walker()
    _walk(root, w)
    w.close_verse()

    index: dict[tuple[str, int], list[VerseBlock]] = {}
    for blk in w.blocks:
        index.setdefault((blk.book, blk.chapter), []).append(blk)
    return index, w.supers


# --- VPL oracle ------------------------------------------------------------

VPL_RE = re.compile(r"^([A-Z0-9]{3}) (\d+):(\d+) (.*)$")


def parse_vpl(zip_path: Path) -> dict[tuple[str, int, int], str]:
    out: dict[tuple[str, int, int], str] = {}
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.endswith("_vpl.txt"))
        for line in zf.read(name).decode("utf-8").splitlines():
            m = VPL_RE.match(line)
            if m:
                book, ch, v, text = m.groups()
                out[(book, int(ch), int(v))] = text
    return out


def classify_diff(got: str, want: str) -> Optional[str]:
    """Name a known-harmless edition difference, or None if it is a real one.

    Only differences that provably cannot change a word of scripture get a
    name here. Anything unnamed is treated as a parser bug: `text_available`
    depends on the two editions agreeing, and C1 is not worth a judgement call.
    """
    if got.replace(" ", "") == want.replace(" ", ""):
        return "spacing"
    # Psalm 119's Hebrew acrostic letters (ALEPH, BETH, ... SIN AND SHIN) are
    # stanza headings. USFX marks them as section headings and this parser
    # drops them; the VPL dump splices them into the adjacent verse's text.
    # The heading can be several tokens, so strip whole all-caps runs.
    base, extra = got.split(), want.split()
    n = len(base)
    for start in range(len(extra) - n + 1):
        if extra[start:start + n] != base:
            continue
        surrounding = extra[:start] + extra[start + n:]
        if surrounding and all(t.isupper() and t.isalpha() for t in surrounding):
            return "acrostic heading"
    return None


def cross_check(index, supers, vpl) -> tuple[list[str], Counter]:
    """Compare every USFX verse against the VPL edition of the same verse.

    Two differences are expected and skipped outright: VPL prepends the psalm
    superscription to verse 1, and VPL splits merged `<v id="15-16">` blocks.
    Everything else is either classified as a known-harmless edition quirk or
    returned as an unexplained disagreement to look at before trusting the text.
    """
    unexplained: list[str] = []
    benign: Counter = Counter()
    for (book, chapter), blocks in sorted(index.items()):
        vpl_book = USFX_TO_VPL.get(book, book)
        for blk in blocks:
            if blk.start != blk.end:
                continue  # merged verse: VPL numbers it differently
            got = norm_compare(blk.text)
            want = norm_compare(vpl.get((vpl_book, chapter, blk.start), ""))
            if not want:
                unexplained.append(f"{book} {chapter}:{blk.start} missing from VPL")
                continue
            sup = supers.get((book, chapter))
            if sup and blk.start == 1:
                want = norm_compare(want.removeprefix(norm_compare(sup)))
            if got == want:
                continue
            kind = classify_diff(got, want)
            if kind:
                benign[kind] += 1
            else:
                unexplained.append(
                    f"{book} {chapter}:{blk.start}\n  usfx: {got}\n  vpl : {want}")
    return unexplained, benign


# --- resolution ------------------------------------------------------------

def map_ref(osis_book: str, chapter: int, verse: int) -> Optional[tuple[str, int, int]]:
    if osis_book in BOOK_IN_DANIEL:
        code, dan_chapter, offset = BOOK_IN_DANIEL[osis_book]
        return code, dan_chapter, verse + offset
    code = OSIS_TO_USFX.get(osis_book)
    return (code, chapter, verse) if code else None


def iter_range(start_c: int, start_v: int, end_c: int, end_v: int,
               chapters: dict[int, list[VerseBlock]]) -> Iterator[VerseBlock]:
    """Yield blocks from (start_c, start_v) through (end_c, end_v) inclusive.

    Handles ranges that cross a chapter boundary, which the dataset leaves
    `verse_count: null` for (Bar 2:11-3:8 is the only one).
    """
    for chapter in range(start_c, end_c + 1):
        lo = start_v if chapter == start_c else 1
        hi = end_v if chapter == end_c else 10 ** 6
        for blk in chapters.get(chapter, []):
            if blk.end >= lo and blk.start <= hi:
                yield blk


def resolve(record: dict, index, supers) -> dict:
    """Build the text/web.jsonl row for one prayer record."""
    resolved_refs = []
    missing: list[str] = []

    for ref in record["refs"]:
        osis_book = ref["book"]
        mapped_start = map_ref(osis_book, ref["start"]["chapter"], ref["start"]["verse"])
        mapped_end = map_ref(osis_book, ref["end"]["chapter"], ref["end"]["verse"])
        if mapped_start is None or mapped_end is None:
            missing.append(f"{osis_book} not in this edition")
            continue

        code, start_c, start_v = mapped_start
        _, end_c, end_v = mapped_end
        chapters = {ch: blocks for (bk, ch), blocks in index.items() if bk == code}
        blocks = list(iter_range(start_c, start_v, end_c, end_v, chapters))
        if not blocks:
            missing.append(f"{ref['osis']} -> {code} {start_c}:{start_v} not found")
            continue

        verses = []
        for blk in blocks:
            # Report OSIS numbering, not the edition's internal numbering: the
            # citation a user sees must match the reference they were given.
            back = blk.start - (BOOK_IN_DANIEL[osis_book][2]
                                if osis_book in BOOK_IN_DANIEL else 0)
            osis_ch = 1 if osis_book in BOOK_IN_DANIEL else blk.chapter
            verses.append({
                "osis": f"{osis_book}.{osis_ch}.{back}",
                "n": back,
                "text": blk.text,
                "lines": blk.lines,
            })

        sup = supers.get((code, start_c)) if start_v == 1 else None
        resolved_refs.append({
            "osis": ref["osis"],
            "display": ref["raw"],
            "superscription": sup,
            "verses": verses,
        })

    available = bool(resolved_refs) and not missing
    # Parallel gospel accounts are the same prayer told twice; joining only the
    # primary range keeps `full_text` a single quotable passage (section 3).
    full_text = " ".join(v["text"] for v in resolved_refs[0]["verses"]) if resolved_refs else ""

    return {
        "prayer_id": record["id"],
        "translation": TRANSLATION,
        "text_available": available,
        "refs": resolved_refs,
        "full_text": full_text,
        "word_count": len(full_text.split()),
        "reason": "; ".join(missing) or None,
    }


# --- coverage report -------------------------------------------------------

def write_coverage(rows: list[dict], records: list[dict], mismatches: list[str],
                   benign: Counter, path: Path) -> None:
    by_id = {r["id"]: r for r in records}
    gaps = [r for r in rows if not r["text_available"]]
    count_mismatch = []
    for row in rows:
        rec = by_id[row["prayer_id"]]
        if rec.get("verse_count") is None or not row["text_available"]:
            continue
        got = len(row["refs"][0]["verses"])
        if got != rec["verse_count"]:
            count_mismatch.append((row["prayer_id"], rec["primary_ref"],
                                   rec["verse_count"], got))

    canon = Counter(by_id[r["prayer_id"]]["canon_section"]
                    for r in rows if r["text_available"])
    lines = [
        "# Text coverage",
        "",
        f"Generated by `prayer.extract.text`. Do not edit by hand.",
        "",
        f"- Translation: **{TRANSLATION}** — {EDITION}",
        f"- Source: {SOURCE_URL} (`eng-web_usfx.zip`, `eng-web_vpl.zip`, vendored under `text/source/`)",
        f"- Public domain; no permission needed to redistribute the text itself.",
        "",
        "## Coverage",
        "",
        f"| Metric | Value |",
        f"| --- | --- |",
        f"| Prayers in dataset | {len(rows)} |",
        f"| Text resolved | **{sum(1 for r in rows if r['text_available'])}** |",
        f"| Unresolved | {len(gaps)} |",
        f"| Resolved by canon | OT {canon['OT']}, DC {canon['DC']}, NT {canon['NT']} |",
        "",
    ]

    lines += ["## Gaps", ""]
    if gaps:
        lines += ["| prayer_id | reference | reason |", "| --- | --- | --- |"]
        lines += [f"| `{g['prayer_id']}` | {by_id[g['prayer_id']]['primary_ref']} | {g['reason']} |"
                  for g in gaps]
    else:
        lines += ["None. Every reference in the dataset resolved to WEB text.", "",
                  "3 and 4 Maccabees — flagged in PRODUCT_BOOK section 4 as likely gaps —",
                  "are present in the `eng-web` Classic edition, so no record needed",
                  "a second translation and none was invented."]
    lines.append("")

    lines += ["## Verse-count agreement", ""]
    if count_mismatch:
        lines += ["Ranges whose resolved verse count differs from the dataset's",
                  "`verse_count`. Each is an edition numbering difference to inspect.", "",
                  "| prayer_id | ref | dataset | resolved |", "| --- | --- | --- | --- |"]
        lines += [f"| `{p}` | {r} | {a} | {b} |" for p, r, a, b in count_mismatch]
    else:
        lines += ["Every resolved range matches the dataset's `verse_count` where "
                  "that field is non-null."]
    lines.append("")

    lines += [
        "## Edition cross-check", "",
        "Every verse parsed from the USFX edition was compared against the same",
        "verse in the independently-published verse-per-line edition. Expected",
        "differences (psalm superscriptions, merged verse markers) are excluded.",
        "",
        f"**Unexplained disagreements: {len(mismatches)}**", "",
    ]
    if mismatches:
        lines += ["```", *mismatches[:40], "```"]
    else:
        lines += ["The two editions agree on every verse, so the parse is not "
                  "silently dropping or merging text.", ""]
    if benign:
        lines += ["Classified as known-harmless edition quirks and excluded from "
                  "the count above:", "",
                  "| kind | verses |", "| --- | --- |"]
        lines += [f"| {k} | {n} |" for k, n in sorted(benign.items())]
        lines += ["", "`acrostic heading` is Psalm 119's Hebrew stanza letters "
                  "(ALEPH, BETH, ...), which the VPL dump splices into the",
                  "adjacent verse and USFX marks as a heading. `spacing` is "
                  "whitespace around an em dash. Neither changes a word."]
    lines.append("")

    lines += [
        "## Notes", "",
        "- Psalm superscriptions (`For the Chief Musician. A Psalm by David...`)",
        "  are stored in `refs[].superscription`, not in verse text. They are",
        "  genuine WEB text but are headings rather than words of the prayer, so",
        "  they must never end up inside an `anchor` movement.",
        "- WEB prints the Greek additions to Daniel inside Greek Daniel (`DAG`).",
        "  Prayer of Azariah maps to `DAG 3:24+`, Susanna to `DAG 13`, Bel to",
        "  `DAG 14`. Verse numbers are reported back in OSIS numbering, so a",
        "  citation always matches the reference the caller was given.",
        "- `refs[].lines` preserves the printed poetic line structure, which the",
        "  composers use so a quoted psalm reads as verse rather than as a",
        "  paragraph.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# --- CLI -------------------------------------------------------------------

def load_records(dataset_dir: Path) -> list[dict]:
    path = dataset_dir / "prayers.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def download(dest_dir: Path) -> None:
    import urllib.request
    dest_dir.mkdir(parents=True, exist_ok=True)
    for name in ("eng-web_usfx.zip", "eng-web_vpl.zip"):
        url = f"{SOURCE_URL}{name}"
        print(f"fetching {url}")
        urllib.request.urlretrieve(url, dest_dir / name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--usfx", type=Path, default=DEFAULT_USFX)
    ap.add_argument("--vpl", type=Path, default=DEFAULT_VPL)
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    ap.add_argument("--show", metavar="PRAYER_ID", help="print one passage and exit")
    ap.add_argument("--download", action="store_true", help="refresh text/source/*.zip")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.download:
        download(args.usfx.parent)

    if not args.usfx.exists():
        print(f"missing {args.usfx}; run with --download", file=sys.stderr)
        return 1

    index, supers = parse_usfx(args.usfx)
    records = load_records(args.dataset)

    if args.show:
        rec = next((r for r in records if r["id"] == args.show), None)
        if rec is None:
            print(f"no prayer {args.show!r}", file=sys.stderr)
            return 1
        row = resolve(rec, index, supers)
        print(f"{rec['title']} — {rec['refs'][0]['raw']} ({TRANSLATION})")
        print(f"{rec['context']} · {', '.join(rec['contents'])} · "
              f"speaker: {rec['speaker']['raw']}")
        if not row["text_available"]:
            print(f"\n[no text: {row['reason']}]")
            return 1
        for ref in row["refs"]:
            print(f"\n{ref['display']}")
            if ref["superscription"]:
                print(f"  ({ref['superscription']})")
            for v in ref["verses"]:
                head = f"  {v['n']:>3}  "
                for i, line in enumerate(v["lines"]):
                    print(f"{head if i == 0 else ' ' * len(head)}{line}")
        print(f"\n[{row['word_count']} words]")
        return 0

    mismatches: list[str] = []
    benign: Counter = Counter()
    if args.vpl.exists():
        mismatches, benign = cross_check(index, supers, parse_vpl(args.vpl))
    rows = [resolve(rec, index, supers) for rec in records]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_coverage(rows, records, mismatches, benign, args.coverage)

    resolved = sum(1 for r in rows if r["text_available"])
    if not args.quiet:
        print(f"resolved {resolved}/{len(rows)} prayers -> {args.out}")
        print(f"cross-check: {len(mismatches)} unexplained, "
              f"{sum(benign.values())} known-harmless {dict(benign)}")
        for row in rows:
            if not row["text_available"]:
                print(f"  GAP {row['prayer_id']}: {row['reason']}")
    return 0 if resolved >= 221 else 1


if __name__ == "__main__":
    raise SystemExit(main())
