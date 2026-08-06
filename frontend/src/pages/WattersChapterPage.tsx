import { Link, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { getToc, getWattersChapter } from '../api/client'
import { CitationEntry } from '../components/ReaderBody'

export default function WattersChapterPage() {
  const { chapterN: chapterParam } = useParams<{ chapterN: string }>()
  const chapterN = Number(chapterParam)

  const chapterQuery = useQuery({
    queryKey: ['watters-chapter', chapterN],
    queryFn: () => getWattersChapter(chapterN),
    enabled: Number.isFinite(chapterN),
  })
  // Shares the query-cache entry SourceTocPage already populated when a
  // reader arrived here via "Read this chapter", so this is usually free --
  // only needed for the chapter-to-chapter Prev/Next below.
  const tocQuery = useQuery({ queryKey: ['toc', 'watters1883'], queryFn: () => getToc('watters1883') })

  if (chapterQuery.isLoading) {
    return (
      <div className="container">
        <p className="state-message">Loading…</p>
      </div>
    )
  }
  if (chapterQuery.error || !chapterQuery.data) {
    return (
      <div className="container">
        <p className="state-message">
          {(chapterQuery.error as Error)?.message ?? 'Chapter not found'}
        </p>
      </div>
    )
  }
  const chapter = chapterQuery.data
  const heading = chapter.roman ? `${chapter.roman}. ${chapter.title}` : chapter.title

  const chapterIds = (tocQuery.data?.sections[0]?.subsections ?? []).map((s) => Number(s.id))
  const index = chapterIds.indexOf(chapterN)
  const prev = index > 0 ? chapterIds[index - 1] : undefined
  const next = index >= 0 && index < chapterIds.length - 1 ? chapterIds[index + 1] : undefined

  return (
    <div className="container reader">
      <div className="breadcrumb">
        <Link to="/">Home</Link>
        <span>/</span>
        <Link to="/sources/watters1883">The Prayers of the Bible (Watters, 1883)</Link>
        <span>/</span>
        <span>{heading}</span>
      </div>

      <div className="reader-header">
        <h1>{heading}</h1>
        <div className="ref">
          {chapter.n_citations.toLocaleString()} citations across {chapter.topics.length} topics
        </div>
      </div>

      {chapter.topics.map((topic) => (
        <section className="chapter-topic" key={topic.id}>
          <h2>{topic.label}</h2>
          {topic.citations.length > 0 && (
            <ul className="citation-list">
              {topic.citations.map((c) => (
                <CitationEntry citation={c} showContext={false} key={c.id} />
              ))}
            </ul>
          )}
          {topic.subtopics.map((sub) => (
            <div className="chapter-subtopic" key={sub.id}>
              <h3>{sub.label}</h3>
              <ul className="citation-list">
                {sub.citations.map((c) => (
                  <CitationEntry citation={c} showContext={false} key={c.id} />
                ))}
              </ul>
            </div>
          ))}
        </section>
      ))}

      {chapterIds.length > 0 && (
        <div className="reader-nav">
          {prev !== undefined ? (
            <Link to={`/sources/watters1883/chapters/${prev}`}>‹ Prev chapter</Link>
          ) : (
            <span className="disabled">‹ Prev chapter</span>
          )}
          <span className="position">
            {index >= 0 ? `Chapter ${index + 1} / ${chapterIds.length}` : ''}
          </span>
          {next !== undefined ? (
            <Link to={`/sources/watters1883/chapters/${next}`}>Next chapter ›</Link>
          ) : (
            <span className="disabled">Next chapter ›</span>
          )}
        </div>
      )}
    </div>
  )
}
