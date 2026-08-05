import type {
  CitationsResponse,
  LockyerBookSection,
  LockyerBookSectionsResponse,
  PrayerDetail,
  SourceItemDetail,
  SourcesResponse,
  TocResponse,
  WattersBackMatter,
  WattersCrossReference,
  WattersEditorialNote,
  WattersFrontMatter,
} from './types'

class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export function listSources(): Promise<SourcesResponse> {
  return getJson('/sources')
}

export function getToc(sourceId: string): Promise<TocResponse> {
  return getJson(`/sources/${sourceId}/toc`)
}

export function getSourceItem(sourceId: string, itemId: string): Promise<SourceItemDetail> {
  return getJson(`/sources/${sourceId}/items/${itemId}`)
}

export function getWattersCitations(itemId: string): Promise<CitationsResponse> {
  return getJson(`/sources/watters1883/items/${itemId}/citations`)
}

export function listLockyerBookSections(): Promise<LockyerBookSectionsResponse> {
  return getJson('/sources/lockyer1959/book-sections')
}

export function getLockyerBookSection(sectionId: string): Promise<LockyerBookSection> {
  return getJson(`/sources/lockyer1959/book-sections/${sectionId}`)
}

export function getWattersFrontMatter(): Promise<WattersFrontMatter> {
  return getJson('/sources/watters1883/front-matter')
}

export function getWattersBackMatter(): Promise<WattersBackMatter> {
  return getJson('/sources/watters1883/back-matter')
}

export function listWattersEditorialNotes(): Promise<WattersEditorialNote[]> {
  return getJson('/sources/watters1883/editorial-notes')
}

export function listWattersCrossReferences(): Promise<WattersCrossReference[]> {
  return getJson('/sources/watters1883/cross-references')
}

// Parks items don't carry their own book prose (SourceInfo.text_includable
// === false); their id is shared with the retrieval corpus, so this pulls
// the public-domain WEB scripture text to read alongside the metadata.
export function getPrayer(prayerId: string): Promise<PrayerDetail> {
  return getJson(`/prayers/${prayerId}`)
}

export { ApiError }
