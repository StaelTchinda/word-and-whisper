#!/usr/bin/env python3
"""Read-only browse/search surface over the three raw extracted sources.

Independent of prayer.api.corpus.Corpus: this loads directly from
data/build/datasets/sources/<source_id>/ and never touches the retrieval
pipeline, PrayerRecord, or the /suggest //prayers/{id} contract. Merging the
sources into the retrieval corpus is a separate, deferred, human-owned
decision (docs/PRODUCT_BOOK.md section 11, open decision 7) -- this module
must not make that call by accident.

Lockyer's `exposition`, `poetry`, and `derived.application_sentences` fields
are in-copyright (c. 1959 Zondervan; see docs/datasets.md). The loader below
never reads them into a servable field -- only into the has_exposition /
has_poetry / exposition_paragraph_count counters -- so the redaction boundary
is enforced by the shape of LockyerItemDetail itself (an allowlist), not by
remembering to strip fields later.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query

from prayer.api.models import (CanonSection, CitationsResponse,
                        LockyerItemDetail, LockyerScriptureQuote,
                        ParksItemDetail, SearchResponse, SourceInfo,
                        SourceItemDetail, SourceItemSummary, SourceRef,
                        SourcesResponse, WattersCitation,
                        WattersPassageDetail, WattersTopicTag)
from prayer.refs.bible_books import BOOKS

log = logging.getLogger("prayer.api.sources")

OSIS_TO_CANON = {book.osis: book.canon for book in BOOKS.values()}

SOURCE_META: dict[str, dict] = {
    "parks2021": dict(
        display_name="All the Prayers in the Bible (Parks, 2021)",
        unit="prayer", license="proprietary", text_includable=False),
    "lockyer1959": dict(
        display_name="All the Prayers of the Bible (Lockyer, 1959)",
        unit="entry", license="in_copyright", text_includable=True),
    "watters1883": dict(
        display_name="The Prayers of the Bible (Watters, 1883)",
        unit="passage", license="public_domain", text_includable=True),
}


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _ref_display(primary_ref: Optional[str], refs: list[SourceRef]) -> str:
    return refs[0].raw if refs else (primary_ref or "")


# --- per-source loaders ------------------------------------------------

def _load_parks(source_dir: Path) -> tuple[list[ParksItemDetail], dict]:
    rows = _read_jsonl(source_dir / "prayers.jsonl")
    items = [
        ParksItemDetail(
            id=r["id"], title=r["title"], slug=r["slug"],
            canon_section=r["canon_section"],
            refs=[SourceRef(**ref) for ref in r["refs"]],
            primary_ref=r["primary_ref"], verse_count=r.get("verse_count"),
            speaker=r["speaker"], addressee=r["addressee"], context=r["context"],
            contents=r.get("contents", []), places=r.get("places", []),
            related_pericopes=r.get("related_pericopes", []),
        )
        for r in rows
    ]
    return items, {}


def _load_lockyer(source_dir: Path) -> tuple[list[LockyerItemDetail], dict]:
    rows = _read_jsonl(source_dir / "entries.jsonl")
    items = []
    for r in rows:
        exposition = r.get("exposition") or {}
        poetry = r.get("poetry") or []
        items.append(LockyerItemDetail(
            id=r["id"], entry_type=r["entry_type"], title=r["title"],
            title_raw=r["title_raw"], slug=r["slug"],
            canon_section=r["canon_section"], book_section=r["book_section"],
            refs=[SourceRef(**ref) for ref in r.get("refs", [])],
            primary_ref=r.get("primary_ref"), ref_raw=r.get("ref_raw"),
            scripture_quotes=[
                LockyerScriptureQuote(
                    position=q["position"], text=q["text"],
                    attribution_raw=q["attribution_raw"], osis=q["osis"])
                for q in r.get("scripture_quotes", [])
            ],
            has_exposition=bool(exposition.get("paragraphs")),
            has_poetry=bool(poetry),
            exposition_paragraph_count=len(exposition.get("paragraphs", [])),
        ))
    return items, {}


def _load_watters(source_dir: Path) -> tuple[list[WattersPassageDetail], dict[str, list[WattersCitation]]]:
    passage_rows = _read_jsonl(source_dir / "passages.jsonl")
    citation_rows = _read_jsonl(source_dir / "citations.jsonl")
    citations_by_id = {c["id"]: c for c in citation_rows}

    items = []
    citations_by_passage: dict[str, list[WattersCitation]] = {}
    for r in passage_rows:
        item_id = f"watters1883.psg.{r['osis']}"
        cids = r.get("citation_ids", [])
        text_reason = None
        if r.get("text") is None:
            text_reason = ("text spans multiple references and cannot be "
                          "attributed to this passage alone; see the linked citations")
        items.append(WattersPassageDetail(
            id=item_id, osis=r["osis"], book=r["book"],
            canon_section=OSIS_TO_CANON.get(r["book"]),
            text=r.get("text"), text_is_exact=r["text_is_exact"],
            text_reason=text_reason,
            n_citations=r["n_citations"], citation_ids=cids,
            topics=[WattersTopicTag(**t) for t in r.get("topics", [])],
            facets=r.get("facets", []),
        ))
        citations_by_passage[item_id] = [
            WattersCitation(
                id=cid, chapter_n=c["chapter_n"], chapter_title=c["chapter_title"],
                facet=c["facet"], topic=c["topic"], subtopic=c.get("subtopic"),
                ref_raw=c["ref_raw"], primary_ref=c["primary_ref"],
                text=c.get("text"), text_source=c["text_source"], page=c.get("page"),
            )
            for cid in cids
            for c in [citations_by_id[cid]]
        ]
    return items, citations_by_passage


_LOADERS: dict[str, Callable[[Path], tuple[list, dict]]] = {
    "parks2021": _load_parks,
    "lockyer1959": _load_lockyer,
    "watters1883": _load_watters,
}


# --- per-source search-text allowlists --------------------------------
#
# `q` matches only against these fields, never against raw source rows --
# keeps Lockyer's in-copyright exposition/poetry/derived text unsearchable
# even if a future extractor change adds new fields to entries.jsonl.

def _parks_blob(item: ParksItemDetail) -> str:
    return " ".join([item.title, item.context, " ".join(item.contents),
                     " ".join(item.places), item.speaker.raw, item.addressee.raw])


def _lockyer_blob(item: LockyerItemDetail) -> str:
    return " ".join([item.title, item.title_raw, item.book_section,
                     " ".join(q.text for q in item.scripture_quotes)])


def _watters_blob(item: WattersPassageDetail) -> str:
    return " ".join([item.text or "", item.book,
                     " ".join(t.path for t in item.topics), " ".join(item.facets)])


_BLOB_BUILDERS: dict[str, Callable] = {
    "parks2021": _parks_blob,
    "lockyer1959": _lockyer_blob,
    "watters1883": _watters_blob,
}


# --- summaries -------------------------------------------------------------

def _summary(item) -> SourceItemSummary:
    if isinstance(item, ParksItemDetail):
        return SourceItemSummary(
            id=item.id, source_id=item.source_id, unit=item.unit, title=item.title,
            primary_ref=item.primary_ref,
            ref_display=_ref_display(item.primary_ref, item.refs),
            canon_section=item.canon_section, labels=list(item.contents))
    if isinstance(item, LockyerItemDetail):
        return SourceItemSummary(
            id=item.id, source_id=item.source_id, unit=item.unit, title=item.title,
            primary_ref=item.primary_ref,
            ref_display=_ref_display(item.primary_ref, item.refs),
            canon_section=item.canon_section, labels=[item.book_section])
    if isinstance(item, WattersPassageDetail):
        return SourceItemSummary(
            id=item.id, source_id=item.source_id, unit=item.unit, title=None,
            primary_ref=item.osis, ref_display=item.osis,
            canon_section=item.canon_section, labels=list(item.facets))
    raise TypeError(f"unhandled item type {type(item)!r}")


# --- store -------------------------------------------------------------

@dataclass
class SourceStore:
    source_id: str
    status: str  # "ok" | "unavailable"
    detail: Optional[str] = None
    items: list = field(default_factory=list)
    by_id: dict = field(default_factory=dict)
    citations_by_passage: dict = field(default_factory=dict)
    _search_blobs: Optional[dict] = field(default=None, init=False, repr=False)

    def blobs(self) -> dict:
        if self._search_blobs is None:
            builder = _BLOB_BUILDERS[self.source_id]
            self._search_blobs = {item.id: builder(item).casefold() for item in self.items}
        return self._search_blobs


def load_sources(sources_dir: Path) -> dict[str, SourceStore]:
    """Load each source independently; one source failing to parse must not
    take the others down (mirrors the degrade-not-crash pattern in
    api/app.py's lifespan)."""
    stores: dict[str, SourceStore] = {}
    for source_id, loader in _LOADERS.items():
        try:
            items, citations_by_passage = loader(sources_dir / source_id)
            stores[source_id] = SourceStore(
                source_id=source_id, status="ok",
                items=items, by_id={i.id: i for i in items},
                citations_by_passage=citations_by_passage)
        except Exception as exc:  # not-yet-built source must not crash the app
            log.error("failed to load source %s: %s", source_id, exc)
            stores[source_id] = SourceStore(
                source_id=source_id, status="unavailable",
                detail=f"{type(exc).__name__}: {exc}")
    return stores


# --- router ------------------------------------------------------------

router = APIRouter(prefix="/sources", tags=["sources"])

_stores: dict[str, SourceStore] = {}


def set_stores(stores: dict[str, SourceStore]) -> None:
    global _stores
    _stores = stores


def _store_or_404(source_id: str) -> SourceStore:
    store = _stores.get(source_id)
    if store is None:
        raise HTTPException(404, detail=f"no source {source_id!r}; "
                            f"available: {sorted(_stores)}")
    return store


def _loaded_store(source_id: str) -> SourceStore:
    store = _store_or_404(source_id)
    if store.status != "ok":
        raise HTTPException(503, detail=f"source {source_id!r} not loaded: {store.detail}")
    return store


def _source_info(source_id: str, store: SourceStore) -> SourceInfo:
    return SourceInfo(id=source_id, status=store.status, detail=store.detail,
                      record_count=len(store.items), **SOURCE_META[source_id])


@router.get("", response_model=SourcesResponse)
def list_sources() -> SourcesResponse:
    return SourcesResponse(sources=[
        _source_info(sid, store) for sid, store in sorted(_stores.items())
    ])


@router.get("/{source_id}", response_model=SourceInfo)
def get_source(source_id: str) -> SourceInfo:
    return _source_info(source_id, _store_or_404(source_id))


def _item_matches(source_id: str, item, *, book: Optional[str], canon: Optional[CanonSection],
                  q_tokens: list[str], blob: str, context: Optional[str],
                  content: Optional[str], speaker: Optional[str],
                  book_section: Optional[str], has_quote: Optional[bool],
                  facet: Optional[str], topic: Optional[str],
                  has_text: Optional[bool]) -> bool:
    if book is not None:
        refs = getattr(item, "refs", None)
        if refs is not None:
            if not any(r.book == book for r in refs):
                return False
        elif getattr(item, "book", None) != book:
            return False
    if canon is not None and item.canon_section != canon:
        return False
    if q_tokens and not all(tok in blob for tok in q_tokens):
        return False

    if source_id == "parks2021":
        if context is not None and item.context != context:
            return False
        if content is not None and content not in item.contents:
            return False
        if speaker is not None and speaker.casefold() not in item.speaker.raw.casefold():
            return False
    elif source_id == "lockyer1959":
        if book_section is not None and item.book_section != book_section:
            return False
        if has_quote is not None and bool(item.scripture_quotes) != has_quote:
            return False
    elif source_id == "watters1883":
        if facet is not None and facet not in item.facets:
            return False
        if topic is not None and not any(t.path == topic for t in item.topics):
            return False
        if has_text is not None and (item.text is not None) != has_text:
            return False
    return True


@router.get("/{source_id}/items", response_model=SearchResponse)
def search_items(
    source_id: str,
    q: Optional[str] = Query(default=None, description="case-folded token match over a per-source text allowlist"),
    book: Optional[str] = Query(default=None, description="OSIS book code, e.g. Gen"),
    canon: Optional[CanonSection] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    context: Optional[str] = Query(default=None, description="parks2021 only"),
    content: Optional[str] = Query(default=None, description="parks2021 only"),
    speaker: Optional[str] = Query(default=None, description="parks2021 only"),
    book_section: Optional[str] = Query(default=None, description="lockyer1959 only"),
    has_quote: Optional[bool] = Query(default=None, description="lockyer1959 only"),
    facet: Optional[str] = Query(default=None, description="watters1883 only"),
    topic: Optional[str] = Query(default=None, description="watters1883 only"),
    has_text: Optional[bool] = Query(default=None, description="watters1883 only"),
) -> SearchResponse:
    store = _loaded_store(source_id)
    q_tokens = q.casefold().split() if q else []
    blobs = store.blobs() if q_tokens else {}

    filtered = [
        item for item in store.items
        if _item_matches(source_id, item, book=book, canon=canon, q_tokens=q_tokens,
                         blob=blobs.get(item.id, ""), context=context, content=content,
                         speaker=speaker, book_section=book_section, has_quote=has_quote,
                         facet=facet, topic=topic, has_text=has_text)
    ]
    page = filtered[offset:offset + limit]
    return SearchResponse(total=len(filtered), limit=limit, offset=offset,
                          items=[_summary(item) for item in page])


@router.get("/{source_id}/items/{item_id}", response_model=SourceItemDetail)
def get_item(source_id: str, item_id: str):
    store = _loaded_store(source_id)
    item = store.by_id.get(item_id)
    if item is None:
        raise HTTPException(404, detail=f"no item {item_id!r} in source {source_id!r}")
    return item


@router.get("/watters1883/items/{item_id}/citations", response_model=CitationsResponse)
def get_watters_citations(item_id: str) -> CitationsResponse:
    store = _loaded_store("watters1883")
    if item_id not in store.by_id:
        raise HTTPException(404, detail=f"no item {item_id!r} in source 'watters1883'")
    citations = store.citations_by_passage.get(item_id, [])
    return CitationsResponse(total=len(citations), items=citations)
