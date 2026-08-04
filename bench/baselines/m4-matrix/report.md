# Benchmark report

- Generated: 2026-08-04 11:39 UTC
- Query set: `data/build/bench/queries/tier1.jsonl` (Tier 1, n=224)
- k: 3
- abstain_threshold: 0.08
- psalm_penalty: 0.0

> **Tier 1 measures wiring, not product quality.** The queries are
> paraphrases of each record's own title, and real users do not
> describe their lives in the vocabulary of prayer titles. Treat
> these numbers as regression detection only. Product quality is
> Tier 3's job (M8), together with blind human ratings.

## Retrieval

| retriever | composer | R@1 | R@5 | R@10 | MRR | nDCG@10 | label-P@5 | psalm@5 | abstain |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bm25 | deterministic | 0.799 | 0.942 | 0.973 | 0.870 | 0.895 | 0.914 | 0.232 | 0.000 |
| dense | deterministic | 0.857 | 0.973 | 0.987 | 0.909 | 0.928 | 0.812 | 0.207 | 0.000 |
| hybrid | deterministic | 0.884 | 0.978 | 0.987 | 0.924 | 0.939 | 0.891 | 0.266 | 0.000 |

`psalm@5` reference line with no Psalm bias at all: **0.192** (43 of 224 records).

## Composition

| retriever | composer | n | anchor-verbatim | citation-valid | schema-valid | words 60-180 | fallback | explain-only | median words | reading grade |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bm25 | deterministic | 668 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 4 | 76 | 5.9 |
| dense | deterministic | 663 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 9 | 77 | 6.1 |
| hybrid | deterministic | 669 | 1.000 | 1.000 | 1.000 | 1.000 | 0.000 | 3 | 77 | 6.0 |

`anchor-verbatim` **must be 1.000**. Any other value is a C1 violation and a release blocker.

Grammar checking was not run (`--grammar` opt-in: it needs a JVM and a one-time download, and the harness must work offline).

## System

| retriever | composer | p50 ms | p95 ms | canon distribution @5 |
| --- | --- | --- | --- | --- |
| bm25 | deterministic | 2.4 | 5.8 | DC 157, NT 196, OT 767 |
| dense | deterministic | 13.0 | 26.4 | DC 158, NT 156, OT 806 |
| hybrid | deterministic | 13.8 | 23.4 | DC 149, NT 160, OT 811 |

## What is not measured here

No automatic metric in this report can judge whether a prayer is
*pastorally* right, which is the thing that actually matters. From
M8 that gap is covered by blind human 1-5 ratings on ~50 sampled
outputs for the finalist configurations. Until then, every number
above is a proxy.
