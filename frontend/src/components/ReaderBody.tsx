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
      <div className="facet-groups">
        <div className="facet-row facet-speaker">
          <span className="flabel">Speaker</span>
          <span className="facet-val">{item.speaker.raw}</span>
        </div>
        {item.addressee.raw && (
          <div className="facet-row facet-addressee">
            <span className="flabel">To</span>
            <span className="facet-val">{item.addressee.raw}</span>
          </div>
        )}
        <div className="facet-row facet-occasion">
          <span className="flabel">Occasion</span>
          <span className="facet-val">{item.context}</span>
        </div>
        {item.contents.length > 0 && (
          <div className="facet-row facet-themes">
            <span className="flabel">Themes</span>
            <div className="theme-chips">
              {item.contents.map((c) => (
                <span className="theme-chip" key={c}>
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}
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
  // has_exposition/has_poetry are always accurate; exposition/poetry are only
  // populated when the backend was started with
  // PRAYER_INCLUDE_COPYRIGHTED_TEXT=true (see docs/datasets.md). A mismatch
  // between the two means the content exists but this deployment withholds it.
  const withheld = (item.has_exposition && !item.exposition) || (item.has_poetry && item.poetry.length === 0)

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

        {item.exposition && (
          <div className="exposition">
            {item.exposition.paragraphs.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
            {item.exposition.outline.length > 0 && (
              <ol className="outline">
                {item.exposition.outline.map((o) => (
                  <li key={o.n}>{o.text}</li>
                ))}
              </ol>
            )}
          </div>
        )}

        {item.poetry.map((poem) => (
          <blockquote className="quote poem" key={poem.position}>
            {poem.text.split('\n').map((line, i) => (
              <span className="quote-text" key={i}>
                {line}
              </span>
            ))}
            {poem.attribution && <span className="quote-attr">{poem.attribution}</span>}
          </blockquote>
        ))}
      </div>

      {withheld && (
        <p className="notice">
          Lockyer's exposition{item.has_poetry ? ' and poetry' : ''} on this entry
          {item.has_exposition &&
            ` (${item.exposition_paragraph_count} paragraph${
              item.exposition_paragraph_count === 1 ? '' : 's'
            })`}{' '}
          {item.exposition_paragraph_count === 1 ? 'is' : 'are'} not reproduced here — in
          copyright, © Zondervan 1959. Set PRAYER_INCLUDE_COPYRIGHTED_TEXT=true on the API to
          read it for personal, local use.
        </p>
      )}
    </>
  )
}

function CitationNotes({ citation }: { citation: WattersCitation }) {
  if (citation.notes.length === 0 && !citation.see_also) return null
  return (
    <div className="citation-notes">
      {citation.notes.map((note, i) => (
        <p className="note" key={i}>
          {note}
        </p>
      ))}
      {citation.see_also && <p className="see-also">See also: {citation.see_also}</p>}
    </div>
  )
}

// `showContext` includes the chapter/topic/subtopic prefix on the meta line;
// the single-passage view (WattersBody, below) needs it since a citation
// there is read out of context, but a chapter/topic reading view
// (WattersChapterPage) already shows that same context as a heading, so it
// passes false to avoid repeating it on every citation.
export function CitationEntry({
  citation,
  showContext,
}: {
  citation: WattersCitation
  showContext: boolean
}) {
  return (
    <li>
      <div className="citation-meta">
        {showContext && (
          <>
            Ch. {citation.chapter_n} · {citation.chapter_title}
            {citation.topic ? ` · ${citation.topic}` : ''}
            {citation.subtopic ? ` · ${citation.subtopic}` : ''} ·{' '}
          </>
        )}
        {citation.ref_raw}
        {citation.page ? ` · p. ${citation.page}` : ''}
      </div>
      <div className="reader-body">{citation.text}</div>
      <CitationNotes citation={citation} />
    </li>
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
  const ownCitation = citations?.find((c) => c.text === item.text && c.text_source === 'inline')

  if (item.text) {
    return (
      <div className="reader-body">
        <p>{item.text}</p>
        {ownCitation && <CitationNotes citation={ownCitation} />}
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
            <CitationEntry citation={c} showContext key={c.id} />
          ))}
        </ul>
      )}
    </>
  )
}
