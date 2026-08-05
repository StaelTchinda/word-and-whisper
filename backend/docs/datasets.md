# The datasets

Structured prayer data extracted from published prayer reference works, plus a
cross-source alignment table. It all lives under `data/build/datasets/` and is
**generated** — never edit it by hand, and never commit it. Rebuild instead; the
whole thing takes about a second.

```
sources/
  parks2021/     All the Prayers in the Bible — Jimmy Parks (Faithlife, 2021)
  lockyer1959/   All the Prayers of the Bible — Herbert Lockyer (Zondervan, 1959)
  watters1883/   The Prayers of the Bible — Philip Watters (Phillips & Hunt, 1883)
links/           cross-source alignment by scripture-range overlap
```

## Rebuild

```bash
make data          # or: python -m prayer.extract
```

Each step is deterministic: same input, same bytes out.

## The three sources are complementary, not redundant

|  | parks2021 | lockyer1959 | watters1883 |
| --- | --- | --- | --- |
| Unit | prayer | prayer | **citation** (topic × passage) |
| Records | 224 | 344 + 66 book intros | 2,241 citations |
| Structured labels | context + 16 content labels, speaker, addressee, place | none | **754 topics in 30 chapters, 23 facets** |
| Scripture text | **none** — references only | 378 quotations | 1,990 inline quotations (KJV) |
| Commentary | none | ~59k words of exposition | none |
| Titles | descriptive | situation-shaped | topical |
| Canon | OT, deuterocanon, NT | Protestant only | Protestant only |
| **Licence** | proprietary | in copyright | **public domain** |

Parks contributes labels without text. Lockyer contributes exposition and
hand-picked quotations without labels. Watters contributes a hand-built topical
index with full KJV text, and is the only source that may be redistributed.

Watters is also the connective tissue: it overlaps both other sources more than
they overlap each other. See `links/COVERAGE.md` for the pairwise numbers.

**Watters' unit is a citation, not a prayer.** The same passage recurs under many
topics *by design* — that repetition is the labelling signal, not duplication.
`sources/watters1883/passages.jsonl` inverts it, grouping by OSIS reference.

Read each directory's generated report for exact counts, gaps, and caveats:
`data/build/datasets/sources/*/COVERAGE.md` and
`data/build/datasets/links/COVERAGE.md`.

## Nothing is dropped

`prayer/extract/watters.py` accounts for the source **line by line**: every line is
assigned to a record or to an explicit structural bucket, and the build fails if
any line is left over. That check is what caught 249 citations written as
`**Ref** *(as above under Affliction)*` rather than `**Ref** — text`, plus three
malformed source lines and a class of reference-inheritance errors. Its coverage
report carries the full accounting table.

Where the source cannot be resolved, the raw text is kept and flagged rather than
dropped: `refs[].unresolved`, `text_source: "unresolved"`, `book_inferred`.

## Conventions

- **`primary_ref` is the cross-source join key**, in OSIS form (`Gen.32.9-Gen.32.12`).
  `id` is source-scoped and is never comparable across sources.
- **Every normalised field keeps its `raw` form** alongside it, so any parsing
  judgment stays auditable and re-derivable.
- **`derived.*` fields are heuristic**, not authored by the source. Treat them as
  a convenience layer that may be regenerated with different rules.
- References are intervals, never strings: compare with the logic in
  `prayer/extract/links.py`, not with string equality. Lockyer works at chapter
  level where Parks is verse-precise.

## Consumers

`prayer.api.config` sets `dataset_dir` to a **single source directory**
(`data/build/datasets/sources/parks2021`), not to the datasets root. Anything
reading across sources should take `prayer.paths.DATASETS` and navigate down.

## Licensing — read before publishing anything

Only one of the three is public domain.

- **parks2021** — proprietary, © Faithlife LLC.
- **lockyer1959** — in copyright, © 1959 Zondervan. The `exposition` and `poetry`
  fields are protected expression, not fact. The `scripture_quotes` are KJV and
  are public domain.
- **watters1883** — **public domain.** Text and taxonomy may both be
  redistributed and shipped in a product.

The first two are fine for personal analysis and derived work; settle the rights
question before redistributing them or shipping a product that surfaces the
exposition. Watters carries no such restriction.

### Reading Lockyer's exposition/poetry in the `/sources` API and reader UI

`entries.jsonl` and `book_sections.jsonl` always carry the full `exposition`,
`poetry`, `outline` and `derived.application_sentences` fields — nothing is
lost at extraction. `prayer.api.sources` withholds them from the servable
`LockyerItemDetail`/`LockyerBookSection` models by default; set
`PRAYER_INCLUDE_COPYRIGHTED_TEXT=true` (see `.env.example`) to have the API
serve them and the reader UI render them instead of a "not reproduced here"
notice. This is fine for personal, local use; leave it off (the default) on
any deployment you don't fully control the audience of, per the licensing
note above. It never affects `q` search, which stays restricted to the
title/quote allowlist regardless.
