import { Link } from 'react-router'
import type { SourceInfo } from '../api/types'
import { SOURCE_BLURBS, parseDisplayName, pluralizeUnit } from '../sourceMeta'
import LicenseBadge from './LicenseBadge'

export default function SourceCard({ source }: { source: SourceInfo }) {
  const { title, byline } = parseDisplayName(source.display_name)
  const available = source.status === 'ok'

  return (
    <Link
      className="source-card"
      to={available ? `/sources/${source.id}` : '#'}
      aria-disabled={!available}
      onClick={(e) => {
        if (!available) e.preventDefault()
      }}
    >
      <h2>{title}</h2>
      {byline && <div className="byline">{byline}</div>}
      <p className="blurb">{SOURCE_BLURBS[source.id]}</p>
      <div className="meta-row">
        <LicenseBadge license={source.license} />
        <span className="count">
          {available
            ? `${source.record_count.toLocaleString()} ${pluralizeUnit(source.unit)}`
            : 'unavailable'}
        </span>
      </div>
    </Link>
  )
}
