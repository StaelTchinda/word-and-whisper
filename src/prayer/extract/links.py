#!/usr/bin/env python3
"""Align records across sources by scripture-range overlap.

Usage:
    python -m prayer.extract.links [--datasets DIR] [--quiet]

Writes data/build/datasets/links/:

    prayer_links.jsonl   one row per overlapping pair of records
    prayer_links.csv     flat view
    COVERAGE.md          generated report: what linked, what did not, and why

Titles are useless for this — the books name the same prayer completely
differently ("Hannah Prays for a Son" / "Prayer for a Son" / "Mothers").
Scripture ranges are the only reliable join, and they must be compared as
*intervals*: Lockyer works at chapter level where Parks is verse-precise, and
Watters cites the same passage under many topics at once.
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path

from prayer import paths

DEFAULT_DATASETS = paths.DATASETS

# Ranking from most to least informative; a pair keeps its strongest relation.
RELATION_RANK = {"exact": 0, "contains": 1, "within": 2, "overlaps": 3}

SOURCES = [
    {"key": "parks2021", "file": "sources/parks2021/prayers.jsonl",
     "unit": "prayer", "title": lambda r: r["title"]},
    {"key": "lockyer1959", "file": "sources/lockyer1959/entries.jsonl",
     "unit": "prayer", "title": lambda r: r["title"],
     "keep": lambda r: r["entry_type"] == "prayer"},
    {"key": "watters1883", "file": "sources/watters1883/citations.jsonl",
     "unit": "citation",
     "title": lambda r: " > ".join(r["topic_path"]) or r["chapter_title"]},
]


def bounds(ref: dict) -> tuple[tuple[int, int], tuple[int, int]]:
    """Normalise a ref to a comparable (start, end) interval of (chapter, verse).

    A chapter-level ref (verse is None) spans the whole chapter, so it opens at
    verse 0 and closes at a sentinel beyond any real verse count.
    """
    s, e = ref["start"], ref["end"]
    lo = (s["chapter"], s["verse"] if s.get("verse") is not None else 0)
    hi = (e["chapter"], e["verse"] if e.get("verse") is not None else 10**6)
    return lo, hi


def relate(a: dict, b: dict) -> str | None:
    """How ref `b` relates to ref `a`, or None if they are disjoint."""
    if a["book"] != b["book"]:
        return None
    a_lo, a_hi = bounds(a)
    b_lo, b_hi = bounds(b)
    if a_hi < b_lo or b_hi < a_lo:
        return None
    if a_lo == b_lo and a_hi == b_hi:
        return "exact"
    if b_lo <= a_lo and a_hi <= b_hi:
        return "contains"       # b's range encloses a
    if a_lo <= b_lo and b_hi <= a_hi:
        return "within"
    return "overlaps"


def confidence(ref_b: dict, relation: str) -> str:
    """Verse-level agreement is trustworthy; whole-chapter containment is a hint."""
    if ref_b.get("role") == "see_also":
        # Matched only through a "see also" cross-reference, so the passage is
        # related to that entry rather than the subject of it.
        return "low"
    if ref_b.get("book_inferred"):
        # The book was inferred rather than printed; treat with suspicion.
        return "low"
    if relation == "exact":
        return "high"
    if ref_b.get("granularity") in ("chapter", "chapter_range"):
        return "medium"
    return "high" if relation in ("contains", "within") else "medium"


def load(datasets: Path) -> dict[str, list[dict]]:
    loaded = {}
    for spec in SOURCES:
        path = datasets / spec["file"]
        if not path.exists():
            print(f"FAILED: missing {path} — run the extractor first",
                  file=sys.stderr)
            raise SystemExit(1)
        rows = [json.loads(x) for x in
                path.read_text(encoding="utf-8").splitlines() if x]
        keep = spec.get("keep", lambda r: True)
        loaded[spec["key"]] = [{
            "id": r["id"], "title": spec["title"](r),
            "refs": [x for x in r["refs"] if x.get("osis")],
        } for r in rows if keep(r)]
    return loaded


def link_pair(a_key: str, a_rows: list[dict],
              b_key: str, b_rows: list[dict]) -> list[dict]:
    index: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for r in b_rows:
        for ref in r["refs"]:
            index[ref["book"]].append((r, ref))

    best: dict[tuple[str, str], dict] = {}
    for a in a_rows:
        for a_ref in a["refs"]:
            for b, b_ref in index.get(a_ref["book"], []):
                rel = relate(a_ref, b_ref)
                if rel is None:
                    continue
                key = (a["id"], b["id"])
                cand = {
                    "left_source": a_key, "left_id": a["id"], "left_title": a["title"],
                    "right_source": b_key, "right_id": b["id"], "right_title": b["title"],
                    "relation": rel, "confidence": confidence(b_ref, rel),
                    "left_ref": a_ref["osis"], "right_ref": b_ref["osis"],
                    "book": a_ref["book"],
                }
                prev = best.get(key)
                if prev is None or RELATION_RANK[rel] < RELATION_RANK[prev["relation"]]:
                    best[key] = cand
    return sorted(best.values(), key=lambda x: (x["left_id"], x["right_id"]))


def report(loaded: dict[str, list[dict]], links: list[dict]) -> str:
    L = [
        "# Cross-source links", "",
        f"Generated {date.today().isoformat()} by `prayer.extract.links`. "
        "Do not edit by hand.", "",
        "Records are joined on scripture-range overlap, never on title. "
        "`relation` reads from the right-hand record's side: `contains` means "
        "the right record's passage encloses the left one's.", "",
        "## Coverage per pair", "",
        "| pair | links | left matched | right matched |",
        "| --- | --- | --- | --- |",
    ]
    for a_key, b_key in combinations(loaded, 2):
        rel = [x for x in links
               if x["left_source"] == a_key and x["right_source"] == b_key]
        la, lb = len({x["left_id"] for x in rel}), len({x["right_id"] for x in rel})
        L.append(f"| {a_key} × {b_key} | {len(rel)} | {la}/{len(loaded[a_key])} "
                 f"| {lb}/{len(loaded[b_key])} |")
    L += ["", "## Relation", "", "| relation | n |", "| --- | --- |"]
    L += [f"| {k} | {v} |" for k, v in
          Counter(x["relation"] for x in links).most_common()]
    L += ["", "| confidence | n |", "| --- | --- |"]
    L += [f"| {k} | {v} |" for k, v in
          Counter(x["confidence"] for x in links).most_common()]

    linked_parks = {x["left_id"] for x in links if x["left_source"] == "parks2021"}
    unlinked = [r for r in loaded["parks2021"] if r["id"] not in linked_parks]
    L += [
        "", "## Notes", "",
        f"- {len(unlinked)} of {len(loaded['parks2021'])} Parks records reach "
        "neither other source. The deuterocanonical ones never can: both Lockyer "
        "and Watters work from the Protestant canon only.",
        "- Watters is a topical index, so its unit is a *citation*, not a prayer. "
        "One passage legitimately links to many Watters citations — that fan-out "
        "is the topic tagging, not duplication.",
        "- `confidence: low` marks a link found through a \"see also\" pointer or "
        "through a reference whose book had to be inferred. Filter these out when "
        "precision matters.",
        "", "## How to use this", "",
        "The three sources are complementary. Parks contributes structured labels "
        "with no text; Lockyer contributes exposition and hand-picked KJV "
        "quotations; Watters contributes a 754-topic index, full KJV text, and is "
        "the only one of the three in the public domain. Join here to get all "
        "three for the same passage.", "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--datasets", type=Path, default=DEFAULT_DATASETS)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    loaded = load(args.datasets)
    links = []
    for a_key, b_key in combinations(loaded, 2):
        links += link_pair(a_key, loaded[a_key], b_key, loaded[b_key])

    out = args.datasets / "links"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "prayer_links.jsonl").open("w", encoding="utf-8") as fh:
        for x in links:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    fields = ["left_source", "left_id", "left_title", "right_source", "right_id",
              "right_title", "relation", "confidence", "book", "left_ref", "right_ref"]
    with (out / "prayer_links.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(links)
    (out / "COVERAGE.md").write_text(report(loaded, links), "utf-8")

    if not args.quiet:
        print(f"wrote {len(links)} links to {out}")
        for a_key, b_key in combinations(loaded, 2):
            rel = [x for x in links
                   if x["left_source"] == a_key and x["right_source"] == b_key]
            la = len({x["left_id"] for x in rel})
            lb = len({x["right_id"] for x in rel})
            print(f"  {a_key:12} x {b_key:12} {len(rel):6} links  "
                  f"{la}/{len(loaded[a_key])} <-> {lb}/{len(loaded[b_key])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
