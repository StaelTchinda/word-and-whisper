import type { TocItem, TocResponse, TocSubsection } from './api/types'

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
