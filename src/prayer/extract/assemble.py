#!/usr/bin/env python3
"""Assemble cleaned chapter files into the single canonical clean/<book>.md.

Usage: python -m prayer.extract.assemble <book_dir>

Expects <book_dir>/work/assemble.json:
{
  "slug": "output filename stem",
  "title": "...", "author": "...", "year": "...",
  "source_note": "one-line provenance of the scan",
  "toc_depth": 3,              # include headings up to this level in the TOC
  "front": ["work/chapters/00_front.md"],   # files placed BEFORE the TOC
  "chapters": ["work/chapters/ch_01.md", ...]  # files placed AFTER the TOC
}

Also checks page-marker continuity: every `<!-- p. N ... -->` must increase by 1.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
PAGE_RE = re.compile(r"<!--\s*p\.\s*(\d+)")


def github_slug(text: str, seen: dict) -> str:
    slug = text.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    if slug in seen:
        seen[slug] += 1
        slug = f"{slug}-{seen[slug]}"
    else:
        seen[slug] = 0
    return slug


def main(book_dir: str):
    book = Path(book_dir)
    cfg = json.loads((book / "work" / "assemble.json").read_text())

    front_parts = [Path(book, f).read_text().strip() for f in cfg.get("front", [])]
    chapter_parts = [Path(book, f).read_text().strip() for f in cfg["chapters"]]

    # Build TOC from chapter headings (## and deeper, up to toc_depth)
    seen: dict = {}
    toc_lines = []
    for part in chapter_parts:
        in_code = False
        for line in part.splitlines():
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            m = HEADING_RE.match(line)
            if not m:
                continue
            level, text = len(m.group(1)), m.group(2)
            plain = re.sub(r"<!--.*?-->", "", text)
            plain = re.sub(r"[*_`]", "", plain).strip()
            anchor = github_slug(plain, seen)
            if 2 <= level <= cfg.get("toc_depth", 3):
                indent = "  " * (level - 2)
                toc_lines.append(f"{indent}- [{plain}](#{anchor})")

    header = f"""<!--
  {cfg["title"]} — {cfg["author"]} ({cfg["year"]})
  Source: {cfg["source_note"]}
  Converted: {date.today().isoformat()} (OCR + LLM cleanup)
  STATUS: OCR-cleaned draft — page-by-page verification against the scans
  is still pending (see VERIFICATION.md). Spots the cleanup pass could not
  confidently repair are marked inline with `unverified` comments.
  Conventions: `<!-- p. N | ... -->` = start of print page N in the scan;
  `<!-- ref: ... -->` = normalized form of the scripture reference printed
  just before it.
-->

# {cfg["title"]}

*by {cfg["author"]}* ({cfg["year"]})
"""

    out = [header]
    out.extend(front_parts)
    out.append("---\n\n## Table of Contents\n\n" + "\n".join(toc_lines))
    out.extend(chapter_parts)
    text = "\n\n---\n\n".join(p for p in out if p) + "\n"

    # page-marker continuity check
    pages = [int(n) for n in PAGE_RE.findall(text)]
    gaps = [
        (a, b) for a, b in zip(pages, pages[1:]) if b != a + 1
    ]
    out_path = book / "clean" / f"{cfg['slug']}.md"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(text)
    print(f"Wrote {out_path} ({len(text.splitlines())} lines, {len(pages)} page markers)")
    if gaps:
        print(f"WARNING: {len(gaps)} page-marker discontinuities:")
        for a, b in gaps:
            print(f"  p. {a} -> p. {b}")
    else:
        print("Page markers continuous.")


if __name__ == "__main__":
    main(sys.argv[1])
