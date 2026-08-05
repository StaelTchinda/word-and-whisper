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


# --- redaction (F1): the whole reason this is a separate, allowlisted model set --

def test_lockyer_exposition_and_poetry_never_served(settings):
    """lockyer1959's exposition/poetry/derived fields are in copyright
    (c. 1959 Zondervan, see docs/datasets.md) and must never leave the API,
    either in the detail response or as a `q` search match."""
    from fastapi.testclient import TestClient
    from prayer.api.app import app

    raw_path = settings.sources_dir / "lockyer1959" / "entries.jsonl"
    raw = json.loads(raw_path.read_text().splitlines()[0])
    assert raw["id"] == "lockyer1959.0001"
    exposition_sentence = raw["exposition"]["paragraphs"][0]
    poetry_line = raw["poetry"][0]["text"]
    application_sentence = raw["derived"]["application_sentences"][0]

    with TestClient(app) as c:
        body = c.get("/sources/lockyer1959/items/lockyer1959.0001").json()
        serialized = json.dumps(body)
        assert exposition_sentence not in serialized
        assert poetry_line not in serialized
        assert application_sentence not in serialized
        assert "exposition" not in body
        assert "poetry" not in body
        assert "derived" not in body

        # a substring unique to the exposition must not be a `q` hit either
        needle = exposition_sentence[:40]
        hits = c.get("/sources/lockyer1959/items",
                     params={"q": needle, "limit": 100}).json()
        assert not any(item["id"] == "lockyer1959.0001" for item in hits["items"])


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


def test_watters_toc_is_chapters_not_canon(client):
    """Watters' chapters ("Who Prayed", "Duty of Prayer", ...) are topical and
    cut across canon/Bible book, so the toc has one flat run of chapters
    rather than an OT/DC/NT split -- see prayer.api.sources._build_toc_watters."""
    body = client.get("/sources/watters1883/toc").json()
    assert body["source_id"] == "watters1883"
    assert [s["id"] for s in body["sections"]] == ["chapters"]

    subsections = body["sections"][0]["subsections"]
    chapter_ns = [int(sub["id"]) for sub in subsections]
    assert chapter_ns == sorted(chapter_ns)
    assert chapter_ns[0] == 1

    first = subsections[0]
    assert first["label"] == "I. Who Prayed"
    assert first["items"]
    assert all(i["ref_display"] and i["title"] is None for i in first["items"])

    # a passage cited from more than one chapter of the original book is
    # listed under each of them
    by_item = {}
    for sub in subsections:
        for item in sub["items"]:
            by_item.setdefault(item["id"], set()).add(sub["id"])
    assert any(len(chs) > 1 for chs in by_item.values())
