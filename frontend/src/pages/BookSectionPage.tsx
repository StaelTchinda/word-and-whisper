import { Link, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { getLockyerBookSection } from '../api/client'

export default function BookSectionPage() {
  const { sectionId } = useParams<{ sectionId: string }>()

  const query = useQuery({
    queryKey: ['book-section', sectionId],
    queryFn: () => getLockyerBookSection(sectionId!),
    enabled: !!sectionId,
  })

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
    </div>
  )
}
