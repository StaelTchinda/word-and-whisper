// Mirrors the Pydantic response models in src/prayer/api/models.py that this
// app actually reads from. Field names and shapes must stay in sync by hand
// -- there is no shared schema between the two.

export type CanonSection = 'OT' | 'DC' | 'NT'
export type SourceUnit = 'prayer' | 'entry' | 'passage'
export type SourceLicense = 'proprietary' | 'in_copyright' | 'public_domain'

export interface SourceInfo {
  id: string
  display_name: string
  unit: SourceUnit
  record_count: number
  license: SourceLicense
  text_includable: boolean
  status: 'ok' | 'unavailable'
  detail: string | null
}

export interface SourcesResponse {
  sources: SourceInfo[]
}

export interface SourceRefStart {
  chapter: number
  verse: number | null
}

export interface SourceRef {
  osis: string
  book: string
  book_name: string
  canon: CanonSection
  start: SourceRefStart
  end: SourceRefStart
  raw: string
  role: string | null
  granularity: string | null
  verse_only: boolean | null
  unresolved: boolean | null
}

export interface Speaker {
  raw: string
  agents: string[]
  collective: boolean
}

export interface Addressee {
  raw: string
  agents: string[]
}

export interface ParksItemDetail {
  source_id: 'parks2021'
  id: string
  unit: 'prayer'
  title: string
  slug: string
  canon_section: CanonSection
  refs: SourceRef[]
  primary_ref: string
  verse_count: number | null
  speaker: Speaker
  addressee: Addressee
  context: string
  contents: string[]
  places: string[]
  related_pericopes: string[]
}

export interface LockyerScriptureQuote {
  position: number
  text: string
  attribution_raw: string
  osis: string
  translation: 'KJV'
}

export interface LockyerOutlinePoint {
  n: number
  text: string
}

export interface LockyerPoem {
  position: number
  text: string
  lines: number
  attribution: string | null
}

// In copyright (c. 1959 Zondervan) -- null/empty unless the backend was
// started with PRAYER_INCLUDE_COPYRIGHTED_TEXT=true. See docs/datasets.md.
export interface LockyerExposition {
  paragraphs: string[]
  word_count: number
  outline: LockyerOutlinePoint[]
}

export interface LockyerItemDetail {
  source_id: 'lockyer1959'
  id: string
  unit: 'entry'
  entry_type: string
  title: string
  title_raw: string
  slug: string
  canon_section: CanonSection
  book_section: string
  refs: SourceRef[]
  primary_ref: string | null
  ref_raw: string | null
  scripture_quotes: LockyerScriptureQuote[]
  has_exposition: boolean
  has_poetry: boolean
  exposition_paragraph_count: number
  exposition: LockyerExposition | null
  poetry: LockyerPoem[]
  application_sentences: string[]
  page: number | null
}

// One Bible book's introduction (all 66, incl. the 22 with no recorded
// prayers -- for those this is the only content Lockyer gives). `intro`
// follows the same copyright gating as LockyerItemDetail.exposition.
export interface LockyerBookSection {
  id: string
  source_id: 'lockyer1959'
  book: string | null
  book_section: string
  canon_section: CanonSection
  has_prayers: boolean
  n_prayer_entries: number
  has_intro: boolean
  intro_word_count: number
  intro: LockyerExposition | null
  poetry: LockyerPoem[]
}

export interface LockyerBookSectionsResponse {
  items: LockyerBookSection[]
}

export interface WattersTopicTag {
  chapter_n: number
  path: string
  facet: string
}

export interface WattersPassageDetail {
  source_id: 'watters1883'
  id: string
  unit: 'passage'
  osis: string
  book: string
  canon_section: CanonSection | null
  text: string | null
  text_is_exact: boolean
  text_reason: string | null
  translation: 'KJV'
  n_citations: number
  citation_ids: string[]
  topics: WattersTopicTag[]
  facets: string[]
}

export type SourceItemDetail = ParksItemDetail | LockyerItemDetail | WattersPassageDetail

export interface WattersCitation {
  id: string
  chapter_n: number
  chapter_title: string
  facet: string
  topic: string | null
  subtopic: string | null
  ref_raw: string
  primary_ref: string
  text: string | null
  translation: 'KJV'
  text_source: string
  page: number | null
  // Public domain, never gated: body_prose that continued on from this
  // citation in the source, and the "see also" target of any cross-reference
  // drawn from this citation's own back-reference.
  notes: string[]
  see_also: string | null
}

export interface CitationsResponse {
  total: number
  items: WattersCitation[]
}

export interface WattersFrontMatter {
  id: string
  headings: string[]
  paragraphs: string[]
  word_count: number
}

export interface WattersBackMatter {
  id: string
  content_type: string
  headings: string[]
  paragraphs: string[]
  note: string
}

export interface WattersEditorialNote {
  id: string
  kind: 'page_marker' | 'editorial'
  page: number | null
  text: string
}

export interface WattersCrossReference {
  id: string
  kind: string
  from_chapter_n: number
  from_topic_path: string[]
  to_topic_raw: string | null
  from_citation_id: string | null
}

export interface TocItem {
  id: string
  title: string | null
  ref_display: string
  page: number | null
}

export interface TocSubsection {
  id: string
  label: string
  items: TocItem[]
  // Watters nests chapter -> topic -> subtopic; Parks/Lockyer never populate this.
  children: TocSubsection[]
  // Set only for a Lockyer book with no recorded prayers: `items` is empty,
  // but the book still has an introduction worth reading.
  book_section_id: string | null
}

export interface TocSection {
  id: string
  label: string
  subsections: TocSubsection[]
}

export interface TocResponse {
  source_id: string
  sections: TocSection[]
}

// From the retrieval side (GET /prayers/{id}) -- used only to fetch the
// public-domain WEB scripture text for parks2021 items, which never carry
// their own book prose (SourceInfo.text_includable === false).
export interface ReferenceBlock {
  osis: string
  display: string
  translation: string
  parallels: string[]
}

export interface LabelBlock {
  context: string
  contents: string[]
  speaker: string
  canon_section: CanonSection
}

export interface PrayerDetail {
  prayer_id: string
  title: string
  reference: ReferenceBlock
  labels: LabelBlock
  compose_policy: 'compose' | 'explain_only' | 'exclude'
  policy_reason: string | null
  text_available: boolean
  passage_text: string | null
  verse_count: number
}
