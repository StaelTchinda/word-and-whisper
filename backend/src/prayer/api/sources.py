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
only ever reads them into a servable field when `Settings.include_copyrighted_text`
is on (default off) -- see `_lockyer_exposition` / `_lockyer_poetry`. They are
never indexed for `q` search regardless of that setting.
"""
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Query

from prayer.api.models import (CanonSection, CitationsResponse,
                        LockyerBookSection, LockyerBookSectionsResponse,
                        LockyerExposition, LockyerItemDetail,
                        LockyerOutlinePoint, LockyerPoem,
                        LockyerScriptureQuote, ParksItemDetail,
                        SearchResponse, SourceInfo, SourceItemDetail,
                        SourceItemSummary, SourceRef, SourcesResponse,
                        TocItem, TocResponse, TocSection, TocSubsection,
                        WattersBackMatter, WattersCitation,
                        WattersCrossReference, WattersEditorialNote,
                        WattersFrontMatter, WattersPassageDetail,
                        WattersTopicTag)
from prayer.refs.bible_books import BOOKS

log = logging.getLogger("prayer.api.sources")

OSIS_TO_CANON = {book.osis: book.canon for book in BOOKS.values()}

# BOOKS.values() is already in canonical reading order (OT, then DC, then NT,
# each book in scripture order) -- reuse that order for the TOC instead of
# re-deriving it.
CANON_ORDER = ["OT", "DC", "NT"]
CANON_LABELS = {"OT": "Old Testament", "DC": "Deuterocanon", "NT": "New Testament"}
BOOK_ORDER = {book.osis: i for i, book in enumerate(BOOKS.values())}

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

def _load_parks(source_dir: Path, include_copyrighted: bool) -> tuple[list[ParksItemDetail], dict, dict]:
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
    return items, {}, {}


def _lockyer_exposition(exposition: dict, include_copyrighted: bool) -> Optional[LockyerExposition]:
    if not include_copyrighted or not exposition.get("paragraphs"):
        return None
    return LockyerExposition(
        paragraphs=exposition["paragraphs"], word_count=exposition.get("word_count", 0),
        outline=[LockyerOutlinePoint(**o) for o in exposition.get("outline", [])])


def _lockyer_poetry(poetry: list[dict], include_copyrighted: bool) -> list[LockyerPoem]:
    if not include_copyrighted:
        return []
    return [LockyerPoem(**p) for p in poetry]


def _load_lockyer(source_dir: Path, include_copyrighted: bool) -> tuple[list[LockyerItemDetail], dict, dict]:
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
            exposition=_lockyer_exposition(exposition, include_copyrighted),
            poetry=_lockyer_poetry(poetry, include_copyrighted),
            application_sentences=(r.get("derived", {}).get("application_sentences", [])
                                   if include_copyrighted else []),
            page=(r.get("page") or {}).get("original"),
        ))

    book_sections: dict[str, LockyerBookSection] = {}
    sections_path = source_dir / "book_sections.jsonl"
    if sections_path.exists():
        for r in _read_jsonl(sections_path):
            intro = r.get("intro") or {}
            book_sections[r["id"]] = LockyerBookSection(
                id=r["id"], book=r.get("book"), book_section=r["book_section"],
                canon_section=r["canon_section"], has_prayers=r["has_prayers"],
                n_prayer_entries=r["n_prayer_entries"],
                has_intro=bool(intro.get("paragraphs")),
                intro_word_count=intro.get("word_count", 0),
                intro=_lockyer_exposition(intro, include_copyrighted),
                poetry=_lockyer_poetry(r.get("poetry", []), include_copyrighted),
            )
    return items, {}, {"book_sections": book_sections}


def _load_watters(source_dir: Path, include_copyrighted: bool) -> tuple[list[WattersPassageDetail], dict[str, list[WattersCitation]], dict]:
    passage_rows = _read_jsonl(source_dir / "passages.jsonl")
    citation_rows = _read_jsonl(source_dir / "citations.jsonl")
    citations_by_id = {c["id"]: c for c in citation_rows}

    # body_prose.jsonl entries that continue straight on from a citation
    # (`attaches_to`), and cross_references.jsonl edges drawn from a citation's
    # own back-reference -- both public domain, so both always shown, threaded
    # back onto the citation they followed in the source rather than left as
    # disconnected lists.
    notes_by_citation: dict[str, list[str]] = defaultdict(list)
    for p in _read_jsonl(source_dir / "body_prose.jsonl") if (source_dir / "body_prose.jsonl").exists() else []:
        if p.get("attaches_to"):
            notes_by_citation[p["attaches_to"]].append(p["text"])
    see_also_by_citation: dict[str, str] = {}
    xref_rows = (_read_jsonl(source_dir / "cross_references.jsonl")
                if (source_dir / "cross_references.jsonl").exists() else [])
    for x in xref_rows:
        if x.get("from_citation_id") and x.get("to_topic_raw"):
            see_also_by_citation[x["from_citation_id"]] = x["to_topic_raw"]

    def _citation(c: dict) -> WattersCitation:
        return WattersCitation(
            id=c["id"], chapter_n=c["chapter_n"], chapter_title=c["chapter_title"],
            facet=c["facet"], topic=c["topic"], subtopic=c.get("subtopic"),
            ref_raw=c["ref_raw"], primary_ref=c["primary_ref"],
            text=c.get("text"), text_source=c["text_source"], page=c.get("page"),
            notes=notes_by_citation.get(c["id"], []),
            see_also=see_also_by_citation.get(c["id"]),
        )

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
        citations_by_passage[item_id] = [_citation(citations_by_id[cid]) for cid in cids]

    # The original book's own chapters (data/build/datasets/sources/watters1883/
    # chapters.jsonl) -- Watters is organised topically ("Who Prayed", "Duty of
    # Prayer", ...), not by canon or Bible book, so this is the source's real
    # table of contents. Keyed by chapter_n to match passages[].topics[].chapter_n.
    chapters = {
        r["chapter_n"]: {"title": r["title"], "roman": r.get("roman")}
        for r in _read_jsonl(source_dir / "chapters.jsonl")
    }
    topics = _read_jsonl(source_dir / "topics.jsonl") if (source_dir / "topics.jsonl").exists() else []

    front_path = source_dir / "front_matter.jsonl"
    front_rows = _read_jsonl(front_path) if front_path.exists() else []
    back_path = source_dir / "back_matter.jsonl"
    back_rows = _read_jsonl(back_path) if back_path.exists() else []
    notes_path = source_dir / "editorial_notes.jsonl"
    editorial_notes = _read_jsonl(notes_path) if notes_path.exists() else []
    # Bare "(See Other Topic)" pointers under a topic heading, not tied to any
    # one citation -- the ones with a `from_citation_id` are already folded
    # onto that citation's `see_also` above.
    bare_cross_refs = [x for x in xref_rows if not x.get("from_citation_id")]

    return items, citations_by_passage, {
        "chapters": chapters, "topics": topics,
        "front_matter": front_rows[0] if front_rows else None,
        "back_matter": back_rows[0] if back_rows else None,
        "editorial_notes": editorial_notes,
        "cross_references": bare_cross_refs,
    }


_LOADERS: dict[str, Callable[[Path, bool], tuple[list, dict, dict]]] = {
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
    extra: dict = field(default_factory=dict)
    _search_blobs: Optional[dict] = field(default=None, init=False, repr=False)

    def blobs(self) -> dict:
        if self._search_blobs is None:
            builder = _BLOB_BUILDERS[self.source_id]
            self._search_blobs = {item.id: builder(item).casefold() for item in self.items}
        return self._search_blobs


def load_sources(sources_dir: Path, include_copyrighted: bool = False) -> dict[str, SourceStore]:
    """Load each source independently; one source failing to parse must not
    take the others down (mirrors the degrade-not-crash pattern in
    api/app.py's lifespan)."""
    stores: dict[str, SourceStore] = {}
    for source_id, loader in _LOADERS.items():
        try:
            items, citations_by_passage, extra = loader(sources_dir / source_id, include_copyrighted)
            stores[source_id] = SourceStore(
                source_id=source_id, status="ok",
                items=items, by_id={i.id: i for i in items},
                citations_by_passage=citations_by_passage, extra=extra)
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


# --- table of contents ---------------------------------------------------
#
# One pre-grouped tree per source, following each source's own structure
# rather than one scheme applied uniformly -- see docs on TocResponse.

def _toc_item(item) -> TocItem:
    if isinstance(item, WattersPassageDetail):
        return TocItem(id=item.id, ref_display=item.osis)
    return TocItem(id=item.id, title=item.title,
                    ref_display=_ref_display(getattr(item, "primary_ref", None), item.refs),
                    page=getattr(item, "page", None))


def _build_toc_by_book(store: SourceStore, *, group_key: Callable, group_label: Callable,
                       empty_sections: Optional[dict[str, LockyerBookSection]] = None
                       ) -> list[TocSection]:
    """Parks/Lockyer: canon -> Bible book (Parks) or the book_section the
    source itself organises by (Lockyer). Both are already presented in
    scripture order in their source books, so canon is the natural top
    level.

    `empty_sections` (Lockyer only): book_sections.jsonl keyed by
    `book_section`, so a book with zero recorded prayers still gets a
    subsection -- with no items, but a `book_section_id` pointing at its
    introduction (Lockyer's own note on why, e.g. Leviticus or Esther)."""
    grouped: dict[str, dict[str, list]] = {c: {} for c in CANON_ORDER}
    labels: dict[tuple[str, str], str] = {}
    order_keys: dict[tuple[str, str], int] = {}
    for item in store.items:
        canon = item.canon_section
        key = group_key(item)
        bucket = grouped.setdefault(canon, {})
        bucket.setdefault(key, []).append(item)
        labels.setdefault((canon, key), group_label(item))
        book = item.refs[0].book if getattr(item, "refs", None) else None
        order_key = BOOK_ORDER.get(book, len(BOOK_ORDER))
        order_keys[(canon, key)] = min(order_key, order_keys.get((canon, key), order_key))

    section_by_book: dict[str, LockyerBookSection] = {}
    if empty_sections:
        for sec in empty_sections.values():
            section_by_book[sec.book_section] = sec
            if sec.n_prayer_entries == 0:
                canon, key = sec.canon_section, sec.book_section
                grouped.setdefault(canon, {}).setdefault(key, [])
                labels.setdefault((canon, key), key)
                order_key = BOOK_ORDER.get(sec.book, len(BOOK_ORDER))
                order_keys[(canon, key)] = min(order_key, order_keys.get((canon, key), order_key))

    sections = []
    for canon in CANON_ORDER:
        books = grouped.get(canon) or {}
        if not books:
            continue
        subsections = [
            TocSubsection(id=key, label=labels[(canon, key)],
                          items=[_toc_item(i) for i in books[key]],
                          book_section_id=(section_by_book[key].id if key in section_by_book else None))
            for key in sorted(books, key=lambda k: order_keys[(canon, k)])
        ]
        sections.append(TocSection(id=canon, label=CANON_LABELS[canon], subsections=subsections))
    return sections


def _build_toc_watters(store: SourceStore) -> list[TocSection]:
    """Watters is organised topically ("Who Prayed", "Duty of Prayer", ...)
    and each chapter cuts across canon/book, so canon grouping doesn't apply
    here -- the chapters themselves (data/build/datasets/sources/watters1883/
    chapters.jsonl, loaded into store.extra) are the source's real table of
    contents, nested chapter -> topic -> subtopic using topics.jsonl. A
    passage can belong to more than one topic (it may be cited in more than
    one place in the original book) and is listed under each."""
    chapters: dict[int, dict] = store.extra.get("chapters", {})
    topic_rows: list[dict] = store.extra.get("topics", [])
    items_by_id = {i.id: i for i in store.items}

    # citation -> passage item, so a topic (which only knows citation_ids) can
    # list the passages its citations point at.
    passage_by_citation: dict[str, str] = {}
    for item_id, cites in store.citations_by_passage.items():
        for c in cites:
            passage_by_citation[c.id] = item_id

    if not topic_rows:
        # Fallback for an older sources.jsonl layout without topics.jsonl:
        # flatten straight to chapter -> passages, as before.
        by_chapter: dict[int, list] = {n: [] for n in chapters}
        for item in store.items:
            seen = set()
            for topic in item.topics:
                if topic.chapter_n not in seen:
                    seen.add(topic.chapter_n)
                    by_chapter.setdefault(topic.chapter_n, []).append(item)
        subsections = [
            TocSubsection(
                id=str(n), label=f"{chapters[n]['roman']}. {chapters[n]['title']}" if n in chapters
                                 else f"Chapter {n}",
                items=[_toc_item(i) for i in items],
            )
            for n, items in sorted(by_chapter.items())
        ]
        return [TocSection(id="chapters", label="Chapters", subsections=subsections)]

    def topic_items(t: dict) -> list[TocItem]:
        seen, out = set(), []
        for cid in t.get("citation_ids", []):
            item_id = passage_by_citation.get(cid)
            if item_id and item_id not in seen:
                seen.add(item_id)
                out.append(_toc_item(items_by_id[item_id]))
        return out

    by_chapter: dict[int, list[dict]] = defaultdict(list)
    for t in topic_rows:
        by_chapter[t["chapter_n"]].append(t)

    subsections = []
    for n in sorted(by_chapter):
        level3 = [t for t in by_chapter[n] if t["level"] == 3]
        level4_by_topic: dict[str, list[dict]] = defaultdict(list)
        for t in by_chapter[n]:
            if t["level"] == 4:
                level4_by_topic[t["topic"]].append(t)
        topic_subsections = [
            TocSubsection(
                id=t["id"], label=t["topic"], items=topic_items(t),
                children=[TocSubsection(id=c["id"], label=c["subtopic"], items=topic_items(c))
                          for c in level4_by_topic.get(t["topic"], [])],
            )
            for t in level3
        ]
        label = f"{chapters[n]['roman']}. {chapters[n]['title']}" if n in chapters else f"Chapter {n}"
        subsections.append(TocSubsection(id=str(n), label=label, items=[], children=topic_subsections))

    return [TocSection(id="chapters", label="Chapters", subsections=subsections)]


@router.get("/{source_id}/toc", response_model=TocResponse)
def get_toc(source_id: str) -> TocResponse:
    store = _loaded_store(source_id)
    if source_id == "parks2021":
        sections = _build_toc_by_book(
            store,
            group_key=lambda i: i.refs[0].book if i.refs else "?",
            group_label=lambda i: i.refs[0].book_name if i.refs else "Unplaced",
        )
    elif source_id == "lockyer1959":
        sections = _build_toc_by_book(
            store, group_key=lambda i: i.book_section, group_label=lambda i: i.book_section,
            empty_sections=store.extra.get("book_sections"))
    elif source_id == "watters1883":
        sections = _build_toc_watters(store)
    else:
        raise HTTPException(404, detail=f"no source {source_id!r}")
    return TocResponse(source_id=source_id, sections=sections)


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


# --- lockyer1959: book introductions --------------------------------------
#
# Every Bible book gets one, including the 22 with no recorded prayers, for
# which this is the only content Lockyer gives. `intro`/`poetry` follow the
# same include_copyrighted_text gating as LockyerItemDetail.exposition.

@router.get("/lockyer1959/book-sections", response_model=LockyerBookSectionsResponse)
def list_lockyer_book_sections() -> LockyerBookSectionsResponse:
    store = _loaded_store("lockyer1959")
    sections: dict[str, LockyerBookSection] = store.extra.get("book_sections", {})
    return LockyerBookSectionsResponse(items=sorted(sections.values(), key=lambda s: s.id))


@router.get("/lockyer1959/book-sections/{section_id}", response_model=LockyerBookSection)
def get_lockyer_book_section(section_id: str) -> LockyerBookSection:
    store = _loaded_store("lockyer1959")
    sections: dict[str, LockyerBookSection] = store.extra.get("book_sections", {})
    section = sections.get(section_id)
    if section is None:
        raise HTTPException(404, detail=f"no book section {section_id!r}")
    return section


# --- watters1883: front/back matter, editorial notes, cross-references ----
#
# Public domain, so no gating -- these are simply the rest of the book, not
# yet surfaced anywhere else. Editorial notes and back-references that are
# already tied to a specific citation are folded onto that citation's
# `notes`/`see_also` instead (see `_load_watters`); what's left here is
# untethered to any one item: the title page, the endorsements, and the bare
# "(See X)" pointers under a topic heading.

@router.get("/watters1883/front-matter", response_model=WattersFrontMatter)
def get_watters_front_matter() -> WattersFrontMatter:
    store = _loaded_store("watters1883")
    front = store.extra.get("front_matter")
    if front is None:
        raise HTTPException(404, detail="no front matter recorded for watters1883")
    return WattersFrontMatter(**front)


@router.get("/watters1883/back-matter", response_model=WattersBackMatter)
def get_watters_back_matter() -> WattersBackMatter:
    store = _loaded_store("watters1883")
    back = store.extra.get("back_matter")
    if back is None:
        raise HTTPException(404, detail="no back matter recorded for watters1883")
    return WattersBackMatter(**back)


@router.get("/watters1883/editorial-notes", response_model=list[WattersEditorialNote])
def list_watters_editorial_notes(
    kind: Optional[str] = Query(default=None, description="'page_marker' or 'editorial'"),
) -> list[WattersEditorialNote]:
    store = _loaded_store("watters1883")
    notes = store.extra.get("editorial_notes", [])
    if kind is not None:
        notes = [n for n in notes if n["kind"] == kind]
    return [WattersEditorialNote(**n) for n in notes]


@router.get("/watters1883/cross-references", response_model=list[WattersCrossReference])
def list_watters_cross_references(
    chapter_n: Optional[int] = Query(default=None),
) -> list[WattersCrossReference]:
    store = _loaded_store("watters1883")
    xrefs = store.extra.get("cross_references", [])
    if chapter_n is not None:
        xrefs = [x for x in xrefs if x["from_chapter_n"] == chapter_n]
    return [WattersCrossReference(**x) for x in xrefs]
