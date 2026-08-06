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

// A nav stop's `label`, when given, is shown alongside the arrow (e.g.
// "‹ Genesis" when Prev crosses into a different book's introduction).
// Left off, it falls back to a plain "Prev"/"Next" -- the terser default for
// stepping between entries of the same kind, where naming the destination
// adds noise rather than context.
export interface NavStop {
  href: string
  label?: string
}

export function ReaderNav({
  prev,
  next,
  position,
  total,
}: {
  prev?: NavStop
  next?: NavStop
  position: number
  total: number
}) {
  return (
    <div className="reader-nav">
      {prev ? (
        <Link to={prev.href}>‹ {prev.label ?? 'Prev'}</Link>
      ) : (
        <span className="disabled">‹ Prev</span>
      )}
      <span className="position">
        {position} / {total}
      </span>
      {next ? (
        <Link to={next.href}>{next.label ?? 'Next'} ›</Link>
      ) : (
        <span className="disabled">Next ›</span>
      )}
    </div>
  )
}
