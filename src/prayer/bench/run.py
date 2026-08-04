#!/usr/bin/env python3
"""Benchmark runner — PRODUCT_BOOK sections 8 (M3) and 9.

    python3 bench/run.py                          # all registered components
    python3 bench/run.py --retrievers bm25 --composers deterministic
    python3 bench/run.py --queries bench/queries/tier3_dev.jsonl

Runs a retriever x composer matrix and writes bench/results/<ts>/report.md
plus raw.jsonl. Components are discovered from the registry, never from a
list in this file -- adding a retriever must make it benchmarkable without
touching the harness.
"""
import argparse
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


from prayer.api import registry
from prayer.api.config import get_settings
from prayer.api.corpus import load_corpus
from prayer.api.models import SuggestRequest, SuggestResponse
from prayer.api.pipeline import Pipeline
from prayer.bench import metrics as M

from prayer import paths

DEFAULT_QUERIES = paths.BENCH / "queries/tier1.jsonl"
RESULTS = paths.BENCH / "results"

# 43 of 224 records are Psalms; this is the no-bias reference line for
# psalm_share@5.
PSALM_BASELINE = 43 / 224


def load_queries(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def evaluate(pipe: Pipeline, corpus, queries: list[dict], retriever: str,
             composer: str, k: int, grammar: bool) -> tuple[M.RunSummary, list[dict]]:
    summary = M.RunSummary(retriever=retriever, composer=composer,
                           n_queries=len(queries))
    contents_by_id = {r.id: r.contents for r in corpus.records}
    raw: list[dict] = []

    for query in queries:
        relevance = query.get("relevance", {})
        started = time.perf_counter()
        response = pipe.suggest(SuggestRequest(
            situation=query["situation"], k=k, retriever=retriever,
            composer=composer))
        elapsed_ms = (time.perf_counter() - started) * 1000
        summary.latency_ms.append(elapsed_ms)

        # Rank over the full candidate pool, not just the k returned: recall@10
        # is meaningless if the pipeline only ever emits 3 suggestions.
        ranked = rank_only(pipe, corpus, query["situation"], retriever)

        summary.recall_1 += M.recall_at_k(ranked, relevance, 1)
        summary.recall_5 += M.recall_at_k(ranked, relevance, 5)
        summary.recall_10 += M.recall_at_k(ranked, relevance, 10)
        summary.mrr += M.reciprocal_rank(ranked, relevance)
        summary.ndcg_10 += M.ndcg_at_k(ranked, relevance, 10)

        gold = query.get("gold")
        gold_contents = set(contents_by_id.get(gold, [])) if gold else set()
        summary.label_precision_5 += M.label_precision_at_k(
            ranked, gold_contents, contents_by_id, 5)
        summary.psalm_share_5 += M.psalm_share_at_k(ranked, corpus.is_psalm, 5)

        for pid in ranked[:5]:
            record = corpus.record(pid)
            if record:
                summary.canon[record.canon_section] += 1

        if response.abstained:
            summary.abstained += 1

        score_composition(summary.composition, response, corpus, grammar)
        raw.append({
            "query_id": query.get("query_id"),
            "gold": gold,
            "top10": ranked[:10],
            "abstained": response.abstained,
            "latency_ms": round(elapsed_ms, 2),
            "suggestions": [
                {"prayer_id": s.prayer_id,
                 "score": s.match.score,
                 "matched_on": s.match.matched_on,
                 "composer": s.provenance.composer,
                 "fallback_used": s.provenance.fallback_used,
                 "word_count": s.spoken_prayer.word_count if s.spoken_prayer else None}
                for s in response.suggestions
            ],
        })

    n = max(1, summary.n_queries)
    for attr in ("recall_1", "recall_5", "recall_10", "mrr", "ndcg_10",
                 "label_precision_5", "psalm_share_5"):
        setattr(summary, attr, getattr(summary, attr) / n)
    return summary, raw


def rank_only(pipe: Pipeline, corpus, situation: str, retriever: str) -> list[str]:
    """The retriever's own ranking, unfiltered by composition success."""
    from prayer.api.models import Filters
    q = pipe.analyzer.analyze(situation)
    candidates = pipe.retriever(retriever).retrieve(q, 25, Filters())
    return [c.prayer_id for c in candidates]


def score_composition(stats: M.CompositionStats, response: SuggestResponse,
                      corpus, grammar: bool) -> None:
    import textstat

    for suggestion in response.suggestions:
        if suggestion.spoken_prayer is None:
            stats.explain_only += 1
            continue

        stats.n += 1
        passage = corpus.passage(suggestion.prayer_id)
        anchors = [m for m in suggestion.spoken_prayer.movements if m.kind == "anchor"]

        if anchors and anchors[0].text in passage.full_text:
            stats.anchor_verbatim += 1
        valid_osis = {v.osis for ref in passage.refs for v in ref.verses}
        if anchors and anchors[0].verbatim_from in valid_osis:
            stats.citation_valid += 1

        try:
            type(response).model_validate(response.model_dump())
            stats.schema_valid += 1
        except Exception:
            pass

        n_words = suggestion.spoken_prayer.word_count
        stats.word_counts.append(n_words)
        if 60 <= n_words <= 180:
            stats.words_in_range += 1
        if suggestion.provenance.fallback_used:
            stats.fallback_used += 1
        stats.retries += suggestion.provenance.retry_count

        stats.reading_grade.append(
            textstat.flesch_kincaid_grade(suggestion.spoken_prayer.text))

        if grammar:
            stats.grammar_errors.append(count_grammar_errors(
                suggestion.spoken_prayer.text))


_TOOL = None


def count_grammar_errors(text: str) -> int:
    """language_tool_python needs a JVM and a one-time download.

    Off by default: the harness must run offline and in CI without either.
    """
    global _TOOL
    if _TOOL is None:
        import language_tool_python
        _TOOL = language_tool_python.LanguageTool("en-US")
    return len(_TOOL.check(text))


# --- reporting --------------------------------------------------------------

def fmt(value, spec="{:.3f}") -> str:
    return "—" if value is None else spec.format(value)


def write_report(summaries: list[M.RunSummary], queries_path: Path, k: int,
                 grammar: bool, out_dir: Path, settings) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    tier = "1" if "tier1" in queries_path.name else queries_path.stem

    lines = [
        f"# Benchmark report",
        "",
        f"- Generated: {stamp}",
        f"- Query set: `{queries_path.relative_to(paths.ROOT)}` (Tier {tier}, "
        f"n={summaries[0].n_queries if summaries else 0})",
        f"- k: {k}",
        f"- abstain_threshold: {settings.abstain_threshold}",
        f"- psalm_penalty: {settings.psalm_penalty}",
        "",
    ]

    if tier == "1":
        lines += [
            "> **Tier 1 measures wiring, not product quality.** The queries are",
            "> paraphrases of each record's own title, and real users do not",
            "> describe their lives in the vocabulary of prayer titles. Treat",
            "> these numbers as regression detection only. Product quality is",
            "> Tier 3's job (M8), together with blind human ratings.",
            "",
        ]

    lines += ["## Retrieval", "",
              "| retriever | composer | R@1 | R@5 | R@10 | MRR | nDCG@10 | "
              "label-P@5 | psalm@5 | abstain |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in summaries:
        lines.append(
            f"| {s.retriever} | {s.composer} | {fmt(s.recall_1)} | {fmt(s.recall_5)} | "
            f"{fmt(s.recall_10)} | {fmt(s.mrr)} | {fmt(s.ndcg_10)} | "
            f"{fmt(s.label_precision_5)} | {fmt(s.psalm_share_5)} | "
            f"{fmt(s.abstention_rate)} |")
    lines += ["",
              f"`psalm@5` reference line with no Psalm bias at all: "
              f"**{PSALM_BASELINE:.3f}** (43 of 224 records).", ""]

    lines += ["## Composition", "",
              "| retriever | composer | n | anchor-verbatim | citation-valid | "
              "schema-valid | words 60-180 | fallback | explain-only | median words | "
              "reading grade |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in summaries:
        c = s.composition
        median_words = statistics.median(c.word_counts) if c.word_counts else None
        grade = statistics.median(c.reading_grade) if c.reading_grade else None
        lines.append(
            f"| {s.retriever} | {s.composer} | {c.n} | {fmt(c.rate('anchor_verbatim'))} | "
            f"{fmt(c.rate('citation_valid'))} | {fmt(c.rate('schema_valid'))} | "
            f"{fmt(c.rate('words_in_range'))} | {fmt(c.rate('fallback_used'))} | "
            f"{c.explain_only} | {fmt(median_words, '{:.0f}')} | {fmt(grade, '{:.1f}')} |")
    lines += ["",
              "`anchor-verbatim` **must be 1.000**. Any other value is a C1 "
              "violation and a release blocker.", ""]

    if grammar:
        lines += ["| retriever | composer | median grammar errors |",
                  "| --- | --- | --- |"]
        for s in summaries:
            errs = s.composition.grammar_errors
            lines.append(f"| {s.retriever} | {s.composer} | "
                         f"{fmt(statistics.median(errs) if errs else None, '{:.1f}')} |")
        lines.append("")
    else:
        lines += ["Grammar checking was not run (`--grammar` opt-in: it needs a "
                  "JVM and a one-time download, and the harness must work "
                  "offline).", ""]

    lines += ["## System", "",
              "| retriever | composer | p50 ms | p95 ms | canon distribution @5 |",
              "| --- | --- | --- | --- | --- |"]
    for s in summaries:
        canon = ", ".join(f"{c} {n}" for c, n in sorted(s.canon.items()))
        lines.append(f"| {s.retriever} | {s.composer} | {s.p50:.1f} | {s.p95:.1f} | "
                     f"{canon} |")
    lines += ["",
              "## What is not measured here", "",
              "No automatic metric in this report can judge whether a prayer is",
              "*pastorally* right, which is the thing that actually matters. From",
              "M8 that gap is covered by blind human 1-5 ratings on ~50 sampled",
              "outputs for the finalist configurations. Until then, every number",
              "above is a proxy.",
              ""]

    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    ap.add_argument("--retrievers", nargs="*", default=None,
                    help="default: every registered selectable retriever")
    ap.add_argument("--composers", nargs="*", default=None,
                    help="default: every registered composer, fallback included")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--grammar", action="store_true",
                    help="run language_tool_python (needs a JVM)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    registry.load_builtins()
    settings = get_settings(reload=True)
    corpus = load_corpus(settings.dataset_dir, settings.text_dir,
                         settings.policy_dir, settings.translation)
    pipe = Pipeline(corpus, settings)

    # Discovered from the registry, not hardcoded: that is the M3 DoD.
    retrievers = args.retrievers or registry.available("retriever", selectable_only=True)
    composers = args.composers or [
        c for c in registry.available("composer", conformant_only=True)
        if c != "free" or settings.enable_free_composer]
    if not retrievers or not composers:
        print("nothing registered to benchmark", file=sys.stderr)
        return 1

    queries = load_queries(args.queries)
    out_dir = args.out or (RESULTS / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries, all_raw = [], []
    for retriever in retrievers:
        for composer in composers:
            print(f"running {retriever} x {composer} over {len(queries)} queries...")
            summary, raw = evaluate(pipe, corpus, queries, retriever, composer,
                                    args.k, args.grammar)
            summaries.append(summary)
            for row in raw:
                row |= {"retriever": retriever, "composer": composer}
            all_raw.extend(raw)
            print(f"  R@1={summary.recall_1:.3f} R@5={summary.recall_5:.3f} "
                  f"MRR={summary.mrr:.3f} p95={summary.p95:.0f}ms "
                  f"anchor-verbatim={fmt(summary.composition.rate('anchor_verbatim'))}")

    with (out_dir / "raw.jsonl").open("w", encoding="utf-8") as fh:
        for row in all_raw:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    write_report(summaries, args.queries, args.k, args.grammar, out_dir, settings)

    print(f"\nreport -> {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
