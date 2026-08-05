import { useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { getPrayer, getSourceItem, getToc, getWattersCitations, listSources } from '../api/client'
import { parseDisplayName } from '../sourceMeta'
import { flattenToc } from '../toc'
import { ReaderBreadcrumb, ReaderNav } from '../components/ReaderNav'
import { LockyerBody, ParksBody, WattersBody } from '../components/ReaderBody'

export default function ReaderPage() {
  const { sourceId, itemId } = useParams<{ sourceId: string; itemId: string }>()

  const sourcesQuery = useQuery({ queryKey: ['sources'], queryFn: listSources })
  const tocQuery = useQuery({
    queryKey: ['toc', sourceId],
    queryFn: () => getToc(sourceId!),
    enabled: !!sourceId,
  })
  const itemQuery = useQuery({
    queryKey: ['item', sourceId, itemId],
    queryFn: () => getSourceItem(sourceId!, itemId!),
    enabled: !!sourceId && !!itemId,
  })

  // Parks items carry no book prose of their own (SourceInfo.text_includable
  // === false) but share ids with the retrieval corpus, so the reader pulls
  // the public-domain WEB passage from there instead.
  const prayerQuery = useQuery({
    queryKey: ['prayer', itemId],
    queryFn: () => getPrayer(itemId!),
    enabled: sourceId === 'parks2021' && !!itemId,
  })

  const item = itemQuery.data
  // Needed whenever the item has no single quotable text (to enumerate its
  // sources) and also when it does (to thread each citation's notes/see_also
  // onto the passage -- see WattersBody).
  const needsCitations = item?.source_id === 'watters1883'
  const citationsQuery = useQuery({
    queryKey: ['citations', itemId],
    queryFn: () => getWattersCitations(itemId!),
    enabled: needsCitations && !!itemId,
  })

  if (itemQuery.isLoading || tocQuery.isLoading) {
    return (
      <div className="container">
        <p className="state-message">Loading…</p>
      </div>
    )
  }
  if (itemQuery.error || !item) {
    return (
      <div className="container">
        <p className="state-message">
          {(itemQuery.error as Error)?.message ?? 'Item not found'}
        </p>
      </div>
    )
  }

  const info = sourcesQuery.data?.sources.find((s) => s.id === sourceId)
  const { title: sourceTitle } = parseDisplayName(info?.display_name ?? sourceId ?? '')

  const flat = tocQuery.data ? flattenToc(tocQuery.data) : []
  const index = flat.findIndex((e) => e.item.id === itemId)
  const entry = index >= 0 ? flat[index] : undefined
  const prev = index > 0 ? flat[index - 1] : undefined
  const next = index >= 0 && index < flat.length - 1 ? flat[index + 1] : undefined

  return (
    <div className="container reader">
      <ReaderBreadcrumb sourceId={sourceId!} sourceTitle={sourceTitle} entry={entry} />

      <div className="reader-header">
        {item.source_id === 'watters1883' ? (
          <h1>{item.osis}</h1>
        ) : (
          <>
            <h1>{item.title}</h1>
            <div className="ref">
              {item.primary_ref ?? item.refs[0]?.raw ?? ''}
              {item.source_id === 'lockyer1959' && item.page && ` · p. ${item.page}`}
            </div>
          </>
        )}
      </div>

      {item.source_id === 'parks2021' && (
        <ParksBody item={item} prayer={prayerQuery.data} prayerLoading={prayerQuery.isLoading} />
      )}
      {item.source_id === 'lockyer1959' && <LockyerBody item={item} />}
      {item.source_id === 'watters1883' && (
        <WattersBody
          item={item}
          citations={citationsQuery.data?.items}
          citationsLoading={citationsQuery.isLoading}
        />
      )}

      {flat.length > 0 && (
        <ReaderNav
          sourceId={sourceId!}
          prev={prev}
          next={next}
          position={index + 1}
          total={flat.length}
        />
      )}
    </div>
  )
}
