import { Link, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { getLockyerBookSection, getToc } from '../api/client'
import { lockyerReadingOrder } from '../toc'
import { ReaderNav, type NavStop } from '../components/ReaderNav'

export default function BookSectionPage() {
  const { sectionId } = useParams<{ sectionId: string }>()

  const query = useQuery({
    queryKey: ['book-section', sectionId],
    queryFn: () => getLockyerBookSection(sectionId!),
    enabled: !!sectionId,
  })
  // Shares the query-cache entry SourceTocPage already populated when a
  // reader arrived here from the table of contents, so this is usually free
  // -- only needed for the book-to-book Prev/Next below.
  const tocQuery = useQuery({ queryKey: ['toc', 'lockyer1959'], queryFn: () => getToc('lockyer1959') })

  if (query.isLoading) {
    return (
      <div className="container">
        <p className="state-message">Loading…</p>
      </div>
    )
  }
  if (query.error || !query.data) {
    return (
      <div className="container">
        <p className="state-message">{(query.error as Error)?.message ?? 'Not found'}</p>
      </div>
    )
  }

  const section = query.data

  // "Next" from a book's introduction goes to that book's own first entry,
  // not straight to the next book's introduction (and the reverse for
  // "Prev") -- see lockyerReadingOrder. A book with zero recorded prayers
  // has no entry to land on, so its neighbor is the adjacent book's intro
  // instead.
  const order = tocQuery.data ? lockyerReadingOrder(tocQuery.data) : []
  const index = order.findIndex((e) => e.kind === 'intro' && e.id === sectionId)
  const toNavStop = (id: string, kind: 'entry' | 'intro', label: string): NavStop => ({
    href: kind === 'intro' ? `/sources/lockyer1959/book-sections/${id}` : `/sources/lockyer1959/${id}`,
    label,
  })
  const prevEntity = index > 0 ? order[index - 1] : undefined
  const nextEntity = index >= 0 && index < order.length - 1 ? order[index + 1] : undefined
  const prev = prevEntity && toNavStop(prevEntity.id, prevEntity.kind, prevEntity.label)
  const next = nextEntity && toNavStop(nextEntity.id, nextEntity.kind, nextEntity.label)

  return (
    <div className="container reader book-section-page">
      <div className="breadcrumb">
        <Link to="/">Home</Link>
        <span>/</span>
        <Link to="/sources/lockyer1959">All the Prayers of the Bible (Lockyer, 1959)</Link>
        <span>/</span>
        <span>{section.book_section}</span>
      </div>

      <div className="reader-header">
        <h1>{section.book_section}</h1>
      </div>

      {section.has_prayers ? (
        <p className="notice">
          {section.n_prayer_entries} recorded prayer{section.n_prayer_entries === 1 ? '' : 's'} in
          this book — see the table of contents for each one.
        </p>
      ) : (
        <p className="notice">
          Lockyer records no prayer of any individual in {section.book_section}.
        </p>
      )}

      {section.intro && (
        <div className="reader-body">
          {section.intro.paragraphs.map((p, i) => (
            <p key={i}>{p}</p>
          ))}
          {section.intro.outline.length > 0 && (
            <ol className="outline">
              {section.intro.outline.map((o) => (
                <li key={o.n}>{o.text}</li>
              ))}
            </ol>
          )}
        </div>
      )}

      {section.poetry.map((poem) => (
        <blockquote className="quote poem" key={poem.position}>
          {poem.text.split('\n').map((line, i) => (
            <span className="quote-text" key={i}>
              {line}
            </span>
          ))}
          {poem.attribution && <span className="quote-attr">{poem.attribution}</span>}
        </blockquote>
      ))}

      {section.has_intro && !section.intro && (
        <p className="notice">
          Lockyer's introduction to {section.book_section} ({section.intro_word_count} words) is
          not reproduced here — in copyright, © Zondervan 1959. Set
          PRAYER_INCLUDE_COPYRIGHTED_TEXT=true on the API to read it for personal, local use.
        </p>
      )}

      {order.length > 0 && (
        <ReaderNav prev={prev} next={next} position={index + 1} total={order.length} />
      )}
    </div>
  )
}
