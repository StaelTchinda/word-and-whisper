import { useState } from 'react'
import { Link, Route, Routes, useNavigate } from 'react-router'
import HomePage from './pages/HomePage'
import SourceTocPage from './pages/SourceTocPage'
import ReaderPage from './pages/ReaderPage'
import BookSectionPage from './pages/BookSectionPage'
import WattersMatterPage from './pages/WattersMatterPage'
import WattersChapterPage from './pages/WattersChapterPage'
import SearchPage from './pages/SearchPage'

function TopbarSearch() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  return (
    <form
      className="topbar-search"
      onSubmit={(e) => {
        e.preventDefault()
        if (q.trim()) navigate(`/search?q=${encodeURIComponent(q.trim())}`)
      }}
    >
      <input
        type="search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search all prayers, people, places…"
        aria-label="Search all prayers, people, places"
      />
    </form>
  )
}

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          Word &amp; Whisper
        </Link>
        <TopbarSearch />
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/sources/:sourceId" element={<SourceTocPage />} />
        <Route path="/sources/lockyer1959/book-sections/:sectionId" element={<BookSectionPage />} />
        <Route path="/sources/watters1883/front-matter" element={<WattersMatterPage />} />
        <Route path="/sources/watters1883/back-matter" element={<WattersMatterPage />} />
        <Route path="/sources/watters1883/chapters/:chapterN" element={<WattersChapterPage />} />
        <Route path="/sources/:sourceId/:itemId" element={<ReaderPage />} />
      </Routes>
    </div>
  )
}
