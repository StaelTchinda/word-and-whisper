import type { TocItem, TocResponse } from './api/types'

export interface FlatTocEntry {
  item: TocItem
  sectionLabel: string
  subsectionLabel: string
}

// Flattens the toc tree into reading order for Prev/Next and breadcrumbs. A
// Watters passage can appear under more than one chapter (it may be cited in
// more than one place in the original book); only its first occurrence is
// kept here, so navigation follows one consistent path through the book.
export function flattenToc(toc: TocResponse): FlatTocEntry[] {
  const seen = new Set<string>()
  const flat: FlatTocEntry[] = []
  for (const section of toc.sections) {
    for (const sub of section.subsections) {
      for (const item of sub.items) {
        if (seen.has(item.id)) continue
        seen.add(item.id)
        flat.push({ item, sectionLabel: section.label, subsectionLabel: sub.label })
      }
    }
  }
  return flat
}
