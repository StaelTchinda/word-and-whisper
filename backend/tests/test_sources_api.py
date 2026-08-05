"""GET /sources, GET /sources/{id}, GET /sources/{id}/items[/{item_id}[/citations]].

Independent of the /suggest //prayers/{id} contract -- see
docs/PRODUCT_BOOK.md section 11 open decision 7 and prayer/api/sources.py's
module docstring.
"""
import json

import pytest


# --- /sources ----------------------------------------------------------

def test_list_sources_reports_all_three(client):
    body = client.get("/sources").json()
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["parks2021"]["record_count"] == 224
    assert by_id["lockyer1959"]["record_count"] == 347
    assert by_id["watters1883"]["record_count"] == 2483
    for info in by_id.values():
        assert info["status"] == "ok"


def test_get_one_source(client):
    body = client.get("/sources/watters1883").json()
    assert body["unit"] == "passage"
    assert body["license"] == "public_domain"


def test_unknown_source_404s(client):
    assert client.get("/sources/nope").status_code == 404
    assert client.get("/sources/nope/items").status_code == 404
    assert client.get("/sources/nope/items/x").status_code == 404


# --- redaction (F1): copyright gating on lockyer1959's own prose ------------
#
# `exposition`/`poetry`/`application_sentences` are in copyright (c. 1959
# Zondervan, see docs/datasets.md). Off by default (PRAYER_INCLUDE_COPYRIGHTED_TEXT
# unset); populated only when a deployment opts in. Never a `q` search match
# either way -- see `_lockyer_blob` in prayer/api/sources.py.

def _lockyer_first_entry_raw(settings) -> dict:
    raw_path = settings.sources_dir / "lockyer1959" / "entries.jsonl"
    raw = json.loads(raw_path.read_text().splitlines()[0])
    assert raw["id"] == "lockyer1959.0001"
    return raw


def test_lockyer_exposition_and_poetry_gated_off_by_default(settings):
    from fastapi.testclient import TestClient
    from prayer.api.app import app

    raw = _lockyer_first_entry_raw(settings)
    exposition_sentence = raw["exposition"]["paragraphs"][0]
    poetry_line = raw["poetry"][0]["text"]
    application_sentence = raw["derived"]["application_sentences"][0]

    with TestClient(app) as c:
        body = c.get("/sources/lockyer1959/items/lockyer1959.0001").json()
        serialized = json.dumps(body)
        assert exposition_sentence not in serialized
        assert poetry_line not in serialized
        assert application_sentence not in serialized
        assert body["exposition"] is None
        assert body["poetry"] == []
        assert body["application_sentences"] == []

        # a substring unique to the exposition must not be a `q` hit either
        needle = exposition_sentence[:40]
        hits = c.get("/sources/lockyer1959/items",
                     params={"q": needle, "limit": 100}).json()
        assert not any(item["id"] == "lockyer1959.0001" for item in hits["items"])


def test_lockyer_exposition_and_poetry_served_when_opted_in(monkeypatch, settings):
    """`PRAYER_INCLUDE_COPYRIGHTED_TEXT=true` is the explicit, human-owned
    opt-in for personal/local use (see .env.example) -- with it set, the same
    in-copyright prose the previous test proves is withheld by default must
    actually come through."""
    from fastapi.testclient import TestClient
    from prayer.api.app import app
    from prayer.api.config import get_settings

    raw = _lockyer_first_entry_raw(settings)
    exposition_sentence = raw["exposition"]["paragraphs"][0]
    poetry_line = raw["poetry"][0]["text"]
    application_sentence = raw["derived"]["application_sentences"][0]

    monkeypatch.setenv("PRAYER_INCLUDE_COPYRIGHTED_TEXT", "true")
    get_settings(reload=True)
    try:
        with TestClient(app) as c:
            body = c.get("/sources/lockyer1959/items/lockyer1959.0001").json()
            assert body["exposition"]["paragraphs"][0] == exposition_sentence
            assert body["poetry"][0]["text"] == poetry_line
            assert application_sentence in body["application_sentences"]

            # still never a `q` search match -- the allowlist gates search
            # independently of what the detail response happens to include
            needle = exposition_sentence[:40]
            hits = c.get("/sources/lockyer1959/items",
                         params={"q": needle, "limit": 100}).json()
            assert not any(item["id"] == "lockyer1959.0001" for item in hits["items"])
    finally:
        monkeypatch.delenv("PRAYER_INCLUDE_COPYRIGHTED_TEXT", raising=False)
        get_settings(reload=True)


def test_lockyer_detail_key_set_is_the_declared_allowlist(client):
    from prayer.api.models import LockyerItemDetail
    body = client.get("/sources/lockyer1959/items/lockyer1959.0001").json()
    assert set(body.keys()) == set(LockyerItemDetail.model_fields.keys())


# --- detail lookups ------------------------------------------------------

def test_parks_item_matches_existing_prayers_endpoint(client):
    a = client.get("/prayers/parks2021.0037").json()
    b = client.get("/sources/parks2021/items/parks2021.0037").json()
    assert a["prayer_id"] == b["id"]
    assert a["reference"]["osis"] == b["primary_ref"]


def test_mismatched_source_and_id_404s(client):
    r = client.get("/sources/parks2021/items/lockyer1959.0001")
    assert r.status_code == 404


def test_unknown_item_404s(client):
    r = client.get("/sources/parks2021/items/parks2021.9999")
    assert r.status_code == 404


# --- watters null-text passage + citations sub-resource -------------------

def test_watters_null_text_passage_has_reason_and_citations(client):
    body = client.get("/sources/watters1883/items/watters1883.psg.1Chr.14.10").json()
    assert body["text"] is None
    assert body["text_reason"]
    assert body["citation_ids"]

    citations = client.get(
        "/sources/watters1883/items/watters1883.psg.1Chr.14.10/citations").json()
    assert citations["total"] >= 1
    assert all(c["text"] for c in citations["items"])


def test_citations_sub_resource_only_exists_for_watters(client):
    r = client.get("/sources/parks2021/items/parks2021.0037/citations")
    assert r.status_code == 404


# --- pagination ------------------------------------------------------------

def test_pagination_is_stable_and_non_overlapping(client):
    page1 = client.get("/sources/watters1883/items", params={"limit": 10, "offset": 0}).json()
    page2 = client.get("/sources/watters1883/items", params={"limit": 10, "offset": 10}).json()
    assert page1["total"] == page2["total"]
    ids1 = {i["id"] for i in page1["items"]}
    ids2 = {i["id"] for i in page2["items"]}
    assert not (ids1 & ids2)
    # same call twice -> same order (deterministic, no relevance scoring)
    again = client.get("/sources/watters1883/items", params={"limit": 10, "offset": 0}).json()
    assert [i["id"] for i in page1["items"]] == [i["id"] for i in again["items"]]


def test_limit_is_bounded(client):
    assert client.get("/sources/parks2021/items", params={"limit": 0}).status_code == 422
    assert client.get("/sources/parks2021/items", params={"limit": 101}).status_code == 422


# --- filters -----------------------------------------------------------

def test_book_filter(client):
    body = client.get("/sources/parks2021/items",
                      params={"book": "Gen", "limit": 100}).json()
    assert body["total"] > 0


def test_canon_filter_excludes_other_canons(client):
    body = client.get("/sources/lockyer1959/items",
                      params={"canon": "NT", "limit": 100}).json()
    assert body["items"]
    assert all(i["canon_section"] == "NT" for i in body["items"])


def test_parks_context_filter(client):
    body = client.get("/sources/parks2021/items",
                      params={"context": "communal", "limit": 100}).json()
    assert body["items"]
    detail = client.get(f"/sources/parks2021/items/{body['items'][0]['id']}").json()
    assert detail["context"] == "communal"


def test_lockyer_book_section_filter(client):
    body = client.get("/sources/lockyer1959/items",
                      params={"book_section": "Genesis", "limit": 100}).json()
    assert body["items"]


def test_watters_facet_filter(client):
    body = client.get("/sources/watters1883/items",
                      params={"facet": "neglect", "limit": 100}).json()
    assert body["items"]
    assert all("neglect" in i["labels"] for i in body["items"])


# --- unit-level: loader correctness against sources_store fixture --------

def test_sources_store_loads_all_three(sources_store):
    assert sources_store["parks2021"].status == "ok"
    assert sources_store["lockyer1959"].status == "ok"
    assert sources_store["watters1883"].status == "ok"
    assert len(sources_store["parks2021"].items) == 224
    assert len(sources_store["lockyer1959"].items) == 347
    assert len(sources_store["watters1883"].items) == 2483


def test_watters_ids_are_unique_and_path_safe(sources_store):
    ids = [item.id for item in sources_store["watters1883"].items]
    assert len(ids) == len(set(ids))
    assert all("/" not in i and "?" not in i for i in ids)


# --- table of contents ------------------------------------------------------

def _toc_all_item_ids(sections: list[dict]) -> list[str]:
    return [item["id"]
            for section in sections
            for subsection in section["subsections"]
            for item in subsection["items"]]


def test_unknown_source_toc_404s(client):
    assert client.get("/sources/nope/toc").status_code == 404


def test_parks_toc_groups_by_canon_then_book_and_covers_every_item(client):
    body = client.get("/sources/parks2021/toc").json()
    assert body["source_id"] == "parks2021"
    section_ids = [s["id"] for s in body["sections"]]
    canon_order = ["OT", "DC", "NT"]
    assert section_ids == [c for c in canon_order if c in section_ids]

    genesis = next(sub for s in body["sections"] for sub in s["subsections"]
                   if sub["label"] == "Genesis")
    assert genesis["items"]
    assert all(i["title"] for i in genesis["items"])

    ids = _toc_all_item_ids(body["sections"])
    assert len(ids) == len(set(ids)) == 224  # every parks item appears exactly once


def test_lockyer_toc_groups_by_book_section(client):
    body = client.get("/sources/lockyer1959/toc").json()
    genesis = next(sub for s in body["sections"] for sub in s["subsections"]
                   if sub["id"] == "Genesis")
    assert genesis["items"]
    ids = _toc_all_item_ids(body["sections"])
    assert len(ids) == len(set(ids)) == 347


def test_lockyer_toc_includes_books_with_no_recorded_prayers(client):
    """Leviticus has no recorded prayers -- Lockyer's introduction to it is
    the only content the book gives, and it must still appear in the TOC
    (empty, but present) rather than silently vanishing. See
    prayer.api.sources._build_toc_by_book's `empty_sections`."""
    body = client.get("/sources/lockyer1959/toc").json()
    leviticus = next((sub for s in body["sections"] for sub in s["subsections"]
                      if sub["id"] == "Leviticus"), None)
    assert leviticus is not None, "Leviticus dropped out of the lockyer1959 TOC"
    assert leviticus["items"] == []
    assert leviticus["book_section_id"]

    detail = client.get(
        f"/sources/lockyer1959/book-sections/{leviticus['book_section_id']}").json()
    assert detail["has_prayers"] is False
    assert detail["book_section"] == "Leviticus"


def test_watters_toc_nests_chapter_then_topic_then_subtopic(client):
    """Watters' chapters ("Who Prayed", "Duty of Prayer", ...) are topical and
    cut across canon/Bible book, so the toc has one flat run of chapters
    rather than an OT/DC/NT split, each chapter nesting its own topic/subtopic
    outline -- see prayer.api.sources._build_toc_watters."""
    body = client.get("/sources/watters1883/toc").json()
    assert body["source_id"] == "watters1883"
    assert [s["id"] for s in body["sections"]] == ["chapters"]

    chapters = body["sections"][0]["subsections"]
    chapter_ns = [int(sub["id"]) for sub in chapters]
    assert chapter_ns == sorted(chapter_ns)
    assert chapter_ns[0] == 1

    first = chapters[0]
    assert first["label"] == "I. Who Prayed"
    assert first["items"] == []  # a chapter holds topics, not passages, directly
    assert first["children"], "chapter I carries no topics"

    topic = first["children"][0]
    assert topic["label"]
    # a topic either lists passages directly, or nests subtopics that do
    assert topic["items"] or topic["children"]
    if topic["children"]:
        subtopic = topic["children"][0]
        assert subtopic["items"]
        assert all(i["ref_display"] and i["title"] is None for i in subtopic["items"])

    # a passage cited under more than one topic in the original book is
    # listed under each of them
    by_item: dict[str, set] = {}
    for chapter in chapters:
        for topic in chapter["children"]:
            for item in topic["items"]:
                by_item.setdefault(item["id"], set()).add(topic["id"])
            for sub in topic["children"]:
                for item in sub["items"]:
                    by_item.setdefault(item["id"], set()).add(sub["id"])
    assert any(len(paths) > 1 for paths in by_item.values())


# --- watters1883: the rest of the book (public domain, no gating) ---------

def test_watters_front_and_back_matter(client):
    front = client.get("/sources/watters1883/front-matter").json()
    assert front["paragraphs"]
    back = client.get("/sources/watters1883/back-matter").json()
    assert back["paragraphs"] or back["headings"]


def test_watters_editorial_notes_include_page_markers(client):
    notes = client.get("/sources/watters1883/editorial-notes",
                       params={"kind": "page_marker"}).json()
    assert notes
    assert all(n["kind"] == "page_marker" and n["page"] for n in notes)


def test_watters_citation_carries_inline_notes_and_see_also(client):
    """`body_prose.jsonl` entries that continue on from a citation, and
    cross-reference targets drawn from a citation's own back-reference, are
    threaded onto that citation rather than left as disconnected lists."""
    found_note = found_see_also = False
    for offset in range(0, 500, 100):
        page = client.get("/sources/watters1883/items",
                          params={"limit": 100, "offset": offset}).json()
        for summary in page["items"]:
            citations = client.get(
                f"/sources/watters1883/items/{summary['id']}/citations").json()["items"]
            found_note = found_note or any(c["notes"] for c in citations)
            found_see_also = found_see_also or any(c["see_also"] for c in citations)
        if found_note and found_see_also:
            break
    assert found_note, "no citation carried an attached note"
    assert found_see_also, "no citation carried a see_also target"
