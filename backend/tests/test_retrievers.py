"""M4: R2 dense and R3 hybrid — PRODUCT_BOOK section 8.

DoD: all three selectable, Tier 1 metrics for all three in one report, the
index build is deterministic and cached, retrieval p95 still under 50 ms.
"""
import json
import statistics
import time
from pathlib import Path

import numpy as np
import pytest

from prayer.api import registry
from prayer.api.analyze import SituationAnalyzer
from prayer.api.models import Filters

from prayer import paths

TIER1 = paths.BENCH / "queries/tier1.jsonl"

RETRIEVERS = ["bm25", "dense", "hybrid"]


@pytest.fixture(scope="module")
def analyzer(settings):
    return SituationAnalyzer(settings.policy_dir)


@pytest.fixture(scope="module")
def built(corpus, settings):
    made = {}
    for name in RETRIEVERS:
        made[name] = registry.get("retriever", name)(corpus, settings)
    return made


def test_all_three_are_registered_and_selectable():
    available = registry.available("retriever", selectable_only=True)
    for name in RETRIEVERS:
        assert name in available


def test_all_three_appear_in_config(client):
    names = [r["name"] for r in client.get("/config").json()["retrievers"]]
    for name in RETRIEVERS:
        assert name in names


@pytest.mark.parametrize("name", RETRIEVERS)
def test_retriever_satisfies_the_protocol(built, name):
    from prayer.api.retrievers.base import Retriever
    assert isinstance(built[name], Retriever)


@pytest.mark.parametrize("name", RETRIEVERS)
def test_scores_are_normalised_and_ordered(built, analyzer, name):
    q = analyzer.analyze("I am frightened about my test results next week.")
    results = built[name].retrieve(q, 10, Filters())
    assert results
    scores = [c.score for c in results]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 <= s <= 1.0 for s in scores), \
        "scores must share a [0,1] scale so abstain_threshold means one thing"
    assert all(c.matched_on for c in results), "matched_on is required"


@pytest.mark.parametrize("name", RETRIEVERS)
def test_filters_are_honoured(built, corpus, analyzer, name):
    q = analyzer.analyze("I need God to protect my family.")
    results = built[name].retrieve(q, 20, Filters(canon=["NT"]))
    for candidate in results:
        assert corpus.record(candidate.prayer_id).canon_section == "NT"


@pytest.mark.parametrize("name", RETRIEVERS)
def test_excluded_records_never_surface(built, analyzer, name):
    q = analyzer.analyze("I called out and nobody answered me at all.")
    results = built[name].retrieve(q, 50, Filters())
    assert "parks2021.0059" not in [c.prayer_id for c in results]


@pytest.mark.parametrize("name", RETRIEVERS)
def test_retrieval_is_deterministic(built, analyzer, name):
    q = analyzer.analyze("My mother died and I cannot face her house.")
    first = [c.prayer_id for c in built[name].retrieve(q, 10, Filters())]
    second = [c.prayer_id for c in built[name].retrieve(q, 10, Filters())]
    assert first == second


# --- the index --------------------------------------------------------------

def test_index_exists_and_matches_the_corpus(corpus, settings):
    path = Path(settings.index_dir) / f"{Path(settings.embedding_model_dir).name}.npz"
    assert path.exists(), "run prayer.api.build.index"
    data = np.load(path, allow_pickle=False)
    assert len(data["ids"]) == len(corpus.records)
    assert data["vectors"].shape == (len(corpus.records), 384)


def test_index_vectors_are_l2_normalised(settings):
    path = Path(settings.index_dir) / f"{Path(settings.embedding_model_dir).name}.npz"
    vectors = np.load(path, allow_pickle=False)["vectors"]
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_index_build_is_cached(settings):
    """A second build with unchanged inputs must not re-embed."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "prayer.api.build.index"], cwd=str(paths.ROOT),
        capture_output=True, text=True, check=True)
    assert "up to date" in result.stdout


def test_index_is_not_stale(corpus, settings):
    """The committed index matches the documents it claims to cover.

    Cheaper and stricter than rebuilding: a stale index is the failure that
    actually happens (someone edits the corpus and forgets the build step),
    and re-embedding 224 records twice just to compare bytes costs a minute
    of every test run.
    """
    import json as _json
    from prayer.api.build.index import fingerprint
    from prayer.api.retrievers.dense import dense_document

    documents = [dense_document(corpus, r) for r in corpus.records]
    expected = fingerprint(documents, Path(settings.embedding_model_dir))
    meta = _json.loads((Path(settings.index_dir) / "index_meta.json").read_text())
    assert meta["fingerprint"] == expected, "index is stale; run prayer.api.build.index"


def test_embedding_is_deterministic(settings):
    """Same text, same bytes -- the property the index build relies on."""
    from prayer.api.retrievers.encoder import OnnxEncoder
    encoder = OnnxEncoder(Path(settings.embedding_model_dir), threads=1)
    texts = ["Hannah prays for a son.", "A lament with no resolution."]
    first = encoder.encode(texts)
    second = encoder.encode(texts)
    assert first.tobytes() == second.tobytes()


def test_index_vectors_match_a_fresh_encode(corpus, settings):
    """Spot-check that the stored vectors are what the encoder produces now."""
    from prayer.api.retrievers.encoder import OnnxEncoder
    from prayer.api.retrievers.dense import dense_document

    path = Path(settings.index_dir) / f"{Path(settings.embedding_model_dir).name}.npz"
    data = np.load(path, allow_pickle=False)
    ids = [str(x) for x in data["ids"]]

    encoder = OnnxEncoder(Path(settings.embedding_model_dir), threads=1)
    sample = [0, len(ids) // 2, len(ids) - 1]
    fresh = encoder.encode([dense_document(corpus, corpus.record(ids[i])) for i in sample])
    for row, i in enumerate(sample):
        assert np.allclose(fresh[row], data["vectors"][i], atol=1e-5)


# --- dense-specific ---------------------------------------------------------

def test_dense_degrades_when_the_model_is_missing(corpus, settings):
    """A missing model must disable R2, not break the service."""
    from prayer.api.retrievers.dense import DenseRetriever
    broken = settings.model_copy(update={
        "embedding_model_dir": Path("/nonexistent/model"),
        "index_dir": Path("/nonexistent/index")})
    retriever = DenseRetriever(corpus, broken)
    assert not retriever.available
    assert retriever.retrieve(
        SituationAnalyzer(settings.policy_dir).analyze("I am afraid."),
        5, Filters()) == []


def test_dense_document_excludes_bm25_style_repetition(corpus):
    from prayer.api.retrievers.dense import dense_document
    document = dense_document(corpus, corpus.record("parks2021.0037"))
    assert "Hannah" in document and "Yahweh of Armies" in document
    assert document.count("petition") <= 2, "a bi-encoder wants prose, not term bags"


# --- hybrid-specific --------------------------------------------------------

def test_hybrid_surfaces_records_either_retriever_alone_ranks_lower(built, analyzer):
    """The point of fusion: agreement beats one retriever's confidence."""
    q = analyzer.analyze("I've been trying for a child for four years and I'm losing hope.")
    lexical = [c.prayer_id for c in built["bm25"].retrieve(q, 5, Filters())]
    semantic = [c.prayer_id for c in built["dense"].retrieve(q, 5, Filters())]
    fused = [c.prayer_id for c in built["hybrid"].retrieve(q, 5, Filters())]
    agreed = set(lexical) & set(semantic)
    for pid in agreed:
        assert pid in fused, "a record both retrievers rank must survive fusion"


def test_hybrid_reports_agreement_as_a_reason(built, analyzer):
    q = analyzer.analyze("My friend is very ill and I do not know what to ask for.")
    results = built["hybrid"].retrieve(q, 5, Filters())
    assert any("both retrievers agree" in c.matched_on for c in results)


# --- latency (M4 DoD: retrieval p95 < 50 ms) --------------------------------

@pytest.mark.perf
@pytest.mark.parametrize("name", RETRIEVERS)
def test_retrieval_p95_under_50ms(built, analyzer, name):
    queries = [json.loads(line)["situation"]
               for line in TIER1.read_text().splitlines()[:60] if line.strip()]
    retriever = built[name]
    retriever.retrieve(analyzer.analyze("warm up the session"), 5, Filters())

    timings = []
    for situation in queries:
        q = analyzer.analyze(situation)
        started = time.perf_counter()
        retriever.retrieve(q, 25, Filters())
        timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 < 50, f"{name} retrieval p95 {p95:.1f} ms (p50 {statistics.median(timings):.1f})"
