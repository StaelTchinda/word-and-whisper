#!/usr/bin/env python3
"""Generate the Tier 1 known-item query set from data/build/datasets.

    python3 bench/build_tier1.py

Query = a paraphrase of each record's own title and descriptor; the correct
answer is that record. n=224, free to build, fully deterministic.

READ THIS BEFORE QUOTING A TIER 1 NUMBER
----------------------------------------
Tier 1 measures whether retrieval is *wired up correctly*. It does not measure
whether the product is any good. A system can ace this and be useless, because
real users do not describe their circumstances in the vocabulary of prayer
titles -- they write "I got laid off", not "a prayer for provision by a
servant". Its job is regression detection between M3 and M8, and nothing else.

The paraphrasing below deliberately degrades the query away from the indexed
document: verbs are swapped for synonyms, the speaker's name is dropped from
half the queries, and label *definitions* replace label names. Without that,
the query would be close to a copy of the document and the numbers would mean
even less than they already do.
"""
import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from prayer import paths


DEFAULT_DATASET = paths.DATASETS / "sources/parks2021"
DEFAULT_OUT = paths.BENCH / "queries/tier1.jsonl"

# Title verb -> a phrasing a person might plausibly reach for instead.
VERB_SWAPS = [
    (r"\bPrays for\b", "is asking for"),
    (r"\bPrays Against\b", "is asking God to deal with"),
    (r"\bPrays to\b", "is speaking to"),
    (r"\bPrays\b", "is praying"),
    (r"\bPraises God for\b", "is thanking God for"),
    (r"\bPraises\b", "is praising"),
    (r"\bBlesses\b", "is blessing"),
    (r"\bThanks\b", "is thanking"),
    (r"\bConfesses\b", "is admitting"),
    (r"\bLaments?\b", "is grieving over"),
    (r"\bRepents? for\b", "is turning away from"),
    (r"\bAsks?\b", "is asking"),
    (r"\bIntercedes? for\b", "is pleading for"),
    (r"\bMakes? an Oath\b", "is swearing an oath"),
    (r"\bComplains? About\b", "is complaining about"),
]

DROP_SPEAKER_RE = None  # built per record


def paraphrase(record: dict, content_defs: dict[str, str],
               context_defs: dict[str, str]) -> str:
    title = record["title"]
    for pattern, replacement in VERB_SWAPS:
        title = re.sub(pattern, replacement, title)

    # Drop the speaker's name from half the queries, chosen by a hash of the
    # id so the split is stable across runs.
    digest = hashlib.sha256(record["id"].encode()).digest()[0]
    speaker = record["speaker"]["raw"]
    if digest % 2 == 0 and speaker and speaker.lower() not in ("god",):
        title = title.replace(speaker, "someone")
        for agent in record["speaker"]["agents"]:
            title = title.replace(agent, "someone")

    parts = [title.lower().rstrip(".")]

    # Label definitions rather than label names: the definitions are indexed
    # too, but as prose they overlap the query far less than the bare labels.
    defs = [content_defs.get(c, "") for c in record["contents"]]
    defs = [d.lower().rstrip(".") for d in defs if d]
    if defs:
        parts.append("; ".join(defs))

    context_def = context_defs.get(record["context"], "")
    if context_def:
        parts.append(context_def.lower().rstrip("."))

    return ". ".join(parts) + "."


def load_defs(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["id"]: row["definition"] for row in csv.DictReader(fh)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    records = [json.loads(line) for line in
               (args.dataset / "prayers.jsonl").read_text(encoding="utf-8").splitlines()
               if line.strip()]
    content_defs = load_defs(args.dataset / "vocab/contents.csv")
    context_defs = load_defs(args.dataset / "vocab/contexts.csv")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for record in records:
            row = {
                "query_id": f"t1.{record['id'].split('.')[-1]}",
                "tier": 1,
                "situation": paraphrase(record, content_defs, context_defs),
                # Binary relevance: exactly one record is correct.
                "relevance": {record["id"]: 2},
                "gold": record["id"],
            }
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    print(f"wrote {len(records)} Tier 1 queries -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
