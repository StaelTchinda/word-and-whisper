import { useQuery } from '@tanstack/react-query'
import { listSources } from '../api/client'
import SourceCard from '../components/SourceCard'

export default function HomePage() {
  const { data, isLoading, error } = useQuery({ queryKey: ['sources'], queryFn: listSources })

  return (
    <div className="container">
      <section className="hero">
        <h1>Word &amp; Whisper</h1>
        <p>
          Every prayer recorded in Scripture, drawn from three source books spanning
          almost a century and a half of study. Each is presented here as its own
          reader — one prayer, entry, or passage at a time — organised the way that
          book organises itself.
        </p>
      </section>

      {isLoading && <p className="state-message">Loading sources…</p>}
      {error && (
        <p className="state-message">Could not reach the API: {(error as Error).message}</p>
      )}

      {data && (
        <div className="source-grid">
          {data.sources.map((source) => (
            <SourceCard key={source.id} source={source} />
          ))}
        </div>
      )}
    </div>
  )
}
