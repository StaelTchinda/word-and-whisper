#!/usr/bin/env python3
"""Metric definitions — PRODUCT_BOOK section 9.

Split from prayer.bench/run.py so the metric definitions can be read and argued with
on their own. Retrieval metrics take graded relevance (Tier 3 uses 2/1/0), so
the same code serves Tier 1's binary case without a second implementation.
"""
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Optional


# --- retrieval --------------------------------------------------------------

def recall_at_k(ranked: list[str], relevance: dict[str, int], k: int) -> float:
    """Fraction of relevant records retrieved in the top k.

    For Tier 1 there is exactly one relevant record, so this is 1.0 or 0.0 and
    reads as "did we find it".
    """
    relevant = {pid for pid, grade in relevance.items() if grade > 0}
    if not relevant:
        return 0.0
    return len(relevant & set(ranked[:k])) / len(relevant)


def reciprocal_rank(ranked: list[str], relevance: dict[str, int]) -> float:
    for i, pid in enumerate(ranked, start=1):
        if relevance.get(pid, 0) > 0:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], relevance: dict[str, int], k: int) -> float:
    """Graded nDCG with the standard 2^rel - 1 gain."""
    def dcg(grades: Iterable[int]) -> float:
        return sum((2 ** g - 1) / math.log2(i + 1)
                   for i, g in enumerate(grades, start=1))

    actual = dcg(relevance.get(pid, 0) for pid in ranked[:k])
    ideal = dcg(sorted(relevance.values(), reverse=True)[:k])
    return actual / ideal if ideal else 0.0


def label_precision_at_k(ranked: list[str], gold_contents: set[str],
                         contents_by_id: dict[str, list[str]], k: int) -> float:
    """Fraction of the top k sharing at least one content label with the gold.

    A softer signal than recall: a retriever that misses the exact record but
    returns prayers of the same kind is doing something useful, and this is
    the only automatic metric that notices.
    """
    top = ranked[:k]
    if not top or not gold_contents:
        return 0.0
    hits = sum(1 for pid in top if gold_contents & set(contents_by_id.get(pid, [])))
    return hits / len(top)


def psalm_share_at_k(ranked: list[str], is_psalm, k: int) -> float:
    """43 of 224 records are Psalms and dominate top-k without correction.

    Baseline for reference: 43/224 = 0.192 is the share you would expect from
    a retriever with no Psalm bias at all.
    """
    top = ranked[:k]
    if not top:
        return 0.0
    return sum(1 for pid in top if is_psalm(pid)) / len(top)


# --- composition ------------------------------------------------------------

@dataclass
class CompositionStats:
    n: int = 0
    anchor_verbatim: int = 0
    citation_valid: int = 0
    schema_valid: int = 0
    words_in_range: int = 0
    fallback_used: int = 0
    explain_only: int = 0
    retries: int = 0
    word_counts: list[int] = field(default_factory=list)
    reading_grade: list[float] = field(default_factory=list)
    grammar_errors: list[int] = field(default_factory=list)

    def rate(self, attr: str) -> Optional[float]:
        return getattr(self, attr) / self.n if self.n else None


# --- system -----------------------------------------------------------------

def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * p))
    return ordered[index]


@dataclass
class RunSummary:
    retriever: str
    composer: str
    n_queries: int = 0
    recall_1: float = 0.0
    recall_5: float = 0.0
    recall_10: float = 0.0
    mrr: float = 0.0
    ndcg_10: float = 0.0
    label_precision_5: float = 0.0
    psalm_share_5: float = 0.0
    canon: Counter = field(default_factory=Counter)
    abstained: int = 0
    latency_ms: list[float] = field(default_factory=list)
    composition: CompositionStats = field(default_factory=CompositionStats)

    @property
    def p50(self) -> float:
        return statistics.median(self.latency_ms) if self.latency_ms else 0.0

    @property
    def p95(self) -> float:
        return percentile(self.latency_ms, 0.95)

    @property
    def abstention_rate(self) -> float:
        return self.abstained / self.n_queries if self.n_queries else 0.0
