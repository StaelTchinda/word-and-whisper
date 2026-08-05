// Short blurbs for the home page. The API's SourceInfo.display_name already
// carries "Title (Author, Year)" -- this just adds the one-line description
// a card needs, since that's editorial copy the API has no reason to serve.
export const SOURCE_BLURBS: Record<string, string> = {
  parks2021:
    'Every prayer in Scripture, catalogued by speaker, occasion, and content — 224 prayers from Genesis to Revelation.',
  lockyer1959:
    'A study of Bible prayer, book by book, pairing each entry with the scripture it prays.',
  watters1883:
    'A public-domain 19th-century survey of prayer in the Bible, organised by its own 30 topical chapters — Who Prayed, the Grounds of Prayer, and more.',
}

export function pluralizeUnit(unit: string): string {
  return unit.endsWith('y') ? `${unit.slice(0, -1)}ies` : `${unit}s`
}

export function parseDisplayName(displayName: string): { title: string; byline: string | null } {
  const match = displayName.match(/^(.*) \(([^)]+)\)$/)
  if (!match) return { title: displayName, byline: null }
  return { title: match[1], byline: match[2] }
}
