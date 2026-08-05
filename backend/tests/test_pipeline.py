"""M2 Definition of Done, plus the constraint tests from PRODUCT_BOOK section 2.

The 20 situations in tests/fixtures/situations.jsonl are the DoD's benchmark:
every one must produce a schema-valid response with a real spoken prayer (or a
correct crisis response), and the anchor-verbatim invariant must hold for all
of them.
"""
import json
import statistics
import time
from pathlib import Path

import pytest

from prayer.api.models import SuggestRequest, SuggestResponse

FIXTURES = Path(__file__).parent / "fixtures/situations.jsonl"
SITUATIONS = [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def pipe(corpus, settings):
    from prayer.api.pipeline import Pipeline
    p = Pipeline(corpus, settings)
    p.retriever(settings.retriever)  # warm the index outside the timing tests
    return p


def test_fixture_file_has_twenty_situations():
    assert len(SITUATIONS) == 20


@pytest.mark.parametrize("case", SITUATIONS, ids=[c["id"] for c in SITUATIONS])
def test_every_fixture_returns_a_valid_response(pipe, case):
    response = pipe.suggest(SuggestRequest(situation=case["situation"], k=3))
    assert isinstance(response, SuggestResponse)
    SuggestResponse.model_validate(response.model_dump())  # schema-valid

    # C4: complete suggestion or explicit abstention, never a partial success.
    if response.abstained:
        assert response.suggestions == [] and response.message
    else:
        assert response.suggestions
        for suggestion in response.suggestions:
            assert suggestion.instructions.why_it_fits
            assert suggestion.instructions.how_to_pray
            assert suggestion.match.matched_on, "matched_on is required, not optional"


@pytest.mark.parametrize("case", SITUATIONS, ids=[c["id"] for c in SITUATIONS])
def test_anchor_verbatim_holds_for_every_fixture(pipe, corpus, case):
    """C1 asserted across the DoD set, as M2 requires."""
    response = pipe.suggest(SuggestRequest(situation=case["situation"], k=3))
    for suggestion in response.suggestions:
        if suggestion.spoken_prayer is None:
            continue
        passage = corpus.passage(suggestion.prayer_id)
        anchors = [m for m in suggestion.spoken_prayer.movements if m.kind == "anchor"]
        assert len(anchors) == 1
        assert anchors[0].text in passage.full_text
        valid_osis = {v.osis for ref in passage.refs for v in ref.verses}
        assert anchors[0].verbatim_from in valid_osis


@pytest.mark.parametrize("case", [c for c in SITUATIONS if c["expect"] == "ok"],
                         ids=[c["id"] for c in SITUATIONS if c["expect"] == "ok"])
def test_non_crisis_fixtures_produce_a_real_spoken_prayer(pipe, case):
    response = pipe.suggest(SuggestRequest(situation=case["situation"], k=3))
    if response.abstained:
        pytest.skip("abstained; C4 allows this and it is measured in bench/")
    spoken = [s for s in response.suggestions if s.spoken_prayer]
    assert spoken, "a non-abstained response must contain something to actually pray"
    for suggestion in spoken:
        prayer = suggestion.spoken_prayer
        assert 60 <= prayer.word_count <= 180
        assert prayer.read_time_seconds > 0
        assert prayer.text.count("\n") >= 4  # five or more movements


# --- safety gate (section 7.1) ---------------------------------------------

@pytest.mark.parametrize("case", [c for c in SITUATIONS if c["expect"] == "crisis"],
                         ids=[c["id"] for c in SITUATIONS if c["expect"] == "crisis"])
def test_crisis_fixtures_trigger_the_gate(pipe, case):
    response = pipe.suggest(SuggestRequest(situation=case["situation"], k=3))
    assert response.safety.status == "crisis"
    assert response.safety.notice, "a crisis response must carry signposting"
    # Still a prayer: a person in crisis asking for prayer is not met with a
    # blank refusal.
    assert response.suggestions or response.abstained


@pytest.mark.parametrize("case", [c for c in SITUATIONS if c["expect"] == "crisis"],
                         ids=[c["id"] for c in SITUATIONS if c["expect"] == "crisis"])
def test_crisis_forces_the_deterministic_composer(pipe, case):
    """No model may improvise words to a person in crisis."""
    response = pipe.suggest(SuggestRequest(situation=case["situation"], k=3,
                                           composer="phrasebank"))
    assert response.query.composer == "deterministic"


def test_crisis_narrows_retrieval_to_honest_prayers(pipe, corpus):
    response = pipe.suggest(SuggestRequest(
        situation="I don't want to live anymore and I don't know who to tell.", k=3))
    allowed = set(pipe.gate.allowed_contents)
    for suggestion in response.suggestions:
        assert set(suggestion.labels.contents) & allowed, \
            f"{suggestion.prayer_id} is not one of the corpus's honest prayers"


def test_gate_runs_regardless_of_configuration(pipe):
    """C7: before retrieval, on every request."""
    response = pipe.suggest(SuggestRequest(
        situation="My husband hits me and I am frightened to go home tonight.",
        k=1, retriever="bm25", composer="deterministic"))
    assert response.safety.status == "crisis"


def test_ordinary_situations_do_not_trigger_the_gate(pipe):
    for situation in ["I am grateful for my family today.",
                      "I have a decision to make about a job."]:
        response = pipe.suggest(SuggestRequest(situation=situation, k=1))
        assert response.safety.status == "ok"
        assert response.safety.notice is None


def test_crisis_notice_is_flagged_unapproved(pipe):
    """Section 11 item 3 is outstanding; nothing may claim otherwise."""
    assert not pipe.gate.notice_is_approved


# --- compose policy (section 7.2) ------------------------------------------

def test_explain_only_records_return_no_spoken_prayer(pipe, corpus, settings):
    from prayer.api.models import Candidate
    from prayer.api.analyze import SituationAnalyzer
    q = SituationAnalyzer(settings.policy_dir).analyze(
        "I keep comparing myself to other people and feeling superior.")
    record = corpus.record("parks2021.0202")  # the proud Pharisee
    assert record.compose_policy == "explain_only"
    suggestion = pipe._build(
        Candidate(prayer_id=record.id, score=0.5, matched_on=["test"]),
        q, "deterministic", True)
    assert suggestion.spoken_prayer is None
    assert suggestion.note, "the response must say why there is nothing to pray"
    assert suggestion.instructions.why_it_fits


def test_excluded_records_are_never_retrieved(pipe, corpus):
    """The Baal prayer must not surface for anything."""
    assert corpus.record("parks2021.0059").compose_policy == "exclude"
    for situation in ["I have prayed and prayed and heard nothing back.",
                      "I am asking God to answer me by fire.",
                      "no one answers when I call"]:
        response = pipe.suggest(SuggestRequest(situation=situation, k=10))
        assert "parks2021.0059" not in [s.prayer_id for s in response.suggestions]


def test_excluded_records_are_out_of_the_retrievable_set(corpus):
    assert "parks2021.0059" not in [r.id for r in corpus.composable]


# --- abstention (C4) --------------------------------------------------------

def test_abstains_rather_than_returning_a_generic_psalm(pipe):
    response = pipe.suggest(SuggestRequest(
        situation="zxqvw plkjhg mnbvcxz qwertyuiop asdfghjkl", k=3))
    assert response.abstained
    assert response.suggestions == []
    assert response.message


# --- latency (M2 DoD: p95 < 100 ms) ----------------------------------------

@pytest.mark.perf
def test_p95_latency_under_100ms(pipe):
    timings = []
    for case in SITUATIONS:
        for _ in range(3):
            started = time.perf_counter()
            pipe.suggest(SuggestRequest(situation=case["situation"], k=3))
            timings.append((time.perf_counter() - started) * 1000)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95)]
    assert p95 < 100, f"p95 {p95:.1f} ms exceeds the M2 budget (p50 {statistics.median(timings):.1f} ms)"
