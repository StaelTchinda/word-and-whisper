# Prayer Suggestion API

Takes a described life situation and returns biblical prayers with instructions
and, for each, **a ready-to-speak prayer** — first-person words to say aloud now.

Runs fully offline. Scripture is never paraphrased.

Specification: [docs/PRODUCT_BOOK.md](docs/PRODUCT_BOOK.md). Everything below
follows it; section references point back to it.

## Status

| Milestone | State |
| --- | --- |
| M0 skeleton | done |
| M1 text layer | done — 224/224 references resolved |
| M2 R1 + deterministic composer + safety gate | done |
| M3 benchmark harness + Tier 1 | done |
| M4 R2 dense + R3 hybrid | done |
| M5–M9 | not started — **M5 is blocked on an open decision** (see below) |

183 tests pass. `data/build/bench/results/m4-matrix/report.md` is the current
report; `.../m2-baseline/report.md` is the M2 baseline every later change is
compared against.

## Quick start

The source books are copyrighted and are **not** in this repository. Point
`PRAYER_DATA_URL` at an archive of `data/input/` to fetch them.

```bash
python3 -m venv venv && make install
```

```bash
make fetch PRAYER_DATA_URL=https://example.com/prayer-input.tar.gz
```

```bash
make setup
```

`make setup` builds the datasets, resolves the WEB text, downloads the encoder
and precomputes the vectors. It needs the network once; nothing does afterwards.

```bash
make serve
```

```bash
curl -s localhost:8000/suggest -H 'content-type: application/json' -d '{"situation":"I have been trying for a child for four years and I am losing hope.","k":3,"retriever":"hybrid"}'
```

## Layout

Organised by lifecycle, not by topic.

```
src/prayer/       all the code, one installable package
  paths.py        every on-disk location, in one place
  refs/           printed references -> OSIS ranges
  extract/        the dataset build — stdlib only, about a second end to end
  api/            the service; api/build/ holds the index and golden builders
  bench/          the evaluation harness
policy/           reviewable YAML: situation lexicon, compose policy,
                  safety terms, phrase bank
configs/base.yaml runtime config; PRAYER_* env vars override it
deploy/           Dockerfile and .dockerignore
data/             nothing here is in version control
  input/          downloaded — cleaned source markdown (copyrighted books)
  scans/          downloaded — the original PDFs
  vendor/         downloaded — ONNX encoder, WEB archives
  build/          generated — datasets, text, index, bench, fixtures
```

**One rule: if a command can regenerate it, it lives in `data/build/`.** That
makes `make clean && make setup` a safe, complete reset. Nothing under `data/`
is edited by hand and nothing under it is committed.

## Results so far

Tier 1, n=224, deterministic composer:

| retriever | R@1 | R@5 | MRR | nDCG@10 | psalm@5 | retrieval p95 |
| --- | --- | --- | --- | --- | --- | --- |
| bm25 | 0.799 | 0.942 | 0.870 | 0.895 | 0.232 | 2 ms |
| dense | 0.857 | 0.973 | 0.909 | 0.928 | 0.207 | 17 ms |
| **hybrid** | **0.884** | **0.978** | **0.924** | **0.939** | 0.266 | 20 ms |

anchor-verbatim and citation-valid are **1.000** for every configuration. They
have to be: anything else is a C1 violation and a release blocker.

**These are not product-quality numbers.** Tier 1 queries are paraphrases of
each record's own title, and nobody describes their life in the vocabulary of
prayer titles. The numbers detect regressions and nothing more. Real quality
needs the Tier 3 gold set (M8) and blind human ratings.

`psalm@5` against a 0.192 no-bias line shows the Psalm skew the product book
predicted, mildly present in all three and worst in hybrid. `psalm_penalty` is
the knob; it stays at 0 until M8 tunes it on Tier 3 **dev**.

## The text layer

`data/build/text/COVERAGE.md` is the audit trail. Summary:

- **224/224 references resolved.** WEB Classic (`eng-web`) carries 15 DC books
  including 3 and 4 Maccabees, so the gap section 4 flagged did not
  materialise and nothing was invented to fill one.
- Two independently published editions of WEB (USFX and verse-per-line) are
  parsed and compared verse by verse. **0 unexplained disagreements**; 23
  classified as known-harmless (22 Psalm 119 acrostic headings, 1 spacing).
- Psalm superscriptions are stored out of band so they can never end up inside
  an `anchor`.

Note: the product book's worked example quotes 1 Sam 1:11 as "look **on** the
affliction". The real WEB text reads "look **at**". That is the exact hazard C1
exists for, and there is a test asserting the real reading.

## Open decisions — these block further work

From section 11. I have not guessed at any of them.

1. **Local model choice and size (M5+).** *This blocks M5.* The whole runtime
   is in place — `LocalLM` protocol, `llm/null.py`, lazy loading, fallback on
   every failure path — but which model to load is a quality/latency/RAM
   trade-off that should be measured on your hardware. Say the word and I will
   benchmark two or three candidates and recommend one.
2. **Sign-off on `policy/compose_policy.yaml`.** Proposed, with reasoning
   per entry: `exclude` the prophets of Baal; `explain_only` the proud
   Pharisee, Antiochus IV, and Jdg 21:18; the six composable imprecatory
   records stay `compose` under the section 7.3 ask rule. `sign_off: pending`.
3. **Crisis-notice wording and locale.** `policy/safety_terms.yaml`
   contains a **placeholder** with no phone number and no organisation name,
   because the product book forbids the agent inventing crisis-line details.
   The gate itself works and is tested. `sign_off: pending`, and the service
   logs a warning at startup while it stays that way. **Do not expose this to
   real users until you have written that text.**
4. **Whether the deterministic composer is publicly selectable.** Currently
   `selectable=False`, so it is the internal fallback only. One word to change.
5. **WEB text redistribution.** WEB is public domain and ebible.org states it is
   redistributable; the archives are vendored under `data/vendor/web/`. Nothing
   under `data/` is committed, so this only matters if you later ship the text
   in an image or a release.

## Tests

```bash
make test
```

The suite that matters most is `tests/test_invariants.py`: it is parametrized
over every registered composer, so a new composer is held to anchor-verbatim,
word bounds, movement completeness, no-scripture-outside-anchor and the
imprecation policy simply by existing. `tests/test_contract.py` registers a
retriever and composer from a test module and drives them end to end — that is
the executable definition of the modularity requirement.

## Licence

The code in this repository is MIT licensed (see `LICENSE`).

**The source books are not.** *All the Prayers in the Bible* (Jimmy Parks,
© Faithlife 2021) and *All the Prayers of the Bible* (Herbert Lockyer,
© Zondervan 1959) are under copyright and are not distributed here — neither the
cleaned markdown nor the datasets built from them. `make fetch` pulls them from
wherever you host your own copies. *The Prayers of the Bible* (Philip Watters,
1883) is public domain.

The World English Bible text used for passages is public domain.
