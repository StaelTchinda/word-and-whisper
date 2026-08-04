"""M0 DoD: the app serves, /config reports registered components."""


def test_health_reports_corpus(client):
    body = client.get("/health").json()
    assert body["corpus_loaded"] is True
    assert body["prayers"] == 224


def test_config_lists_components_and_defaults(client):
    body = client.get("/config").json()
    assert body["defaults"]["translation"] == "WEB"
    assert isinstance(body["retrievers"], list)
    assert isinstance(body["composers"], list)
    # Whatever is registered, the free composer stays hidden while the config
    # flag is off (PRODUCT_BOOK section 5.5).
    assert "free" not in [c["name"] for c in body["composers"]]


def test_prayer_detail(client):
    body = client.get("/prayers/parks2021.0037").json()
    assert body["prayer_id"] == "parks2021.0037"
    assert body["reference"]["translation"] == "WEB"


def test_unknown_prayer_404s(client):
    assert client.get("/prayers/nope.9999").status_code == 404


# --- /suggest ---------------------------------------------------------------

def test_suggest_returns_a_complete_response(client):
    body = client.post("/suggest", json={
        "situation": "I've been trying for a child for four years and I'm losing hope.",
        "k": 2}).json()
    assert body["abstained"] is False
    assert body["safety"]["status"] == "ok"
    assert 1 <= len(body["suggestions"]) <= 2
    first = body["suggestions"][0]
    assert first["spoken_prayer"]["text"]
    assert first["reference"]["translation"] == "WEB"
    assert first["match"]["matched_on"]
    assert body["timings"]["total_ms"] >= 0


def test_suggest_crisis_path(client):
    body = client.post("/suggest", json={
        "situation": "I don't want to live anymore and I don't know who to tell."}).json()
    assert body["safety"]["status"] == "crisis"
    assert body["safety"]["notice"]
    assert body["query"]["composer"] == "deterministic"


def test_suggest_rejects_unknown_retriever(client):
    r = client.post("/suggest", json={"situation": "I am afraid.",
                                      "retriever": "nope"})
    assert r.status_code == 400
    assert "available" in r.json()["detail"]


def test_free_composer_is_rejected_while_disabled(client):
    r = client.post("/suggest", json={"situation": "I am afraid.",
                                      "composer": "free"})
    assert r.status_code == 400


def test_suggest_rejects_unbundled_translation(client):
    r = client.post("/suggest", json={"situation": "I am afraid.",
                                      "translation": "NIV"})
    assert r.status_code == 400


def test_canon_filter_excludes_deuterocanon(client):
    body = client.post("/suggest", json={
        "situation": "I am asking God to protect my family from danger.",
        "k": 5, "canon": ["OT", "NT"]}).json()
    for suggestion in body["suggestions"]:
        assert suggestion["labels"]["canon_section"] in ("OT", "NT")


def test_situation_length_is_validated(client):
    assert client.post("/suggest", json={"situation": "no"}).status_code == 422
    assert client.post("/suggest", json={"situation": "x" * 1001}).status_code == 422


def test_include_passage_text_can_be_turned_off(client):
    body = client.post("/suggest", json={"situation": "I am afraid of what comes next.",
                                         "k": 1, "include_passage_text": False}).json()
    if body["suggestions"]:
        assert body["suggestions"][0]["passage_text"] is None
