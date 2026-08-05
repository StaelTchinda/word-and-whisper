import { Link, useLocation } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { getWattersBackMatter, getWattersFrontMatter } from '../api/client'

function Crumb({ label }: { label: string }) {
  return (
    <div className="breadcrumb">
      <Link to="/">Home</Link>
      <span>/</span>
      <Link to="/sources/watters1883">The Prayers of the Bible (Watters, 1883)</Link>
      <span>/</span>
      <span>{label}</span>
    </div>
  )
}

function FrontMatterView() {
  const query = useQuery({ queryKey: ['watters-front-matter'], queryFn: getWattersFrontMatter })

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
  const matter = query.data

  return (
    <div className="container reader">
      <Crumb label="Front matter" />
      <div className="reader-header">
        <h1>{matter.headings[0] ?? 'Front matter'}</h1>
      </div>
      <div className="reader-body">
        {matter.headings.slice(1).map((h, i) => (
          <p key={i}>
            <strong>{h}</strong>
          </p>
        ))}
        {matter.paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
    </div>
  )
}

function BackMatterView() {
  const query = useQuery({ queryKey: ['watters-back-matter'], queryFn: getWattersBackMatter })

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
  const matter = query.data

  return (
    <div className="container reader">
      <Crumb label="Back matter" />
      <div className="reader-header">
        <h1>{matter.headings[0] ?? 'Back matter'}</h1>
      </div>
      <div className="reader-body">
        {matter.headings.slice(1).map((h, i) => (
          <p key={i}>
            <strong>{h}</strong>
          </p>
        ))}
        {matter.paragraphs.map((p, i) => (
          <p key={i}>{p}</p>
        ))}
      </div>
      {matter.note && <p className="notice">{matter.note}</p>}
    </div>
  )
}

export default function WattersMatterPage() {
  const isFront = useLocation().pathname.endsWith('front-matter')
  return isFront ? <FrontMatterView /> : <BackMatterView />
}
