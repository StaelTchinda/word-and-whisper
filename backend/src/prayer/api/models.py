#!/usr/bin/env python3
"""Every Pydantic model that crosses a boundary, in one place.

Boundary means: HTTP request/response, or the hand-off between two pipeline
stages. Keeping them together is what lets a new retriever or composer ship
without touching the API layer -- a stage only ever sees these types, never
another stage's internals.

The response models mirror docs/PRODUCT_BOOK.md section 6 field for field. Changing
them is a breaking change for the benchmark harness as well as for callers.
"""
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

CanonSection = Literal["OT", "DC", "NT"]
MovementKind = Literal["address", "anchor", "naming", "ask", "trust", "close"]
ComposePolicy = Literal["compose", "explain_only", "exclude"]
SafetyStatus = Literal["ok", "crisis"]

# The movements a valid spoken prayer must contain (PRODUCT_BOOK section 5.4).
# `trust` is the one optional movement: laments frequently have none, and
# manufacturing one would misrepresent the source prayer.
REQUIRED_MOVEMENTS: tuple[MovementKind, ...] = (
    "address", "anchor", "naming", "ask", "close",
)

WORDS_PER_MINUTE = 150  # for read_time_seconds
MIN_PRAYER_WORDS = 60
MAX_PRAYER_WORDS = 180


# --- corpus records --------------------------------------------------------

class RefStart(BaseModel):
    chapter: int
    verse: int


class PrayerRef(BaseModel):
    osis: str
    book: str
    book_name: str
    canon: CanonSection
    start: RefStart
    end: RefStart
    verse_only: bool
    raw: str


class Speaker(BaseModel):
    raw: str
    agents: list[str] = Field(default_factory=list)
    collective: bool = False


class Addressee(BaseModel):
    raw: str
    agents: list[str] = Field(default_factory=list)


class PrayerRecord(BaseModel):
    """One row of data/build/datasets/prayers.jsonl, plus the overlay fields we add."""
    model_config = ConfigDict(extra="ignore")

    id: str
    source_id: str
    title: str
    slug: str
    canon_section: CanonSection
    refs: list[PrayerRef]
    primary_ref: str
    verse_count: Optional[int] = None
    speaker: Speaker
    addressee: Addressee
    context: str
    contents: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    related_pericopes: list[str] = Field(default_factory=list)

    # Overlay, not from the dataset: set from prayer.api/policy/compose_policy.yaml.
    compose_policy: ComposePolicy = "compose"
    policy_reason: Optional[str] = None


class Verse(BaseModel):
    osis: str
    n: int
    text: str
    # Poetic line breaks from the USFX <q> structure. Empty for prose.
    lines: list[str] = Field(default_factory=list)


class ResolvedRef(BaseModel):
    osis: str
    display: str
    # Psalm superscriptions ("For the Chief Musician...") are real translation
    # text but not part of the prayer, so they are kept out of the verse text.
    superscription: Optional[str] = None
    verses: list[Verse] = Field(default_factory=list)


class Passage(BaseModel):
    """Resolved scripture for one prayer record. The source of truth for C1."""
    prayer_id: str
    translation: str
    text_available: bool
    refs: list[ResolvedRef] = Field(default_factory=list)
    full_text: str = ""
    word_count: int = 0
    reason: Optional[str] = None  # why text_available is false

    @property
    def verse_count(self) -> int:
        return sum(len(r.verses) for r in self.refs)


# --- analysis --------------------------------------------------------------

class AnalyzedSituation(BaseModel):
    """What the SituationAnalyzer hands to retrieval and composition."""
    situation: str
    tokens: list[str] = Field(default_factory=list)
    # Content labels from the dataset vocabulary that the situation implies.
    content_labels: list[str] = Field(default_factory=list)
    context_labels: list[str] = Field(default_factory=list)
    # Free-text themes that matched, for `matched_on` and for the naming movement.
    themes: list[str] = Field(default_factory=list)
    # Corpus-vocabulary terms the themes imply. Retrieval weights these below
    # the user's own words; see api/policy/situation_lexicon.yaml.
    expansions: list[str] = Field(default_factory=list)
    intercessory: bool = False  # praying for someone else -> "we"/"them"
    subject_phrase: Optional[str] = None  # the user's own words, lightly cleaned
    safety_status: SafetyStatus = "ok"


class Filters(BaseModel):
    canon: list[CanonSection] = Field(default_factory=lambda: ["OT", "DC", "NT"])
    require_text: bool = True
    allowed_contents: Optional[list[str]] = None  # crisis gate narrows to these
    exclude_ids: list[str] = Field(default_factory=list)


class Candidate(BaseModel):
    prayer_id: str
    score: float
    # Human-readable reasons this record surfaced. Required, not optional: it
    # is both the explainability surface and the only practical way to debug
    # a bad ranking in the benchmark.
    matched_on: list[str] = Field(default_factory=list)


# --- composition -----------------------------------------------------------

class Movement(BaseModel):
    kind: MovementKind
    text: str
    # Set only on `anchor`; the OSIS ref the verbatim text was taken from.
    verbatim_from: Optional[str] = None


class Instructions(BaseModel):
    why_it_fits: str
    how_to_pray: str
    posture: str


class Composition(BaseModel):
    """A composer's output, before the pipeline turns it into a Suggestion."""
    movements: list[Movement]
    instructions: Instructions
    composer: str
    model: Optional[str] = None
    fallback_used: bool = False
    retry_count: int = 0


# --- HTTP boundary ---------------------------------------------------------

class SuggestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    situation: str = Field(min_length=3, max_length=1000)
    k: int = Field(default=3, ge=1, le=10)
    retriever: Optional[str] = None  # defaults from config.yaml
    composer: Optional[str] = None
    canon: list[CanonSection] = Field(default_factory=lambda: ["OT", "DC", "NT"])
    translation: str = "WEB"
    include_passage_text: bool = True


class QueryEcho(BaseModel):
    situation: str
    k: int
    retriever: str
    composer: str


class SafetyBlock(BaseModel):
    status: SafetyStatus = "ok"
    notice: Optional[str] = None


class ReferenceBlock(BaseModel):
    osis: str
    display: str
    translation: str
    # Parallel gospel accounts of the same prayer (n_refs > 1), listed but
    # never concatenated into the passage.
    parallels: list[str] = Field(default_factory=list)


class LabelBlock(BaseModel):
    context: str
    contents: list[str]
    speaker: str
    canon_section: CanonSection


class MatchBlock(BaseModel):
    score: float
    matched_on: list[str]


class SpokenPrayer(BaseModel):
    text: str
    movements: list[Movement]
    word_count: int
    read_time_seconds: int


class ProvenanceBlock(BaseModel):
    composer: str
    model: Optional[str] = None
    fallback_used: bool = False
    retry_count: int = 0
    latency_ms: int = 0


class Suggestion(BaseModel):
    prayer_id: str
    title: str
    reference: ReferenceBlock
    passage_text: Optional[str] = None
    passage_truncated: bool = False
    passage_excerpt: Optional[str] = None
    labels: LabelBlock
    match: MatchBlock
    instructions: Instructions
    # Null when compose_policy is `explain_only`; `note` says why.
    spoken_prayer: Optional[SpokenPrayer] = None
    note: Optional[str] = None
    provenance: ProvenanceBlock


class Timings(BaseModel):
    total_ms: int = 0
    retrieval_ms: int = 0
    composition_ms: int = 0


class SuggestResponse(BaseModel):
    query: QueryEcho
    safety: SafetyBlock
    abstained: bool = False
    message: Optional[str] = None
    suggestions: list[Suggestion] = Field(default_factory=list)
    timings: Timings = Field(default_factory=Timings)


class PrayerDetail(BaseModel):
    """GET /prayers/{prayer_id}."""
    prayer_id: str
    title: str
    reference: ReferenceBlock
    labels: LabelBlock
    compose_policy: ComposePolicy
    policy_reason: Optional[str] = None
    text_available: bool
    passage_text: Optional[str] = None
    verse_count: int = 0


class ComponentInfo(BaseModel):
    name: str
    kind: str
    description: str = ""
    selectable: bool = True


class ConfigResponse(BaseModel):
    retrievers: list[ComponentInfo]
    composers: list[ComponentInfo]
    translations: list[str]
    defaults: dict[str, str]
    corpus: dict[str, int]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    corpus_loaded: bool
    prayers: int
    passages: int
    detail: Optional[str] = None


# --- source browsing (not part of the section 6 contract) ------------------
#
# Read-only browse/search surface over each raw extracted source
# (data/build/datasets/sources/<source_id>/), loaded and served independently
# of the Corpus/retrieval pipeline above by prayer.api.sources. Not covered
# by docs/PRODUCT_BOOK.md section 6 and not held to the same compatibility
# bar as the models above.

SourceUnit = Literal["prayer", "entry", "passage"]
SourceLicense = Literal["proprietary", "in_copyright", "public_domain"]


class SourceInfo(BaseModel):
    id: str
    display_name: str
    unit: SourceUnit
    record_count: int
    license: SourceLicense
    text_includable: bool
    status: Literal["ok", "unavailable"]
    detail: Optional[str] = None


class SourcesResponse(BaseModel):
    sources: list[SourceInfo]


class SourceRefStart(BaseModel):
    chapter: int
    verse: Optional[int] = None  # null for chapter-level refs (lockyer)


class SourceRef(BaseModel):
    """Common ref shape across the three sources' differing refs[] schemas."""
    model_config = ConfigDict(extra="ignore")

    osis: str
    book: str
    book_name: str
    canon: CanonSection
    start: SourceRefStart
    end: SourceRefStart
    raw: str
    role: Optional[str] = None
    granularity: Optional[str] = None
    verse_only: Optional[bool] = None
    unresolved: Optional[bool] = None


class SourceItemSummary(BaseModel):
    id: str
    source_id: str
    unit: SourceUnit
    title: Optional[str] = None
    primary_ref: Optional[str] = None
    ref_display: str
    canon_section: Optional[CanonSection] = None
    labels: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SourceItemSummary]


# --- cross-source search -----------------------------------------------
#
# SearchResponse above is per-source (GET /sources/{id}/items?q=). This is
# its counterpart across all three at once -- one query box, one result list,
# each hit labeled with which source it came from and which field matched,
# since "speaker" and "topic" mean different things per source. See
# prayer.api.sources.search_all.

class GlobalSearchResult(BaseModel):
    id: str
    source_id: str
    unit: SourceUnit
    title: Optional[str] = None
    ref_display: str
    # A short excerpt containing the match, or the closest thing to one --
    # e.g. the theme/topic string itself when the match isn't in body text.
    snippet: str
    # Human-readable label for *why* this hit matched: "speaker", "theme",
    # "occasion", "title", "scripture", "topic", "text" -- source-specific,
    # deliberately not an enum, since each source's fields differ.
    matched_on: str


class GlobalSearchResponse(BaseModel):
    q: str
    total: int
    items: list[GlobalSearchResult]


class ParksItemDetail(BaseModel):
    source_id: Literal["parks2021"] = "parks2021"
    id: str
    unit: Literal["prayer"] = "prayer"
    title: str
    slug: str
    canon_section: CanonSection
    refs: list[SourceRef]
    primary_ref: str
    verse_count: Optional[int] = None
    speaker: Speaker
    addressee: Addressee
    context: str
    contents: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    related_pericopes: list[str] = Field(default_factory=list)


class LockyerScriptureQuote(BaseModel):
    position: int
    text: str
    attribution_raw: str
    osis: str
    translation: Literal["KJV"] = "KJV"


class LockyerOutlinePoint(BaseModel):
    n: int
    text: str


class LockyerPoem(BaseModel):
    position: int
    text: str
    lines: int
    attribution: Optional[str] = None


class LockyerExposition(BaseModel):
    """Lockyer's own prose. In copyright (c. 1959 Zondervan) -- only ever
    populated when `Settings.include_copyrighted_text` is true; see
    `prayer.api.sources` and docs/datasets.md licensing section."""
    paragraphs: list[str]
    word_count: int
    outline: list[LockyerOutlinePoint] = Field(default_factory=list)


class LockyerItemDetail(BaseModel):
    """`exposition`, `poetry`, and `application_sentences` are in-copyright
    (c. 1959 Zondervan) -- populated only when `include_copyrighted_text` is
    on, and never indexed for `q` search regardless. See
    docs/datasets.md licensing section."""
    source_id: Literal["lockyer1959"] = "lockyer1959"
    id: str
    unit: Literal["entry"] = "entry"
    entry_type: str
    title: str
    title_raw: str
    slug: str
    canon_section: CanonSection
    book_section: str
    refs: list[SourceRef]
    primary_ref: Optional[str] = None
    ref_raw: Optional[str] = None
    scripture_quotes: list[LockyerScriptureQuote] = Field(default_factory=list)
    has_exposition: bool
    has_poetry: bool
    exposition_paragraph_count: int
    exposition: Optional[LockyerExposition] = None
    poetry: list[LockyerPoem] = Field(default_factory=list)
    application_sentences: list[str] = Field(default_factory=list)
    page: Optional[int] = None


class LockyerBookSection(BaseModel):
    """One Bible book's introduction, incl. the 22 books with no recorded
    prayers -- for those, this is the only content Lockyer gives. `intro` is
    the same in-copyright prose as `LockyerExposition` and follows the same
    gating."""
    id: str
    source_id: Literal["lockyer1959"] = "lockyer1959"
    book: Optional[str] = None
    book_section: str
    canon_section: CanonSection
    has_prayers: bool
    n_prayer_entries: int
    has_intro: bool
    intro_word_count: int
    intro: Optional[LockyerExposition] = None
    poetry: list[LockyerPoem] = Field(default_factory=list)


class LockyerBookSectionsResponse(BaseModel):
    items: list[LockyerBookSection]


class WattersTopicTag(BaseModel):
    chapter_n: int
    path: str
    facet: str


class WattersPassageDetail(BaseModel):
    source_id: Literal["watters1883"] = "watters1883"
    id: str
    unit: Literal["passage"] = "passage"
    osis: str
    book: str
    canon_section: Optional[CanonSection] = None
    text: Optional[str] = None
    text_is_exact: bool
    text_reason: Optional[str] = None
    translation: Literal["KJV"] = "KJV"
    n_citations: int
    citation_ids: list[str] = Field(default_factory=list)
    topics: list[WattersTopicTag] = Field(default_factory=list)
    facets: list[str] = Field(default_factory=list)


SourceItemDetail = Annotated[
    Union[ParksItemDetail, LockyerItemDetail, WattersPassageDetail],
    Field(discriminator="source_id"),
]


class WattersCitation(BaseModel):
    id: str
    chapter_n: int
    chapter_title: str
    facet: str
    topic: Optional[str] = None
    subtopic: Optional[str] = None
    ref_raw: str
    primary_ref: str
    text: Optional[str] = None
    translation: Literal["KJV"] = "KJV"
    text_source: str
    page: Optional[int] = None
    # `body_prose.jsonl` entries that followed this citation in the source
    # (continuation text or an editorial aside), and the "see also" target of
    # any cross-reference drawn from this citation's back-reference. Public
    # domain -- always populated, no gating.
    notes: list[str] = Field(default_factory=list)
    see_also: Optional[str] = None


class CitationsResponse(BaseModel):
    total: int
    items: list[WattersCitation]


# --- watters1883: whole-chapter reading view --------------------------------
#
# The TOC (`TocSection`/`TocSubsection` below) nests chapter -> topic ->
# subtopic -> passage *links*, one click per passage. This mirrors the same
# chapter -> topic -> subtopic shape but inlines each citation's full text, so
# a whole chapter (Watters' real unit of reading -- "Who Prayed", "The Duty of
# Prayer", ...) can be read in one page instead of one passage at a time.

class WattersChapterSubtopic(BaseModel):
    id: str
    label: str
    citations: list[WattersCitation] = Field(default_factory=list)


class WattersChapterTopic(BaseModel):
    id: str
    label: str
    citations: list[WattersCitation] = Field(default_factory=list)
    subtopics: list[WattersChapterSubtopic] = Field(default_factory=list)


class WattersChapterDetail(BaseModel):
    chapter_n: int
    title: str
    roman: Optional[str] = None
    n_citations: int
    topics: list[WattersChapterTopic] = Field(default_factory=list)


class WattersFrontMatter(BaseModel):
    id: str
    headings: list[str]
    paragraphs: list[str]
    word_count: int


class WattersBackMatter(BaseModel):
    id: str
    content_type: str
    headings: list[str]
    paragraphs: list[str]
    note: str


class WattersEditorialNote(BaseModel):
    id: str
    kind: str  # "page_marker" | "editorial"
    page: Optional[int] = None
    text: str


class WattersCrossReference(BaseModel):
    id: str
    kind: str
    from_chapter_n: int
    from_topic_path: list[str]
    to_topic_raw: Optional[str] = None
    from_citation_id: Optional[str] = None


# --- source table of contents -----------------------------------------------
#
# One pre-grouped tree per source, following each source's own structure
# (Parks/Lockyer: canon -> Bible book; Watters: the original book's own
# chapters -- see prayer.api.sources._build_toc for why canon doesn't apply
# there). Read-only navigation aid for the ebook-reader UI; not part of the
# section 6 contract.

class TocItem(BaseModel):
    id: str
    title: Optional[str] = None
    ref_display: str
    page: Optional[int] = None


class TocSubsection(BaseModel):
    id: str
    label: str
    items: list[TocItem] = Field(default_factory=list)
    # Watters' topics nest a subtopic level under a topic (chapter -> topic ->
    # subtopic -> passages); Parks/Lockyer never populate this.
    children: list["TocSubsection"] = Field(default_factory=list)
    # Set only for a Lockyer book with no recorded prayers: `items` is empty,
    # but the book itself still has an introduction worth reading (see
    # `/sources/lockyer1959/book-sections/{id}`).
    book_section_id: Optional[str] = None


TocSubsection.model_rebuild()


class TocSection(BaseModel):
    id: str
    label: str
    subsections: list[TocSubsection] = Field(default_factory=list)


class TocResponse(BaseModel):
    source_id: str
    sections: list[TocSection] = Field(default_factory=list)
