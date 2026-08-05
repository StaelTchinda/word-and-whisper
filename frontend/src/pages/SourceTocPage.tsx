import { Link, useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { getToc, listSources } from '../api/client'
import { parseDisplayName } from '../sourceMeta'
import TocTree from '../components/TocTree'

export default function SourceTocPage() {
  const { sourceId } = useParams<{ sourceId: string }>()

  const tocQuery = useQuery({
    queryKey: ['toc', sourceId],
    queryFn: () => getToc(sourceId!),
    enabled: !!sourceId,
  })
  // Shares the query-cache entry HomePage already populated, so this is
  // usually free.
  const sourcesQuery = useQuery({ queryKey: ['sources'], queryFn: listSources })

  if (tocQuery.isLoading) {
    return (
      <div className="container">
        <p className="state-message">Loading contents…</p>
      </div>
    )
  }
  if (tocQuery.error || !tocQuery.data) {
    return (
      <div className="container">
        <p className="state-message">{(tocQuery.error as Error)?.message ?? 'Not found'}</p>
      </div>
    )
  }

  const info = sourcesQuery.data?.sources.find((s) => s.id === sourceId)
  const { title, byline } = parseDisplayName(info?.display_name ?? sourceId ?? '')
  const toc = tocQuery.data

  return (
    <div className="container">
      <div className="breadcrumb">
        <Link to="/">Home</Link>
        <span>/</span>
        <span>{title}</span>
      </div>
      <div className="toc-header">
        <h1>{title}</h1>
        {byline && <div className="byline">{byline}</div>}
      </div>
      <TocTree sourceId={sourceId!} toc={toc} />
    </div>
  )
}
