#!/usr/bin/env python3
"""R2: dense retrieval over 224 precomputed vectors (PRODUCT_BOOK M4).

Exhaustive numpy search, no vector database. 224 x 384 float32 is 344 KB and
a full scan is one matrix multiply -- an index would add a dependency, a
failure mode and a build step to save microseconds.

What this buys over R1: the corpus and the user share almost no vocabulary.
Someone writes "trying for a child"; the passage says "boy", "womb",
"remember me". BM25 needs api/policy/situation_lexicon.yaml to hand-bridge
that gap term by term. Embeddings bridge it without a lexicon entry, which is
the whole reason M4 exists.
"""
from pathlib import Path
from typing import Optional

import numpy as np

from prayer.api import registry
from prayer.api.models import AnalyzedSituation, Candidate, Filters
from prayer.api.retrievers.base import saturate
from prayer.api.retrievers.encoder import load_encoder

from prayer import paths

# Cosine similarity is already bounded, but the useful range for a normalised
# bi-encoder sits well above zero -- unrelated text still scores ~0.3-0.5. The
# rescale below maps that band onto [0, 1] so `abstain_threshold` means
# roughly the same thing for R1 and R2.
COSINE_FLOOR = 0.45
PIVOT = 0.22

INDEX_SUFFIX = ".npz"


def dense_document(corpus, record) -> str:
    """Natural-language rendering of a record, for embedding.

    Deliberately not BM25's weighted token bag: a bi-encoder was trained on
    prose, and repeating "petition petition petition" to express field weight
    would make the vector worse, not better. Field emphasis here comes from
    ordering -- what a sentence leads with carries more weight.
    """
    passage = corpus.passage(record.id)
    contents = ", ".join(record.contents)
    content_defs = " ".join(corpus.content_defs.get(c, "") for c in record.contents)
    context_def = corpus.context_defs.get(record.context, "")
    place = f" The prayer was in {', '.join(record.places)}." if record.places else ""

    return (
        f"{record.title}. "
        f"A prayer by {record.speaker.raw} to {record.addressee.raw}. "
        f"It is a {record.context} prayer: {context_def}. "
        f"Its content is {contents}: {content_defs}.{place} "
        f"{passage.full_text if passage else ''}"
    ).strip()


@registry.register("retriever", "dense",
                   description="Local ONNX bi-encoder over precomputed "
                               "vectors; exhaustive numpy search.")
class DenseRetriever:
    def __init__(self, corpus, settings=None):
        self.corpus = corpus
        self.settings = settings
        self.index_dir = Path(settings.index_dir) if settings else paths.INDEX
        threads = getattr(settings, "embedding_threads", 4) if settings else 4
        self.encoder = load_encoder(self._model_dir(), threads)
        self.ids: list[str] = []
        self.matrix: Optional[np.ndarray] = None
        self._load_index()

    def _model_dir(self) -> Path:
        configured = getattr(self.settings, "embedding_model_dir", None) if self.settings else None
        if configured:
            return Path(configured)
        return paths.EMBEDDING_MODEL

    def _load_index(self) -> None:
        path = self.index_dir / f"{self._model_dir().name}{INDEX_SUFFIX}"
        if not path.exists():
            return
        data = np.load(path, allow_pickle=False)
        self.ids = [str(x) for x in data["ids"]]
        self.matrix = data["vectors"].astype(np.float32)
        self.index_by_id = {pid: i for i, pid in enumerate(self.ids)}

    @property
    def available(self) -> bool:
        return self.encoder is not None and self.matrix is not None

    def retrieve(self, q: AnalyzedSituation, k: int, filters: Filters) -> list[Candidate]:
        if not self.available:
            # No index or no model: report nothing rather than raise. The
            # pipeline abstains, which is a correct C4 outcome, and BM25 is
            # unaffected.
            return []

        query_vector = self.encoder.encode_query(self._query_text(q))
        scores = self.matrix @ query_vector  # both sides L2-normalised

        order = np.argsort(-scores, kind="stable")
        out: list[Candidate] = []
        for index in order:
            pid = self.ids[index]
            if not self._passes(pid, filters):
                continue
            cosine = float(scores[index])
            normalised = saturate(max(0.0, cosine - COSINE_FLOOR), PIVOT)
            if normalised <= 0:
                continue
            normalised = self._diversify(pid, normalised)
            out.append(Candidate(prayer_id=pid, score=round(normalised, 4),
                                 matched_on=self._matched_on(pid, q)))
            if len(out) >= k:
                break
        return out

    def _query_text(self, q: AnalyzedSituation) -> str:
        """The situation, plus what the analyzer inferred, as one sentence.

        The inferred labels are appended rather than substituted: the user's
        own wording is the signal, and the labels only nudge.
        """
        parts = [q.situation]
        if q.content_labels:
            parts.append("This is a prayer of " + ", ".join(q.content_labels) + ".")
        return " ".join(parts)

    def _passes(self, pid: str, filters: Filters) -> bool:
        record = self.corpus.by_id.get(pid)
        if record is None:
            return False
        if record.compose_policy == "exclude" or pid in filters.exclude_ids:
            return False
        if record.canon_section not in filters.canon:
            return False
        if filters.require_text and not self.corpus.has_text(pid):
            return False
        if filters.allowed_contents is not None:
            if not set(record.contents) & set(filters.allowed_contents):
                return False
        return True

    def _diversify(self, pid: str, score: float) -> float:
        penalty = getattr(self.settings, "psalm_penalty", 0.0) if self.settings else 0.0
        if penalty and self.corpus.is_psalm(pid):
            return score * (1.0 - penalty)
        return score

    def _matched_on(self, pid: str, q: AnalyzedSituation) -> list[str]:
        """Dense retrieval has no matching terms to point at.

        Saying so is better than inventing a plausible-looking term list: the
        shared labels and themes are the honest explanation of why this record
        came back, and "semantic similarity" is the honest fallback.
        """
        record = self.corpus.by_id[pid]
        reasons = [c for c in record.contents if c in q.content_labels]
        reasons += [t for t in q.themes if t not in reasons]
        if not reasons:
            reasons = ["semantic similarity"]
        return reasons[:6]
