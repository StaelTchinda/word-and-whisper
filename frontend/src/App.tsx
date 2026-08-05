import { Link, Route, Routes } from 'react-router'
import HomePage from './pages/HomePage'
import SourceTocPage from './pages/SourceTocPage'
import ReaderPage from './pages/ReaderPage'
import BookSectionPage from './pages/BookSectionPage'
import WattersMatterPage from './pages/WattersMatterPage'

export default function App() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/">
          Word &amp; Whisper
        </Link>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/sources/:sourceId" element={<SourceTocPage />} />
        <Route path="/sources/lockyer1959/book-sections/:sectionId" element={<BookSectionPage />} />
        <Route path="/sources/watters1883/front-matter" element={<WattersMatterPage />} />
        <Route path="/sources/watters1883/back-matter" element={<WattersMatterPage />} />
        <Route path="/sources/:sourceId/:itemId" element={<ReaderPage />} />
      </Routes>
    </div>
  )
}
