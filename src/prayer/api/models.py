#!/usr/bin/env python3
"""Every Pydantic model that crosses a boundary, in one place.

Boundary means: HTTP request/response, or the hand-off between two pipeline
stages. Keeping them together is what lets a new retriever or composer ship
without touching the API layer -- a stage only ever sees these types, never
another stage's internals.

The response models mirror docs/PRODUCT_BOOK.md section 6 field for field. Changing
them is a breaking change for the benchmark harness as well as for callers.
"""
from typing import Literal, Optional

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
