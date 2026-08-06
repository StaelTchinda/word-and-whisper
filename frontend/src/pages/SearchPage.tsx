import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { searchAll } from '../api/client'
import { SOURCE_SHORT_LABELS } from '../sourceMeta'
import type { GlobalSearchResult } from '../api/types'

function ResultRow({ result }: { result: GlobalSearchResult }) {
  return (
    <li className="gs-result">
      <div className="gs-top">
        <span className={`src-badge src-badge-${result.source_id}`}>
          {SOURCE_SHORT_LABELS[result.source_id] ?? result.source_id}
        </span>
        <Link to={`/sources/${result.source_id}/${result.id}`} className="gs-title">
          {result.title ?? result.ref_display}
        </Link>
        {result.title && <span className="gs-ref">{result.ref_display}</span>}
      </div>
      <p className="gs-snippet">{result.snippet}</p>
      <div className="gs-match">
        matched <b>{result.matched_on}</b>
      </div>
    </li>
  )
}

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const [draft, setDraft] = useState(q)

  const query = useQuery({
    queryKey: ['search', q],
    queryFn: () => searchAll(q),
    enabled: q.length > 0,
  })

  return (
    <div className="container search-page">
      <div className="breadcrumb">
        <Link to="/">Home</Link>
        <span>/</span>
        <span>Search</span>
      </div>

      <form
        className="gs-input-row"
        onSubmit={(e) => {
          e.preventDefault()
          setParams(draft ? { q: draft } : {})
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Search all prayers, people, places…"
          autoFocus
        />
      </form>

      {q.length === 0 && (
        <p className="state-message">Search across all three sources by title, person, place, or theme.</p>
      )}
      {query.isLoading && <p className="state-message">Searching…</p>}
      {query.error && (
        <p className="state-message">{(query.error as Error).message}</p>
      )}
      {query.data && query.data.total === 0 && (
        <p className="state-message">No results for &ldquo;{q}&rdquo;.</p>
      )}
      {query.data && query.data.total > 0 && (
        <>
          <div className="result-count">
            {query.data.total.toLocaleString()} result{query.data.total === 1 ? '' : 's'}
            {query.data.items.length < query.data.total && ` (showing first ${query.data.items.length})`}
          </div>
          <ul className="gs-results">
            {query.data.items.map((r) => (
              <ResultRow result={r} key={`${r.source_id}.${r.id}`} />
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
