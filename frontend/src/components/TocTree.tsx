import { useMemo } from 'react'
import { Link } from 'react-router'
import type { TocResponse, TocSubsection as TocSubsectionType } from '../api/types'
import { filterToc } from '../toc'

function countItems(sub: TocSubsectionType): number {
  return sub.items.length + sub.children.reduce((n, c) => n + countItems(c), 0)
}

// Wraps the substring of `text` matching `query` (case-insensitive) in
// <mark>, so a filtered result shows *why* it matched, not just that it did.
function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>
  const i = text.toLowerCase().indexOf(query.toLowerCase())
  if (i === -1) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + query.length)}</mark>
      {text.slice(i + query.length)}
    </>
  )
}

function Subsection({
  sourceId,
  sub,
  isChapter = false,
  filter,
}: {
  sourceId: string
  sub: TocSubsectionType
  // True only for a Watters top-level subsection, which is one of the
  // book's own 30 chapters -- its own reading unit, distinct from the
  // topic/subtopic subsections nested underneath it.
  isChapter?: boolean
  filter: string
}) {
  const n = countItems(sub)
  return (
    <details className="toc-subsection" open={filter ? true : undefined}>
      <summary>
        <Highlight text={sub.label} query={filter} /> <span className="item-count">({n})</span>
      </summary>
      {isChapter && (
        <p className="toc-empty-section">
          <Link to={`/sources/watters1883/chapters/${sub.id}`}>Read this chapter →</Link>
        </p>
      )}
      {sub.book_section_id && (
        <p className="toc-empty-section">
          {sub.items.length === 0 && sub.children.length === 0 && 'No prayers recorded here. '}
          <Link to={`/sources/${sourceId}/book-sections/${sub.book_section_id}`}>
            Book introduction →
          </Link>
        </p>
      )}
      {sub.items.length > 0 && (
        <ul className="toc-items">
          {sub.items.map((item) => (
            <li key={item.id}>
              <Link to={`/sources/${sourceId}/${item.id}`}>
                <span>
                  <Highlight text={item.title ?? item.ref_display} query={filter} />
                </span>
                {item.title && (
                  <span className="ref">
                    <Highlight text={item.ref_display} query={filter} />
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
      {sub.children.map((child) => (
        <Subsection sourceId={sourceId} sub={child} filter={filter} key={child.id} />
      ))}
    </details>
  )
}

export default function TocTree({
  sourceId,
  toc,
  filter = '',
}: {
  sourceId: string
  toc: TocResponse
  filter?: string
}) {
  const filtered = useMemo(() => filterToc(toc, filter), [toc, filter])

  if (filter && filtered.matchCount === 0) {
    return <p className="state-message">No entries match &ldquo;{filter}&rdquo;.</p>
  }

  return (
    <div className="toc">
      {filter && (
        <p className="result-count">
          {filtered.matchCount.toLocaleString()} entr{filtered.matchCount === 1 ? 'y' : 'ies'} match &ldquo;
          {filter}&rdquo;
        </p>
      )}
      {filtered.sections.map((section, index) => (
        <details className="toc-section" key={section.id} open={filter ? true : index === 0}>
          <summary>{section.label}</summary>
          {section.subsections.map((sub) => (
            <Subsection
              sourceId={sourceId}
              sub={sub}
              isChapter={sourceId === 'watters1883'}
              filter={filter}
              key={sub.id}
            />
          ))}
        </details>
      ))}
    </div>
  )
}
