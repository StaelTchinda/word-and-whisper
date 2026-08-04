"""The invariant suite — PRODUCT_BOOK section 10.

Parametrized over every registered composer. This is the suite that keeps the
composers interchangeable: a new composer becomes subject to all of it by
being registered, with no edit here.
"""
import json
from pathlib import Path

import pytest

from prayer.api import registry
from prayer.api.analyze import SituationAnalyzer
from prayer.api.composers import anchor as anchor_mod
from prayer.api.composers.base import MOVEMENT_ORDER
from prayer.api.composers.verify import spoken_text, verify, word_count
from prayer.api.models import (MAX_PRAYER_WORDS, MIN_PRAYER_WORDS, REQUIRED_MOVEMENTS)

FIXTURES = Path(__file__).parent / "fixtures/situations.jsonl"


def load_situations():
    return [json.loads(line) for line in FIXTURES.read_text().splitlines() if line.strip()]


def composer_names():
    # Every composer that claims to be conformant, including the ones users
    # cannot select: the fallback path is held to the same invariants as the
    # fancy ones, since it is what people actually receive whenever a model
    # misbehaves. Only the deliberately-broken stubs in tests/test_fallback.py
    # opt out, via conformant=False.
    return registry.available("composer", conformant_only=True)


@pytest.fixture(scope="module")
def analyzer(settings):
    return SituationAnalyzer(settings.policy_dir)


def _composable_sample(corpus, n=40):
    """A spread across the corpus, not just the first n records."""
    records = [r for r in corpus.composable if r.compose_policy == "compose"]
    step = max(1, len(records) // n)
    return records[::step][:n]


@pytest.mark.parametrize("composer_name", composer_names())
def test_every_composer_satisfies_every_invariant(corpus, settings, analyzer,
                                                  composer_name):
    """Anchor-verbatim, movement completeness, word bounds, quote containment."""
    composer = registry.get("composer", composer_name)(corpus, settings, None)
    q = analyzer.analyze("I am frightened and I do not know what happens next.")

    checked = 0
    for record in _composable_sample(corpus):
        passage = corpus.passage(record.id)
        composition = composer.compose(q, record, passage)
        address = anchor_mod.find_address(passage)
        result = verify(composition, passage, record,
                        allow_address_span=address.text if address else None)
        assert result.ok, f"{composer_name}/{record.id}: {result.violations}"
        checked += 1
    assert checked >= 20


@pytest.mark.parametrize("composer_name", composer_names())
def test_anchor_is_byte_exact(corpus, settings, analyzer, composer_name):
    """C1, stated on its own because it is the one that must never bend."""
    composer = registry.get("composer", composer_name)(corpus, settings, None)
    q = analyzer.analyze("My father is dying and I cannot be there.")
    for record in _composable_sample(corpus, 60):
        passage = corpus.passage(record.id)
        composition = composer.compose(q, record, passage)
        anchors = [m for m in composition.movements if m.kind == "anchor"]
        assert len(anchors) == 1
        assert anchors[0].text in passage.full_text
        assert anchors[0].verbatim_from


@pytest.mark.parametrize("composer_name", composer_names())
def test_word_count_bounds(corpus, settings, analyzer, composer_name):
    composer = registry.get("composer", composer_name)(corpus, settings, None)
    q = analyzer.analyze("I have been waiting for years and nothing has changed.")
    for record in _composable_sample(corpus, 60):
        composition = composer.compose(q, record, corpus.passage(record.id))
        n = word_count(composition)
        assert MIN_PRAYER_WORDS <= n <= MAX_PRAYER_WORDS, f"{record.id}: {n} words"


@pytest.mark.parametrize("composer_name", composer_names())
def test_movements_are_complete_and_ordered(corpus, settings, analyzer, composer_name):
    composer = registry.get("composer", composer_name)(corpus, settings, None)
    q = analyzer.analyze("Thank you for what happened this week.")
    for record in _composable_sample(corpus, 30):
        composition = composer.compose(q, record, corpus.passage(record.id))
        kinds = [m.kind for m in composition.movements]
        for required in REQUIRED_MOVEMENTS:
            assert required in kinds, f"{record.id} missing {required}"
        assert len(kinds) == len(set(kinds)), f"{record.id} has duplicate movements"
        assert all(k in MOVEMENT_ORDER for k in kinds)


@pytest.mark.parametrize("composer_name", composer_names())
def test_imprecatory_ask_never_requests_harm(corpus, settings, analyzer, composer_name):
    """Section 7.3, with dedicated coverage as the PRODUCT_BOOK requires."""
    composer = registry.get("composer", composer_name)(corpus, settings, None)
    q = analyzer.analyze("Someone at work lied about me and got me suspended.")
    imprecatory = [r for r in corpus.records
                   if {"imprecation", "curse"} & set(r.contents)
                   and r.compose_policy == "compose"]
    assert len(imprecatory) == 6, "6 of the 7 are composable; Jdg 21:18 is explain_only"
    for record in imprecatory:
        passage = corpus.passage(record.id)
        composition = composer.compose(q, record, passage)
        address = anchor_mod.find_address(passage)
        result = verify(composition, passage, record,
                        allow_address_span=address.text if address else None)
        assert result.ok, f"{record.id}: {result.violations}"


@pytest.mark.parametrize("composer_name", composer_names())
def test_no_scripture_outside_the_anchor(corpus, settings, analyzer, composer_name):
    composer = registry.get("composer", composer_name)(corpus, settings, None)
    q = analyzer.analyze("I am at the end of what I can cope with.")
    for record in _composable_sample(corpus, 40):
        passage = corpus.passage(record.id)
        composition = composer.compose(q, record, passage)
        address = anchor_mod.find_address(passage)
        allowed = address.text if address else None
        from prayer.api.composers.verify import _check_no_scripture_outside_anchor
        violations = _check_no_scripture_outside_anchor(
            composition, passage.full_text, allowed)
        assert not violations, f"{record.id}: {violations}"


def test_spoken_text_is_rendered_in_movement_order(corpus, settings, analyzer):
    composer = registry.get("composer", "deterministic")(corpus, settings, None)
    q = analyzer.analyze("I am grateful and I want to say so.")
    record = corpus.record("parks2021.0037")
    composition = composer.compose(q, record, corpus.passage(record.id))
    lines = spoken_text(composition).split("\n")
    kinds = [m.kind for m in sorted(composition.movements,
                                    key=lambda m: MOVEMENT_ORDER.index(m.kind))]
    assert len(lines) == len(kinds)
    assert kinds[0] == "address" and kinds[-1] == "close"


def test_intercessory_situations_switch_person(corpus, settings, analyzer):
    composer = registry.get("composer", "deterministic")(corpus, settings, None)
    q = analyzer.analyze("My daughter is very ill and I am frightened for her.")
    assert q.intercessory
    record = corpus.record("parks2021.0037")
    composition = composer.compose(q, record, corpus.passage(record.id))
    naming = next(m for m in composition.movements if m.kind == "naming")
    lowered = naming.text.lower()
    assert "their daughter" in lowered and "they are" in lowered
    assert "my daughter" not in lowered
