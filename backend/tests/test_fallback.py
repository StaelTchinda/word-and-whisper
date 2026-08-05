"""C5: composition never fails the request — PRODUCT_BOOK sections 2, 10.

Composers that raise, hang, or emit something the verifier rejects must all
end at the same place: a valid response with `fallback_used: true`. These
stubs stand in for the failure modes a real local model will produce in M5+,
so the fallback path is exercised before there is a model to exercise it.
"""
import pytest

from prayer.api import registry
from prayer.api.analyze import SituationAnalyzer
from prayer.api.composers.base import CompositionError
from prayer.api.llm.base import LLMUnavailable
from prayer.api.models import (AnalyzedSituation, Candidate, Composition, Instructions,
                        Movement, Passage, PrayerRecord, SuggestRequest)

SITUATION = "I am at the end of what I can cope with and I need help."


@registry.register("composer", "broken_raises", selectable=False,
                   conformant=False,
                   description="test-only: always raises")
class RaisingComposer:
    def __init__(self, corpus, settings=None, llm=None):
        pass

    def compose(self, q, p, passage) -> Composition:
        raise CompositionError("simulated model failure")


@registry.register("composer", "broken_fabricates", selectable=False,
                   conformant=False,
                   description="test-only: fabricates scripture")
class FabricatingComposer:
    """The failure mode that matters most: confident, plausible, and wrong."""

    def __init__(self, corpus, settings=None, llm=None):
        pass

    def compose(self, q, p, passage) -> Composition:
        return Composition(
            movements=[
                Movement(kind="address", text="Lord,"),
                # Not in any passage. Reads exactly like scripture.
                Movement(kind="anchor",
                         text="Be still, and know that I have never once forsaken you,",
                         verbatim_from=passage.refs[0].verses[0].osis),
                Movement(kind="naming", text="This is where I am: " + SITUATION),
                Movement(kind="ask", text="Hear me. " + "I am asking you to act. " * 8),
                Movement(kind="close", text="Amen."),
            ],
            instructions=Instructions(why_it_fits="x", how_to_pray="y", posture="z"),
            composer="broken_fabricates",
        )


@registry.register("composer", "broken_too_short", selectable=False,
                   conformant=False,
                   description="test-only: under the word floor")
class ShortComposer:
    def __init__(self, corpus, settings=None, llm=None):
        pass

    def compose(self, q, p, passage) -> Composition:
        first = passage.refs[0].verses[0]
        return Composition(
            movements=[
                Movement(kind="address", text="God,"),
                Movement(kind="anchor", text=first.text[:40], verbatim_from=first.osis),
                Movement(kind="naming", text="Here I am."),
                Movement(kind="ask", text="Help."),
                Movement(kind="close", text="Amen."),
            ],
            instructions=Instructions(why_it_fits="x", how_to_pray="y", posture="z"),
            composer="broken_too_short",
        )


@pytest.fixture(scope="module")
def pipe(corpus, settings):
    from prayer.api.pipeline import Pipeline
    return Pipeline(corpus, settings)


@pytest.mark.parametrize("broken", ["broken_raises", "broken_fabricates",
                                    "broken_too_short"])
def test_broken_composers_fall_back_cleanly(pipe, broken):
    request = SuggestRequest(situation=SITUATION, k=2)
    response = pipe.suggest(request)
    assert not response.abstained

    # Drive the broken composer through the same path a real request takes.
    from prayer.api.analyze import SituationAnalyzer
    q = pipe.analyzer.analyze(SITUATION)
    for suggestion in response.suggestions:
        candidate = Candidate(prayer_id=suggestion.prayer_id, score=0.5,
                              matched_on=["test"])
        built = pipe._build(candidate, q, broken, True)
        assert built is not None, "a broken composer must not lose the suggestion"
        assert built.spoken_prayer is not None
        assert built.provenance.fallback_used is True
        assert built.provenance.composer == "deterministic"


def test_fabricated_scripture_never_reaches_the_response(pipe, corpus):
    """The verifier must catch an anchor that is not in the passage (C1)."""
    q = pipe.analyzer.analyze(SITUATION)
    record = corpus.record("parks2021.0037")
    candidate = Candidate(prayer_id=record.id, score=0.9, matched_on=["test"])
    built = pipe._build(candidate, q, "broken_fabricates", True)
    anchor = next(m for m in built.spoken_prayer.movements if m.kind == "anchor")
    assert "never once forsaken" not in anchor.text
    assert anchor.text in corpus.passage(record.id).full_text


def test_missing_local_model_is_not_an_error(pipe):
    """llm_backend='null' is the default; it must degrade, not raise."""
    assert pipe._llm() is not None
    with pytest.raises(LLMUnavailable):
        pipe._llm().generate("x", max_tokens=10, timeout_s=1.0)
    response = pipe.suggest(SuggestRequest(situation=SITUATION, k=2))
    assert response.suggestions


def test_unknown_llm_backend_degrades_to_none(corpus, settings):
    from prayer.api.pipeline import Pipeline
    broken = settings.model_copy(update={"llm_backend": "does-not-exist"})
    assert Pipeline(corpus, broken)._llm() is None
