#!/usr/bin/env python3
"""R3: reciprocal rank fusion of R1 and R2 (PRODUCT_BOOK M4).

RRF rather than a weighted score blend, because BM25 and cosine scores are not
on a common scale and any blend weight would be a number tuned on Tier 1 --
which the PRODUCT_BOOK is explicit does not measure product quality. RRF uses
only the ranks, so it needs no calibration and cannot be overfitted to a
metric that does not matter.

    rrf(d) = sum over retrievers of 1 / (K + rank(d))

K=60 is the constant from the original Cormack et al. formulation; it damps
the difference between rank 1 and rank 2 so a single retriever's confident
mistake cannot dominate.
"""
from typing import Optional

from prayer.api import registry
from prayer.api.models import AnalyzedSituation, Candidate, Filters

RRF_K = 60

# The fused score is a sum of small reciprocals with no natural upper bound,
# so it is rescaled against the best score achievable by this fusion (both
# retrievers ranking a record first). That keeps `abstain_threshold`
# comparable across R1, R2 and R3.
MAX_RRF = 2.0 / (RRF_K + 1)


@registry.register("retriever", "hybrid",
                   description="Reciprocal rank fusion of bm25 and dense.")
class HybridRetriever:
    def __init__(self, corpus, settings=None):
        from prayer.api.retrievers.bm25 import BM25Retriever
        from prayer.api.retrievers.dense import DenseRetriever

        self.corpus = corpus
        self.settings = settings
        self.lexical = BM25Retriever(corpus, settings)
        self.semantic = DenseRetriever(corpus, settings)

    @property
    def pool(self) -> int:
        return getattr(self.settings, "candidate_pool", 25) if self.settings else 25

    def retrieve(self, q: AnalyzedSituation, k: int, filters: Filters) -> list[Candidate]:
        # Fuse over a deeper pool than k: a record that BM25 puts at rank 12
        # and the encoder puts at rank 3 is exactly what fusion is for, and it
        # is invisible if both lists are truncated at k.
        depth = max(self.pool, k * 5)
        lexical = self.lexical.retrieve(q, depth, filters)
        semantic = self.semantic.retrieve(q, depth, filters)

        fused: dict[str, float] = {}
        reasons: dict[str, list[str]] = {}
        sources: dict[str, list[str]] = {}

        for label, results in (("bm25", lexical), ("dense", semantic)):
            for rank, candidate in enumerate(results, start=1):
                pid = candidate.prayer_id
                fused[pid] = fused.get(pid, 0.0) + 1.0 / (RRF_K + rank)
                sources.setdefault(pid, []).append(label)
                for reason in candidate.matched_on:
                    bucket = reasons.setdefault(pid, [])
                    if reason not in bucket and reason != "semantic similarity":
                        bucket.append(reason)

        # Sort by fused score, then by id so ties are stable across runs.
        ordered = sorted(fused.items(), key=lambda kv: (-kv[1], kv[0]))
        out: list[Candidate] = []
        for pid, score in ordered[:k]:
            matched = reasons.get(pid, [])[:5]
            # Agreement between two independent retrievers is itself a
            # human-readable reason, and the most useful one for debugging.
            if len(sources.get(pid, [])) > 1:
                matched = matched[:4] + ["both retrievers agree"]
            elif not matched:
                matched = ["semantic similarity"]
            out.append(Candidate(prayer_id=pid,
                                 score=round(min(1.0, score / MAX_RRF), 4),
                                 matched_on=matched))
        return out
