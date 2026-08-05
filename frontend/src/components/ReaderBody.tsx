import type {
  LockyerItemDetail,
  ParksItemDetail,
  PrayerDetail,
  WattersCitation,
  WattersPassageDetail,
} from '../api/types'

export function ParksBody({
  item,
  prayer,
  prayerLoading,
}: {
  item: ParksItemDetail
  prayer: PrayerDetail | undefined
  prayerLoading: boolean
}) {
  return (
    <>
      <div className="reader-labels">
        <span className="tag">{item.speaker.raw}</span>
        {item.addressee.raw && <span className="tag">to {item.addressee.raw}</span>}
        <span className="tag">{item.context}</span>
        {item.contents.map((c) => (
          <span className="tag" key={c}>
            {c}
          </span>
        ))}
      </div>

      <div className="reader-body">
        {prayerLoading && <p>Loading scripture text…</p>}
        {prayer?.passage_text && <p>{prayer.passage_text}</p>}
        {!prayerLoading && !prayer?.passage_text && (
          <p>
            <em>Scripture text is not available for this passage.</em>
          </p>
        )}
      </div>

      <p className="notice">
        Parks catalogues this prayer's speaker, occasion, and setting, but its own
        commentary is not reproduced here (proprietary, © Faithlife 2021). The
        passage above is the World English Bible (public domain).
      </p>
    </>
  )
}

export function LockyerBody({ item }: { item: LockyerItemDetail }) {
  return (
    <>
      <div className="reader-body">
        {item.scripture_quotes.length === 0 && (
          <p>
            <em>No scripture quotation is recorded for this entry.</em>
          </p>
        )}
        {item.scripture_quotes.map((q) => (
          <blockquote className="quote" key={q.position}>
            <span className="quote-text">{q.text}</span>
            <span className="quote-attr">
              {q.attribution_raw} · {q.translation}
            </span>
          </blockquote>
        ))}
      </div>

      {(item.has_exposition || item.has_poetry) && (
        <p className="notice">
          Lockyer's exposition{item.has_poetry ? ' and poetry' : ''} on this entry
          {item.has_exposition &&
            ` (${item.exposition_paragraph_count} paragraph${
              item.exposition_paragraph_count === 1 ? '' : 's'
            })`}{' '}
          are not reproduced here — in copyright, © Zondervan 1959.
        </p>
      )}
    </>
  )
}

export function WattersBody({
  item,
  citations,
  citationsLoading,
}: {
  item: WattersPassageDetail
  citations: WattersCitation[] | undefined
  citationsLoading: boolean
}) {
  if (item.text) {
    return (
      <div className="reader-body">
        <p>{item.text}</p>
      </div>
    )
  }

  return (
    <>
      <p className="notice">{item.text_reason ?? 'This passage has no single quotable text.'}</p>
      {citationsLoading && <p className="state-message">Loading citations…</p>}
      {citations && (
        <ul className="citation-list">
          {citations.map((c) => (
            <li key={c.id}>
              <div className="citation-meta">
                Ch. {c.chapter_n} · {c.chapter_title}
                {c.topic ? ` · ${c.topic}` : ''} · {c.ref_raw}
              </div>
              <div className="reader-body">{c.text}</div>
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
