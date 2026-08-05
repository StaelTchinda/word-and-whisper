"""M1 DoD: every reference resolves, and the resolved text is really scripture.

These tests guard C1 from below. If the text layer is wrong, every anchor in
the product is wrong in a way no downstream test can detect.
"""
import json

from prayer import paths

import pytest


def test_every_record_has_a_row(corpus):
    assert len(corpus.passages) == len(corpus.records) == 224


def test_resolution_meets_dod(corpus):
    resolved = sum(1 for p in corpus.passages.values() if p.text_available)
    assert resolved >= 221, "PRODUCT_BOOK section 4 DoD: 221+/224 must resolve"
    assert resolved == 224, "regression: all 224 resolved when M1 landed"


def test_verse_counts_match_the_dataset(corpus):
    """The dataset's own verse_count is an independent check on our ranges."""
    for rec in corpus.records:
        if rec.verse_count is None:
            continue
        passage = corpus.passage(rec.id)
        assert passage and passage.text_available
        got = len(passage.refs[0].verses)
        assert got == rec.verse_count, f"{rec.id} {rec.primary_ref}: {got} != {rec.verse_count}"


def test_chapter_crossing_record_resolves(corpus):
    """Bar 2:11-3:8 is the one range with a null verse_count (section 3)."""
    passage = corpus.passage("parks2021.0175")
    verses = passage.refs[0].verses
    assert passage.text_available
    assert {v.osis.split(".")[1] for v in verses} == {"2", "3"}


def test_full_text_uses_only_the_primary_ref(corpus):
    """Parallel gospel accounts must not be concatenated (section 3)."""
    for rec in corpus.records:
        if len(rec.refs) <= 1:
            continue
        passage = corpus.passage(rec.id)
        primary = " ".join(v.text for v in passage.refs[0].verses)
        assert passage.full_text == primary


def test_multi_ref_records_keep_their_parallels(corpus):
    multi = [r for r in corpus.records if len(r.refs) > 1]
    assert len(multi) == 3
    for rec in multi:
        assert len(corpus.passage(rec.id).refs) == len(rec.refs)


def test_superscriptions_are_not_in_verse_text(corpus):
    """A superscription is a heading; it must never be anchorable text."""
    passage = corpus.passage("parks2021.0095")  # Ps 35, has a superscription
    ref = passage.refs[0]
    if ref.superscription:
        assert ref.superscription not in passage.full_text


def test_no_markup_leaked_into_text(corpus):
    for passage in corpus.passages.values():
        assert "<" not in passage.full_text, f"markup leaked into {passage.prayer_id}"
        assert "\\" not in passage.full_text


def test_known_passage_is_verbatim(corpus):
    """A hand-checked verse, to catch a whole-corpus shift in numbering."""
    passage = corpus.passage("parks2021.0037")  # Hannah, 1 Sam 1:11
    assert "look at the affliction of your servant and remember me" in passage.full_text
    # The PRODUCT_BOOK's illustrative text said "look on"; the real WEB reads
    # "look at". That is exactly the paraphrase risk C1 exists to stop.
    assert "look on the affliction" not in passage.full_text


def test_three_and_four_maccabees_resolved(corpus):
    """The gap PRODUCT_BOOK section 4 told us to resolve rather than assume."""
    for prayer_id in ("parks2021.0190", "parks2021.0191", "parks2021.0192"):
        passage = corpus.passage(prayer_id)
        assert passage.text_available, f"{prayer_id} must have real text or be flagged"
        assert passage.word_count > 10


@pytest.mark.parametrize("prayer_id,needle", [
    ("parks2021.0176", "Blessed are you, O Lord"),      # PrAzar -> DAG 3:26
    ("parks2021.0178", "O everlasting God, you know the secrets"),  # Sus -> DAG 13
    ("parks2021.0180", "Great are you, O Lord, you God of Daniel"),  # Bel -> DAG 14
    ("parks2021.0179", "O LORD Almighty in heaven"),    # PrMan -> MAN
])
def test_daniel_addition_offsets(corpus, prayer_id, needle):
    """The riskiest mappings: books WEB folds into Greek Daniel."""
    assert needle in corpus.passage(prayer_id).full_text


def test_build_is_deterministic(tmp_path, settings):
    """Same input, same bytes (section 12)."""
    import subprocess
    import sys
    out = tmp_path / "web.jsonl"
    for _ in range(2):
        subprocess.run([sys.executable, "-m", "prayer.extract.text",
                        "--out", str(out),
                        "--coverage", str(tmp_path / "COVERAGE.md"), "--quiet"],
                       check=True, cwd=str(paths.ROOT))
        digest = out.read_bytes()
        if "first" not in locals():
            first = digest
    assert first == digest
