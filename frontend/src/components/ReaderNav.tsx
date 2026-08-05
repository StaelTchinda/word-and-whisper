import { Link } from 'react-router'
import type { FlatTocEntry } from '../toc'

export function ReaderBreadcrumb({
  sourceId,
  sourceTitle,
  entry,
}: {
  sourceId: string
  sourceTitle: string
  entry?: FlatTocEntry
}) {
  return (
    <div className="breadcrumb">
      <Link to="/">Home</Link>
      <span>/</span>
      <Link to={`/sources/${sourceId}`}>{sourceTitle}</Link>
      {entry && (
        <>
          <span>/</span>
          <span>{entry.subsectionLabel}</span>
        </>
      )}
    </div>
  )
}

export function ReaderNav({
  sourceId,
  prev,
  next,
  position,
  total,
}: {
  sourceId: string
  prev?: FlatTocEntry
  next?: FlatTocEntry
  position: number
  total: number
}) {
  return (
    <div className="reader-nav">
      {prev ? (
        <Link to={`/sources/${sourceId}/${prev.item.id}`}>‹ Prev</Link>
      ) : (
        <span className="disabled">‹ Prev</span>
      )}
      <span className="position">
        {position} / {total}
      </span>
      {next ? (
        <Link to={`/sources/${sourceId}/${next.item.id}`}>Next ›</Link>
      ) : (
        <span className="disabled">Next ›</span>
      )}
    </div>
  )
}
