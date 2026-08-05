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
}

export interface CitationsResponse {
  total: number
  items: WattersCitation[]
}

export interface TocItem {
  id: string
  title: string | null
  ref_display: string
}

export interface TocSubsection {
  id: string
  label: string
  items: TocItem[]
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
