#!/usr/bin/env python3
"""R1: BM25 over a synthetic document per prayer (PRODUCT_BOOK M2).

Each record becomes one document built from its title, its context and content
labels, *the source's own definitions of those labels*, its speaker and
addressee, its places, and the resolved WEB passage text. Folding in the label
definitions is what gives a lexical retriever any chance on this corpus: a
record tagged `imprecation` carries no useful surface words, but the
definition "request for justice or vengeance to come down on another" shares
vocabulary with how a wronged person actually writes.

Fields are weighted by repeating their terms. It is the crudest possible field
weighting and it is the right one here: 224 documents, no training data, and a
weighting scheme a human can read off the FIELD_WEIGHTS table.
"""
import math
import re
from collections import Counter
from typing import Optional

from prayer.api import registry
from prayer.api.models import AnalyzedSituation, Candidate, Filters
from prayer.api.retrievers.base import saturate

WORD_RE = re.compile(r"[a-z']+")

# Repetition counts, not multipliers on a final score: BM25 saturates term
# frequency, so repeating a title term three times is meaningfully different
# from tripling the score, and behaves better for short fields.
FIELD_WEIGHTS = {
    "title": 3,
    "contents": 3,
    "content_defs": 2,
    "context": 2,
    "context_def": 1,
    "speaker": 2,
    "places": 1,
    "passage": 1,
}

K1 = 1.2
B = 0.75
# BM25 score at which a match is considered middling; see base.saturate.
# Calibrated against Tier 1 in M3 and re-checked against Tier 3 dev in M8.
PIVOT = 9.0


@registry.register("retriever", "bm25",
                   description="Lexical BM25 over title, labels, label "
                               "definitions, speaker and passage text.")
class BM25Retriever:
    def __init__(self, corpus, settings=None):
        self.corpus = corpus
        self.settings = settings
        self.stopwords = _stopwords(corpus)
        self._build()

    def _document(self, rec) -> list[str]:
        passage = self.corpus.passage(rec.id)
        fields = {
            "title": rec.title,
            "contents": " ".join(rec.contents),
            "content_defs": " ".join(self.corpus.content_defs.get(c, "")
                                     for c in rec.contents),
            "context": rec.context,
            "context_def": self.corpus.context_defs.get(rec.context, ""),
            "speaker": f"{rec.speaker.raw} {rec.addressee.raw}",
            "places": " ".join(rec.places),
            "passage": passage.full_text if passage else "",
        }
        terms: list[str] = []
        for field, text in fields.items():
            tokens = self._tokenise(text)
            terms.extend(tokens * FIELD_WEIGHTS[field])
        return terms

    def _tokenise(self, text: str) -> list[str]:
        return [w for w in WORD_RE.findall(text.lower())
                if w not in self.stopwords and len(w) > 2]

    def _build(self) -> None:
        self.ids: list[str] = []
        self.tfs: list[Counter] = []
        self.lengths: list[int] = []
        df: Counter = Counter()

        for rec in self.corpus.records:
            terms = self._document(rec)
            tf = Counter(terms)
            self.ids.append(rec.id)
            self.tfs.append(tf)
            self.lengths.append(len(terms))
            df.update(tf.keys())

        n = len(self.ids)
        self.avgdl = (sum(self.lengths) / n) if n else 0.0
        # BM25+ style idf floor: with 224 documents a term in half of them
        # would otherwise go negative and actively push relevant records down.
        self.idf = {
            term: max(0.01, math.log(1 + (n - freq + 0.5) / (freq + 0.5)))
            for term, freq in df.items()
        }
        self.index_by_id = {pid: i for i, pid in enumerate(self.ids)}

    # --- retrieval ---------------------------------------------------------

    def retrieve(self, q: AnalyzedSituation, k: int, filters: Filters) -> list[Candidate]:
        query_terms = self._query_terms(q)
        if not query_terms:
            return []

        scored: list[tuple[float, str, list[str]]] = []
        for pid, tf, length in zip(self.ids, self.tfs, self.lengths):
            if not self._passes(pid, filters):
                continue
            score = 0.0
            hits: list[tuple[float, str]] = []
            for term, weight in query_terms.items():
                freq = tf.get(term, 0)
                if not freq:
                    continue
                denom = freq + K1 * (1 - B + B * length / (self.avgdl or 1))
                contribution = weight * self.idf.get(term, 0.0) * (freq * (K1 + 1)) / denom
                score += contribution
                hits.append((contribution, term))
            if score <= 0:
                continue
            score = self._diversify(pid, score)
            hits.sort(reverse=True)
            scored.append((score, pid, [t for _, t in hits[:6]]))

        scored.sort(key=lambda row: (-row[0], row[1]))  # id tiebreak = determinism
        return [
            Candidate(prayer_id=pid, score=round(saturate(raw, PIVOT), 4),
                      matched_on=self._matched_on(pid, terms, q))
            for raw, pid, terms in scored[:k]
        ]

    def _query_terms(self, q: AnalyzedSituation) -> dict[str, float]:
        """Query terms with weights: the user's words, plus what they implied.

        The analyzer's inferred content labels and their definitions are added
        as query terms rather than as a post-hoc filter, so a situation that
        implies `lament` ranks lament records up without excluding anything.
        """
        weights: dict[str, float] = {}
        for token in self._tokenise(q.situation):
            weights[token] = weights.get(token, 0.0) + 1.0
        for label in q.content_labels:
            weights[label] = weights.get(label, 0.0) + 1.5
            for token in self._tokenise(self.corpus.content_defs.get(label, "")):
                weights[token] = weights.get(token, 0.0) + 0.5
        for label in q.context_labels:
            weights[label] = weights.get(label, 0.0) + 1.0
        # Below the user's own words on purpose: expansions steer ranking
        # toward the corpus's vocabulary without overriding what was written.
        for term in q.expansions:
            weights[term] = weights.get(term, 0.0) + 0.7
        return weights

    def _passes(self, pid: str, filters: Filters) -> bool:
        rec = self.corpus.by_id[pid]
        if rec.compose_policy == "exclude" or pid in filters.exclude_ids:
            return False
        if rec.canon_section not in filters.canon:
            return False
        if filters.require_text and not self.corpus.has_text(pid):
            return False
        if filters.allowed_contents is not None:
            if not set(rec.contents) & set(filters.allowed_contents):
                return False
        return True

    def _diversify(self, pid: str, score: float) -> float:
        """Hold the Psalms back by a configured factor.

        43 of 224 records are Psalms and they are the most thematically
        generic, so they dominate top-k for almost any query. The knob defaults
        to 0 (no penalty) and is tuned in M8 on Tier 3 dev only; applying an
        untuned correction would just trade one bias for another.
        """
        penalty = getattr(self.settings, "psalm_penalty", 0.0) if self.settings else 0.0
        if penalty and self.corpus.is_psalm(pid):
            return score * (1.0 - penalty)
        return score

    def _matched_on(self, pid: str, top_terms: list[str],
                    q: AnalyzedSituation) -> list[str]:
        """Human-readable reasons, most specific first.

        Label and theme names come before raw terms because "petition,
        longing" explains a suggestion to a person and "affliction, servant"
        mostly explains it to a search engineer.
        """
        rec = self.corpus.by_id[pid]
        reasons: list[str] = []
        for label in rec.contents:
            if label in q.content_labels:
                reasons.append(label)
        for theme in q.themes:
            if theme not in reasons:
                reasons.append(theme)
        for term in top_terms:
            if term not in reasons and len(reasons) < 6:
                reasons.append(term)
        return reasons[:6]


def _stopwords(corpus) -> frozenset[str]:
    from prayer.api.analyze import load_lexicon
    from prayer.api.config import get_settings
    try:
        return load_lexicon(get_settings().policy_dir).stopwords
    except Exception:
        return frozenset()
