#!/usr/bin/env python3
"""The Retriever seam (PRODUCT_BOOK section 5.3).

A retriever sees an AnalyzedSituation and the corpus, and returns scored
Candidates. It never resolves text and never composes -- that keeps the two
pluggable axes genuinely independent.

Scores must be comparable across retrievers, because `abstain_threshold` is a
single number in config.yaml. Every implementation therefore normalises to
roughly [0, 1]; `normalise` below is the shared helper.
"""
from typing import Protocol, runtime_checkable

from prayer.api.models import AnalyzedSituation, Candidate, Filters


@runtime_checkable
class Retriever(Protocol):
    name: str

    def retrieve(self, q: AnalyzedSituation, k: int,
                 filters: Filters) -> list[Candidate]: ...


def saturate(score: float, pivot: float) -> float:
    """Map an unbounded non-negative score into [0, 1) as score / (score + pivot).

    Must not be relative to the best score in the result set: dividing by the
    top hit would force the best candidate to 1.0 for every query, including
    queries the corpus has nothing for, and `abstain_threshold` would never
    fire. Saturation keeps the absolute information that abstention needs
    (C4) while putting BM25 and cosine on one comparable scale.

    `pivot` is the score at which a retriever considers a match middling, so it
    is a property of the scoring function and is set by each implementation.
    """
    if score <= 0:
        return 0.0
    return score / (score + pivot)
