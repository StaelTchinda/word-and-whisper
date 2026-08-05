"""The modularity requirement, made executable (PRODUCT_BOOK sections 5.1, 10).

A retriever and a composer defined entirely inside this test module must work
end to end without a single edit under api/. If this test ever needs an api/
change to pass, the pluggable-axes design has regressed.
"""
from prayer.api import registry
from prayer.api.composers.base import MOVEMENT_ORDER
from prayer.api.models import (AnalyzedSituation, Candidate, Composition, Filters,
                        Instructions, Movement, Passage, PrayerRecord)


@registry.register("retriever", "stub_test", description="test-only", selectable=False)
class StubRetriever:
    """Returns the first k records in corpus order."""

    def __init__(self, corpus, settings=None):
        self.corpus = corpus

    def retrieve(self, q: AnalyzedSituation, k: int, filters: Filters) -> list[Candidate]:
        out = []
        for rec in self.corpus.composable[:k]:
            out.append(Candidate(prayer_id=rec.id, score=1.0, matched_on=["stub"]))
        return out


@registry.register("composer", "stub_test", description="test-only", selectable=False)
class StubComposer:
    """Anchors on the first verse and pads to the word floor."""

    def __init__(self, corpus, settings=None, llm=None):
        self.corpus = corpus

    def compose(self, q: AnalyzedSituation, p: PrayerRecord,
                passage: Passage) -> Composition:
        first = passage.refs[0].verses[0]
        filler = " ".join(["I bring this to you now."] * 12)
        return Composition(
            movements=[
                Movement(kind="address", text="God,"),
                Movement(kind="anchor", text=first.text, verbatim_from=first.osis),
                Movement(kind="naming", text=f"This is my situation: {q.situation}"),
                Movement(kind="ask", text=f"Hear me. {filler}"),
                Movement(kind="close", text="Amen."),
            ],
            instructions=Instructions(why_it_fits="stub", how_to_pray="stub",
                                      posture="stub"),
            composer="stub_test",
        )


def test_stub_components_are_registered():
    assert "stub_test" in registry.available("retriever")
    assert "stub_test" in registry.available("composer")


def test_stubs_are_not_publicly_selectable():
    # selectable=False keeps test and fallback components out of /config.
    assert "stub_test" not in registry.available("retriever", selectable_only=True)
    assert "stub_test" not in registry.available("composer", selectable_only=True)


def test_registry_rejects_duplicate_names():
    import pytest
    with pytest.raises(ValueError):
        @registry.register("retriever", "stub_test")
        class Other:
            pass


def test_stub_retriever_satisfies_protocol(corpus):
    from prayer.api.retrievers.base import Retriever
    assert isinstance(StubRetriever(corpus), Retriever)


def test_stub_composer_satisfies_protocol(corpus):
    from prayer.api.composers.base import Composer
    assert isinstance(StubComposer(corpus), Composer)


def test_movement_order_covers_every_kind():
    from typing import get_args
    from prayer.api.models import MovementKind
    assert set(MOVEMENT_ORDER) == set(get_args(MovementKind))
