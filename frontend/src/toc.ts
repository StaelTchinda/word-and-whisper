import type { TocItem, TocResponse, TocSection, TocSubsection } from './api/types'

export interface FlatTocEntry {
  item: TocItem
  sectionLabel: string
  subsectionLabel: string
}

function* walk(sub: TocSubsection, sectionLabel: string, seen: Set<string>): Generator<FlatTocEntry> {
  for (const item of sub.items) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    yield { item, sectionLabel, subsectionLabel: sub.label }
  }
  for (const child of sub.children) {
    yield* walk(child, sectionLabel, seen)
  }
}

// Flattens the toc tree into reading order for Prev/Next and breadcrumbs. A
// Watters passage can appear under more than one chapter or topic (it may be
// cited in more than one place in the original book); only its first
// occurrence is kept here, so navigation follows one consistent path through
// the book. Nested subtopics (Watters) are walked depth-first after their
// parent topic's own items.
export function flattenToc(toc: TocResponse): FlatTocEntry[] {
  const seen = new Set<string>()
  const flat: FlatTocEntry[] = []
  for (const section of toc.sections) {
    for (const sub of section.subsections) {
      flat.push(...walk(sub, section.label, seen))
    }
  }
  return flat
}

export type LockyerReadingEntity =
  | { kind: 'intro'; id: string; label: string }
  | { kind: 'entry'; id: string; label: string }

// One linear reading order for Lockyer: each book's introduction immediately
// followed by its own entries, book after book in canonical scripture order
// (the toc's own top-level order -- see _build_toc_by_book). Used for
// Prev/Next on both the book-introduction page and the entry reader, so
// "next" from a book's intro lands on that book's own first entry rather
// than skipping straight to the next book's intro, and the reverse on the
// way back.
//
// Intro entities are deduped by book_section_id and only emitted at their
// first occurrence: a handful of entries carry the wrong canon_section in
// the source data (e.g. several Malachi entries tagged NT), which would
// otherwise re-introduce the same book a second time. Their entries are
// still included in the order at the point they occur -- only the redundant
// intro stop is skipped.
export function lockyerReadingOrder(toc: TocResponse): LockyerReadingEntity[] {
  const seenIntro = new Set<string>()
  const order: LockyerReadingEntity[] = []
  for (const section of toc.sections) {
    for (const sub of section.subsections) {
      if (sub.book_section_id && !seenIntro.has(sub.book_section_id)) {
        seenIntro.add(sub.book_section_id)
        order.push({ kind: 'intro', id: sub.book_section_id, label: sub.label })
      }
      for (const item of sub.items) {
        order.push({ kind: 'entry', id: item.id, label: item.title ?? item.ref_display })
      }
    }
  }
  return order
}

function matchesText(text: string, q: string): boolean {
  return text.toLowerCase().includes(q)
}

// Keeps only the branches of a subsection that match `q` (case-insensitive,
// already lower-cased by the caller). If the subsection's own label matches
// -- e.g. typing "genesis" -- the whole branch is kept as-is, on the
// assumption that browsing by name means "show me everything in it" rather
// than "highlight only the word Genesis somewhere inside it".
function filterSubsection(sub: TocSubsection, q: string): TocSubsection | null {
  if (matchesText(sub.label, q)) return sub
  const items = sub.items.filter(
    (item) => (item.title && matchesText(item.title, q)) || matchesText(item.ref_display, q),
  )
  const children = sub.children
    .map((child) => filterSubsection(child, q))
    .filter((child): child is TocSubsection => child !== null)
  if (items.length === 0 && children.length === 0) return null
  return { ...sub, items, children }
}

function filterSection(section: TocSection, q: string): TocSection | null {
  const subsections = section.subsections
    .map((sub) => filterSubsection(sub, q))
    .filter((sub): sub is TocSubsection => sub !== null)
  if (subsections.length === 0) return null
  return { ...section, subsections }
}

export interface FilteredToc {
  sections: TocSection[]
  matchCount: number
}

// Client-side filter over a toc already fetched in full -- no new endpoint,
// just narrows what's rendered. Matching is substring, not tokenized, since
// the toc only holds short titles/refs/labels, not body text.
export function filterToc(toc: TocResponse, query: string): FilteredToc {
  const q = query.trim().toLowerCase()
  if (!q) return { sections: toc.sections, matchCount: flattenToc(toc).length }
  const sections = toc.sections
    .map((section) => filterSection(section, q))
    .filter((section): section is TocSection => section !== null)
  const matchCount = flattenToc({ source_id: toc.source_id, sections }).length
  return { sections, matchCount }
}
